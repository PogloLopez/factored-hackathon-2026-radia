"""Tests de radia.ml.limit_model."""

import numpy as np
import pandas as pd
import pytest

from radia.contracts.common import ProductCode
from radia.contracts.data.gold_features import make_gold_features
from radia.contracts.data.gold_labels import make_limit_labels
from radia.contracts.ml import LimitModel, LimitPrediction
from radia.ml.dataset import build_training_table
from radia.ml.limit_model import QuantileLimitModel

CARDS = (ProductCode.CC_BASIC, ProductCode.CC_GOLD, ProductCode.CC_BLACK)


@pytest.fixture(scope="module")
def features():
    return make_gold_features(300, seed=1)


@pytest.fixture(scope="module")
def table(features):
    labels = make_limit_labels(features, seed=1)
    return build_training_table(features, labels)


@pytest.fixture(scope="module")
def model(table):
    return QuantileLimitModel(max_iter=20).fit(table)


def test_cumple_el_protocol_limit_model(model):
    typed: LimitModel = model
    assert isinstance(typed.version, str) and typed.version
    assert callable(typed.predict)


@pytest.mark.parametrize(
    "quantiles",
    [
        (0.5, 0.5, 0.9),
        (0.9, 0.5, 0.1),
        (0.0, 0.5, 0.9),
        (0.1, 0.5, 1.0),
        (-0.1, 0.5, 0.9),
    ],
)
def test_cuantiles_invalidos_lanzan_value_error(quantiles):
    with pytest.raises(ValueError):
        QuantileLimitModel(quantiles=quantiles)


def test_predict_table_sin_fit_lanza_runtime_error(table):
    with pytest.raises(RuntimeError):
        QuantileLimitModel(max_iter=20).predict_table(table)


def test_fit_devuelve_self(table):
    m = QuantileLimitModel(max_iter=20)
    assert m.fit(table) is m


def test_predict_table_rango_ordenado_positivo_e_indice(model, table):
    out = model.predict_table(table)
    assert list(out.columns) == ["lower", "pred", "upper"]
    assert out.index.equals(table.index)
    assert (out["lower"] <= out["pred"]).all()
    assert (out["pred"] <= out["upper"]).all()
    assert (out > 0).all().all()


def test_predict_table_conserva_indice_no_contiguo(model, table):
    sub = table.iloc[::-3]
    out = model.predict_table(sub)
    assert out.index.equals(sub.index)


def test_predict_omite_ingreso_nan_o_cero(model, features):
    f = features.dropna(subset=["monthly_income_usd"]).head(5).copy()
    f.loc[f.index[0], "monthly_income_usd"] = np.nan
    f.loc[f.index[1], "monthly_income_usd"] = 0
    preds = model.predict(f, ProductCode.CC_GOLD)
    assert [p.customer_id for p in preds] == list(f["customer_id"].iloc[2:])


def test_predict_devuelve_predicciones_validas(model, features):
    f = features.dropna(subset=["monthly_income_usd"]).head(10)
    preds = model.predict(f, ProductCode.PERSONAL_LOAN)
    assert len(preds) == len(f)
    for p in preds:
        assert isinstance(p, LimitPrediction)
        assert p.model_version == model.version
        assert p.product_code == ProductCode.PERSONAL_LOAN
        assert 0 < p.lower_usd <= p.suggested_limit_usd <= p.upper_usd


def test_predict_features_vacias_devuelve_lista_vacia(model, features):
    assert model.predict(features.iloc[0:0], ProductCode.CC_BASIC) == []


def test_predict_sin_ingreso_devuelve_lista_vacia(model, features):
    f = features.head(5).copy()
    f["monthly_income_usd"] = np.nan
    assert model.predict(f, ProductCode.CC_BASIC) == []


def test_tres_tarjetas_reciben_la_misma_prediccion(model, features):
    f = features.dropna(subset=["monthly_income_usd"]).head(10)
    basic, gold, black = (
        [
            (p.suggested_limit_usd, p.lower_usd, p.upper_usd)
            for p in model.predict(f, code)
        ]
        for code in CARDS
    )
    assert basic == gold == black


def test_mismo_seed_mismo_resultado(table):
    a = QuantileLimitModel(seed=3, max_iter=20).fit(table).predict_table(table)
    b = QuantileLimitModel(seed=3, max_iter=20).fit(table).predict_table(table)
    pd.testing.assert_frame_equal(a, b)
