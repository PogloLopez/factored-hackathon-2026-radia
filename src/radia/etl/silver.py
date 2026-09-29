"""Capa Silver: tipos, limpieza y deduplicación desde Bronze.

Pasos por tabla:
1. `TRIM` a todo y `''` a NULL.
2. `TRY_CAST` al tipo de la spec. Un valor que no castea queda NULL y se cuenta.
3. Filas sin PK completa se descartan.
4. Duplicados exactos (mismas columnas de la spec) se reducen a una fila.
5. Por PK queda la última versión según `order_by` (desempate: archivo más reciente).

Cada corrida escribe `silver/<tabla>.parquet` y `quality/<tabla>.json`.
"""

from datetime import UTC, datetime
from pathlib import Path

import duckdb
from pydantic import AwareDatetime, BaseModel

from radia.config import Settings
from radia.etl.bronze import bronze_path, sql_literal
from radia.etl.tables import TableSpec

METADATA_COLUMNS = ("_source_file", "_ingested_at")
# Columnas que agrega `hive_partitioning` en tablas particionadas por día.
PARTITION_COLUMNS = ("year", "month", "day")


class QualityReport(BaseModel):
    table: str
    generated_at: AwareDatetime
    rows_in: int
    rows_out: int
    null_pk_removed: int
    exact_duplicates_removed: int
    stale_versions_removed: int
    null_rate: dict[str, float]
    cast_failures: dict[str, int]
    # None: la dimensión de referencia aún no tiene Silver.
    orphans: dict[str, int | None]
    missing_columns: list[str]
    unexpected_columns: list[str]


def ident(name: str) -> str:
    """Identificador SQL entre comillas dobles (hay columnas como `date`)."""
    return '"' + name.replace('"', '""') + '"'


def silver_path(settings: Settings, table: str) -> Path:
    return settings.data_dir / "silver" / f"{table}.parquet"


def report_path(settings: Settings, table: str) -> Path:
    return settings.data_dir / "quality" / f"{table}.json"


def _count(con: duckdb.DuckDBPyConnection, sql: str) -> int:
    return con.execute(sql).fetchone()[0]


def build_silver(
    spec: TableSpec, settings: Settings, con: duckdb.DuckDBPyConnection | None = None
) -> QualityReport:
    """Construye Silver y su reporte de calidad. Requiere Bronze de la tabla."""
    src = bronze_path(settings, spec.name)
    if not src.exists():
        raise FileNotFoundError(f"{spec.name}: falta Bronze en {src}")
    con = con or duckdb.connect()
    con.execute(
        f"CREATE OR REPLACE TEMP VIEW bronze AS SELECT * FROM read_parquet({sql_literal(src)})"
    )
    bronze_cols = [r[0] for r in con.execute("DESCRIBE bronze").fetchall()]
    missing = [c for c in spec.columns if c not in bronze_cols]
    ignored = set(spec.columns) | set(METADATA_COLUMNS) | set(PARTITION_COLUMNS)
    unexpected = [c for c in bronze_cols if c not in ignored]

    # Texto limpio por columna; una columna ausente en Bronze queda NULL.
    raw = {
        c: f"NULLIF(TRIM({ident(c)}), '')" if c in bronze_cols else "NULL::VARCHAR"
        for c in spec.columns
    }
    typed = {
        c: raw[c] if t == "VARCHAR" else f"TRY_CAST({raw[c]} AS {t})"
        for c, t in spec.columns.items()
    }

    failures_sql = ", ".join(
        f"COUNT(*) FILTER (WHERE {raw[c]} IS NOT NULL AND {typed[c]} IS NULL)"
        for c in spec.columns
    )
    failures_row = con.execute(f"SELECT {failures_sql} FROM bronze").fetchone()
    cast_failures = dict(zip(spec.columns, failures_row, strict=True))

    cols = ", ".join(f"{typed[c]} AS {ident(c)}" for c in spec.columns)
    con.execute(
        f"CREATE OR REPLACE TEMP TABLE typed AS SELECT {cols}, _source_file, _ingested_at FROM bronze"
    )
    rows_in = _count(con, "SELECT COUNT(*) FROM typed")

    pk_not_null = " AND ".join(f"{ident(c)} IS NOT NULL" for c in spec.primary_key)
    con.execute(
        f"CREATE OR REPLACE TEMP TABLE with_pk AS SELECT * FROM typed WHERE {pk_not_null}"
    )
    with_pk = _count(con, "SELECT COUNT(*) FROM with_pk")

    all_cols = ", ".join(ident(c) for c in spec.columns)
    con.execute(
        f"""
        CREATE OR REPLACE TEMP TABLE distinct_rows AS
        SELECT * FROM with_pk
        QUALIFY row_number() OVER (PARTITION BY {all_cols} ORDER BY _source_file) = 1
        """
    )
    distinct_rows = _count(con, "SELECT COUNT(*) FROM distinct_rows")

    pk_cols = ", ".join(ident(c) for c in spec.primary_key)
    order = f"{ident(spec.order_by)} DESC NULLS LAST, " if spec.order_by else ""
    con.execute(
        f"""
        CREATE OR REPLACE TEMP TABLE latest AS
        SELECT * FROM distinct_rows
        QUALIFY row_number() OVER (
            PARTITION BY {pk_cols} ORDER BY {order}_source_file DESC
        ) = 1
        """
    )
    rows_out = _count(con, "SELECT COUNT(*) FROM latest")

    out = silver_path(settings, spec.name)
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(".parquet.tmp")
    con.execute(
        f"COPY (SELECT * FROM latest ORDER BY {pk_cols}) TO {sql_literal(tmp)} (FORMAT parquet)"
    )
    tmp.replace(out)

    nulls_sql = ", ".join(
        f"COUNT(*) FILTER (WHERE {ident(c)} IS NULL)" for c in spec.columns
    )
    nulls_row = con.execute(f"SELECT {nulls_sql} FROM latest").fetchone()
    null_rate = {
        c: (n / rows_out if rows_out else 0.0)
        for c, n in zip(spec.columns, nulls_row, strict=True)
    }

    orphans: dict[str, int | None] = {}
    for fk in spec.foreign_keys:
        ref = silver_path(settings, fk.ref_table)
        key = f"{fk.column}->{fk.ref_table}.{fk.ref_column}"
        if not ref.exists():
            orphans[key] = None
            continue
        orphans[key] = _count(
            con,
            f"""
            SELECT COUNT(*) FROM latest l
            WHERE l.{ident(fk.column)} IS NOT NULL
              AND NOT EXISTS (
                SELECT 1 FROM read_parquet({sql_literal(ref)}) r
                WHERE r.{ident(fk.ref_column)} = l.{ident(fk.column)}
              )
            """,
        )

    report = QualityReport(
        table=spec.name,
        generated_at=datetime.now(UTC),
        rows_in=rows_in,
        rows_out=rows_out,
        null_pk_removed=rows_in - with_pk,
        exact_duplicates_removed=with_pk - distinct_rows,
        stale_versions_removed=distinct_rows - rows_out,
        null_rate=null_rate,
        cast_failures=cast_failures,
        orphans=orphans,
        missing_columns=missing,
        unexpected_columns=unexpected,
    )
    path = report_path(settings, spec.name)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(report.model_dump_json(indent=2), encoding="utf-8")
    return report
