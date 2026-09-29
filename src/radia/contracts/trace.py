"""C11. Registro de tracing por turno de conversación.

Productor: orquestador. Consumidores: métricas de latencia y costo (ETL) y
evaluación (C10 compara `behaviors` con lo esperado).

- Es la evidencia de auditoría: qué se entendió, qué tools corrieron, con qué
  versión de política, modelo y prompt, y qué resultó. El chain-of-thought del
  LLM no es evidencia y no se guarda.
- Sin texto del cliente ni datos personales: solo `customer_id` pseudónimo.
"""

from enum import StrEnum
from typing import Self

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from radia.contracts.eval_case import Behavior

CONTRACT_VERSION = "0.1.0"

_FROZEN = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False)


class Outcome(StrEnum):
    ANSWERED = "answered"
    AWAITING_CONFIRMATION = "awaiting_confirmation"
    ACTION_COMPLETED = "action_completed"
    HANDOFF = "handoff"
    CLARIFICATION = "clarification"
    REDIRECTED = "redirected"
    REFUSED = "refused"
    FALLBACK = "fallback"
    ERROR = "error"


class ToolCall(BaseModel):
    model_config = _FROZEN

    name: str = Field(min_length=1)
    ok: bool
    latency_ms: float = Field(ge=0)
    attempt: int = Field(default=1, ge=1)  # reintentos acotados
    error: str | None = None
    # Denegada por la capa de permisos, no por una falla técnica.
    denied: bool = False

    @model_validator(mode="after")
    def check_error(self) -> Self:
        if self.ok and (self.error or self.denied):
            raise ValueError("una llamada exitosa no trae error ni denegación")
        if not self.ok and not self.error:
            raise ValueError("una llamada fallida explica su error")
        return self


class TurnTrace(BaseModel):
    model_config = _FROZEN

    trace_id: str = Field(min_length=1)
    session_id: str = Field(min_length=1)
    turn_index: int = Field(ge=0)
    timestamp: AwareDatetime
    customer_id: str | None = None  # nulo si no hay sesión autenticada
    case_id: str | None = None  # solo en corridas de evaluación
    intent: str = Field(min_length=1)
    tools: list[ToolCall] = Field(default_factory=list)
    behaviors: list[Behavior] = Field(default_factory=list)
    outcome: Outcome
    policy_version: str | None = None
    llm_model: str = Field(min_length=1)
    prompt_version: str = Field(min_length=1)
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    cost_usd: float = Field(ge=0)
    latency_ms: float = Field(ge=0)
    handoff_case_id: str | None = None

    @model_validator(mode="after")
    def check_handoff(self) -> Self:
        if (self.outcome == Outcome.HANDOFF) != (self.handoff_case_id is not None):
            raise ValueError("handoff_case_id va solo y siempre con outcome handoff")
        return self
