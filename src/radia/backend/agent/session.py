"""Sesión de chat y su máquina de estados.

- El `customer_id` sale del login (token de sesión), nunca del texto del chat.
- Estados: idle → awaiting_confirmation → done / handoff. `handoff` es
  terminal: el caso ya está con una persona.
- Moneda y tasa a USD las inyecta quien crea la sesión: los montos del chat
  vienen en moneda local y se convierten antes de compararlos con cupos en USD.
- La confirmación pendiente vive en la sesión. La tool de solicitudes la exige
  aceptada, así que sin confirmación explícita no hay acción.
"""

from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from radia.backend.agent.llm import ChatMessage
from radia.contracts.common import ProductCode
from radia.contracts.eval_case import Language

MAX_HISTORY = 20


class Currency(StrEnum):
    """Moneda local del cliente. Los cupos de C6 están en USD."""

    MXN = "MXN"
    COP = "COP"
    ARS = "ARS"
    USD = "USD"


class SessionState(StrEnum):
    IDLE = "idle"
    AWAITING_CONFIRMATION = "awaiting_confirmation"
    DONE = "done"
    HANDOFF = "handoff"


ALLOWED_TRANSITIONS: dict[SessionState, set[SessionState]] = {
    SessionState.IDLE: {
        SessionState.IDLE,
        SessionState.AWAITING_CONFIRMATION,
        SessionState.HANDOFF,
    },
    SessionState.AWAITING_CONFIRMATION: {
        SessionState.IDLE,
        SessionState.AWAITING_CONFIRMATION,
        SessionState.DONE,
        SessionState.HANDOFF,
    },
    SessionState.DONE: {
        SessionState.IDLE,
        SessionState.AWAITING_CONFIRMATION,
        SessionState.DONE,
        SessionState.HANDOFF,
    },
    SessionState.HANDOFF: {SessionState.HANDOFF},
}


class InvalidTransition(RuntimeError):
    pass


class PendingConfirmation(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False)

    confirmation_id: str = Field(min_length=1)
    action: Literal["create_application"] = "create_application"
    offer_id: str = Field(min_length=1)
    product_code: ProductCode
    limit_usd: float = Field(gt=0)
    summary: str = Field(min_length=1)
    # Solo `Orchestrator.confirm` lo prende, con el botón explícito del cliente.
    accepted: bool = False


class Session(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    session_id: str = Field(min_length=1)
    customer_id: str = Field(min_length=1)
    expires_at: AwareDatetime
    state: SessionState = SessionState.IDLE
    language: Language = Language.ES
    history: list[ChatMessage] = Field(default_factory=list)
    pending: PendingConfirmation | None = None
    focus_product: ProductCode | None = None
    handoff_case_id: str | None = None
    turn_index: int = Field(default=0, ge=0)
    eval_case_id: str | None = None
    # Las inyecta quien crea la sesión (login y servicio de tasas), nunca el chat.
    currency: Currency | None = None
    # USD por unidad de moneda local. Sin tasa, un monto local no enruta.
    usd_per_unit: float | None = Field(default=None, gt=0, allow_inf_nan=False)

    def is_active(self, now: datetime) -> bool:
        return now < self.expires_at

    def move_to(self, state: SessionState) -> None:
        if state not in ALLOWED_TRANSITIONS[self.state]:
            raise InvalidTransition(f"{self.state} → {state} no está permitido")
        self.state = state

    def remember(self, message: ChatMessage) -> None:
        self.history = [*self.history, message][-MAX_HISTORY:]
