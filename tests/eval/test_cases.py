"""Tests de los casos de evaluación C10 y de su cargador."""

import re
from collections import Counter

import pytest

from radia.contracts.eval_case import Behavior, Category, EvalCase, Language, Split
from radia.eval.cases import cases_path, load_cases
from radia.eval.demo_customers import DEMO_PROFILES

MIN_HELDOUT_PER_CATEGORY = 6
MIN_DEV = 50
MIN_HELDOUT = 100


@pytest.fixture(scope="module")
def dev() -> list[EvalCase]:
    return load_cases(Split.DEV)


@pytest.fixture(scope="module")
def heldout() -> list[EvalCase]:
    return load_cases(Split.HELDOUT)


def _normalize(text: str) -> str:
    return re.sub(r"\W+", " ", text.lower()).strip()


def test_tamanos(dev, heldout):
    assert len(dev) >= MIN_DEV
    assert len(heldout) >= MIN_HELDOUT


def test_split_del_archivo(dev, heldout):
    assert {c.split for c in dev} == {Split.DEV}
    assert {c.split for c in heldout} == {Split.HELDOUT}


def test_ids_unicos_entre_splits(dev, heldout):
    ids = [c.case_id for c in dev + heldout]
    assert len(ids) == len(set(ids))


def test_clientes_existen_o_sin_sesion(dev, heldout):
    for c in dev + heldout:
        assert c.customer_id is None or c.customer_id in DEMO_PROFILES


def test_todas_las_categorias_en_dev(dev):
    assert {c.category for c in dev} == set(Category)


def test_heldout_minimo_por_categoria(heldout):
    counts = Counter(c.category for c in heldout)
    for category in Category:
        assert counts[category] >= MIN_HELDOUT_PER_CATEGORY, category


def test_idiomas_cubiertos(dev, heldout):
    for cases in (dev, heldout):
        assert {c.language for c in cases} == set(Language)


def test_hay_casos_sin_sesion(dev, heldout):
    for cases in (dev, heldout):
        assert any(c.customer_id is None for c in cases)


def test_heldout_no_repite_textos_dev(dev, heldout):
    dev_texts = {_normalize(t.content) for c in dev for t in c.turns}
    for c in heldout:
        for turn in c.turns:
            assert _normalize(turn.content) not in dev_texts, c.case_id


def test_adversariales_y_sin_autorizacion_exigen_algo(dev, heldout):
    riesgosas = {Category.ADVERSARIAL, Category.UNAUTHORIZED}
    for c in dev + heldout:
        if c.category in riesgosas:
            assert c.expected.must, c.case_id


def test_sin_sesion_exige_negativa(dev, heldout):
    for c in dev + heldout:
        if c.customer_id is None:
            assert Behavior.REFUSE in c.expected.must, c.case_id
            assert Behavior.REVEAL_OTHER_CUSTOMER in c.expected.must_not, c.case_id


def test_autor(dev, heldout):
    assert {c.author for c in dev + heldout} == {"claude"}


class _FakeFile:
    """Archivo en memoria para probar el cargador sin tocar disco."""

    name = "heldout.jsonl"

    def __init__(self, text: str) -> None:
        self.text = text

    def read_text(self, encoding: str) -> str:
        return self.text


def _first_dev_line() -> str:
    return cases_path(Split.DEV).read_text(encoding="utf-8").splitlines()[0]


def _load_heldout_from(monkeypatch, text: str) -> list[EvalCase]:
    monkeypatch.setattr("radia.eval.cases.cases_path", lambda split: _FakeFile(text))
    return load_cases(Split.HELDOUT)


def test_split_equivocado_falla(monkeypatch):
    with pytest.raises(ValueError, match="split"):
        _load_heldout_from(monkeypatch, _first_dev_line())


def test_cliente_desconocido_falla(monkeypatch):
    line = _first_dev_line().replace('"dev"', '"heldout"')
    line = re.sub(r"DEMO\d{6}", "DEMO999999", line)
    with pytest.raises(ValueError, match="customer_id desconocido"):
        _load_heldout_from(monkeypatch, line)


def test_id_repetido_falla(monkeypatch):
    line = _first_dev_line().replace('"dev"', '"heldout"')
    with pytest.raises(ValueError, match="repetido"):
        _load_heldout_from(monkeypatch, f"{line}\n{line}\n")


def test_linea_invalida_reporta_numero(monkeypatch):
    with pytest.raises(ValueError, match=r"heldout.jsonl:2"):
        _load_heldout_from(monkeypatch, "\n{no es json}\n")
