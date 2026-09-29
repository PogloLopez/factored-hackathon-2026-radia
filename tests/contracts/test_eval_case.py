"""Tests de radia.contracts.eval_case (C10)."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from radia.contracts.common import AttentionLevel
from radia.contracts.eval_case import (
    CONTRACT_VERSION,
    FAILURES_BY_CATEGORY,
    REQUIRES_FAILURE,
    Behavior,
    Category,
    EvalCase,
    Expected,
    InjectedFailure,
)

DOC = Path(__file__).parents[2] / "docs/propuesta/trabajo_en_paralelo.md"


def case(**over) -> EvalCase:
    data = {
        "case_id": "EX-001",
        "split": "dev",
        "category": "automatic",
        "turns": [{"content": "hola"}],
        "expected": {"attention_level": "automatic"},
        "author": "test",
    }
    data.update(over)
    return EvalCase.model_validate(data)


def test_doc_example_ex002_valid():
    text = DOC.read_text(encoding="utf-8")
    line = next(ln for ln in text.splitlines() if '"case_id": "EX-002"' in ln)
    c = EvalCase.model_validate_json(line)
    assert c.case_id == "EX-002"
    assert c.language == "es"
    assert Behavior.INVENT_OFFER in c.expected.must_not


@pytest.mark.parametrize("cid", ["ex-001", "E-001", "EX-01", "EX001", "EXXXXX-001", ""])
def test_invalid_case_id(cid):
    with pytest.raises(ValidationError):
        case(case_id=cid)


def test_empty_turns_fails():
    with pytest.raises(ValidationError):
        case(turns=[])


def test_empty_turn_content_fails():
    with pytest.raises(ValidationError):
        case(turns=[{"content": ""}])


def test_expected_empty_fails():
    with pytest.raises(ValidationError):
        Expected()


def test_expected_only_attention_level_ok():
    assert Expected(attention_level=AttentionLevel.ANALYST).must == []


def test_same_behavior_in_must_and_must_not_fails():
    with pytest.raises(ValidationError):
        Expected(must=[Behavior.HANDOFF], must_not=[Behavior.HANDOFF])


def test_customer_id_none_allowed():
    assert case().customer_id is None
    assert case(customer_id="C1").customer_id == "C1"


@pytest.mark.parametrize("lang", ["en", "pt", "es"])
def test_languages(lang):
    assert case(language=lang).language == lang


def test_invalid_language():
    with pytest.raises(ValidationError):
        case(language="fr")


def test_tool_failure_requires_failure():
    with pytest.raises(ValidationError):
        case(category="tool_failure")


@pytest.mark.parametrize("f", ["policy_down", "tool_timeout"])
def test_tool_failure_valid(f):
    assert case(category="tool_failure", inject_failure=f).inject_failure == f


@pytest.mark.parametrize("f", ["offers_expired", "session_expired"])
def test_tool_failure_wrong_failure(f):
    with pytest.raises(ValidationError):
        case(category="tool_failure", inject_failure=f)


def test_stale_data_requires_offers_expired():
    assert case(category="stale_data", inject_failure="offers_expired")
    with pytest.raises(ValidationError):
        case(category="stale_data")
    with pytest.raises(ValidationError):
        case(category="stale_data", inject_failure="policy_down")


def test_unauthorized_optional_session_expired():
    assert case(category="unauthorized").inject_failure is None
    assert case(category="unauthorized", inject_failure="session_expired")
    with pytest.raises(ValidationError):
        case(category="unauthorized", inject_failure="policy_down")


@pytest.mark.parametrize("cat", [c for c in Category if c not in FAILURES_BY_CATEGORY])
def test_other_categories_reject_failure(cat):
    assert case(category=cat).inject_failure is None
    for f in InjectedFailure:
        with pytest.raises(ValidationError):
            case(category=cat, inject_failure=f)


def test_requires_failure_constant():
    assert {Category.TOOL_FAILURE, Category.STALE_DATA} == REQUIRES_FAILURE


def test_frozen_and_extra_forbid():
    c = case()
    with pytest.raises(ValidationError):
        c.author = "otro"
    with pytest.raises(ValidationError):
        case(extra_field=1)
    with pytest.raises(ValidationError):
        Expected(attention_level="automatic", nope=1)


def test_contract_version():
    assert CONTRACT_VERSION == "0.2.0"


def test_refuse_behavior():
    assert Behavior("refuse") is Behavior.REFUSE
    e = Expected(must=["refuse"], must_not=["reveal_other_customer"])
    assert e.must == [Behavior.REFUSE]
    with pytest.raises(ValidationError):
        Expected(must=[Behavior.REFUSE], must_not=[Behavior.REFUSE])
