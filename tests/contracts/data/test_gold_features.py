"""Tests de radia.contracts.data.gold_features (C1)."""

import pandas as pd
import pandera.pandas as pa
import pytest

from radia.contracts.data import validate
from radia.contracts.data.gold_features import (
    CONTRACT_VERSION,
    GoldCustomerFeatures,
    make_gold_features,
)

ERRORS = (pa.errors.SchemaError, pa.errors.SchemaErrors)


@pytest.fixture
def df():
    return make_gold_features(n=50, seed=1)


def test_mock_valida():
    out = make_gold_features()
    assert len(out) == 1000
    validate(GoldCustomerFeatures, out)


def test_mock_determinista_por_seed():
    pd.testing.assert_frame_equal(
        make_gold_features(seed=3), make_gold_features(seed=3)
    )


def test_mock_seeds_distintos_difieren():
    a, b = make_gold_features(seed=1), make_gold_features(seed=2)
    assert not a["credit_score"].equals(b["credit_score"])


def test_mock_n_y_snapshot_date():
    out = make_gold_features(n=7, snapshot_date="2026-01-31")
    assert len(out) == 7
    assert (out["snapshot_date"] == pd.Timestamp("2026-01-31")).all()


def test_mock_n_cero_valida():
    assert len(make_gold_features(n=0)) == 0


def test_mock_nulos_cerca_de_5_por_ciento():
    out = make_gold_features(n=20000, seed=0)
    assert out["credit_score"].isna().mean() == pytest.approx(0.05, abs=0.01)
    assert out["monthly_income_usd"].isna().mean() == pytest.approx(0.05, abs=0.01)


def test_mock_sin_nulos_en_columnas_no_nullable():
    out = make_gold_features(n=500)
    for col in [
        "customer_id",
        "snapshot_date",
        "country",
        "segment",
        "n_credit_products",
    ]:
        assert out[col].notna().all()


def test_contract_version():
    assert CONTRACT_VERSION == "0.1.0"


def test_pais_fuera_del_enum_falla(df):
    df.loc[0, "country"] = "Chile"
    with pytest.raises(ERRORS):
        validate(GoldCustomerFeatures, df)


@pytest.mark.parametrize("bad", [299, 851, 0, -5])
def test_credit_score_fuera_de_rango_falla(df, bad):
    df["credit_score"] = df["credit_score"].astype("Int64")
    df.loc[0, "credit_score"] = bad
    with pytest.raises(ERRORS):
        validate(GoldCustomerFeatures, df)


@pytest.mark.parametrize("ok", [300, 850])
def test_credit_score_limites_validos(df, ok):
    df.loc[0, "credit_score"] = ok
    validate(GoldCustomerFeatures, df)


def test_columna_extra_falla_por_strict(df):
    df["extra"] = 1
    with pytest.raises(ERRORS):
        validate(GoldCustomerFeatures, df)


def test_columna_faltante_falla(df):
    with pytest.raises(ERRORS):
        validate(GoldCustomerFeatures, df.drop(columns=["segment"]))


def test_clave_duplicada_falla(df):
    df.loc[1, "customer_id"] = df.loc[0, "customer_id"]
    with pytest.raises(ERRORS):
        validate(GoldCustomerFeatures, df)


def test_mismo_cliente_distinta_fecha_es_valido(df):
    otro = df.iloc[[0]].copy()
    otro["snapshot_date"] = pd.Timestamp("2026-07-17")
    validate(GoldCustomerFeatures, pd.concat([df, otro]))


@pytest.mark.parametrize(
    "col",
    [
        "tenure_months",
        "monthly_income_usd",
        "total_credit_balance_usd",
        "debt_to_income",
        "credit_utilization",
        "avg_monthly_inflow_usd_6m",
        "income_stability_6m",
        "n_credit_products",
        "max_days_past_due",
    ],
)
def test_negativos_fallan(df, col):
    df.loc[0, col] = -1
    with pytest.raises(ERRORS):
        validate(GoldCustomerFeatures, df)


@pytest.mark.parametrize("col", ["customer_id", "country", "tenure_months"])
def test_nulos_no_permitidos_fallan(df, col):
    df[col] = df[col].astype(object)
    df.loc[0, col] = None
    with pytest.raises(ERRORS):
        validate(GoldCustomerFeatures, df)


def test_coerce_convierte_strings_de_fecha(df):
    df["snapshot_date"] = df["snapshot_date"].dt.strftime("%Y-%m-%d")
    out = validate(GoldCustomerFeatures, df)
    assert pd.api.types.is_datetime64_any_dtype(out["snapshot_date"])


def test_features_vetadas_para_cupo_existen_en_el_contrato():
    from radia.contracts.data.gold_features import LIMIT_MODEL_EXCLUDED_FEATURES

    columns = set(GoldCustomerFeatures.to_schema().columns)
    assert set(LIMIT_MODEL_EXCLUDED_FEATURES) <= columns
