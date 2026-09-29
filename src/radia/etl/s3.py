"""Único punto de acceso al bucket de Factored.

Reglas (ver [[propuesta]] y `.claude/rules/git.md`, checkpoints):
- Solo las tablas de crédito (`CREDIT_TABLES`), nunca el bucket completo.
- Primero un manifiesto con LIST (claves, tamaños, ETags). Pablo lo aprueba.
- Cada objeto se descarga una sola vez a `data/local/raw/`. Un objeto ya local
  con el mismo ETag no se vuelve a pedir. Así los re-sync solo traen datos
  nuevos o tardíos.
- Concurrencia baja y acotada (`s3_max_concurrency`).
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

import boto3
from boto3.s3.transfer import TransferConfig
from pydantic import AwareDatetime, BaseModel, Field
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from radia.config import CREDIT_TABLES, Settings

if TYPE_CHECKING:
    from mypy_boto3_s3 import S3Client


class ManifestEntry(BaseModel):
    table: str
    key: str
    size_bytes: int = Field(ge=0)
    etag: str
    last_modified: AwareDatetime


class Manifest(BaseModel):
    bucket: str
    prefix: str
    created_at: AwareDatetime
    entries: list[ManifestEntry]

    def summary(self) -> dict[str, dict[str, int]]:
        """Objetos y bytes por tabla, para que Pablo apruebe la descarga."""
        out: dict[str, dict[str, int]] = {}
        for e in self.entries:
            row = out.setdefault(e.table, {"objects": 0, "bytes": 0})
            row["objects"] += 1
            row["bytes"] += e.size_bytes
        return out

    @property
    def total_bytes(self) -> int:
        return sum(e.size_bytes for e in self.entries)


def make_client(settings: Settings) -> S3Client:
    """Cliente con credenciales de la configuración, o la cadena por defecto de boto3."""
    kwargs: dict[str, str] = {"region_name": settings.aws_default_region}
    if bool(settings.aws_access_key_id) != bool(settings.aws_secret_access_key):
        raise ValueError("credenciales de AWS incompletas: falta la clave o el secreto")
    if settings.aws_access_key_id and settings.aws_secret_access_key:
        kwargs["aws_access_key_id"] = settings.aws_access_key_id.get_secret_value()
        kwargs["aws_secret_access_key"] = (
            settings.aws_secret_access_key.get_secret_value()
        )
    return boto3.client("s3", **kwargs)


def _table_of(key: str, prefix: str, tables: Iterable[str]) -> str | None:
    """Tabla a la que pertenece una clave: `data/<tabla>.csv` o `data/<tabla>/...`."""
    rest = key.removeprefix(prefix)
    head = rest.split("/", 1)[0]
    name = head.split(".", 1)[0]
    return name if name in tables else None


def build_manifest(
    client: S3Client,
    bucket: str,
    prefix: str = "data/",
    tables: Iterable[str] = CREDIT_TABLES,
) -> Manifest:
    """Lista solo las claves de las tablas pedidas. Solo LIST, nada de GET."""
    tables = tuple(tables)
    paginator = client.get_paginator("list_objects_v2")
    entries: list[ManifestEntry] = []
    for table in tables:
        for page in paginator.paginate(Bucket=bucket, Prefix=f"{prefix}{table}"):
            for obj in page.get("Contents", []):
                if _table_of(obj["Key"], prefix, tables) != table:
                    continue  # p. ej. `products_v2` al pedir `products`
                entries.append(
                    ManifestEntry(
                        table=table,
                        key=obj["Key"],
                        size_bytes=obj["Size"],
                        etag=obj["ETag"].strip('"'),
                        last_modified=obj["LastModified"],
                    )
                )
    return Manifest(
        bucket=bucket, prefix=prefix, created_at=datetime.now(UTC), entries=entries
    )


def save_manifest(manifest: Manifest, directory: Path) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    stamp = manifest.created_at.strftime("%Y%m%dT%H%M%SZ")
    path = directory / f"manifest_{stamp}.json"
    path.write_text(manifest.model_dump_json(indent=2), encoding="utf-8")
    return path


def load_manifest(path: Path) -> Manifest:
    return Manifest.model_validate_json(path.read_text(encoding="utf-8"))


def _state_path(raw_dir: Path) -> Path:
    return raw_dir / "_etags.json"


def _load_state(raw_dir: Path) -> dict[str, str]:
    """ETags ya descargados. Un estado ilegible cuenta como vacío (se re-verifica)."""
    path = _state_path(raw_dir)
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except ValueError:
        return {}


# En Windows el antivirus o el indexador abren un archivo recién escrito por
# un instante y `os.replace` falla con PermissionError. Se reintenta poco.
@retry(
    retry=retry_if_exception_type(PermissionError),
    stop=stop_after_attempt(5),
    wait=wait_exponential(multiplier=0.05, max=1),
    reraise=True,
)
def _save_state(raw_dir: Path, state: dict[str, str]) -> None:
    """Escritura atómica: un corte a mitad nunca deja el JSON corrupto."""
    tmp = _state_path(raw_dir).with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=0), encoding="utf-8")
    os.replace(tmp, _state_path(raw_dir))


def _target(raw_dir: Path, key: str) -> Path:
    """Ruta local de una clave, sin salir de raw_dir aunque el manifiesto traiga `..`."""
    target = (raw_dir / key).resolve()
    if not target.is_relative_to(raw_dir.resolve()):
        raise ValueError(f"clave fuera de raw_dir: {key}")
    return target


def pending_entries(manifest: Manifest, raw_dir: Path) -> list[ManifestEntry]:
    """Objetos que faltan localmente o cambiaron de ETag (datos tardíos o corregidos)."""
    state = _load_state(raw_dir)
    return [
        e
        for e in manifest.entries
        if state.get(e.key) != e.etag or not _target(raw_dir, e.key).exists()
    ]


def download(
    client: S3Client, manifest: Manifest, raw_dir: Path, max_concurrency: int = 4
) -> list[ManifestEntry]:
    """Descarga solo lo pendiente. Devuelve lo descargado.

    Cada éxito queda anotado aunque otro archivo falle, así un reintento no
    vuelve a pedir lo que ya llegó. El primer error se relanza al final.
    """
    raw_dir.mkdir(parents=True, exist_ok=True)
    todo = pending_entries(manifest, raw_dir)
    # Una sola conexión por archivo: la concurrencia la controla el pool de abajo.
    transfer = TransferConfig(use_threads=False)
    state = _load_state(raw_dir)

    def fetch(entry: ManifestEntry) -> ManifestEntry:
        target = _target(raw_dir, entry.key)
        target.parent.mkdir(parents=True, exist_ok=True)
        part = target.with_name(target.name + ".part")
        client.download_file(manifest.bucket, entry.key, str(part), Config=transfer)
        os.replace(part, target)
        return entry

    done: list[ManifestEntry] = []
    errors: list[BaseException] = []
    with ThreadPoolExecutor(max_workers=max_concurrency) as pool:
        futures = [pool.submit(fetch, e) for e in todo]
        for future in as_completed(futures):
            try:
                entry = future.result()
            # Cualquier falla (incluido RetriesExceededError de boto3) se anota y
            # se relanza al final: primero se guardan todos los éxitos.
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)
                continue
            state[entry.key] = entry.etag
            done.append(entry)
            try:
                _save_state(raw_dir, state)
            except OSError as exc:  # p. ej. antivirus con el archivo abierto
                errors.append(exc)
    # Último guardado con todo lo logrado, por si alguno intermedio falló.
    _save_state(raw_dir, state)
    if errors:
        raise errors[0]
    return done
