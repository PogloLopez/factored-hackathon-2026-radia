"""C8. API HTTP hacia la web: request y response de cada endpoint.

Productor: backend (`radia.backend.api`). Consumidor: frontend.

- Endpoints y ejemplos en [[trabajo_en_paralelo]], momento 4.
- La identidad sale del token de `POST /auth/login`. El `customer_id` nunca
  viaja en el cuerpo de una ruta de cliente.
- El cliente no ve el rango de negociación: es del asesor y del analista.
- Los montos van en USD, como C6. La moneda local es solo para leer el chat.
- Política sintética: toda oferta lleva `synthetic_policy` verdadero.
- Errores: el formato por defecto de FastAPI (`{"detail": ...}`). 401 sin token
  válido, 403 con rol ajeno, 404 si no existe o es una sesión ajena (misma
  respuesta: no se sondea un id ajeno), 409 si el estado no permite la
  operación y 422 si el cuerpo no valida o el monto sale del rango.
"""

from enum import StrEnum
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from radia.contracts.common import AttentionLevel, ProductCode
from radia.contracts.handoff import CaseStatus, HandoffCase

CONTRACT_VERSION = "0.1.1"

_FROZEN = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False)

MAX_MESSAGE_CHARS = 2000


class UserRole(StrEnum):
    CUSTOMER = "customer"
    ANALYST = "analyst"
    ADVISOR = "advisor"


class ChatState(StrEnum):
    """Estado de la sesión de chat. Mismos valores que la máquina de estados."""

    IDLE = "idle"
    AWAITING_CONFIRMATION = "awaiting_confirmation"
    DONE = "done"
    HANDOFF = "handoff"


# --- POST /auth/login ---------------------------------------------------------


class LoginRequest(BaseModel):
    model_config = _FROZEN

    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=128)


class LoginResponse(BaseModel):
    model_config = _FROZEN

    access_token: str = Field(min_length=1)
    token_type: Literal["bearer"] = "bearer"
    role: UserRole
    # Solo para el rol cliente. Nulo para analista y asesor.
    customer_id: str | None = None
    expires_at: AwareDatetime


# --- GET /customers/me/offers -------------------------------------------------


class OfferView(BaseModel):
    """Una oferta vigente de C6, sin el rango de negociación."""

    model_config = _FROZEN

    offer_id: str = Field(min_length=1)
    product_code: ProductCode
    attention_level: AttentionLevel
    # Nulo si no es elegible o no hay cupo.
    offered_limit_usd: float | None = Field(default=None, gt=0)
    alternative_product_code: ProductCode | None = None
    preferential: bool = False
    reasons: list[str] = Field(default_factory=list)
    expires_at: AwareDatetime


class OffersResponse(BaseModel):
    model_config = _FROZEN

    customer_id: str = Field(min_length=1)
    offers: list[OfferView]
    # La más idónea para destacar en el carrusel. Nula si ninguna aplica.
    highlighted_offer_id: str | None = None
    synthetic_policy: Literal[True] = True


# --- POST /chat/messages y POST /chat/confirm --------------------------------


class ChatMessageRequest(BaseModel):
    model_config = _FROZEN

    # Nulo en el primer mensaje: el backend abre la sesión.
    session_id: str | None = Field(default=None, min_length=1)
    message: str = Field(min_length=1, max_length=MAX_MESSAGE_CHARS)


class ConfirmRequest(BaseModel):
    model_config = _FROZEN

    session_id: str = Field(min_length=1)
    confirmation_id: str = Field(min_length=1)
    accept: bool


class PendingConfirmationView(BaseModel):
    """Lo que el frontend necesita para pintar los botones Sí y No."""

    model_config = _FROZEN

    confirmation_id: str = Field(min_length=1)
    action: str = Field(min_length=1)
    summary: str = Field(min_length=1)


class ChatResponse(BaseModel):
    """Respuesta de `POST /chat/messages` y `POST /chat/confirm`."""

    model_config = _FROZEN

    session_id: str = Field(min_length=1)
    reply: str
    state: ChatState
    pending_confirmation: PendingConfirmationView | None = None
    handoff_case_id: str | None = None
    # Número de solicitud verificado. Solo tras una acción completada.
    application_reference: str | None = None
    trace_id: str = Field(min_length=1)


# --- Analista -----------------------------------------------------------------


class AnalystDecision(StrEnum):
    APPROVE = "approve"
    REJECT = "reject"
    REQUEST_INFO = "request_info"


class AnalystCasesResponse(BaseModel):
    model_config = _FROZEN

    cases: list[HandoffCase]


class AnalystDecisionRequest(BaseModel):
    model_config = _FROZEN

    decision: AnalystDecision
    note: str | None = Field(default=None, max_length=1000)


class AnalystDecisionResponse(BaseModel):
    model_config = _FROZEN

    case: HandoffCase
    decision: AnalystDecision
    status: CaseStatus
    note: str | None = None
    decided_at: AwareDatetime


# --- Asesor -------------------------------------------------------------------


class AdvisorMessageRequest(BaseModel):
    model_config = _FROZEN

    message: str = Field(min_length=1, max_length=MAX_MESSAGE_CHARS)
    # Monto propuesto en USD. Debe caer en el rango de negociación del caso.
    proposed_amount_usd: float | None = Field(default=None, gt=0)


class AdvisorMessage(BaseModel):
    model_config = _FROZEN

    case_id: str = Field(min_length=1)
    message: str = Field(min_length=1)
    proposed_amount_usd: float | None = Field(default=None, gt=0)
    sent_at: AwareDatetime


class AdvisorSession(BaseModel):
    """Conversación traspasada al asesor: expediente C9 y mensajes enviados."""

    model_config = _FROZEN

    case: HandoffCase
    messages: list[AdvisorMessage] = Field(default_factory=list)


class AdvisorSessionsResponse(BaseModel):
    model_config = _FROZEN

    sessions: list[AdvisorSession]
