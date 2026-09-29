"""Corrida pequeña del runner y del baseline sobre 5 casos dev.

Con `FakeLanguageModel`: sin red ni gasto.
"""

import pytest

from radia.backend.agent.llm import FakeLanguageModel
from radia.contracts.eval_case import Behavior
from radia.contracts.trace import Outcome
from radia.eval.cases import load_cases
from radia.eval.evidence import SystemName
from radia.eval.metrics import judge
from radia.eval.runner import NO_SESSION_ID, EvalRunner

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
