"""Tests de la capa Bronze con raw sintético (ver conftest)."""

import tempfile
from pathlib import Path

import duckdb
import pytest

from radia.config import Settings
from radia.etl.bronze import build_bronze, sql_literal
from radia.etl.tables import TABLES


def _query(path: Path, sql: str):
    return duckdb.sql(sql.format(t=f"read_parquet({sql_literal(path)})")).fetchall()


def test_bronze_customers_texto_crudo_con_metadatos(raw_settings):
    out = build_bronze(TABLES["customers"], raw_settings)
    assert out == raw_settings.data_dir / "bronze" / "customers.parquet"
    rows = _query(out, "SELECT first_name, _source_file, _ingested_at FROM {t}")
    assert len(rows) == 6
    # Bronze no limpia: el espacio sobrante sigue ahí.
    assert "Ana " in {r[0] for r in rows}
    assert all(r[1].endswith("customers.csv") for r in rows)
    assert all(r[2] is not None for r in rows)
    types = duckdb.sql(
        f"DESCRIBE SELECT * FROM read_parquet({sql_literal(out)})"
    ).fetchall()
    assert {r[1] for r in types if not r[0].startswith("_")} == {"VARCHAR"}


def test_bronze_transactions_une_particiones_y_esquemas(raw_settings):
    out = build_bronze(TABLES["transactions"], raw_settings)
    rows = _query(out, "SELECT transaction_id, channel_v2, year FROM {t}")
    assert len(rows) == 6
    extra = {r[0]: r[1] for r in rows if r[1] is not None}
    assert extra == {"T3": "app", "T5": "web"}
    assert {str(r[2]) for r in rows} == {"2025", "2026"}


def test_bronze_es_idempotente(raw_settings):
    spec = TABLES["transactions"]
    first = build_bronze(spec, raw_settings)
    second = build_bronze(spec, raw_settings)
    assert first == second
    assert _query(second, "SELECT COUNT(*) FROM {t}") == [(6,)]
    assert not list(second.parent.glob("*.tmp"))


def test_bronze_sin_archivos_falla_claro():
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        settings = Settings(_env_file=None, data_dir=Path(tmp))
        with pytest.raises(FileNotFoundError, match="customers"):
            build_bronze(TABLES["customers"], settings)
