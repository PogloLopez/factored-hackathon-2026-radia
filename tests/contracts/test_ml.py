"""Tests de radia.contracts.ml (C4 y C5)."""

import pandas as pd
import pytest
from pydantic import ValidationError

from radia.contracts.common import ProductCode
from radia.contracts.ml import (
    LimitModel,
    LimitPrediction,
    RiskEstimate,
    RiskModel,
)


def limit(**over) -> LimitPrediction:
    base = {
        "customer_id": "c1",
        "product_code": "CC_GOLD",
        "suggested_limit_usd": 1000.0,
        "lower_usd": 800.0,
        "upper_usd": 1200.0,
        "model_version": "v1",
    }
    return LimitPrediction(**{**base, **over})


def test_limit_valid():
    p = limit()
    assert p.suggested_limit_usd == 1000.0


def test_limit_equal_bounds_pass():
    p = limit(lower_usd=500.0, suggested_limit_usd=500.0, upper_usd=500.0)
    assert p.lower_usd == p.upper_usd == 500.0


@pytest.mark.parametrize(
    "over",
    [
        {"suggested_limit_usd": 799.0},
        {"suggested_limit_usd": 1201.0},
        {"lower_usd": 1300.0},
        {"upper_usd": 700.0},
    ],
)
def test_limit_out_of_range_fails(over):
    with pytest.raises(ValidationError):
        limit(**over)


@pytest.mark.parametrize("field", ["suggested_limit_usd", "lower_usd", "upper_usd"])
@pytest.mark.parametrize("value", [0, -1.0])
def test_limit_non_positive_fails(field, value):
    with pytest.raises(ValidationError):
        limit(**{field: value})


def test_limit_product_code_coerced():
    assert limit(product_code="MORTGAGE").product_code is ProductCode.MORTGAGE


def test_limit_product_code_invalid_fails():
    with pytest.raises(ValidationError):
        limit(product_code="NOPE")


def test_limit_extra_forbidden():
    with pytest.raises(ValidationError):
        limit(extra_field=1)


def test_limit_frozen():
    p = limit()
    with pytest.raises(ValidationError):
        p.suggested_limit_usd = 5.0


@pytest.mark.parametrize("field", ["customer_id", "model_version"])
def test_limit_empty_strings_fail(field):
    with pytest.raises(ValidationError):
        limit(**{field: ""})


@pytest.mark.parametrize("prob", [0, 1, 0.5])
def test_risk_valid_probs(prob):
    assert RiskEstimate(customer_id="c1", prob_delinquent_30p=prob, model_version="v1")


@pytest.mark.parametrize("prob", [-0.01, 1.01])
def test_risk_invalid_probs_fail(prob):
    with pytest.raises(ValidationError):
        RiskEstimate(customer_id="c1", prob_delinquent_30p=prob, model_version="v1")


def test_risk_empty_customer_fails():
    with pytest.raises(ValidationError):
        RiskEstimate(customer_id="", prob_delinquent_30p=0.1, model_version="v1")


def test_risk_extra_forbidden_and_frozen():
    with pytest.raises(ValidationError):
        RiskEstimate(customer_id="c", prob_delinquent_30p=0.1, model_version="v", x=1)
    r = RiskEstimate(customer_id="c", prob_delinquent_30p=0.1, model_version="v")
    with pytest.raises(ValidationError):
        r.prob_delinquent_30p = 0.2


class _DummyLimit:
    version = "dummy"

    def predict(self, features: pd.DataFrame, product_code: ProductCode):
        return [
            limit(customer_id=str(c), product_code=product_code)
            for c in features["customer_id"]
        ]


class _DummyRisk:
    version = "dummy"

    def predict(self, features: pd.DataFrame):
        return [
            RiskEstimate(customer_id=str(c), prob_delinquent_30p=0.1, model_version="d")
            for c in features["customer_id"]
        ]


def test_limit_model_structural():
    model: LimitModel = _DummyLimit()
    out = model.predict(pd.DataFrame({"customer_id": ["a", "b"]}), ProductCode.CC_BASIC)
    assert [p.customer_id for p in out] == ["a", "b"]
    assert out[0].product_code is ProductCode.CC_BASIC


def test_risk_model_structural():
    model: RiskModel = _DummyRisk()
    out = model.predict(pd.DataFrame({"customer_id": ["a"]}))
    assert out[0].prob_delinquent_30p == 0.1


@pytest.mark.parametrize("field", ["lower_usd", "upper_usd", "suggested_limit_usd"])
def test_limit_prediction_rechaza_infinito(field):
    data = {
        "customer_id": "C1",
        "product_code": "CC_BASIC",
        "suggested_limit_usd": 450.0,
        "lower_usd": 360.0,
        "upper_usd": 540.0,
        "model_version": "v",
        field: float("inf"),
    }
    with pytest.raises(ValidationError):
        LimitPrediction(**data)
