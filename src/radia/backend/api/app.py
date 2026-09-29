"""Fábrica de la app FastAPI (C8). Endpoints en [[trabajo_en_paralelo]], momento 4.

La app que levanta uvicorn está en `main.py`. Los tests usan `create_app`.

- La identidad sale del token (`Authorization: Bearer ...`), nunca del cuerpo.
- Chat y confirmación pasan por el orquestador: la decisión sale de C6.
- Una sesión de chat es del cliente que la abrió. Otro cliente recibe 403.
- El monto del asesor debe caer en el rango de negociación del caso.
"""

from collections.abc import Callable
from datetime import datetime
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from radia.backend.agent.llm import LanguageModel
from radia.backend.agent.orchestrator import ChatReply, UnknownSession
from radia.backend.agent.tools import Offer, utc_now
from radia.backend.agent.tracing import TraceSink
from radia.backend.api.auth import InvalidCredentials, Principal
from radia.backend.api.state import ApiState, session_currency
from radia.config import Settings, get_settings
from radia.contracts.api import (
    AdvisorMessage,
    AdvisorMessageRequest,
    AdvisorSession,
    AdvisorSessionsResponse,
    AnalystCasesResponse,
    AnalystDecision,
    AnalystDecisionRequest,
    AnalystDecisionResponse,
    ChatMessageRequest,
    ChatResponse,
    ConfirmRequest,
    LoginRequest,
    LoginResponse,
    OffersResponse,
    OfferView,
    UserRole,
)
from radia.contracts.common import AttentionLevel
from radia.contracts.handoff import CaseStatus, HandoffCase, HandoffType, Priority

# Orden para destacar la oferta más idónea: primero lo que se resuelve solo.
LEVEL_RANK = {
    AttentionLevel.AUTOMATIC: 0,
    AttentionLevel.ADVISOR: 1,
    AttentionLevel.ANALYST: 2,
    AttentionLevel.ANALYST_AND_ADVISOR: 3,
}
DECISION_STATUS = {
    AnalystDecision.APPROVE: CaseStatus.APPROVED,
    AnalystDecision.REJECT: CaseStatus.REJECTED,
    AnalystDecision.REQUEST_INFO: CaseStatus.INFO_REQUESTED,
}
OPEN_STATUSES = {CaseStatus.PENDING, CaseStatus.INFO_REQUESTED}

bearer = HTTPBearer(auto_error=False)


# --- Dependencias -------------------------------------------------------------


def get_state(request: Request) -> ApiState:
    return request.app.state.api


State = Annotated[ApiState, Depends(get_state)]


def current_principal(
    state: State,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
) -> Principal:
    """401 sin token o con token inválido o vencido."""
    principal = credentials and state.tokens.resolve(credentials.credentials)
    if not principal:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "token ausente o inválido",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return principal


def require(role: UserRole):
    def check(principal: Annotated[Principal, Depends(current_principal)]):
        if principal.role != role:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "rol no autorizado")
        return principal

    return check


Customer = Annotated[Principal, Depends(require(UserRole.CUSTOMER))]
Analyst = Annotated[Principal, Depends(require(UserRole.ANALYST))]
Advisor = Annotated[Principal, Depends(require(UserRole.ADVISOR))]


# --- Ayudas -------------------------------------------------------------------


def _offer_view(offer: Offer) -> OfferView:
    return OfferView(
        offer_id=offer.offer_id,
        product_code=offer.product_code,
        attention_level=offer.attention_level,
        offered_limit_usd=offer.offered_limit_usd,
        alternative_product_code=offer.alternative_product_code,
        preferential=offer.preferential,
        reasons=list(offer.reasons),
        expires_at=offer.expires_at,
    )


def _highlight(offers: list[Offer]) -> str | None:
    """Oferta elegible con cupo, primero la de menor atención y mayor cupo."""
    candidates = [
        o
        for o in offers
        if o.attention_level in LEVEL_RANK and o.offered_limit_usd is not None
    ]
    if not candidates:
        return None
    best = min(
        candidates,
        key=lambda o: (LEVEL_RANK[o.attention_level], -(o.offered_limit_usd or 0)),
    )
    return best.offer_id


def _chat_response(reply: ChatReply) -> ChatResponse:
    return ChatResponse.model_validate(reply.model_dump())


def _owned_session(state: ApiState, session_id: str, customer_id: str | None) -> None:
    """404 si la sesión no existe o es de otro cliente.

    Misma respuesta en ambos casos: así no se puede sondear si un id ajeno existe.
    """
    session = state.orchestrator.sessions.get(session_id)
    if session is None or session.customer_id != customer_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "sesión no encontrada")


def _case_of_type(state: ApiState, case_id: str, kind: HandoffType) -> HandoffCase:
    case = state.cases.get(case_id)
    if case is None or case.handoff_type != kind:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "caso no encontrado")
    return case


def _check_amount(case: HandoffCase, amount: float) -> None:
    """422 si el monto sale del rango de negociación o el caso no tiene rango."""
    decision = case.policy_decision
    low = decision.negotiation_min_usd if decision else None
    high = decision.negotiation_max_usd if decision else None
    if low is None or high is None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "el caso no tiene rango de negociación",
        )
    if not low <= amount <= high:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            f"el monto debe estar entre {low:.2f} y {high:.2f} USD",
        )


# --- App ----------------------------------------------------------------------


def create_app(
    settings: Settings | None = None,
    *,
    state: ApiState | None = None,
    sink: TraceSink | None = None,
    llm: LanguageModel | None = None,
    clock: Callable[[], datetime] = utc_now,
) -> FastAPI:
    """Arma la app. Los tests inyectan sink, LLM, reloj o el estado entero."""
    settings = settings or get_settings()
    app = FastAPI(
        title="Radia API",
        version="0.1.0",
        description="API C8 del banco sintético. Identidad MOCK, no real.",
    )
    app.state.api = state or ApiState(settings, sink=sink, llm=llm, clock=clock)

    @app.post("/auth/login")
    def login(body: LoginRequest, state: State) -> LoginResponse:
        try:
            principal = state.tokens.login(body.username, body.password)
        except InvalidCredentials:
            raise HTTPException(
                status.HTTP_401_UNAUTHORIZED, "credenciales inválidas"
            ) from None
        return LoginResponse(
            access_token=principal.token,
            role=principal.role,
            customer_id=principal.customer_id,
            expires_at=principal.expires_at,
        )

    @app.get("/customers/me/offers")
    def my_offers(principal: Customer, state: State) -> OffersResponse:
        now: datetime = state.clock()
        offers = [
            o for o in state.offers.offers_for(principal.customer_id) if o.is_valid(now)
        ]
        return OffersResponse(
            customer_id=principal.customer_id,
            offers=[_offer_view(o) for o in offers],
            highlighted_offer_id=_highlight(offers),
        )

    @app.post("/chat/messages")
    def chat_message(
        body: ChatMessageRequest, principal: Customer, state: State
    ) -> ChatResponse:
        orch = state.orchestrator
        # El lock global cubre solo abrir la sesión o chequear su dueño. El turno
        # (y el LLM) va fuera: el orquestador lo serializa con el lock de la
        # sesión, así clientes distintos conversan en paralelo.
        with state.lock:
            if body.session_id is None:
                currency, rate = session_currency(principal.customer_id)
                session_id = orch.start_session(
                    principal.customer_id, currency=currency, usd_per_unit=rate
                ).session_id
            else:
                session_id = body.session_id
                _owned_session(state, session_id, principal.customer_id)
        try:
            reply = orch.handle_message(session_id, body.message)
        except UnknownSession:
            raise HTTPException(
                status.HTTP_404_NOT_FOUND, "sesión no encontrada"
            ) from None
        return _chat_response(reply)

    @app.post("/chat/confirm")
    def chat_confirm(
        body: ConfirmRequest, principal: Customer, state: State
    ) -> ChatResponse:
        with state.lock:
            _owned_session(state, body.session_id, principal.customer_id)
        try:
            reply = state.orchestrator.confirm(
                body.session_id, body.confirmation_id, body.accept
            )
        except UnknownSession:
            raise HTTPException(
                status.HTTP_404_NOT_FOUND, "sesión no encontrada"
            ) from None
        return _chat_response(reply)

    @app.get("/analyst/cases")
    def analyst_cases(_: Analyst, state: State) -> AnalystCasesResponse:
        cases = [
            c
            for c in state.cases.list_cases()
            if c.handoff_type == HandoffType.ANALYST_REVIEW
            and c.status in OPEN_STATUSES
        ]
        cases.sort(key=lambda c: (c.priority != Priority.HIGH, c.created_at))
        return AnalystCasesResponse(cases=cases)

    @app.post("/analyst/cases/{case_id}/decision")
    def analyst_decision(
        case_id: str, body: AnalystDecisionRequest, _: Analyst, state: State
    ) -> AnalystDecisionResponse:
        with state.lock:
            case = _case_of_type(state, case_id, HandoffType.ANALYST_REVIEW)
            if case.status not in OPEN_STATUSES:
                raise HTTPException(status.HTTP_409_CONFLICT, "el caso ya se decidió")
            new_status = DECISION_STATUS[body.decision]
            updated = state.cases.save(
                HandoffCase.model_validate(case.model_dump() | {"status": new_status})
            )
        return AnalystDecisionResponse(
            case=updated,
            decision=body.decision,
            status=new_status,
            note=body.note,
            decided_at=state.clock(),
        )

    @app.get("/advisor/sessions")
    def advisor_sessions(_: Advisor, state: State) -> AdvisorSessionsResponse:
        sessions = [
            AdvisorSession(
                case=c, messages=list(state.advisor_messages.get(c.case_id, []))
            )
            for c in state.cases.list_cases()
            if c.handoff_type == HandoffType.ADVISOR
        ]
        sessions.sort(key=lambda s: s.case.created_at)
        return AdvisorSessionsResponse(sessions=sessions)

    @app.post("/advisor/sessions/{case_id}/messages")
    def advisor_message(
        case_id: str, body: AdvisorMessageRequest, _: Advisor, state: State
    ) -> AdvisorMessage:
        with state.lock:
            case = _case_of_type(state, case_id, HandoffType.ADVISOR)
            if case.status in {CaseStatus.APPROVED, CaseStatus.REJECTED}:
                raise HTTPException(status.HTTP_409_CONFLICT, "el caso ya está cerrado")
            if body.proposed_amount_usd is not None:
                _check_amount(case, body.proposed_amount_usd)
            message = AdvisorMessage(
                case_id=case_id,
                message=body.message,
                proposed_amount_usd=body.proposed_amount_usd,
                sent_at=state.clock(),
            )
            state.advisor_messages.setdefault(case_id, []).append(message)
        return message

    return app
