"""Tests de radia.contracts.handoff (C9)."""

import json
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from radia.contracts.handoff import (
    CaseStatus,
    HandoffCase,
    HandoffType,
    Priority,
)
from radia.contracts.policy import PolicyDecision

AWARE = datetime(2026, 9, 28, 12, 0, tzinfo=UTC)


def decision(**over) -> PolicyDecision:
    base = {
        "customer_id": "DEMO000001",
        "product_code": "PERSONAL_LOAN",
        "attention_level": "analyst",
        "score": 620,
        "band": "medium",
        "exposure": "medium",
        "offered_limit_usd": 4200.0,
        "negotiation_min_usd": 3360.0,
        "negotiation_max_usd": 5040.0,
        "limit_model_version": "baseline-income-multiple-0.1.0",
        "reasons": ["band_medium_exposure_medium"],
        "alerts": ["declared_income_mismatch"],
        "policy_version": "synthetic-policy-0.1.0",
    }
    return PolicyDecision(**{**base, **over})


def case_data(**over) -> dict:
    base = {
        "case_id": "CASE-0001",
        "handoff_type": "analyst_review",
        "trigger_reason": "Banda media con exposición media",
        "customer_id": "DEMO000001",
        "session_id": "S-1",
        "request_summary": "El cliente solicita un préstamo personal de 5.000 USD",
        "verified_facts": ["Cliente activo"],
        "policy_decision": decision(),
        "created_at": AWARE,
    }
    return {**base, **over}


def test_valid_case_defaults():
    c = HandoffCase(**case_data())
    assert c.status == CaseStatus.PENDING
    assert c.priority == Priority.NORMAL
    assert c.handoff_type == HandoffType.ANALYST_REVIEW
    assert c.score_breakdown == {}
    assert c.actions_taken == []
    assert c.open_questions == []


def test_doc_example_validates():
    raw = {
        "case_id": "CASE-0001",
        "handoff_type": "analyst_review",
        "priority": "normal",
        "trigger_reason": "Banda media con exposición media",
        "customer_id": "DEMO000001",
        "session_id": "S-1",
        "request_summary": "El cliente solicita un préstamo personal de 5.000 USD",
        "verified_facts": [
            "Cliente activo",
            "Sin mora vigente",
            "Ingreso registrado 700 USD",
        ],
        "score_breakdown": {
            "credit_score": 310.0,
            "debt_to_income": -45.0,
            "tenure": 60.0,
        },
        "policy_decision": decision().model_dump(mode="json"),
        "actions_taken": [],
        "open_questions": ["¿El ingreso declarado de 950 USD es verificable?"],
        "created_at": "2026-09-28T12:00:00-05:00",
    }
    c = HandoffCase.model_validate(raw)
    assert c.customer_id == c.policy_decision.customer_id == "DEMO000001"
    assert c.created_at.utcoffset() is not None
    assert c.score_breakdown["debt_to_income"] == -45.0


def test_decision_of_other_customer_fails():
    with pytest.raises(ValidationError, match="no corresponde al cliente"):
        HandoffCase(**case_data(policy_decision=decision(customer_id="OTRO")))


def test_sin_hechos_ni_preguntas_falla():
    with pytest.raises(ValidationError):
        HandoffCase(**case_data(verified_facts=[], open_questions=[]))


def test_fallback_sin_hechos_con_preguntas_pasa():
    c = HandoffCase(
        **case_data(verified_facts=[], open_questions=["¿Sigue caída la política?"])
    )
    assert c.verified_facts == []


def test_naive_created_at_fails():
    with pytest.raises(ValidationError):
        HandoffCase(**case_data(created_at=datetime(2026, 9, 28, 12, 0)))  # noqa: DTZ001
    with pytest.raises(ValidationError):
        HandoffCase(**case_data(created_at="2026-09-28T12:00:00"))


@pytest.mark.parametrize("field", ["handoff_type", "status", "priority"])
def test_invalid_enum_fails(field):
    with pytest.raises(ValidationError):
        HandoffCase(**case_data(**{field: "nope"}))


def test_extra_field_fails():
    with pytest.raises(ValidationError):
        HandoffCase(**case_data(phone="555"))


def test_frozen():
    c = HandoffCase(**case_data())
    with pytest.raises(ValidationError):
        c.status = CaseStatus.APPROVED


def test_round_trip_json():
    c = HandoffCase(
        **case_data(
            priority="high",
            status="info_requested",
            score_breakdown={"tenure": 60.0},
            open_questions=["¿Ingreso verificable?"],
        )
    )
    again = HandoffCase.model_validate_json(c.model_dump_json())
    assert again == c
    assert json.loads(c.model_dump_json())["priority"] == "high"


def test_politica_caida_escala_sin_decision_con_preguntas():
    c = HandoffCase(
        **case_data(policy_decision=None, open_questions=["La política no respondió"])
    )
    assert c.policy_decision is None


def test_sin_decision_ni_preguntas_falla():
    with pytest.raises(ValidationError):
        HandoffCase(**case_data(policy_decision=None, open_questions=[]))
