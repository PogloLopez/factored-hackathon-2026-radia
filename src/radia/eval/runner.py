"""Runner de evaluación: reproduce cada caso C10 contra el orquestador real.

Por caso:
1. Orquestador fresco (sesiones, solicitudes y bandeja vacías) sobre las
   ofertas C6 de los clientes demo (`demo_offers`).
2. Inyecta la falla del caso: política caída, ofertas vencidas, timeout de
   tool o sesión vencida.
3. Abre la sesión del cliente. Sin `customer_id` no hay sesión: se simula la
   puerta de autenticación de la API, que rechaza antes del orquestador.
4. Reproduce los turnos. Si el orquestador pide confirmación, el cliente
   aprieta "Sí" en ese momento, para medir la acción de punta a punta.
5. Guarda los `TurnTrace` (C11) y la evidencia externa (`CaseRun`).

LLM inyectable. Por defecto `FakeLanguageModel`: sin red ni gasto. Groq real
solo con el checkpoint de Pablo.
"""

import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta

from tenacity import wait_none

from radia.backend.agent.llm import FakeLanguageModel, LanguageModel
from radia.backend.agent.orchestrator import SESSION_TTL, ChatReply, Orchestrator
from radia.backend.agent.session import Currency
from radia.backend.agent.tools import (
    Application,
    InMemoryApplicationStore,
    InMemoryCaseStore,
    InMemoryOfferRepository,
    Offer,
    OfferRepository,
    ToolBox,
    TransientToolError,
    utc_now,
)
from radia.backend.agent.tracing import InMemoryTraceSink
from radia.contracts.common import Country
from radia.contracts.eval_case import EvalCase, InjectedFailure
from radia.contracts.trace import Outcome, TurnTrace
from radia.eval.demo_customers import DEMO_PROFILES, demo_offers
from radia.eval.evidence import (
    ActionRecord,
    CaseRun,
    DataRead,
    HandoffRecord,
    OfferFact,
    SystemName,
)

# Las ofertas vencidas se generan con más días que su vigencia (7).
EXPIRED_OFFERS_AGE = timedelta(days=8)
NO_SESSION_ID = "no-session"
# Moneda y tasa fija (USD por unidad local) por país del cliente demo. Fixture:
# aproximaciones redondas, las mismas que usan las notas de los casos. En
# producción salen del servicio de tasas (`daily_exchange_rates`).
CURRENCY_BY_COUNTRY: dict[Country, tuple[Currency, float]] = {
    Country.MEXICO: (Currency.MXN, 1 / 18),
    Country.COLOMBIA: (Currency.COP, 1 / 4000),
    Country.ARGENTINA: (Currency.ARS, 1 / 1000),
}
# Fallas que dejan al sistema sin poder leer ofertas confiables.
UNREADABLE = frozenset(
    {
        InjectedFailure.POLICY_DOWN,
        InjectedFailure.TOOL_TIMEOUT,
        InjectedFailure.OFFERS_EXPIRED,
        InjectedFailure.SESSION_EXPIRED,
    }
)


class _Clock:
    """Reloj real con un desfase: adelantarlo vence la sesión."""

    def __init__(self) -> None:
        self.offset = timedelta(0)

    def __call__(self) -> datetime:
        return utc_now() + self.offset


# --- Fuentes auditadas y con fallas -------------------------------------------


class _DownOfferRepository:
    """Fuente de ofertas caída (política caída o timeout)."""

    def __init__(self, code: str) -> None:
        self.code = code

    def offers_for(self, customer_id: str) -> list[Offer]:
        raise TransientToolError(self.code)


class _TimeoutApplicationStore(InMemoryApplicationStore):
    """Almacén de solicitudes que no responde."""

    def create(self, application: Application) -> Application:
        raise TransientToolError("timeout")

    def get(self, reference: str) -> Application | None:
        raise TransientToolError("timeout")

    def for_offer(self, customer_id: str, offer_id: str) -> Application | None:
        raise TransientToolError("timeout")


class _AuditedOfferRepository:
    """Anota cada lectura exitosa: qué cliente se leyó y en qué turno."""

    def __init__(
        self, inner: OfferRepository, log: list[DataRead], turn: Callable[[], int]
    ) -> None:
        self.inner = inner
        self.log = log
        self.turn = turn

    def offers_for(self, customer_id: str) -> list[Offer]:
        offers = self.inner.offers_for(customer_id)
        self.log.append(
            DataRead(
                turn_index=self.turn(), customer_id=customer_id, source="active_offers"
            )
        )
        return offers


class _AuditedApplicationStore(InMemoryApplicationStore):
    """Anota el turno en que cada solicitud nueva quedó registrada."""

    def __init__(self, turn: Callable[[], int]) -> None:
        super().__init__()
        self.turn = turn
        self.created_turn: dict[str, int] = {}

    def create(self, application: Application) -> Application:
        stored = super().create(application)
        self.created_turn.setdefault(stored.reference, self.turn())
        return stored


# --- Runner ------------------------------------------------------------------


@dataclass
class _Harness:
    orchestrator: Orchestrator
    sink: InMemoryTraceSink
    clock: _Clock
    reads: list[DataRead]
    applications: InMemoryApplicationStore
    cases: InMemoryCaseStore


class EvalRunner:
    """Corre casos C10 contra el orquestador. Un orquestador fresco por caso."""

    def __init__(self, llm: LanguageModel | None = None) -> None:
        self.llm = llm or FakeLanguageModel()
        now = utc_now()
        # Ofertas recién generadas y ofertas ya vencidas: mismo job, otra fecha.
        self._fresh = InMemoryOfferRepository(demo_offers(now - timedelta(hours=1)))
        self._expired = InMemoryOfferRepository(demo_offers(now - EXPIRED_OFFERS_AGE))

    def run(self, cases: Sequence[EvalCase], run_index: int = 0) -> list[CaseRun]:
        return [self.run_case(case, run_index) for case in cases]

    def run_case(self, case: EvalCase, run_index: int = 0) -> CaseRun:
        if case.customer_id is None:
            return self._run_without_session(case, run_index)
        h = self._harness(case.inject_failure)
        currency, usd_per_unit = CURRENCY_BY_COUNTRY[
            DEMO_PROFILES[case.customer_id].country
        ]
        session = h.orchestrator.start_session(
            case.customer_id,
            eval_case_id=case.case_id,
            currency=currency,
            usd_per_unit=usd_per_unit,
        )
        if case.inject_failure == InjectedFailure.SESSION_EXPIRED:
            h.clock.offset = SESSION_TTL + timedelta(minutes=1)

        sid = session.session_id
        confirmed: list[int] = []
        elapsed = 0.0
        for turn in case.turns:
            reply, ms = _timed(h.orchestrator.handle_message, sid, turn.content)
            elapsed += ms
            if reply.pending_confirmation is not None:
                # El cliente aprieta "Sí": se mide la acción de punta a punta.
                confirmed.append(len(h.sink.traces))
                cid = reply.pending_confirmation.confirmation_id
                _, ms = _timed(h.orchestrator.confirm, sid, cid, True)
                elapsed += ms

        return CaseRun(
            system=SystemName.RADIA,
            run_index=run_index,
            case_id=case.case_id,
            customer_id=case.customer_id,
            traces=h.sink.traces,
            data_reads=h.reads,
            actions=_actions(h.applications),
            confirmed_turns=confirmed,
            handoffs=_handoffs(h.sink.traces, h.cases),
            offers=self.offer_facts(case.customer_id, case.inject_failure),
            latency_ms=elapsed,
        )

    def offer_facts(
        self, customer_id: str | None, failure: InjectedFailure | None
    ) -> list[OfferFact]:
        """Verdad de terreno: ofertas del cliente y si el sistema podía leerlas."""
        if customer_id is None:
            return []
        source = self._expired if failure == InjectedFailure.OFFERS_EXPIRED else None
        offers = (source or self._fresh).offers_for(customer_id)
        readable = failure not in UNREADABLE
        return [
            OfferFact(
                offer_id=o.offer_id,
                product_code=o.product_code,
                attention_level=o.attention_level,
                offered_limit_usd=o.offered_limit_usd,
                readable=readable and o.is_valid(utc_now()),
            )
            for o in offers
        ]

    def offer_rows(self, customer_id: str) -> list[Offer]:
        """Filas C6 del cliente sin filtrar vigencia (para el baseline)."""
        return self._fresh.offers_for(customer_id)

    def _harness(self, failure: InjectedFailure | None) -> _Harness:
        sink = InMemoryTraceSink()
        clock = _Clock()
        reads: list[DataRead] = []

        def turn() -> int:
            return len(sink.traces)

        match failure:
            case InjectedFailure.POLICY_DOWN:
                inner: OfferRepository = _DownOfferRepository("policy_down")
            case InjectedFailure.TOOL_TIMEOUT:
                inner = _DownOfferRepository("timeout")
            case InjectedFailure.OFFERS_EXPIRED:
                inner = self._expired
            case _:
                inner = self._fresh
        if failure == InjectedFailure.TOOL_TIMEOUT:
            applications: InMemoryApplicationStore = _TimeoutApplicationStore()
        else:
            applications = _AuditedApplicationStore(turn)
        cases = InMemoryCaseStore()
        tools = ToolBox(
            _AuditedOfferRepository(inner, reads, turn),
            applications,
            cases,
            clock=clock,
            wait=wait_none(),
        )
        orchestrator = Orchestrator(self.llm, tools, sink, clock=clock)
        return _Harness(orchestrator, sink, clock, reads, applications, cases)

    def _run_without_session(self, case: EvalCase, run_index: int) -> CaseRun:
        """Sin sesión la API rechaza antes del orquestador: no hay datos ni LLM."""
        traces = []
        elapsed = 0.0
        for index, _ in enumerate(case.turns):
            started = time.perf_counter()
            trace = TurnTrace(
                trace_id=f"TRC-NOAUTH-{case.case_id}-{index}",
                session_id=NO_SESSION_ID,
                turn_index=index,
                timestamp=utc_now(),
                customer_id=None,
                eval_case_id=case.case_id,
                intent="unauthenticated",
                outcome=Outcome.REFUSED,
                llm_model=self.llm.model_name,
                prompt_version=self.llm.prompt_version,
                input_tokens=0,
                output_tokens=0,
                cost_usd=0.0,
                latency_ms=0.0,
            )
            ms = (time.perf_counter() - started) * 1000
            traces.append(trace.model_copy(update={"latency_ms": ms}))
            elapsed += ms
        return CaseRun(
            system=SystemName.RADIA,
            run_index=run_index,
            case_id=case.case_id,
            customer_id=None,
            traces=traces,
            latency_ms=elapsed,
        )


def _timed(call: Callable[..., ChatReply], *args: object) -> tuple[ChatReply, float]:
    """Llama y mide el reloj de pared en milisegundos."""
    started = time.perf_counter()
    reply = call(*args)
    return reply, (time.perf_counter() - started) * 1000


def _actions(store: InMemoryApplicationStore) -> list[ActionRecord]:
    turns = getattr(store, "created_turn", {})
    return [
        ActionRecord(
            turn_index=turns.get(app.reference, 0),
            customer_id=app.customer_id,
            reference=app.reference,
            offer_id=app.offer_id,
            product_code=app.product_code,
            amount_usd=app.limit_usd,
            stored=True,
        )
        for app in store.applications.values()
    ]


def _handoffs(
    traces: Sequence[TurnTrace], store: InMemoryCaseStore
) -> list[HandoffRecord]:
    records = []
    for trace in traces:
        if trace.handoff_case_id is None or trace.handoff_type is None:
            continue
        case = store.get(trace.handoff_case_id)
        records.append(
            HandoffRecord(
                turn_index=trace.turn_index,
                case_id=trace.handoff_case_id,
                handoff_type=trace.handoff_type,
                found=case is not None,
                n_verified_facts=len(case.verified_facts) if case else 0,
                n_open_questions=len(case.open_questions) if case else 0,
                has_policy_decision=bool(case and case.policy_decision),
            )
        )
    return records
