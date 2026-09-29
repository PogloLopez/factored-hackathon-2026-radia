"""Tests de radia.contracts.trace (C11)."""

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from radia.contracts.trace import Outcome, ToolCall, TurnTrace

AWARE = datetime(2026, 9, 28, 12, 0, tzinfo=UTC)


def trace(**over) -> TurnTrace:
    data = {
        "trace_id": "t1",
        "session_id": "s1",
        "turn_index": 0,
        "timestamp": AWARE,
        "intent": "consulta",
        "outcome": "answered",
        "llm_model": "m",
        "prompt_version": "p1",
        "input_tokens": 10,
        "output_tokens": 5,
        "cost_usd": 0.01,
        "latency_ms": 120.5,
    }
    data.update(over)
    return TurnTrace.model_validate(data)


HANDOFF = {
    "outcome": "handoff",
    "handoff_case_id": "H1",
    "handoff_type": "analyst_review",
}


def test_toolcall_ok_valid():
    t = ToolCall(name="x", ok=True, latency_ms=1)
    assert t.attempt == 1
    assert t.denied is False


def test_toolcall_ok_with_error_fails():
    with pytest.raises(ValidationError):
        ToolCall(name="x", ok=True, latency_ms=1, error="boom")


def test_toolcall_failed_without_error_fails():
    with pytest.raises(ValidationError):
        ToolCall(name="x", ok=False, latency_ms=1)


def test_toolcall_denied_with_ok_fails():
    with pytest.raises(ValidationError):
        ToolCall(name="x", ok=True, latency_ms=1, denied=True)


def test_toolcall_denied_failed_valid():
    assert ToolCall(name="x", ok=False, latency_ms=1, error="denied", denied=True)


def test_toolcall_attempt_min_1():
    with pytest.raises(ValidationError):
        ToolCall(name="x", ok=True, latency_ms=1, attempt=0)
    assert ToolCall(name="x", ok=True, latency_ms=1, attempt=3).attempt == 3


def test_toolcall_negative_latency_and_empty_name():
    with pytest.raises(ValidationError):
        ToolCall(name="x", ok=True, latency_ms=-1)
    with pytest.raises(ValidationError):
        ToolCall(name="", ok=True, latency_ms=1)


def test_handoff_valid():
    assert trace(**HANDOFF).outcome == Outcome.HANDOFF


@pytest.mark.parametrize("missing", ["handoff_case_id", "handoff_type"])
def test_handoff_missing_field_fails(missing):
    data = {k: v for k, v in HANDOFF.items() if k != missing}
    with pytest.raises(ValidationError):
        trace(**data)


def test_handoff_fields_without_handoff_outcome_fails():
    with pytest.raises(ValidationError):
        trace(handoff_case_id="H1")
    with pytest.raises(ValidationError):
        trace(handoff_type="advisor")


def test_action_completed_requires_reference():
    assert trace(outcome="action_completed", application_reference="APP-1")
    with pytest.raises(ValidationError):
        trace(outcome="action_completed")


def test_reference_without_action_completed_fails():
    with pytest.raises(ValidationError):
        trace(application_reference="APP-1")


@pytest.mark.parametrize("rid", ["Rule", "1rule", "a-b", "a b", ""])
def test_rule_ids_not_snake_case_fail(rid):
    with pytest.raises(ValidationError):
        trace(rule_ids=[rid])


def test_rule_ids_valid():
    assert trace(rule_ids=["income_ok", "r2"]).rule_ids == ["income_ok", "r2"]


def test_naive_timestamp_fails():
    with pytest.raises(ValidationError):
        trace(timestamp=datetime(2026, 9, 28, 12, 0))  # noqa: DTZ001


@pytest.mark.parametrize(
    "field", ["input_tokens", "output_tokens", "cost_usd", "latency_ms"]
)
def test_negative_metrics_fail(field):
    with pytest.raises(ValidationError):
        trace(**{field: -1})


@pytest.mark.parametrize("field", ["cost_usd", "latency_ms"])
@pytest.mark.parametrize("bad", [float("inf"), float("nan")])
def test_inf_nan_fail(field, bad):
    with pytest.raises(ValidationError):
        trace(**{field: bad})


def test_toolcall_inf_latency_fails():
    with pytest.raises(ValidationError):
        ToolCall(name="x", ok=True, latency_ms=float("inf"))


def test_negative_turn_index_fails():
    with pytest.raises(ValidationError):
        trace(turn_index=-1)


def test_frozen_and_extra_forbid():
    t = trace()
    with pytest.raises(ValidationError):
        t.intent = "otro"
    with pytest.raises(ValidationError):
        trace(extra=1)


def test_json_round_trip():
    t = trace(
        **HANDOFF,
        tools=[{"name": "x", "ok": False, "latency_ms": 2, "error": "e"}],
        behaviors=["handoff"],
        attention_level="analyst",
        rule_ids=["r_1"],
    )
    assert TurnTrace.model_validate_json(t.model_dump_json()) == t
