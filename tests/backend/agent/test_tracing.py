"""Tests de los sinks del tracing (C11)."""

import tempfile
from datetime import UTC, datetime
from pathlib import Path

from radia.backend.agent.tracing import InMemoryTraceSink, JsonlTraceSink
from radia.config import Settings
from radia.contracts.trace import Outcome, TurnTrace


def trace(turn_index=0):
    return TurnTrace(
        trace_id=f"T{turn_index}",
        session_id="S1",
        turn_index=turn_index,
        timestamp=datetime(2026, 9, 29, 12, tzinfo=UTC),
        customer_id="C1",
        intent="greeting",
        outcome=Outcome.ANSWERED,
        llm_model="fake",
        prompt_version="p0",
        input_tokens=0,
        output_tokens=0,
        cost_usd=0,
        latency_ms=1.0,
    )


def test_sink_en_memoria():
    sink = InMemoryTraceSink()
    sink.write(trace())
    assert sink.traces == [trace()]


def test_sink_jsonl_una_linea_por_turno():
    with tempfile.TemporaryDirectory() as tmp:
        settings = Settings(_env_file=None, data_dir=Path(tmp))
        sink = JsonlTraceSink.from_settings(settings)
        sink.write(trace(0))
        sink.write(trace(1))
        path = sink.path_for(trace())
        assert path.parent == Path(tmp) / "traces"
        lines = path.read_text(encoding="utf-8").splitlines()
        assert [TurnTrace.model_validate_json(x) for x in lines] == [
            trace(0),
            trace(1),
        ]
