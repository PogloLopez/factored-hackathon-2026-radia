"""Tests de los clientes demo: cada perfil produce en C6 el nivel de su celda."""

from datetime import UTC, datetime

import pandas as pd
import pytest

from radia.backend.policy.engine import RulesPolicy
from radia.contracts.common import AttentionLevel, Band, Exposure
from radia.contracts.data import validate
from radia.contracts.data.active_offers import ActiveOffers
from radia.eval.demo_customers import (
    DEMO_PROFILES,
    demo_features,
    demo_offers,
    demo_scores,
)

GENERATED_AT = datetime(2026, 6, 17, 6, 0, tzinfo=UTC)


@pytest.fixture(scope="module")
def offers() -> pd.DataFrame:
    return demo_offers(GENERATED_AT)


def _row(offers: pd.DataFrame, customer_id: str) -> pd.Series:
    profile = DEMO_PROFILES[customer_id]
    match = offers[
        (offers["customer_id"] == customer_id)
        & (offers["product_code"] == profile.product_code)
    ]
    assert len(match) == 1
    return match.iloc[0]


def test_ids_demo_con_formato():
    for cid, profile in DEMO_PROFILES.items():
        assert cid == profile.customer_id
        assert cid.startswith("DEMO") and len(cid) == 10


def test_c1_y_c3_una_fila_por_perfil():
    assert list(demo_features()["customer_id"]) == list(DEMO_PROFILES)
    assert list(demo_scores()["customer_id"]) == list(DEMO_PROFILES)


def test_c6_valida_y_sintetica(offers):
    validate(ActiveOffers, offers)
    assert offers["synthetic_policy"].all()
    assert (offers["policy_version"] == RulesPolicy().version).all()


@pytest.mark.parametrize("customer_id", list(DEMO_PROFILES))
def test_perfil_produce_nivel_esperado(offers, customer_id):
    profile = DEMO_PROFILES[customer_id]
    row = _row(offers, customer_id)
    assert row["attention_level"] == profile.expected_level
    assert row["exposure"] == profile.exposure
    if profile.band is None:
        assert pd.isna(row["band"])
    else:
        assert row["band"] == profile.band


def test_cubre_todas_las_celdas_de_la_matriz():
    cells = {(p.band, p.exposure) for p in DEMO_PROFILES.values() if p.kind == "cell"}
    assert cells == {(b, e) for b in Band for e in Exposure}


def test_cubre_las_excepciones():
    labels = {p.label for p in DEMO_PROFILES.values() if p.kind == "exception"}
    assert labels == {
        "excluded_inactive",
        "days_past_due_above_30",
        "missing_income",
        "missing_score",
        "score_gray_zone",
        "premium_medium_exposure",
    }


def test_cubre_todos_los_niveles():
    levels = {p.expected_level for p in DEMO_PROFILES.values()}
    assert levels == set(AttentionLevel)
