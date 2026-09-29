"""Sinks del tracing por turno (C11).

- `InMemoryTraceSink`: lista en memoria, para tests y la demo.
- `JsonlTraceSink`: una línea JSON por turno en `data_dir/traces/`, un archivo
  por día (UTC). `data/local/` nunca va a Git.
- El trace no lleva texto del cliente: solo lo que define C11.
"""

from pathlib import Path
from typing import Protocol

from radia.config import Settings
from radia.contracts.trace import TurnTrace


class TraceSink(Protocol):
    def write(self, trace: TurnTrace) -> None: ...


class InMemoryTraceSink:
    def __init__(self) -> None:
        self.traces: list[TurnTrace] = []

    def write(self, trace: TurnTrace) -> None:
        self.traces.append(trace)


class JsonlTraceSink:
    def __init__(self, directory: Path) -> None:
        self.directory = directory

    @classmethod
    def from_settings(cls, settings: Settings) -> "JsonlTraceSink":
        return cls(settings.traces_dir)

    def path_for(self, trace: TurnTrace) -> Path:
        return self.directory / f"turn_traces_{trace.timestamp:%Y%m%d}.jsonl"

    def write(self, trace: TurnTrace) -> None:
        path = self.path_for(trace)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(trace.model_dump_json() + "\n")
