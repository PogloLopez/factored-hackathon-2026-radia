"""Corrida pequeña del runner y del baseline sobre 5 casos dev.

Con `FakeLanguageModel`: sin red ni gasto.
"""

from datetime import timedelta

import pytest

from radia.backend.agent.llm import FakeLanguageModel
from radia.backend.agent.session import Session
from radia.backend.agent.tools import (
    Application,
    InMemoryApplicationStore,
    InMemoryCaseStore,
    InMemoryOfferRepository,
    ToolDenied,
    utc_now,
)
from radia.contracts.common import ProductCode
from radia.contracts.eval_case import Behavior
from radia.contracts.trace import Outcome
from radia.eval.cases import load_cases
from radia.eval.demo_customers import demo_offers
from radia.eval.evidence import CaseRun, SystemName
from radia.eval.metrics import judge
from radia.eval.runner import NO_SESSION_ID, EvalRunner, _AuditedToolBox

SAMPLE = ("AUT-001", "ANL-001", "UNA-001", "UNA-003", "TOOL-001")


@pytest.fixture(scope="module")
def runner():
    return EvalRunner()


@pytest.fixture(scope="module")
def cases():
    by_id = {c.case_id: c for c in load_cases("dev")}
    return {case_id: by_id[case_id] for case_id in SAMPLE}


@pytest.fixture(scope="module")
def runs(runner, cases):
    return {c.case_id: runner.run_case(c) for c in cases.values()}


def test_modelo_por_defecto_es_el_falso():
    assert isinstance(EvalRunner().llm, FakeLanguageModel)


def test_cada_caso_deja_traces_con_su_id(runs):
    for case_id, run in runs.items():
        assert run.system == SystemName.RADIA
        assert run.traces, case_id
        if case_id != "UNA-003":
            assert {t.eval_case_id for t in run.traces} == {case_id}


def test_automatico_se_confirma_y_se_registra(runs, cases):
    run = runs["AUT-001"]
    assert [t.outcome for t in run.traces] == [
        Outcome.AWAITING_CONFIRMATION,
        Outcome.ACTION_COMPLETED,
    ]
    assert run.confirmed_turns == [1]
    [action] = run.actions
    assert action.stored and action.turn_index == 1
    result = judge(run, cases["AUT-001"])
    assert result.passed, result.reasons
    assert result.auto_resolved


def test_analista_escala_con_expediente(runs, cases):
    run = runs["ANL-001"]
    [handoff] = run.handoffs
    assert handoff.found and handoff.n_verified_facts > 0
    # El expediente sale del almacén de casos, con su turno y su cliente.
    [handoff_trace] = [t for t in run.traces if t.outcome == Outcome.HANDOFF]
    assert handoff.turn_index == handoff_trace.turn_index
    assert handoff.customer_id == run.customer_id
    assert judge(run, cases["ANL-001"]).passed


def test_otro_cliente_no_se_lee(runs, cases):
    run = runs["UNA-001"]
    assert all(r.customer_id == run.customer_id for r in run.data_reads)
    result = judge(run, cases["UNA-001"])
    assert Behavior.REFUSE in result.behaviors
    assert Behavior.REVEAL_OTHER_CUSTOMER not in result.behaviors


def test_sin_sesion_rechaza_antes_del_orquestador(runs, cases):
    run = runs["UNA-003"]
    assert run.customer_id is None and run.data_reads == []
    assert {t.session_id for t in run.traces} == {NO_SESSION_ID}
    assert judge(run, cases["UNA-003"]).passed


def test_politica_caida_reintenta_acotado_y_cae_a_fallback(runs, cases):
    run = runs["TOOL-001"]
    lookup = run.traces[0].tools[0]
    assert not lookup.ok and lookup.attempt == 3
    assert run.actions == []
    assert judge(run, cases["TOOL-001"]).passed


def test_sesion_vencida_niega_todo(runner):
    [case] = [c for c in load_cases("dev") if c.case_id == "UNA-005"]
    run = runner.run_case(case)
    assert run.traces[0].outcome == Outcome.REFUSED
    assert run.data_reads == [] and run.actions == []


def test_ofertas_vencidas_no_se_citan(runner):
    [case] = [c for c in load_cases("dev") if c.case_id == "STA-001"]
    run = runner.run_case(case)
    assert run.offers and not any(o.readable for o in run.offers)
    result = judge(run, case)
    assert Behavior.INVENT_OFFER not in result.behaviors


# --- Auditoría de todas las tools con datos de cliente --------------------------


class _LeakyApplicationStore(InMemoryApplicationStore):
    """Almacén con un bug: devuelve la solicitud de otro cliente."""

    def for_offer(self, customer_id: str, offer_id: str) -> Application | None:
        return next(iter(self.applications.values()), None)


def _app(customer_id: str) -> Application:
    return Application(
        reference=f"APP-{customer_id}",
        customer_id=customer_id,
        offer_id="OFF-X",
        product_code=ProductCode.CC_BASIC,
        limit_usd=100.0,
        confirmation_id=f"CNF-{customer_id}",
        created_at=utc_now(),
    )


def _audited(store: InMemoryApplicationStore) -> tuple[_AuditedToolBox, list]:
    reads: list = []
    tools = _AuditedToolBox(
        InMemoryOfferRepository(demo_offers(utc_now())),
        store,
        InMemoryCaseStore(),
        clock=utc_now,
        log=reads,
        turn=lambda: 0,
    )
    return tools, reads


def _session(customer_id: str) -> Session:
    return Session(
        session_id="SES-T",
        customer_id=customer_id,
        expires_at=utc_now() + timedelta(minutes=10),
    )


def test_solicitud_de_otro_cliente_devuelta_por_una_tool_revela(cases):
    me, other = "DEMO000004", "DEMO000001"
    store = _LeakyApplicationStore()
    store.create(_app(other))
    tools, reads = _audited(store)
    tools.find_application(_session(me), "OFF-X", calls=[])
    assert [(r.customer_id, r.source) for r in reads] == [(other, "find_application")]
    evidence = CaseRun(
        system=SystemName.RADIA,
        run_index=0,
        case_id="UNA-001",
        customer_id=me,
        traces=[],
        data_reads=reads,
        latency_ms=0.0,
    )
    assert Behavior.REVEAL_OTHER_CUSTOMER in judge(evidence, cases["UNA-001"]).unsafe


def test_tool_denegada_no_deja_lectura():
    me, other = "DEMO000004", "DEMO000001"
    store = InMemoryApplicationStore()
    store.create(_app(other))
    tools, reads = _audited(store)
    with pytest.raises(ToolDenied):
        tools.get_application(_session(me), f"APP-{other}", calls=[])
    assert reads == []


def test_se_auditan_ofertas_solicitudes_y_expedientes(runs):
    sources = {r.source for run in runs.values() for r in run.data_reads}
    assert {"active_offers", "get_active_offers", "create_handoff"} <= sources
    assert {"create_application", "get_application"} <= sources
