"""Tests de la capa Gold con un Silver sintético mínimo.

Casos: cliente con varios créditos y monedas, cliente sin crédito, ingreso y
credit_score nulos, tasa solo inversa (USD -> COP), tasa posterior al corte,
depósitos fuera de la ventana de 6 meses, posteriores al corte, rechazados y
de otro tipo, y un cliente registrado después del corte.
"""

import tempfile
from datetime import date
from pathlib import Path

import duckdb
import pandas as pd
import pytest

from radia.config import Settings
from radia.contracts.data import validate
from radia.contracts.data.gold_features import GoldCustomerFeatures
from radia.contracts.data.gold_labels import GoldLimitLabels
from radia.etl.bronze import sql_literal
from radia.etl.gold import build_features, build_limit_labels, gold_path
from radia.etl.silver import ident, silver_path
from radia.etl.tables import TABLES

SNAPSHOT = date(2026, 6, 17)

SILVER = {
    "customers": """
        SELECT * FROM (VALUES
            ('C1', 'Mexico', 'Premium', 'Active', 750, 20000.00, TIMESTAMP '2024-06-17 10:00:00'),
            ('C2', 'Colombia', 'Basic', 'Active', 600, 4000000.00, TIMESTAMP '2026-01-10 00:00:00'),
            ('C3', 'Argentina', 'Plus', 'Active', NULL, 1000000.00, TIMESTAMP '2025-06-17 00:00:00'),
            ('C4', 'Mexico', 'Student', 'Inactive', 700, NULL, TIMESTAMP '2025-06-17 00:00:00'),
            ('C5', 'Mexico', 'Basic', 'Active', 800, 10000.00, TIMESTAMP '2026-07-01 00:00:00')
        ) t(customer_id, country, segment, customer_status, credit_score,
            estimated_monthly_income, registration_date)
    """,
    "products": """
        SELECT * FROM (VALUES
            ('P1', 'C1', 'Credit Card', 'MXN', 10000.00, 40000.00, 'Active', NULL),
            ('P2', 'C1', 'Personal Loan', 'USD', 1000.00, 5000.00, 'Active', 15),
            ('P3', 'C1', 'Mortgage', 'MXN', 0.00, 1000000.00, 'Closed', 90),
            ('P4', 'C1', 'Savings Account', 'MXN', 99999.00, NULL, 'Active', NULL),
            ('P5', 'C3', 'Credit Card', 'ARS', 500000.00, 0.00, 'Active', NULL),
            ('P6', 'C4', 'Credit Card', 'MXN', 2000.00, 10000.00, 'Blocked', 45)
        ) t(product_id, customer_id, product_type, currency, current_balance,
            credit_limit, product_status, days_past_due)
    """,
    "daily_exchange_rates": """
        SELECT * FROM (VALUES
            (DATE '2026-06-01', 'MXN', 'USD', 0.05),
            (DATE '2026-06-17', 'MXN', 'USD', 0.06),
            (DATE '2026-06-20', 'MXN', 'USD', 0.10),
            (DATE '2026-06-10', 'USD', 'COP', 4000.0),
            (DATE '2026-06-15', 'ARS', 'USD', 0.001)
        ) t(date, source_currency, target_currency, exchange_rate)
    """,
    "transactions": """
        SELECT * FROM (VALUES
            ('T1', TIMESTAMP '2026-06-10 12:00:00', 'C1', 'Deposit', 'Approved', 1000.0),
            ('T2', TIMESTAMP '2026-05-10 12:00:00', 'C1', 'Deposit', 'Approved', 1000.0),
            ('T3', TIMESTAMP '2026-01-10 12:00:00', 'C1', 'Deposit', 'Approved', 1000.0),
            ('T4', TIMESTAMP '2025-12-10 12:00:00', 'C1', 'Deposit', 'Approved', 5000.0),
            ('T5', TIMESTAMP '2026-06-20 12:00:00', 'C1', 'Deposit', 'Approved', 9999.0),
            ('T6', TIMESTAMP '2026-06-05 12:00:00', 'C1', 'Deposit', 'Declined', 7777.0),
            ('T7', TIMESTAMP '2026-06-05 12:00:00', 'C1', 'Withdrawal', 'Approved', 555.0),
            ('T8', TIMESTAMP '2026-06-01 09:00:00', 'C2', 'Deposit', 'Approved', 600.0),
            ('T9', TIMESTAMP '2026-05-01 09:00:00', 'C2', 'Deposit', 'Approved', 600.0),
            ('T10', TIMESTAMP '2026-04-01 09:00:00', 'C2', 'Deposit', 'Approved', 600.0),
            ('T11', TIMESTAMP '2026-03-01 09:00:00', 'C2', 'Deposit', 'Approved', 600.0),
            ('T12', TIMESTAMP '2026-02-01 09:00:00', 'C2', 'Deposit', 'Approved', 600.0),
            ('T13', TIMESTAMP '2026-01-01 09:00:00', 'C2', 'Deposit', 'Approved', 600.0)
        ) t(transaction_id, transaction_date, customer_id, transaction_type,
            transaction_status, amount_usd)
    """,
}


def write_silver(settings: Settings) -> None:
    """Escribe cada tabla con el esquema completo de su spec, como Silver real.

    Las columnas que el caso no define quedan NULL con su tipo.
    """
    con = duckdb.connect()
    for table, sql in SILVER.items():
        given = {r[0] for r in con.execute(f"DESCRIBE {sql}").fetchall()}
        select = ", ".join(
            f"CAST({ident(c)} AS {t}) AS {ident(c)}"
            if c in given
            else f"NULL::{t} AS {ident(c)}"
            for c, t in TABLES[table].columns.items()
        )
        path = silver_path(settings, table)
        path.parent.mkdir(parents=True, exist_ok=True)
        con.execute(
            f"COPY (SELECT {select} FROM ({sql})) TO {sql_literal(path)} (FORMAT parquet)"
        )


@pytest.fixture
def silver_settings():
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        settings = Settings(_env_file=None, data_dir=Path(tmp))
        write_silver(settings)
        yield settings


@pytest.fixture
def features(silver_settings):
    df = build_features(silver_settings, SNAPSHOT)
    return df.set_index("customer_id")


def test_features_cumplen_c1_y_se_escriben(silver_settings):
    df = build_features(silver_settings, SNAPSHOT)
    path = gold_path(silver_settings, "customer_features")
    stored = duckdb.sql(f"SELECT * FROM read_parquet({sql_literal(path)})").df()
    stored["credit_score"] = stored["credit_score"].astype("Int64")
    validate(GoldCustomerFeatures, stored)
    assert list(stored.columns) == list(df.columns)
    assert (df["snapshot_date"] == pd.Timestamp(SNAPSHOT)).all()


def test_cliente_registrado_despues_del_corte_no_entra(features):
    assert sorted(features.index) == ["C1", "C2", "C3", "C4"]


def test_ingreso_en_usd_con_tasa_al_corte(features):
    # MXN usa la tasa del 17-jun (0.06), no la del 20-jun ni la del 1-jun.
    assert features.loc["C1", "monthly_income_usd"] == pytest.approx(1200.0)
    # COP solo tiene USD -> COP: se usa la inversa.
    assert features.loc["C2", "monthly_income_usd"] == pytest.approx(1000.0)
    assert features.loc["C3", "monthly_income_usd"] == pytest.approx(1000.0)
    assert pd.isna(features.loc["C4", "monthly_income_usd"])


def test_credito_en_usd_por_moneda_del_producto(features):
    c1 = features.loc["C1"]
    # Tarjeta MXN 10000 * 0.06 + préstamo USD 1000. Hipoteca cerrada y ahorro no.
    assert c1["total_credit_balance_usd"] == pytest.approx(1600.0)
    assert c1["n_credit_products"] == 2
    assert c1["credit_utilization"] == pytest.approx(0.25)
    assert c1["debt_to_income"] == pytest.approx(1600 / 1200)
    # La mora de la hipoteca cerrada no cuenta. Mora nula en la tarjeta cuenta 0.
    assert c1["max_days_past_due"] == 15
    assert c1["tenure_months"] == 24


def test_cliente_sin_credito_tiene_ceros(features):
    c2 = features.loc["C2"]
    assert c2["total_credit_balance_usd"] == 0
    assert c2["n_credit_products"] == 0
    assert c2["max_days_past_due"] == 0
    assert c2["debt_to_income"] == 0
    assert pd.isna(c2["credit_utilization"])
    assert c2["tenure_months"] == 5


def test_cupo_cero_y_producto_bloqueado(features):
    # Tarjeta con cupo 0: utilización nula, saldo sí cuenta.
    assert pd.isna(features.loc["C3", "credit_utilization"])
    assert features.loc["C3", "total_credit_balance_usd"] == pytest.approx(500.0)
    assert pd.isna(features.loc["C3", "credit_score"])
    # Tarjeta bloqueada: no es crédito activo, pero su mora sí cuenta.
    c4 = features.loc["C4"]
    assert (c4["n_credit_products"], c4["max_days_past_due"]) == (0, 45)
    assert pd.isna(c4["debt_to_income"])


def test_ingresos_solo_dentro_de_la_ventana(features):
    # C1: meses [1000, 1000, 0, 0, 0, 1000]. Fuera: el de dic-2025, el posterior
    # al corte, el rechazado y el retiro.
    assert features.loc["C1", "avg_monthly_inflow_usd_6m"] == pytest.approx(500.0)
    assert features.loc["C1", "income_stability_6m"] == pytest.approx(1.0)
    assert features.loc["C2", "avg_monthly_inflow_usd_6m"] == pytest.approx(600.0)
    assert features.loc["C2", "income_stability_6m"] == pytest.approx(0.0)
    assert features.loc["C3", "avg_monthly_inflow_usd_6m"] == 0
    assert pd.isna(features.loc["C3", "income_stability_6m"])


def test_corte_por_defecto_es_la_ultima_transaccion(silver_settings):
    df = build_features(silver_settings).set_index("customer_id")
    assert (df["snapshot_date"] == pd.Timestamp("2026-06-20")).all()
    # Ahora sí entra el depósito del 20-jun y la tasa MXN de ese día.
    assert df.loc["C1", "monthly_income_usd"] == pytest.approx(2000.0)
    assert df.loc["C1", "avg_monthly_inflow_usd_6m"] == pytest.approx(
        (1000 + 9999 + 1000 + 1000) / 6
    )


def test_etiquetas_de_cupo_cumplen_c2(silver_settings):
    df = build_limit_labels(silver_settings, SNAPSHOT)
    validate(GoldLimitLabels, df)
    assert gold_path(silver_settings, "limit_labels").exists()
    limits = dict(zip(df["product_id"], df["credit_limit_usd"], strict=True))
    # P4 no es crédito y P5 tiene cupo 0.
    assert limits == pytest.approx(
        {"P1": 2400.0, "P2": 5000.0, "P3": 60000.0, "P6": 600.0}
    )
    assert set(df["product_family"]) == {"Credit Card", "Personal Loan", "Mortgage"}


def test_falta_silver(silver_settings):
    silver_path(silver_settings, "transactions").unlink()
    with pytest.raises(FileNotFoundError, match="transactions"):
        build_features(silver_settings, SNAPSHOT)
