"""Orquestador de conversación: máquina de estados por sesión.

Flujo de un turno (ver [[propuesta]], secciones 3 y 6):
1. El LLM entiende el mensaje (`classify`). No decide nada.
2. Guardas: sesión vencida, caso ya en manos humanas, sospecha de inyección,
   otro cliente (la capa de tools lo deniega).
3. La decisión sale SIEMPRE de la oferta vigente (C6, escrita por la política
   C7). Nunca del LLM ni de lo que diga el cliente.
4. Automático: se pide confirmación. La acción solo corre con
   `confirm(..., accept=True)` y se verifica leyéndola antes de reportarla.
5. Analista, asesor, analista y asesor, pedido de humano o disputa: handoff
   C9 con hechos verificados, acciones y preguntas abiertas.
6. No soportado: redirige al canal. Ambiguo: pide aclaración.
7. Ingreso declarado en el chat (con monto explícito): pregunta abierta para
   el analista. Nunca cambia la decisión. Pedir asesor gana.
8. Falla o datos vencidos: fallback seguro. Nunca se inventa una oferta.

Cada turno (mensaje o confirmación) deja un `TurnTrace` (C11) en el sink.
"""

import time
import uuid
from collections.abc import Callable, Sequence
from datetime import datetime, timedelta
from decimal import ROUND_DOWN, Decimal

from pydantic import BaseModel, ConfigDict, Field

from radia.backend.agent.llm import (
    PRODUCT_NAMES,
    WITH_LIMIT,
    ChatMessage,
    Intent,
    LanguageModel,
    Role,
    Understanding,
    UnsupportedTopic,
    Usage,
    fill_template,
    format_usd,
    join_items,
    product_name,
    reasons_text,
)
from radia.backend.agent.session import (
    Currency,
    PendingConfirmation,
    Session,
    SessionState,
)
from radia.backend.agent.tools import (
    Application,
    Offer,
    ToolBox,
    ToolDenied,
    ToolFailed,
    utc_now,
)
from radia.backend.agent.tracing import TraceSink
from radia.contracts.common import AttentionLevel, ProductCode
from radia.contracts.eval_case import Behavior, Language
from radia.contracts.handoff import HandoffCase, HandoffType, Priority
from radia.contracts.trace import Outcome, ToolCall, TurnTrace

SESSION_TTL = timedelta(minutes=30)
# Tras vencer, la sesión se conserva este margen (responde "venció") y luego
# se expulsa del diccionario para que no crezca sin límite.
SESSION_EVICT_AFTER = timedelta(minutes=30)
# Intents de crédito: solo con ellos el ingreso declarado abre su camino.
# `ambiguous` entra porque "gano X" a secas no tiene otro intent: sin él, el
# ingreso dicho tras pedir un producto se perdería en una aclaración.
CREDIT_INTENTS = frozenset(
    {
        Intent.ASK_OFFERS,
        Intent.APPLY_PRODUCT,
        Intent.ASK_REQUIREMENTS,
        Intent.WHY_NOT_ELIGIBLE,
        Intent.AMBIGUOUS,
    }
)
# Un monto convertido bajo este valor no se ofrece: se pide aclaración.
MIN_GRANT_USD = 1.0
GENERIC_PRODUCT = {Language.ES: "crédito", Language.PT: "crédito"}
GENERIC_PRODUCT[Language.EN] = "credit"

# Pedir un humano suma la bandera de asesor; el ingreso declarado, la de
# analista. Igual que las excepciones de la política: nunca bajan el nivel.
WITH_ADVISOR = {
    AttentionLevel.AUTOMATIC: AttentionLevel.ADVISOR,
    AttentionLevel.ANALYST: AttentionLevel.ANALYST_AND_ADVISOR,
    AttentionLevel.ADVISOR: AttentionLevel.ADVISOR,
    AttentionLevel.ANALYST_AND_ADVISOR: AttentionLevel.ANALYST_AND_ADVISOR,
    AttentionLevel.NOT_ELIGIBLE: AttentionLevel.ADVISOR,
}
WITH_ANALYST = {
    AttentionLevel.AUTOMATIC: AttentionLevel.ANALYST,
    AttentionLevel.ANALYST: AttentionLevel.ANALYST,
    AttentionLevel.ADVISOR: AttentionLevel.ANALYST_AND_ADVISOR,
    AttentionLevel.ANALYST_AND_ADVISOR: AttentionLevel.ANALYST_AND_ADVISOR,
}
UNSUPPORTED_TEMPLATE = {
    UnsupportedTopic.LOST_CARD: "unsupported_lost_card",
    UnsupportedTopic.COMPLAINT: "unsupported_complaint",
}


class UnknownSession(KeyError):
    pass


class PendingConfirmationView(BaseModel):
    """Lo que ve el frontend para pintar los botones Sí y No."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    confirmation_id: str
    action: str
    summary: str


class ChatReply(BaseModel):
    """Respuesta de `POST /chat/messages` y `POST /chat/confirm`."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    session_id: str
    reply: str
    state: SessionState
    pending_confirmation: PendingConfirmationView | None = None
    handoff_case_id: str | None = None
    application_reference: str | None = None
    trace_id: str


class _Turn(BaseModel):
    """Lo que el turno acumula para su trace."""

    intent: str
    outcome: Outcome = Outcome.ANSWERED
    behaviors: list[Behavior] = Field(default_factory=list)
    attention_level: AttentionLevel | None = None
    rule_ids: list[str] = Field(default_factory=list)
    sources: list[str] = Field(default_factory=list)
    policy_version: str | None = None
    handoff: HandoffCase | None = None
    application_reference: str | None = None
    # Recolector de tools de ESTE turno: nada compartido entre turnos.
    calls: list[ToolCall] = Field(default_factory=list)
    # Recolector del uso del LLM de ESTE turno, una entrada por llamada.
    llm_usage: list[Usage] = Field(default_factory=list)

    def use_offer(self, offer: Offer) -> None:
        self.rule_ids += offer.reasons + offer.alerts
        self.sources += offer.sources
        self.policy_version = offer.policy_version


def _dedup[T](items: Sequence[T]) -> list[T]:
    return list(dict.fromkeys(items))


def _product_es(code: ProductCode | None) -> str:
    return PRODUCT_NAMES[Language.ES][code] if code else "crédito"


class Orchestrator:
    def __init__(
        self,
        llm: LanguageModel,
        tools: ToolBox,
        sink: TraceSink,
        *,
        clock: Callable[[], datetime] = utc_now,
        session_ttl: timedelta = SESSION_TTL,
        evict_after: timedelta = SESSION_EVICT_AFTER,
    ) -> None:
        self.llm = llm
        self.tools = tools
        self.sink = sink
        self.clock = clock
        self.session_ttl = session_ttl
        self.evict_after = evict_after
        self.sessions: dict[str, Session] = {}

    # --- API pública ---------------------------------------------------------

    def start_session(
        self,
        customer_id: str,
        *,
        eval_case_id: str | None = None,
        currency: Currency | None = None,
        usd_per_unit: float | None = None,
    ) -> Session:
        """Abre sesión para el cliente autenticado (el id sale del login).

        `currency` y `usd_per_unit` (USD por unidad local) vienen del lado
        servidor. Sin tasa, un monto en moneda local no se usa para enrutar.
        """
        self._evict_expired()
        session = Session(
            session_id=f"SES-{uuid.uuid4().hex[:10].upper()}",
            customer_id=customer_id,
            expires_at=self.clock() + self.session_ttl,
            eval_case_id=eval_case_id,
            currency=currency,
            usd_per_unit=usd_per_unit,
        )
        self.sessions[session.session_id] = session
        return session

    def handle_message(self, session_id: str, message: str) -> ChatReply:
        session = self._session(session_id)
        started = time.perf_counter()
        if not session.is_active(self.clock()):
            turn = _Turn(intent="session_expired", outcome=Outcome.REFUSED)
            text = self._say(session, turn, "session_expired")
        elif session.state == SessionState.HANDOFF:
            # El caso ya está con una persona: respuesta fija, sin LLM ni gasto.
            # El idioma de la sesión no cambia.
            turn = _Turn(intent="in_handoff")
            text = fill_template(
                "in_handoff",
                {
                    "language": session.language.value,
                    "case_id": session.handoff_case_id,
                },
            )
        else:
            # El intent sale de `classify`: su uso se anota antes de tener turno.
            llm_usage: list[Usage] = []
            understanding = self.llm.classify(message, session.history, usage=llm_usage)
            session.language = understanding.language
            turn = _Turn(intent=understanding.intent.value, llm_usage=llm_usage)
            text = self._route(session, understanding, turn)
        session.remember(ChatMessage(role=Role.CUSTOMER, content=message))
        return self._finish(session, turn, text, started)

    def confirm(self, session_id: str, confirmation_id: str, accept: bool) -> ChatReply:
        """Botón Sí o No del cliente. Es la única vía para ejecutar una acción."""
        session = self._session(session_id)
        started = time.perf_counter()
        turn = _Turn(intent="confirm")
        if not session.is_active(self.clock()):
            turn.intent, turn.outcome = "session_expired", Outcome.REFUSED
            text = self._say(session, turn, "session_expired")
        else:
            text = self._confirm(session, turn, confirmation_id, accept)
        return self._finish(session, turn, text, started)

    # --- Ruteo ---------------------------------------------------------------

    def _route(self, session: Session, u: Understanding, turn: _Turn) -> str:
        if session.state == SessionState.AWAITING_CONFIRMATION:
            # Un mensaje nuevo anula la confirmación pendiente.
            session.pending = None
            session.move_to(SessionState.IDLE)
        if u.product_code is not None:
            session.focus_product = u.product_code

        if u.injection_suspected:
            turn.outcome = Outcome.REFUSED
            return self._say(session, turn, "injection_refused")
        if u.other_customer_id and u.other_customer_id != session.customer_id:
            try:
                self.tools.get_active_offers(
                    session, u.other_customer_id, calls=turn.calls
                )
            except ToolDenied:
                pass
            turn.outcome = Outcome.REFUSED
            return self._say(session, turn, "access_denied")
        # Solo un ingreso con monto explícito y un intent de crédito abren este
        # camino. Pedir asesor o disputar gana: el ingreso va como pregunta
        # abierta del asesor. Un tema no soportado sigue su redirección.
        if u.declared_monthly_income is not None and u.intent in CREDIT_INTENTS:
            return self._declared_income(session, u, turn)

        match u.intent:
            case Intent.UNSUPPORTED:
                turn.outcome = Outcome.REDIRECTED
                turn.behaviors.append(Behavior.REDIRECT_CHANNEL)
                template = UNSUPPORTED_TEMPLATE.get(
                    u.unsupported_topic or UnsupportedTopic.OTHER, "unsupported_other"
                )
                return self._say(session, turn, template)
            case Intent.AMBIGUOUS:
                return self._clarify(session, turn)
            case Intent.REQUEST_HUMAN | Intent.DISPUTE:
                return self._to_advisor(session, u, turn)
            case Intent.APPLY_PRODUCT:
                return self._apply(session, u, turn)
            case Intent.WHY_NOT_ELIGIBLE:
                return self._why_not(session, u, turn)
            case Intent.ASK_REQUIREMENTS:
                return self._requirements(session, u, turn)
            case _:
                return self._offers(session, turn)

    # --- Casos ---------------------------------------------------------------

    def _offers(self, session: Session, turn: _Turn) -> str:
        offers = self._load_offers(session, turn)
        if offers is None:
            return self._info_fallback(session, turn)
        lang = session.language
        automatic = [o for o in offers if o.attention_level == AttentionLevel.AUTOMATIC]
        review = [
            o
            for o in offers
            if o.attention_level
            not in (AttentionLevel.AUTOMATIC, AttentionLevel.NOT_ELIGIBLE)
        ]
        for offer in automatic or review:
            turn.use_offer(offer)
        if automatic:
            items = [
                WITH_LIMIT[lang].format(
                    product=product_name(o.product_code, lang),
                    limit=format_usd(o.offered_limit_usd or 0),
                )
                for o in automatic
            ]
            return self._say(
                session, turn, "offers_list", offers=join_items(items, lang)
            )
        if review:
            names = [product_name(o.product_code, lang) for o in review]
            return self._say(
                session, turn, "offers_review_only", products=join_items(names, lang)
            )
        return self._say(session, turn, "no_offers")

    def _apply(self, session: Session, u: Understanding, turn: _Turn) -> str:
        product = u.product_code or session.focus_product
        if product is None:
            return self._clarify(session, turn)
        offer = self._offer_for(session, turn, product)
        if offer is None:
            return self._fallback_handoff(session, turn, product)
        turn.use_offer(offer)
        level = offer.attention_level
        if level == AttentionLevel.NOT_ELIGIBLE:
            return self._explain_not_eligible(session, turn, offer)

        amount, shown = _amount_usd(session, u), _amount_text(session, u)
        questions = []
        if shown is not None:
            suggested = format_usd(offer.offered_limit_usd or 0)
            if amount is None:
                questions.append(
                    f"El cliente pide {shown}; sin tasa a USD, el monto no se usó "
                    f"para enrutar. La oferta sugiere {suggested}."
                )
            else:
                questions.append(
                    f"El cliente pide {shown} ({format_usd(amount)}); la oferta "
                    f"sugiere {suggested}."
                )
        if level == AttentionLevel.AUTOMATIC:
            existing = self._existing_application(session, turn, offer)
            if existing is not None:
                # Una solicitud por oferta: no se pide confirmar un duplicado.
                return self._say(
                    session,
                    turn,
                    "application_exists",
                    product=product_name(product, session.language),
                    reference=existing.reference,
                )
            limit = offer.offered_limit_usd
            if limit is None or limit <= 0:
                # Automático sin cupo: no hay qué confirmar. Lo revisa un analista.
                # Sin decisión adjunta: C9 no acepta un automático sin cupo.
                return self._fallback_handoff(
                    session,
                    turn,
                    product,
                    rule_id="offer_without_limit",
                    questions=[f"La oferta {offer.offer_id} es automática sin cupo."],
                )
            if amount is not None:
                # Lo que se muestra es lo que se guarda: centavos hacia abajo.
                amount = _to_cents(amount)
                if amount < MIN_GRANT_USD:
                    # Menos de 1 USD no es un pedido creíble: se pide aclarar.
                    return self._clarify(session, turn)
            if amount is not None and amount > limit:
                # Pedir más del cupo no se aprueba solo: se negocia o se revisa.
                within = amount <= (offer.negotiation_max_usd or 0)
                turn.rule_ids.append("requested_amount_above_offer")
                return self._handoff(
                    session,
                    turn,
                    handoff_type=HandoffType.ADVISOR
                    if within
                    else HandoffType.ANALYST_REVIEW,
                    level=AttentionLevel.ADVISOR if within else AttentionLevel.ANALYST,
                    trigger="requested_amount_above_offer",
                    product=product,
                    amount=shown,
                    offer=offer,
                    open_questions=questions,
                )
            # Pedir menos del cupo se respeta, también bajo el mínimo de
            # negociación: menos monto es menos exposición que lo aprobado. El
            # mínimo acota la negociación del asesor, no el crédito.
            granted = amount if amount is not None else _to_cents(limit)
            return self._ask_confirmation(session, turn, offer, granted)

        if level == AttentionLevel.ANALYST_AND_ADVISOR:
            questions.append("Tras la revisión de riesgo, asignar asesor.")
        is_advisor = level == AttentionLevel.ADVISOR
        return self._handoff(
            session,
            turn,
            handoff_type=HandoffType.ADVISOR
            if is_advisor
            else HandoffType.ANALYST_REVIEW,
            level=level,
            trigger=f"policy_{level.value}",
            product=product,
            amount=shown,
            offer=offer,
            open_questions=questions,
        )

    def _ask_confirmation(
        self, session: Session, turn: _Turn, offer: Offer, limit: float
    ) -> str:
        """Pide confirmar `limit` USD: el cupo o un monto menor pedido."""
        name = product_name(offer.product_code, session.language)
        session.pending = PendingConfirmation(
            confirmation_id=f"CONF-{uuid.uuid4().hex[:10].upper()}",
            offer_id=offer.offer_id,
            product_code=offer.product_code,
            limit_usd=limit,
            summary=f"{name}: {_usd_exact(limit)}",
        )
        session.move_to(SessionState.AWAITING_CONFIRMATION)
        turn.outcome = Outcome.AWAITING_CONFIRMATION
        turn.behaviors.append(Behavior.REQUEST_CONFIRMATION)
        turn.attention_level = AttentionLevel.AUTOMATIC
        return self._say(
            session, turn, "confirm_request", product=name, limit=_usd_exact(limit)
        )

    def _confirm(
        self, session: Session, turn: _Turn, confirmation_id: str, accept: bool
    ) -> str:
        pending = session.pending
        if (
            session.state != SessionState.AWAITING_CONFIRMATION
            or pending is None
            or pending.confirmation_id != confirmation_id
        ):
            turn.outcome = Outcome.REFUSED
            return self._say(session, turn, "nothing_pending")
        if not accept:
            session.pending = None
            session.move_to(SessionState.IDLE)
            return self._say(session, turn, "application_cancelled")

        session.pending = pending.model_copy(update={"accepted": True})
        product = pending.product_code
        offer = self._offer_for(session, turn, product)
        if offer is None or offer.offer_id != pending.offer_id:
            return self._fallback_handoff(
                session,
                turn,
                product,
                actions=["El cliente confirmó la solicitud."],
            )
        turn.use_offer(offer)
        turn.attention_level = AttentionLevel.AUTOMATIC
        confirmed = f"El cliente confirmó la solicitud de la oferta {offer.offer_id}."
        try:
            application = self.tools.create_application(
                session, offer.offer_id, confirmation_id, calls=turn.calls
            )
        except (ToolFailed, ToolDenied):
            return self._fallback_handoff(
                session,
                turn,
                product,
                offer=offer,
                actions=[confirmed, "La tool de solicitudes falló."],
                questions=["Registrar a mano la solicitud confirmada."],
            )
        if not self._verify(session, turn, application, offer):
            ref = application.reference
            return self._fallback_handoff(
                session,
                turn,
                product,
                offer=offer,
                actions=[confirmed, f"Se intentó registrar la solicitud {ref}."],
                questions=[f"Verificar si la solicitud {ref} quedó registrada."],
            )

        session.pending = None
        session.move_to(SessionState.DONE)
        turn.outcome = Outcome.ACTION_COMPLETED
        turn.application_reference = application.reference
        return self._say(
            session,
            turn,
            "application_created",
            product=product_name(product, session.language),
            reference=application.reference,
        )

    def _existing_application(
        self, session: Session, turn: _Turn, offer: Offer
    ) -> Application | None:
        """Solicitud ya registrada para la oferta. Si la tool cae, `None`: la
        tool de creación igual deniega el duplicado."""
        try:
            return self.tools.find_application(
                session, offer.offer_id, calls=turn.calls
            )
        except (ToolFailed, ToolDenied):
            return None

    def _verify(
        self, session: Session, turn: _Turn, application: Application, offer: Offer
    ) -> bool:
        """Lee la solicitud de vuelta. Solo se reporta lo que quedó registrado."""
        try:
            stored = self.tools.get_application(
                session, application.reference, calls=turn.calls
            )
        except (ToolFailed, ToolDenied):
            return False
        return (
            stored is not None
            and stored.customer_id == session.customer_id
            and stored.offer_id == offer.offer_id
            and stored.limit_usd == application.limit_usd
            and stored.status == "submitted"
        )

    def _to_advisor(self, session: Session, u: Understanding, turn: _Turn) -> str:
        product = u.product_code or session.focus_product
        dispute = u.intent == Intent.DISPUTE
        offers = self._load_offers(session, turn)
        offer = self._pick(offers, product) if offers is not None else None
        questions = [
            "El cliente disputa la decisión."
            if dispute
            else "El cliente pide hablar con un asesor."
        ]
        if offer is not None:
            turn.use_offer(offer)
        else:
            questions.append("No se pudo leer una oferta vigente del cliente.")
        if u.declared_monthly_income is not None:
            declared = _money(session, u.declared_monthly_income, u.amount_in_usd)
            questions.append(
                f"El cliente declara en el chat un ingreso de {declared}, sin verificar."
            )
        trigger = (
            "customer_disputes_rejection" if dispute else "customer_requests_human"
        )
        turn.rule_ids.append(trigger)
        return self._handoff(
            session,
            turn,
            handoff_type=HandoffType.ADVISOR,
            level=WITH_ADVISOR[offer.attention_level]
            if offer
            else AttentionLevel.ADVISOR,
            trigger=trigger,
            product=offer.product_code if offer else product,
            amount=_amount_text(session, u),
            offer=offer,
            open_questions=questions,
            high_priority=dispute,
        )

    def _declared_income(self, session: Session, u: Understanding, turn: _Turn) -> str:
        """El ingreso del chat no es un dato verificado: pregunta abierta."""
        product = u.product_code or session.focus_product
        offers = self._load_offers(session, turn)
        offer = self._pick(offers, product) if offers and product else None
        turn.rule_ids.append("declared_income_unverified")
        if offer is not None:
            turn.use_offer(offer)
            if offer.attention_level == AttentionLevel.NOT_ELIGIBLE:
                # Igual que la política: el ingreso declarado no rescata un no elegible.
                return self._explain_not_eligible(session, turn, offer)
        declared = (
            _money(session, u.declared_monthly_income, u.amount_in_usd)
            if u.declared_monthly_income
            else "sin monto"
        )
        questions = [
            (
                "El cliente declara en el chat un ingreso distinto al registrado "
                f"({declared}). ¿Es verificable?"
            )
        ]
        if offer is None:
            questions.append("No hay oferta vigente asociada a la conversación.")
        return self._handoff(
            session,
            turn,
            handoff_type=HandoffType.ANALYST_REVIEW,
            level=WITH_ANALYST[offer.attention_level]
            if offer
            else AttentionLevel.ANALYST,
            trigger="declared_income_unverified",
            product=product,
            amount=_amount_text(session, u),
            offer=offer,
            open_questions=questions,
            template="income_noted",
        )

    def _why_not(self, session: Session, u: Understanding, turn: _Turn) -> str:
        product = u.product_code or session.focus_product
        offers = self._load_offers(session, turn)
        if offers is None:
            return self._info_fallback(session, turn)
        if product is not None:
            offer = self._pick(offers, product)
            if offer is None:
                return self._info_fallback(session, turn)
            turn.use_offer(offer)
            if offer.attention_level == AttentionLevel.NOT_ELIGIBLE:
                return self._explain_not_eligible(session, turn, offer)
            return self._explain_level(session, turn, offer)
        rejected = [
            o for o in offers if o.attention_level == AttentionLevel.NOT_ELIGIBLE
        ]
        if not rejected:
            return self._offers(session, turn)
        turn.use_offer(rejected[0])
        return self._explain_not_eligible(session, turn, rejected[0])

    def _requirements(self, session: Session, u: Understanding, turn: _Turn) -> str:
        product = u.product_code or session.focus_product
        if product is None:
            return self._clarify(session, turn)
        offers = self._load_offers(session, turn)
        offer = self._pick(offers, product) if offers is not None else None
        if offer is None:
            return self._info_fallback(session, turn)
        turn.use_offer(offer)
        if offer.attention_level == AttentionLevel.NOT_ELIGIBLE:
            return self._explain_not_eligible(session, turn, offer)
        return self._explain_level(session, turn, offer)

    # --- Respuestas ------------------------------------------------------------

    def _explain_level(self, session: Session, turn: _Turn, offer: Offer) -> str:
        turn.attention_level = offer.attention_level
        name = product_name(offer.product_code, session.language)
        if offer.attention_level == AttentionLevel.AUTOMATIC:
            limit = format_usd(offer.offered_limit_usd or 0)
            return self._say(
                session, turn, "requirements_automatic", product=name, limit=limit
            )
        return self._say(session, turn, "requirements_review", product=name)

    def _explain_not_eligible(self, session: Session, turn: _Turn, offer: Offer) -> str:
        lang = session.language
        turn.attention_level = AttentionLevel.NOT_ELIGIBLE
        reasons = reasons_text(offer.reasons, lang)
        facts = {"product": product_name(offer.product_code, lang), "reasons": reasons}
        if offer.alternative_product_code is not None:
            alternative = product_name(offer.alternative_product_code, lang)
            return self._say(
                session,
                turn,
                "not_eligible_with_alternative",
                alternative=alternative,
                **facts,
            )
        return self._say(session, turn, "not_eligible", **facts)

    def _clarify(self, session: Session, turn: _Turn) -> str:
        turn.outcome = Outcome.CLARIFICATION
        turn.behaviors.append(Behavior.ASK_CLARIFICATION)
        return self._say(session, turn, "clarify")

    def _info_fallback(self, session: Session, turn: _Turn) -> str:
        """Consulta sin datos confiables: no se inventa nada, se pide reintentar."""
        turn.outcome = Outcome.FALLBACK
        turn.behaviors.append(Behavior.SAFE_FALLBACK)
        return self._say(session, turn, "fallback_unavailable")

    def _fallback_handoff(
        self,
        session: Session,
        turn: _Turn,
        product: ProductCode | None,
        *,
        offer: Offer | None = None,
        actions: Sequence[str] = (),
        questions: Sequence[str] = (),
        rule_id: str | None = None,
    ) -> str:
        """Acción sin oferta confiable o con tool caída: pasa al analista."""
        turn.behaviors.append(Behavior.SAFE_FALLBACK)
        default_rule = "offer_unavailable" if offer is None else "tool_failure"
        turn.rule_ids.append(rule_id or default_rule)
        default = (
            f"No hay oferta vigente verificada para {_product_es(product)} "
            "(vencida, faltante o servicio caído)."
        )
        return self._handoff(
            session,
            turn,
            handoff_type=HandoffType.ANALYST_REVIEW,
            level=offer.attention_level if offer else None,
            trigger="safe_fallback",
            product=product,
            offer=offer,
            actions=actions,
            open_questions=[*questions] if offer else [default, *questions],
            template="fallback_handoff",
        )

    def _handoff(
        self,
        session: Session,
        turn: _Turn,
        *,
        handoff_type: HandoffType,
        level: AttentionLevel | None,
        trigger: str,
        product: ProductCode | None,
        offer: Offer | None,
        amount: str | None = None,
        open_questions: Sequence[str] = (),
        actions: Sequence[str] = (),
        high_priority: bool = False,
        template: str | None = None,
    ) -> str:
        summary = f"El cliente solicita {_product_es(product)}"
        if amount is not None:
            summary += f" por {amount}"
        questions = list(open_questions)
        if offer is None and not questions:
            questions.append("No hay oferta vigente verificada.")
        preferential = offer is not None and offer.preferential
        try:
            case = self.tools.create_handoff(
                session,
                handoff_type=handoff_type,
                trigger_reason=trigger,
                request_summary=summary + ".",
                verified_facts=_verified_facts(offer) if offer else [],
                policy_decision=offer.to_decision() if offer else None,
                actions_taken=actions,
                open_questions=questions,
                priority=Priority.HIGH
                if high_priority or preferential
                else Priority.NORMAL,
                calls=turn.calls,
            )
        except (ToolFailed, ToolDenied):
            # Ni el caso se pudo crear: se avisa sin prometer nada. Una
            # confirmación aceptada no queda colgada: la sesión vuelve a idle.
            session.pending = None
            if session.state not in (SessionState.IDLE, SessionState.HANDOFF):
                session.move_to(SessionState.IDLE)
            return self._info_fallback(session, turn)
        session.pending = None
        session.handoff_case_id = case.case_id
        session.move_to(SessionState.HANDOFF)
        turn.handoff = case
        turn.outcome = Outcome.HANDOFF
        turn.behaviors.append(Behavior.HANDOFF)
        turn.attention_level = level
        if template is None:
            template = (
                "handoff_advisor"
                if handoff_type == HandoffType.ADVISOR
                else "handoff_analyst"
            )
        lang = session.language
        name = product_name(product, lang) if product else GENERIC_PRODUCT[lang]
        return self._say(session, turn, template, product=name, case_id=case.case_id)

    # --- Soporte ---------------------------------------------------------------

    def _evict_expired(self) -> None:
        """Expulsa las sesiones vencidas hace más de `evict_after`.

        Corre en cada acceso (abrir sesión, mensaje, confirmación). Recorre todas
        las sesiones: suficiente para el volumen de la demo.
        """
        cutoff = self.clock() - self.evict_after
        for session_id in [
            sid for sid, s in self.sessions.items() if s.expires_at < cutoff
        ]:
            del self.sessions[session_id]

    def _session(self, session_id: str) -> Session:
        self._evict_expired()
        try:
            return self.sessions[session_id]
        except KeyError:
            raise UnknownSession(session_id) from None

    def _load_offers(self, session: Session, turn: _Turn) -> list[Offer] | None:
        """Ofertas vigentes. `None` si la fuente falló o todo está vencido."""
        try:
            lookup = self.tools.get_active_offers(
                session, session.customer_id, calls=turn.calls
            )
        except (ToolFailed, ToolDenied):
            return None
        if lookup.expired_count and not lookup.offers:
            return None
        return lookup.offers

    @staticmethod
    def _pick(
        offers: Sequence[Offer] | None, product: ProductCode | None
    ) -> Offer | None:
        if not offers or product is None:
            return None
        return next((o for o in offers if o.product_code == product), None)

    def _offer_for(
        self, session: Session, turn: _Turn, product: ProductCode
    ) -> Offer | None:
        return self._pick(self._load_offers(session, turn), product)

    def _say(
        self, session: Session, turn: _Turn, template_id: str, **facts: object
    ) -> str:
        return self.llm.render(
            template_id,
            {"language": session.language.value, **facts},
            usage=turn.llm_usage,
        )

    def _finish(
        self,
        session: Session,
        turn: _Turn,
        text: str,
        started: float,
    ) -> ChatReply:
        usage = sum(turn.llm_usage, Usage())
        case = turn.handoff
        trace = TurnTrace(
            trace_id=f"TRC-{uuid.uuid4().hex}",
            session_id=session.session_id,
            turn_index=session.turn_index,
            timestamp=self.clock(),
            customer_id=session.customer_id,
            eval_case_id=session.eval_case_id,
            intent=turn.intent,
            tools=turn.calls,
            behaviors=_dedup(turn.behaviors),
            outcome=turn.outcome,
            attention_level=turn.attention_level,
            rule_ids=_dedup(turn.rule_ids),
            sources=_dedup(turn.sources),
            policy_version=turn.policy_version,
            llm_model=self.llm.model_name,
            prompt_version=self.llm.prompt_version,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            cost_usd=usage.cost_usd,
            latency_ms=(time.perf_counter() - started) * 1000,
            handoff_case_id=case.case_id if case else None,
            handoff_type=case.handoff_type if case else None,
            application_reference=turn.application_reference,
        )
        self.sink.write(trace)
        session.turn_index += 1
        session.remember(ChatMessage(role=Role.ASSISTANT, content=text))
        pending = session.pending
        return ChatReply(
            session_id=session.session_id,
            reply=text,
            state=session.state,
            pending_confirmation=PendingConfirmationView(
                confirmation_id=pending.confirmation_id,
                action=pending.action,
                summary=pending.summary,
            )
            if pending is not None
            else None,
            handoff_case_id=case.case_id if case else None,
            application_reference=turn.application_reference,
            trace_id=trace.trace_id,
        )


def _money(session: Session, amount: float, in_usd: bool) -> str:
    """Monto con su moneda original, para el analista."""
    currency = "USD" if in_usd else (session.currency or "en moneda local")
    digits = ",.0f" if float(amount).is_integer() else ",.2f"
    return f"{amount:{digits}} {currency}"


def _to_cents(amount: float) -> float:
    """Trunca a centavos. Hacia abajo: nunca supera el cupo que ya cumplía."""
    return float(Decimal(str(amount)).quantize(Decimal("0.01"), ROUND_DOWN))


def _usd_exact(amount: float) -> str:
    """USD con centavos cuando los hay (siempre bajo 1.000): se ve lo que se guarda."""
    if amount < 1000 or not float(amount).is_integer():
        return f"{amount:,.2f} USD"
    return format_usd(amount)


def _amount_text(session: Session, u: Understanding) -> str | None:
    return _money(session, u.amount, u.amount_in_usd) if u.amount else None


def _amount_usd(session: Session, u: Understanding) -> float | None:
    """Monto pedido en USD para compararlo con cupos. `None` si no hay tasa."""
    if u.amount is None:
        return None
    if u.amount_in_usd or session.currency == Currency.USD:
        return u.amount
    if session.usd_per_unit is None:
        return None
    return u.amount * session.usd_per_unit


def _verified_facts(offer: Offer) -> list[str]:
    """Hechos de C6 para el humano. Solo datos de la oferta, nada del chat."""
    facts = [
        f"Oferta {offer.offer_id} vigente hasta {offer.expires_at:%Y-%m-%d %H:%M} UTC.",
        f"Nivel de atención de la política: {offer.attention_level.value}.",
        f"Exposición del producto: {offer.exposure.value}.",
    ]
    if offer.score is not None:
        facts.append(f"Puntaje interno {offer.score} (banda {offer.band}).")
    else:
        facts.append("Sin puntaje interno (datos faltantes).")
    if offer.offered_limit_usd is not None:
        facts.append(
            f"Cupo sugerido {format_usd(offer.offered_limit_usd)}, rango de "
            f"negociación {format_usd(offer.negotiation_min_usd or 0)} a "
            f"{format_usd(offer.negotiation_max_usd or 0)}."
        )
    facts.append(
        f"Política {offer.policy_version}, corte {offer.snapshot_date}, "
        f"puntaje {offer.score_version}."
    )
    return facts
