"""Tests de la capa Gold con el Silver sintético de `conftest.py`."""

from datetime import date

import duckdb
import pandas as pd
import pytest

from radia.contracts.data import validate
from radia.contracts.data.gold_features import GoldCustomerFeatures
from radia.contracts.data.gold_labels import GoldLimitLabels
from radia.etl.bronze import sql_literal
from radia.etl.gold import build_features, build_limit_labels, gold_path
from radia.etl.silver import silver_path

SNAPSHOT = date(2026, 6, 17)


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


def _add_products(settings, values: str) -> None:
    """Agrega productos de C1 al Silver de products (el resto de columnas NULL)."""
    path = silver_path(settings, "products")
    con = duckdb.connect()
    con.execute(
        f"""
        COPY (
            SELECT * FROM read_parquet({sql_literal(path)})
            UNION ALL BY NAME
            SELECT * FROM (VALUES {values})
                t(product_id, customer_id, product_type, currency,
                  current_balance, credit_limit, product_status)
        ) TO {sql_literal(path.with_suffix(".new"))} (FORMAT parquet)
        """
    )
    con.close()
    path.with_suffix(".new").replace(path)


def test_utilizacion_ignora_tarjetas_sin_cupo(silver_settings):
    # Tarjeta activa con cupo 0 y saldo alto: no debe inflar la utilización.
    _add_products(
        silver_settings, "('P7', 'C1', 'Credit Card', 'MXN', 30000.00, 0.00, 'Active')"
    )
    c1 = build_features(silver_settings, SNAPSHOT).set_index("customer_id").loc["C1"]
    assert c1["credit_utilization"] == pytest.approx(0.25)
    # El saldo total de crédito sí incluye la tarjeta sin cupo (30000 * 0.06).
    assert c1["total_credit_balance_usd"] == pytest.approx(1600.0 + 1800.0)
    assert c1["n_credit_products"] == 3


def test_sin_tasa_de_cambio_los_ratios_quedan_nulos(silver_settings):
    # CLP no tiene tasa a USD: el saldo total sería parcial.
    _add_products(
        silver_settings,
        "('P8', 'C1', 'Personal Loan', 'CLP', 500000.00, 900000.00, 'Active')",
    )
    df = build_features(silver_settings, SNAPSHOT)
    c1 = df.set_index("customer_id").loc["C1"]
    assert pd.isna(c1["debt_to_income"])
    assert pd.isna(c1["credit_utilization"])
    # Los demás clientes no se ven afectados.
    c3 = df.set_index("customer_id").loc["C3"]
    assert c3["total_credit_balance_usd"] == pytest.approx(500.0)
    # La salida sigue cumpliendo C1.
    stored = duckdb.sql(
        f"SELECT * FROM read_parquet({sql_literal(gold_path(silver_settings, 'customer_features'))})"
    ).df()
    stored["credit_score"] = stored["credit_score"].astype("Int64")
    validate(GoldCustomerFeatures, stored)


def _add_transactions(settings, values: str) -> None:
    """Agrega depósitos al Silver de transactions (el resto de columnas NULL)."""
    path = silver_path(settings, "transactions")
    con = duckdb.connect()
    con.execute(
        f"""
        COPY (
            SELECT * FROM read_parquet({sql_literal(path)})
            UNION ALL BY NAME
            SELECT * FROM (VALUES {values})
                t(transaction_id, transaction_date, customer_id, transaction_type,
                  transaction_status, amount, currency, amount_usd)
        ) TO {sql_literal(path.with_suffix(".new"))} (FORMAT parquet)
        """
    )
    con.close()
    path.with_suffix(".new").replace(path)


def test_deposito_sin_amount_usd_usa_amount_con_la_tasa(silver_settings, caplog):
    # C2 deposita 10000 MXN sin amount_usd: 10000 * 0.06 = 600 USD en el mes 0.
    # Un depósito en CLP sin amount_usd ni tasa se descarta y se avisa.
    _add_transactions(
        silver_settings,
        "('T20', TIMESTAMP '2026-06-05 09:00:00', 'C2', 'Deposit', 'Approved',"
        " 10000.00, 'MXN', NULL::DECIMAL(15,2)),"
        " ('T21', TIMESTAMP '2026-06-06 09:00:00', 'C2', 'Deposit', 'Approved',"
        " 50000.00, 'CLP', NULL::DECIMAL(15,2))",
    )
    with caplog.at_level("WARNING", logger="radia.etl.gold"):
        df = build_features(silver_settings, SNAPSHOT).set_index("customer_id")
    assert df.loc["C2", "avg_monthly_inflow_usd_6m"] == pytest.approx(
        (600 * 6 + 600) / 6
    )
    assert "1 depósitos sin amount_usd ni tasa" in caplog.text
