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
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

import boto3
from boto3.s3.transfer import TransferConfig
from pydantic import AwareDatetime, BaseModel, Field

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
    path = _state_path(raw_dir)
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def pending_entries(manifest: Manifest, raw_dir: Path) -> list[ManifestEntry]:
    """Objetos que faltan localmente o cambiaron de ETag (datos tardíos o corregidos)."""
    state = _load_state(raw_dir)
    return [
        e
        for e in manifest.entries
        if state.get(e.key) != e.etag or not (raw_dir / e.key).exists()
    ]


def download(
    client: S3Client, manifest: Manifest, raw_dir: Path, max_concurrency: int = 4
) -> list[ManifestEntry]:
    """Descarga solo lo pendiente. Devuelve lo descargado."""
    todo = pending_entries(manifest, raw_dir)
    # Una sola conexión por archivo: la concurrencia la controla el pool de abajo.
    transfer = TransferConfig(use_threads=False)
    state = _load_state(raw_dir)

    def fetch(entry: ManifestEntry) -> ManifestEntry:
        target = raw_dir / entry.key
        target.parent.mkdir(parents=True, exist_ok=True)
        client.download_file(manifest.bucket, entry.key, str(target), Config=transfer)
        return entry

    with ThreadPoolExecutor(max_workers=max_concurrency) as pool:
        for entry in pool.map(fetch, todo):
            state[entry.key] = entry.etag
            # Se guarda tras cada archivo: si se corta, se retoma sin repetir.
            _state_path(raw_dir).write_text(json.dumps(state, indent=0), "utf-8")
    return todo
