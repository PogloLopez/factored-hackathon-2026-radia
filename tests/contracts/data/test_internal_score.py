"""Tests de radia.contracts.data.internal_score (C3)."""

import pandas as pd
import pandera.pandas as pa
import pytest

from radia.contracts.data import validate
from radia.contracts.data.gold_features import make_gold_features
from radia.contracts.data.internal_score import (
    InternalScore,
    _is_breakdown,
    make_internal_scores,
)

ERRORS = (pa.errors.SchemaError, pa.errors.SchemaErrors)


@pytest.fixture
def features():
    return make_gold_features(n=200, seed=1)


@pytest.fixture
def scores(features):
    return make_internal_scores(features, seed=1)


def test_mock_valida(scores, features):
    assert len(scores) == len(features)
    validate(InternalScore, scores)


def test_mock_determinista_por_seed(features):
    a = make_internal_scores(features, seed=5)
    b = make_internal_scores(features, seed=5)
    c = make_internal_scores(features, seed=6)
    pd.testing.assert_frame_equal(a, b)
    assert not a["score"].equals(c["score"])


def test_score_nulo_donde_ingreso_nulo(features, scores):
    mask = features["monthly_income_usd"].isna().to_numpy()
    assert mask.any()
    assert scores["score"].isna().to_numpy().tolist() == mask.tolist()
    assert (scores.loc[mask, "breakdown_json"] == "{}").all()


@pytest.mark.parametrize("value", [150, 950])
def test_bordes_validos(scores, value):
    df = scores.copy()
    df.loc[df.index[0], "score"] = value
    validate(InternalScore, df)


@pytest.mark.parametrize("value", [149, 951])
def test_fuera_de_rango_falla(scores, value):
    df = scores.copy()
    df.loc[df.index[0], "score"] = value
    with pytest.raises(ERRORS):
        validate(InternalScore, df)


@pytest.mark.parametrize(
    "raw", ["no es json", "[1, 2]", '{"a": "x"}', '{"a": true}', "null", "5"]
)
def test_breakdown_invalido_falla(scores, raw):
    df = scores.copy()
    df.loc[df.index[0], "breakdown_json"] = raw
    with pytest.raises(ERRORS):
        validate(InternalScore, df)


def test_breakdown_vacio_pasa(scores):
    df = scores.copy()
    df.loc[df.index[0], "breakdown_json"] = "{}"
    validate(InternalScore, df)


def test_columna_extra_falla(scores):
    df = scores.assign(extra=1)
    with pytest.raises(ERRORS):
        validate(InternalScore, df)


def test_clave_duplicada_falla(scores):
    df = pd.concat([scores, scores.iloc[[0]]])
    with pytest.raises(ERRORS):
        validate(InternalScore, df)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("{}", True),
        ('{"a": 1}', True),
        ('{"a": 1.5, "b": -2}', True),
        ('{"a": true}', False),
        ('{"a": "1"}', False),
        ('{"a": null}', False),
        ('{"a": {"b": 1}}', False),
        ("[1]", False),
        ("5", False),
        ("null", False),
        ("", False),
        ("{malformado", False),
        (None, False),
        (123, False),
    ],
)
def test_is_breakdown(raw, expected):
    assert _is_breakdown(raw) is expected


@pytest.mark.parametrize("raw", ['{"a": NaN}', '{"a": Infinity}', '{"a": -Infinity}'])
def test_breakdown_rechaza_constantes_no_finitas(raw):
    assert not _is_breakdown(raw)
