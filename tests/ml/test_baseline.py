"""Tests de radia.ml.baseline."""

import pandas as pd
import pytest

from radia.contracts.common import ProductCode
from radia.contracts.data.gold_features import make_gold_features
from radia.contracts.ml import LimitModel
from radia.ml.baseline import MULTIPLES, IncomeMultipleBaseline


def test_cumple_el_protocolo_limit_model():
    model: LimitModel = IncomeMultipleBaseline()
    assert model.version.startswith("baseline-")


@pytest.mark.parametrize("product", list(ProductCode))
def test_todo_producto_tiene_multiplo(product):
    assert MULTIPLES[product] > 0


def test_multiplo_y_rango():
    df = pd.DataFrame({"customer_id": ["C1"], "monthly_income_usd": [1000.0]})
    (pred,) = IncomeMultipleBaseline().predict(df, ProductCode.CC_GOLD)
    assert pred.suggested_limit_usd == 2000.0
    assert pred.lower_usd == pytest.approx(1600.0)
    assert pred.upper_usd == pytest.approx(2400.0)
    assert pred.product_code == ProductCode.CC_GOLD


def test_sin_ingreso_no_hay_prediccion():
    df = pd.DataFrame(
        {"customer_id": ["C1", "C2", "C3"], "monthly_income_usd": [None, 0.0, 500.0]}
    )
    preds = IncomeMultipleBaseline().predict(df, "CC_BASIC")
    assert [p.customer_id for p in preds] == ["C3"]


def test_sobre_el_mock_de_c1():
    features = make_gold_features(200, seed=3)
    preds = IncomeMultipleBaseline().predict(features, ProductCode.PERSONAL_LOAN)
    assert len(preds) == int((features["monthly_income_usd"] > 0).sum())
