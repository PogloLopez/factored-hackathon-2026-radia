"""Tests de radia.contracts.policy (C7)."""

import pytest
from pydantic import ValidationError

from radia.contracts.ml import LimitPrediction, RiskEstimate
from radia.contracts.policy import (
    CustomerRequest,
    EligibilityPolicy,
    PolicyDecision,
    PolicyInput,
)


def request(**over) -> CustomerRequest:
    return CustomerRequest(**{"product_code": "CC_GOLD", **over})


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


def risk(**over) -> RiskEstimate:
    base = {"customer_id": "c1", "prob_delinquent_30p": 0.1, "model_version": "v1"}
    return RiskEstimate(**{**base, **over})


def pinput(**over) -> PolicyInput:
    base = {
        "customer_id": "c1",
        "customer_status": "Active",
        "segment": "Plus",
        "max_days_past_due": 0,
        "monthly_income_usd": 2000.0,
        "score": 700,
        "request": request(),
    }
    return PolicyInput(**{**base, **over})


def decision(**over) -> PolicyDecision:
    base = {
        "customer_id": "c1",
        "product_code": "CC_GOLD",
        "attention_level": "automatic",
        "score": 760,
        "band": "high",
        "exposure": "low",
        "offered_limit_usd": 1000.0,
        "negotiation_min_usd": 800.0,
        "negotiation_max_usd": 1200.0,
        "limit_model_version": "m1",
        "reasons": ["score_high"],
        "policy_version": "p1",
    }
    return PolicyDecision(**{**base, **over})


# CustomerRequest
def test_request_valid():
    r = request(requested_amount_usd=500.0)
    assert r.requested_amount_usd == 500.0
    assert r.customer_requests_human is False


@pytest.mark.parametrize("amount", [0, -1.0])
def test_request_amount_not_positive_fails(amount):
    with pytest.raises(ValidationError):
        request(requested_amount_usd=amount)


# PolicyInput
def test_input_valid_without_predictions():
    p = pinput()
    assert p.limit_prediction is None and p.risk_estimate is None


def test_input_valid_with_predictions():
    p = pinput(limit_prediction=limit(), risk_estimate=risk())
    assert p.limit_prediction.customer_id == "c1"


def test_input_limit_other_customer_fails():
    with pytest.raises(ValidationError):
        pinput(limit_prediction=limit(customer_id="c2"))


def test_input_limit_other_product_fails():
    with pytest.raises(ValidationError):
        pinput(limit_prediction=limit(product_code="CC_PLATINUM"))


def test_input_risk_other_customer_fails():
    with pytest.raises(ValidationError):
        pinput(risk_estimate=risk(customer_id="c2"))


@pytest.mark.parametrize("score", [149, 951])
def test_input_score_out_of_range_fails(score):
    with pytest.raises(ValidationError):
        pinput(score=score)


@pytest.mark.parametrize("score", [150, 950])
def test_input_score_bounds_pass(score):
    assert pinput(score=score).score == score


# PolicyDecision
def test_decision_valid():
    d = decision()
    assert d.synthetic_policy is True and d.alerts == []


def test_decision_not_eligible_with_limit_fails():
    with pytest.raises(ValidationError):
        decision(attention_level="not_eligible")


def test_decision_not_eligible_without_limit_passes():
    d = decision(
        attention_level="not_eligible",
        score=None,
        band=None,
        offered_limit_usd=None,
        negotiation_min_usd=None,
        negotiation_max_usd=None,
    )
    assert d.offered_limit_usd is None


@pytest.mark.parametrize(
    "over",
    [
        {"negotiation_min_usd": None, "negotiation_max_usd": None},
        {"offered_limit_usd": None},
        {"negotiation_max_usd": None},
    ],
)
def test_decision_partial_limits_fail(over):
    with pytest.raises(ValidationError):
        decision(**over)


def test_decision_no_limits_at_all_passes():
    d = decision(
        attention_level="analyst",
        offered_limit_usd=None,
        negotiation_min_usd=None,
        negotiation_max_usd=None,
    )
    assert d.negotiation_min_usd is None


@pytest.mark.parametrize("offered", [700.0, 1300.0])
def test_decision_offered_outside_range_fails(offered):
    with pytest.raises(ValidationError):
        decision(offered_limit_usd=offered)


def test_decision_offered_at_bounds_passes():
    assert decision(offered_limit_usd=800.0).offered_limit_usd == 800.0
    assert decision(offered_limit_usd=1200.0).offered_limit_usd == 1200.0


def test_decision_empty_reasons_fails():
    with pytest.raises(ValidationError):
        decision(reasons=[])


def test_decision_synthetic_false_fails():
    with pytest.raises(ValidationError):
        decision(synthetic_policy=False)


@pytest.mark.parametrize("bad", [float("inf"), float("nan")])
@pytest.mark.parametrize(
    "field",
    ["offered_limit_usd", "negotiation_min_usd", "negotiation_max_usd"],
)
def test_decision_inf_nan_fails(field, bad):
    with pytest.raises(ValidationError):
        decision(**{field: bad})


@pytest.mark.parametrize("bad", [float("inf"), float("nan")])
def test_input_and_request_inf_nan_fail(bad):
    with pytest.raises(ValidationError):
        request(requested_amount_usd=bad)
    with pytest.raises(ValidationError):
        pinput(monthly_income_usd=bad)


# frozen y extra=forbid
def test_frozen():
    with pytest.raises(ValidationError):
        decision().offered_limit_usd = 900.0
    with pytest.raises(ValidationError):
        request().customer_requests_human = True
    with pytest.raises(ValidationError):
        pinput().score = 500


def test_extra_forbidden():
    with pytest.raises(ValidationError):
        request(foo=1)
    with pytest.raises(ValidationError):
        pinput(foo=1)
    with pytest.raises(ValidationError):
        decision(foo=1)


# Protocol
def test_minimal_policy_is_callable():
    class Minimal:
        version = "p1"

        def decide(self, policy_input: PolicyInput) -> PolicyDecision:
            return decision(customer_id=policy_input.customer_id)

    policy: EligibilityPolicy = Minimal()
    out = policy.decide(pinput())
    assert out.customer_id == "c1" and policy.version == "p1"


@pytest.mark.parametrize(
    "over",
    [
        {"score": None, "band": None},  # automático sin puntaje
        {
            "offered_limit_usd": None,
            "negotiation_min_usd": None,
            "negotiation_max_usd": None,
        },  # automático sin cupo
        {"score": None},  # score y band no van juntos
        {"band": None},
        {"limit_model_version": None},  # cupo sin versión del modelo
        {"reasons": ["Banda alta"]},  # código que no es snake_case
        {"alerts": [""]},
    ],
)
def test_decision_invariantes_nuevas_fallan(over):
    with pytest.raises(ValidationError):
        decision(**over)


def test_decision_alternativa_y_preferencial():
    d = decision(
        attention_level="not_eligible",
        offered_limit_usd=None,
        negotiation_min_usd=None,
        negotiation_max_usd=None,
        limit_model_version=None,
        alternative_product_code="CC_BASIC",
        preferential=True,
    )
    assert d.alternative_product_code == "CC_BASIC"
    assert d.preferential


@pytest.mark.parametrize("field", ["monthly_income_usd"])
def test_input_ingreso_cero_falla(field):
    with pytest.raises(ValidationError):
        pinput(**{field: 0})


def test_request_ingreso_declarado_cero_falla():
    with pytest.raises(ValidationError):
        CustomerRequest(product_code="CC_BASIC", declared_monthly_income_usd=0)
