"""Tests del puntaje interno (C3) y de la validación de sus pesos."""

import json
import tempfile
from pathlib import Path

import duckdb
import pandas as pd
import pytest
from pydantic import ValidationError

from radia.config import Settings
from radia.contracts.data import validate
from radia.contracts.data.gold_features import make_gold_features
from radia.contracts.data.internal_score import SCORE_MAX, SCORE_MIN, InternalScore
from radia.etl.bronze import sql_literal
from radia.etl.gold import gold_path, write_parquet
from radia.etl.score import (
    DEFAULT_WEIGHTS,
    ScoreWeights,
    build_score,
    compute_scores,
    load_weights,
)


@pytest.fixture(scope="module")
def weights():
    return load_weights()


@pytest.fixture(scope="module")
def features():
    return make_gold_features(n=500, seed=1)


def _customer(**overrides) -> pd.DataFrame:
    row = {
        "customer_id": "C1",
        "snapshot_date": pd.Timestamp("2026-06-17"),
        "country": "Mexico",
        "segment": "Basic",
        "customer_status": "Active",
        "credit_score": 850,
        "tenure_months": 60,
        "monthly_income_usd": 1000.0,
        "total_credit_balance_usd": 0.0,
        "debt_to_income": 0.0,
        "credit_utilization": 0.1,
        "avg_monthly_inflow_usd_6m": 1000.0,
        "income_stability_6m": 0.0,
        "n_credit_products": 0,
        "max_days_past_due": 0,
    }
    row.update(overrides)
    df = pd.DataFrame([row])
    df["credit_score"] = df["credit_score"].astype("Int64")
    return df


def test_pesos_v0_son_validos_y_provisionales(weights):
    assert weights.score_version == "v0-provisional"
    assert "PESOS PROVISIONALES" in DEFAULT_WEIGHTS.read_text(encoding="utf-8")
    # El buró es el componente de mayor peso.
    spans = {
        n: abs(c.points_high - c.points_low) for n, c in weights.components.items()
    }
    assert max(spans, key=spans.get) == "credit_score"


def test_puntaje_cumple_c3_y_esta_en_rango(features, weights):
    scores = compute_scores(features, weights)
    validate(InternalScore, scores)
    assert len(scores) == len(features)
    valid = scores["score"].dropna()
    assert valid.between(SCORE_MIN, SCORE_MAX).all()
    assert valid.nunique() > 10


def test_nulo_si_falta_credit_score_o_ingreso(features, weights):
    scores = compute_scores(features, weights).set_index("customer_id")
    f = features.set_index("customer_id")
    missing = f["credit_score"].isna() | f["monthly_income_usd"].isna()
    assert missing.any()
    assert scores.loc[missing, "score"].isna().all()
    assert (scores.loc[missing, "breakdown_json"] == "{}").all()
    assert scores.loc[~missing, "score"].notna().all()


def test_desglose_suma_el_puntaje(features, weights):
    scores = compute_scores(features, weights).dropna(subset=["score"])
    for score, raw in zip(scores["score"], scores["breakdown_json"], strict=True):
        parts = json.loads(raw)
        assert set(parts) == {"base", *weights.components}
        expected = min(max(round(sum(parts.values())), SCORE_MIN), SCORE_MAX)
        assert score == expected


def test_determinista_e_independiente_del_orden(features, weights):
    a = compute_scores(features, weights)
    b = compute_scores(features.sample(frac=1, random_state=3), weights)
    pd.testing.assert_frame_equal(a, b)


def test_mejor_perfil_llega_al_tope_y_peor_al_piso(weights):
    best = compute_scores(_customer(), weights)
    assert best["score"].iloc[0] == SCORE_MAX
    worst = _customer(
        credit_score=300,
        tenure_months=0,
        debt_to_income=5.0,
        credit_utilization=1.5,
        income_stability_6m=3.0,
        max_days_past_due=120,
    )
    assert compute_scores(worst, weights)["score"].iloc[0] == SCORE_MIN


def test_componentes_penalizan_en_la_direccion_correcta(weights):
    def score(**kw) -> int:
        return int(
            compute_scores(_customer(credit_score=650, **kw), weights)["score"].iloc[0]
        )

    assert score(debt_to_income=1.0) < score(debt_to_income=0.2)
    assert score(max_days_past_due=30) < score(max_days_past_due=0)
    assert score(income_stability_6m=1.0) < score(income_stability_6m=0.1)
    assert score(tenure_months=2) < score(tenure_months=40)
    assert score(credit_utilization=0.9) < score(credit_utilization=0.2)


def _write_yaml(tmp: str, content: str) -> Path:
    path = Path(tmp) / "weights.yaml"
    path.write_text(content, encoding="utf-8")
    return path


VALID_COMPONENT = """
    feature: credit_score
    x_low: 300
    x_high: 850
    points_low: 0
    points_high: 400
    missing_points: 0
"""


@pytest.mark.parametrize(
    "content",
    [
        # x_low >= x_high
        "score_version: v\nbase: 150\ncomponents:\n  a:\n"
        + VALID_COMPONENT.replace("x_low: 300", "x_low: 900"),
        # feature que no existe en C1
        "score_version: v\nbase: 150\ncomponents:\n  a:\n"
        + VALID_COMPONENT.replace("feature: credit_score", "feature: country"),
        # clave desconocida
        "score_version: v\nbase: 150\nextra: 1\ncomponents:\n  a:\n" + VALID_COMPONENT,
        # base fuera de la escala
        "score_version: v\nbase: 1000\ncomponents:\n  a:\n" + VALID_COMPONENT,
        # sin componentes
        "score_version: v\nbase: 150\ncomponents: {}\n",
        # falta un campo
        "score_version: v\nbase: 150\ncomponents:\n  a:\n"
        + VALID_COMPONENT.replace("    missing_points: 0\n", ""),
    ],
)
def test_yaml_invalido_falla(content):
    with tempfile.TemporaryDirectory() as tmp, pytest.raises(ValidationError):
        load_weights(_write_yaml(tmp, content))


def test_pesos_inmutables(weights):
    with pytest.raises(ValidationError):
        weights.base = 300
    assert isinstance(weights, ScoreWeights)


def test_build_score_lee_c1_y_escribe_c3(features):
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        settings = Settings(_env_file=None, data_dir=Path(tmp))
        with pytest.raises(FileNotFoundError, match="radia-etl gold"):
            build_score(settings)
        con = duckdb.connect()
        write_parquet(con, features, gold_path(settings, "customer_features"))
        scores = build_score(settings)
        path = gold_path(settings, "internal_score")
        stored = con.execute(f"SELECT * FROM read_parquet({sql_literal(path)})").df()
        stored["score"] = stored["score"].astype("Int64")
        validate(InternalScore, stored)
        assert stored["score"].isna().sum() == scores["score"].isna().sum()
        assert len(stored) == len(features)
