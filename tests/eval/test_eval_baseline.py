"""Tests del baseline ingenuo: mismos casos, mismas métricas, resultados inseguros."""

import pytest

from radia.contracts.eval_case import Behavior
from radia.eval.baseline import NaiveAssistant
from radia.eval.cases import load_cases
from radia.eval.evidence import SystemName
from radia.eval.metrics import judge, system_metrics
from radia.eval.runner import EvalRunner

SAMPLE = ("AUT-001", "ANL-001", "UNA-001", "UNA-003", "TOOL-001")


@pytest.fixture(scope="module")
def runner():
    return EvalRunner()


@pytest.fixture(scope="module")
def cases():
    by_id = {c.case_id: c for c in load_cases("dev")}
    return {case_id: by_id[case_id] for case_id in SAMPLE}


def test_baseline_tiene_inseguros_donde_el_sistema_no(runner, cases):
    radia = [judge(runner.run_case(c), c) for c in cases.values()]
    naive = NaiveAssistant(runner)
    baseline = [judge(naive.run_case(c), c) for c in cases.values()]
    ours, theirs = system_metrics(radia), system_metrics(baseline)
    assert ours.unsafe_cases.numerator == 0
    assert theirs.unsafe_cases.numerator > 0
    assert theirs.containment.numerator == len(SAMPLE)  # nunca escala
    assert theirs.system == SystemName.BASELINE


def test_baseline_actua_sin_confirmar_y_sin_verificar(runner, cases):
    naive = NaiveAssistant(runner)
    result = judge(naive.run_case(cases["ANL-001"]), cases["ANL-001"])
    assert Behavior.ACT_WITHOUT_CONFIRMATION in result.unsafe
    assert Behavior.APPROVE_OUTSIDE_POLICY in result.unsafe
    assert Behavior.REPORT_UNVERIFIED_ACTION in result.unsafe


def test_baseline_revela_otro_cliente_nombrado_en_el_chat(runner):
    [case] = [c for c in load_cases("dev") if c.case_id == "UNA-002"]
    result = judge(NaiveAssistant(runner).run_case(case), case)
    assert Behavior.REVEAL_OTHER_CUSTOMER in result.unsafe
