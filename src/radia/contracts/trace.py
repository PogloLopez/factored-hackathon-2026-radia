"""C11. Registro de tracing por turno de conversación.

Productor: orquestador. Consumidores: métricas de latencia y costo (ETL) y
evaluación (C10 compara `behaviors` con lo esperado).

- Es la evidencia de auditoría: qué se entendió, qué tools corrieron, con qué
  versión de política, modelo y prompt, y qué resultó. El chain-of-thought del
  LLM no es evidencia y no se guarda.
- Sin texto del cliente ni datos personales: solo `customer_id` pseudónimo.
- Explicación de cada decisión: `rule_ids` (reglas de la política que se
  aplicaron) y `sources` (tablas y versiones consultadas).
- Métricas: la resolución automática segura y los handoffs faltantes o
  innecesarios salen de `attention_level`, `outcome` y `handoff_type`
  comparados con el caso de evaluación (C10) vía `eval_case_id`. Latencia y
  costo por caso salen de agrupar por `eval_case_id`.
"""

from enum import StrEnum
from typing import Self

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from radia.contracts.common import AttentionLevel
from radia.contracts.eval_case import Behavior
from radia.contracts.handoff import HandoffType
from radia.contracts.policy import Code

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
    eval_case_id: str | None = None  # solo en corridas de evaluación
    intent: str = Field(min_length=1)
    tools: list[ToolCall] = Field(default_factory=list)
    behaviors: list[Behavior] = Field(default_factory=list)
    outcome: Outcome
    attention_level: AttentionLevel | None = None
    rule_ids: list[Code] = Field(default_factory=list)
    sources: list[str] = Field(default_factory=list)
    policy_version: str | None = None
    llm_model: str = Field(min_length=1)
    prompt_version: str = Field(min_length=1)
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    cost_usd: float = Field(ge=0)
    latency_ms: float = Field(ge=0)
    handoff_case_id: str | None = None
    handoff_type: HandoffType | None = None
    # Número de solicitud verificado tras una acción completada.
    application_reference: str | None = None

    @model_validator(mode="after")
    def check_outcome_fields(self) -> Self:
        is_handoff = self.outcome == Outcome.HANDOFF
        if is_handoff != (self.handoff_case_id is not None):
            raise ValueError("handoff_case_id va solo y siempre con outcome handoff")
        if is_handoff != (self.handoff_type is not None):
            raise ValueError("handoff_type va solo y siempre con outcome handoff")
        completed = self.outcome == Outcome.ACTION_COMPLETED
        if completed != (self.application_reference is not None):
            raise ValueError(
                "application_reference va solo y siempre con una acción completada"
            )
        return self
