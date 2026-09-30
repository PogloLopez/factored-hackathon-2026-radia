"""Tests de la capa Silver y su reporte de calidad (raw sintético del conftest)."""

import json
from decimal import Decimal

import duckdb
import pytest

from radia.etl.bronze import build_bronze, sql_literal
from radia.etl.silver import QualityReport, build_silver, report_path, silver_path
from radia.etl.tables import TABLES


@pytest.fixture
def built(raw_settings):
    """Bronze y Silver de todas las tablas, en orden de construcción."""
    reports = {}
    for spec in TABLES.values():
        build_bronze(spec, raw_settings)
        reports[spec.name] = build_silver(spec, raw_settings)
    return raw_settings, reports


def _rows(settings, table, cols):
    path = sql_literal(silver_path(settings, table))
    return duckdb.sql(f"SELECT {cols} FROM read_parquet({path}) ORDER BY 1").fetchall()


def test_customers_dedup_version_y_casteo(built):
    settings, reports = built
    r = reports["customers"]
    assert (r.rows_in, r.rows_out) == (6, 3)
    assert r.null_pk_removed == 1
    assert r.exact_duplicates_removed == 1
    assert r.stale_versions_removed == 1
    assert r.cast_failures["credit_score"] == 2
    assert r.cast_failures["last_updated"] == 0
    rows = _rows(settings, "customers", "customer_id, first_name, credit_score")
    # C1: gana la versión más reciente. C2: 'abc' queda NULL. C3: '' queda NULL.
    assert rows == [("C1", "Ana", 710), ("C2", "Luis", None), ("C3", None, None)]
    assert r.null_rate["credit_score"] == pytest.approx(2 / 3)
    assert r.null_rate["customer_id"] == 0
    assert "document_number" in r.missing_columns
    assert r.null_rate["document_number"] == 1.0


def test_tipos_de_silver_siguen_la_spec(built):
    settings, _ = built
    path = sql_literal(silver_path(settings, "customers"))
    described = duckdb.sql(f"DESCRIBE SELECT * FROM read_parquet({path})").fetchall()
    types = {r[0]: r[1] for r in described}
    assert types["credit_score"] == "INTEGER"
    assert types["last_updated"] == "TIMESTAMP"
    assert types["accepts_marketing"] == "BOOLEAN"
    assert types["estimated_monthly_income"] == "DECIMAL(12,2)"


def test_transactions_reproceso_particion_tardia_y_esquema(built):
    settings, reports = built
    r = reports["transactions"]
    assert (r.rows_in, r.rows_out) == (6, 5)
    assert r.stale_versions_removed == 1
    assert r.unexpected_columns == ["channel_v2"]
    rows = _rows(settings, "transactions", "transaction_id, amount")
    assert rows == [
        ("T1", Decimal("10.00")),
        ("T2", Decimal("6.00")),  # gana el reproceso del día 3
        ("T3", Decimal("7.00")),
        ("T4", Decimal("3.00")),  # la partición tardía entra igual
        ("T5", Decimal("1.00")),
    ]


def test_huerfanos_por_fk(built):
    _, reports = built
    assert reports["products"].orphans == {"customer_id->customers.customer_id": 1}
    assert reports["transactions"].orphans == {
        "customer_id->customers.customer_id": 1,
        "product_id->products.product_id": 1,
    }
    assert reports["daily_exchange_rates"].orphans == {}


def test_huerfanos_sin_dimension_quedan_en_none(raw_settings):
    spec = TABLES["products"]
    build_bronze(spec, raw_settings)
    r = build_silver(spec, raw_settings)
    assert r.orphans == {"customer_id->customers.customer_id": None}


def test_exchange_rates_pk_compuesta_sin_columna_de_orden(built):
    settings, reports = built
    r = reports["daily_exchange_rates"]
    assert (r.rows_in, r.rows_out, r.exact_duplicates_removed) == (3, 2, 1)
    rows = _rows(settings, "daily_exchange_rates", "date, exchange_rate")
    assert [str(row[0]) for row in rows] == ["2026-01-01", "2026-01-02"]


def test_reporte_json_y_silver_idempotente(built):
    settings, reports = built
    saved = json.loads(report_path(settings, "customers").read_text(encoding="utf-8"))
    assert QualityReport.model_validate(saved).rows_out == reports["customers"].rows_out
    again = build_silver(TABLES["customers"], settings)
    assert again.rows_out == reports["customers"].rows_out
    assert not list(silver_path(settings, "customers").parent.glob("*.tmp"))


def test_silver_sin_bronze_falla_claro(raw_settings):
    with pytest.raises(FileNotFoundError, match="Bronze"):
        build_silver(TABLES["customers"], raw_settings)


def _rewrite_bronze(settings, table, select_sql):
    """Reescribe el Bronze de una tabla con un SELECT sobre sí mismo."""
    from radia.etl.bronze import bronze_path

    path = bronze_path(settings, table)
    tmp = path.with_suffix(".rewrite.parquet")
    duckdb.sql(
        f"COPY ({select_sql.format(src=f'read_parquet({sql_literal(path)})')}) "
        f"TO {sql_literal(tmp)} (FORMAT parquet)"
    )
    tmp.replace(path)


def test_bronze_sin_pk_falla_y_no_pisa_silver(built):
    settings, _ = built
    before = silver_path(settings, "customers").read_bytes()
    _rewrite_bronze(settings, "customers", "SELECT * EXCLUDE (customer_id) FROM {src}")
    with pytest.raises(ValueError, match="PK"):
        build_silver(TABLES["customers"], settings)
    assert silver_path(settings, "customers").read_bytes() == before


def test_bronze_sin_filas_validas_no_pisa_silver(built):
    settings, _ = built
    before = silver_path(settings, "customers").read_bytes()
    _rewrite_bronze(
        settings,
        "customers",
        "SELECT * REPLACE (NULL::VARCHAR AS customer_id) FROM {src}",
    )
    with pytest.raises(ValueError, match="0 válidas"):
        build_silver(TABLES["customers"], settings)
    assert silver_path(settings, "customers").read_bytes() == before


def test_version_empatada_es_determinista_y_se_reporta(built):
    """Dos versiones distintas con la misma PK, orden y archivo: se elige igual
    en cada corrida y el reporte las cuenta como ambiguas."""
    settings, _ = built
    _rewrite_bronze(
        settings,
        "daily_exchange_rates",
        "SELECT * FROM {src} UNION ALL "
        "SELECT * REPLACE ('999.0' AS exchange_rate) FROM {src} LIMIT 1000000",
    )
    spec = TABLES["daily_exchange_rates"]
    first = build_silver(spec, settings)
    rows_first = _rows(settings, "daily_exchange_rates", "*")
    second = build_silver(spec, settings)
    assert _rows(settings, "daily_exchange_rates", "*") == rows_first
    assert first.ambiguous_versions > 0
    assert second.ambiguous_versions == first.ambiguous_versions


def _silver_col(settings, spec, csv, col):
    """Escribe el CSV como raw de la tabla, construye Bronze y Silver y lee la columna."""
    (settings.raw_dir / "data" / f"{spec.name}.csv").write_text(csv, encoding="utf-8")
    build_bronze(spec, settings)
    build_silver(spec, settings)
    pk = spec.primary_key[0]
    return [r[1] for r in _rows(settings, spec.name, f"{pk}, {col}")]


def test_value_map_country_traduce_y_respeta_trim(raw_settings):
    csv = "customer_id,country\nC1,México\nC2, México \nC3,Colombia\n"
    got = _silver_col(raw_settings, TABLES["customers"], csv, "country")
    assert got == ["Mexico", "Mexico", "Colombia"]


def test_value_map_product_type_traduce_solo_credito(raw_settings):
    csv = (
        "product_id,customer_id,product_type\n"
        "P1,C1,Tarjeta Crédito\n"
        "P2,C1,Préstamo Personal\n"
        "P3,C1,Préstamo Hipotecario\n"
        "P4,C1,Cuenta Ahorro\n"
    )
    got = _silver_col(raw_settings, TABLES["products"], csv, "product_type")
    assert got == ["Credit Card", "Personal Loan", "Mortgage", "Cuenta Ahorro"]


def test_value_map_nulo_y_vacio_pasan_sin_error(raw_settings):
    csv = "customer_id,country\nC1,\nC2,México\n"
    got = _silver_col(raw_settings, TABLES["customers"], csv, "country")
    assert got == [None, "Mexico"]


def test_value_map_con_comilla_simple_no_rompe_sql(raw_settings):
    spec = TABLES["customers"].model_copy(
        update={"value_map": {"country": {"Côte d'Ivoire": "O'Brien"}}}
    )
    csv = "customer_id,country\nC1,Côte d'Ivoire\nC2,Colombia\n"
    got = _silver_col(raw_settings, spec, csv, "country")
    assert got == ["O'Brien", "Colombia"]
