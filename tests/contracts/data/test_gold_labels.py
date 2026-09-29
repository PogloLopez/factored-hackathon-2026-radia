"""Tests de radia.contracts.data.gold_labels (C2)."""

import pandas as pd
import pandera.pandas as pa
import pytest

from radia.contracts.data import validate
from radia.contracts.data.gold_features import make_gold_features
from radia.contracts.data.gold_labels import (
    GoldDelinquencyLabels,
    GoldLimitLabels,
    make_delinquency_labels,
    make_limit_labels,
)

ERRORS = (pa.errors.SchemaError, pa.errors.SchemaErrors)


@pytest.fixture
def features():
    return make_gold_features(n=200, seed=1)


@pytest.fixture
def limits(features):
    return make_limit_labels(features, seed=1)


@pytest.fixture
def delinq(features):
    return make_delinquency_labels(features, seed=1)


def test_limit_mock_valida(limits):
    assert len(limits) > 0
    validate(GoldLimitLabels, limits)


def test_delinquency_mock_valida(features, delinq):
    assert len(delinq) == len(features)
    validate(GoldDelinquencyLabels, delinq)


def test_limit_mock_determinista(features):
    pd.testing.assert_frame_equal(
        make_limit_labels(features, seed=3), make_limit_labels(features, seed=3)
    )


def test_delinquency_mock_determinista(features):
    pd.testing.assert_frame_equal(
        make_delinquency_labels(features, seed=3),
        make_delinquency_labels(features, seed=3),
    )


def test_seeds_distintos_difieren(features):
    a = make_limit_labels(features, seed=1)
    b = make_limit_labels(features, seed=2)
    assert not a["credit_limit_usd"].equals(b["credit_limit_usd"])


def test_limit_solo_clientes_con_credito(features, limits):
    owners = features[features["n_credit_products"] > 0]
    assert len(limits) == len(owners)
    assert set(limits["customer_id"]) == set(owners["customer_id"])
    no_credit = features[features["n_credit_products"] == 0]["customer_id"]
    assert not set(limits["customer_id"]) & set(no_credit)


def test_delinquency_horizonte(features):
    out = make_delinquency_labels(features, horizon_days=30)
    assert ((out["label_date"] - out["feature_cutoff_date"]).dt.days == 30).all()


def test_features_vacias_dan_tablas_vacias_validas(features):
    empty = features.iloc[0:0]
    lim = make_limit_labels(empty)
    dq = make_delinquency_labels(empty)
    assert len(lim) == 0
    assert len(dq) == 0
    validate(GoldLimitLabels, lim)
    validate(GoldDelinquencyLabels, dq)


def test_limit_sin_clientes_con_credito(features):
    none = features.assign(n_credit_products=0)
    assert len(make_limit_labels(none)) == 0


def test_limit_family_fuera_de_enum(limits):
    bad = limits.copy()
    bad.loc[0, "product_family"] = "crypto"
    with pytest.raises(ERRORS):
        validate(GoldLimitLabels, bad)


@pytest.mark.parametrize("value", [0.0, -5.0])
def test_limit_cupo_no_positivo(limits, value):
    bad = limits.copy()
    bad.loc[0, "credit_limit_usd"] = value
    with pytest.raises(ERRORS):
        validate(GoldLimitLabels, bad)


def test_limit_clave_duplicada(limits):
    bad = pd.concat([limits, limits.iloc[[0]]])
    with pytest.raises(ERRORS):
        validate(GoldLimitLabels, bad)


def test_limit_columna_extra(limits):
    with pytest.raises(ERRORS):
        validate(GoldLimitLabels, limits.assign(extra=1))


def test_delinquency_clave_duplicada(delinq):
    bad = pd.concat([delinq, delinq.iloc[[0]]])
    with pytest.raises(ERRORS):
        validate(GoldDelinquencyLabels, bad)


def test_delinquency_columna_extra(delinq):
    with pytest.raises(ERRORS):
        validate(GoldDelinquencyLabels, delinq.assign(extra=1))


def test_delinquency_label_igual_al_corte(delinq):
    bad = delinq.copy()
    bad.loc[0, "label_date"] = bad.loc[0, "feature_cutoff_date"]
    with pytest.raises(ERRORS):
        validate(GoldDelinquencyLabels, bad)


def test_delinquency_label_antes_del_corte(delinq):
    bad = delinq.copy()
    bad.loc[0, "label_date"] = bad.loc[0, "feature_cutoff_date"] - pd.Timedelta(days=1)
    with pytest.raises(ERRORS):
        validate(GoldDelinquencyLabels, bad)
