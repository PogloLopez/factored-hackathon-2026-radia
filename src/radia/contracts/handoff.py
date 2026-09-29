"""C9. Expediente de handoff hacia un humano.

Productor: orquestador. Consumidores: bandeja del analista y consola del asesor.

- Un solo formato para ambos: `handoff_type` distingue revisión del analista y
  atención del asesor.
- Hechos verificados, acciones hechas y preguntas abiertas van separados, como
  pide el enunciado. Lo que dijo el cliente sin verificar va en preguntas.
- Sin datos de contacto ni documento: el humano los consulta en el core.
- Un caso puede traer una decisión automática: si una tool falla al
  ejecutarla, el fallback seguro es escalar con esa decisión adjunta.
"""

from enum import StrEnum
from typing import Self

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from radia.contracts.policy import PolicyDecision

CONTRACT_VERSION = "0.1.0"


class HandoffType(StrEnum):
    ANALYST_REVIEW = "analyst_review"
    ADVISOR = "advisor"


class Priority(StrEnum):
    NORMAL = "normal"
    HIGH = "high"


class CaseStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    INFO_REQUESTED = "info_requested"


class HandoffCase(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False)

    case_id: str = Field(min_length=1)
    handoff_type: HandoffType
    priority: Priority = Priority.NORMAL
    status: CaseStatus = CaseStatus.PENDING
    trigger_reason: str = Field(min_length=1)
    customer_id: str = Field(min_length=1)
    session_id: str = Field(min_length=1)
    request_summary: str = Field(min_length=1)
    verified_facts: list[str] = Field(min_length=1)
    # Puntos por componente del puntaje interno (C3).
    score_breakdown: dict[str, float] = Field(default_factory=dict)
    policy_decision: PolicyDecision
    actions_taken: list[str] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)
    created_at: AwareDatetime

    @model_validator(mode="after")
    def check_decision_matches(self) -> Self:
        if self.policy_decision.customer_id != self.customer_id:
            raise ValueError("policy_decision no corresponde al cliente del caso")
        return self
