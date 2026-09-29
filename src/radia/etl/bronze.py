"""Capa Bronze: CSV crudos a parquet, sin interpretar tipos.

- Todo se lee como texto (`all_varchar`): los tipos se resuelven en Silver.
- `union_by_name` tolera evolución de esquema: una columna nueva en una
  partición queda en NULL para las demás.
- Agrega `_source_file` y `_ingested_at` para trazabilidad.
- Idempotente: cada corrida reconstruye el parquet completo desde raw.
"""

from datetime import UTC, datetime
from pathlib import Path

import duckdb

from radia.config import Settings
from radia.etl.tables import TableSpec


def sql_literal(value: str | Path) -> str:
    """Literal SQL entre comillas simples. Rutas con `/` para DuckDB en Windows."""
    text = value.as_posix() if isinstance(value, Path) else value
    return "'" + text.replace("'", "''") + "'"


def bronze_path(settings: Settings, table: str) -> Path:
    return settings.data_dir / "bronze" / f"{table}.parquet"


def source_files(settings: Settings, spec: TableSpec) -> list[Path]:
    return sorted(p for p in settings.raw_dir.glob(spec.source) if p.is_file())


def build_bronze(
    spec: TableSpec, settings: Settings, con: duckdb.DuckDBPyConnection | None = None
) -> Path:
    """Escribe `bronze/<tabla>.parquet` y devuelve su ruta."""
    files = source_files(settings, spec)
    if not files:
        raise FileNotFoundError(
            f"{spec.name}: no hay archivos en {settings.raw_dir / spec.source}"
        )
    out = bronze_path(settings, spec.name)
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(".parquet.tmp")
    # TIMESTAMP en UTC, sin zona: TIMESTAMPTZ exige pytz al leerlo desde Python.
    ingested_at = datetime.now(UTC).replace(tzinfo=None).isoformat()
    file_list = "[" + ", ".join(sql_literal(p) for p in files) + "]"
    con = con or duckdb.connect()
    con.execute(
        f"""
        COPY (
            SELECT * EXCLUDE (filename),
                   filename AS _source_file,
                   CAST({sql_literal(ingested_at)} AS TIMESTAMP) AS _ingested_at
            FROM read_csv(
                {file_list},
                all_varchar = true,
                hive_partitioning = true,
                filename = true,
                union_by_name = true,
                header = true
            )
        ) TO {sql_literal(tmp)} (FORMAT parquet)
        """
    )
    # Reemplazo atómico: nunca queda un parquet a medio escribir.
    tmp.replace(out)
    return out
