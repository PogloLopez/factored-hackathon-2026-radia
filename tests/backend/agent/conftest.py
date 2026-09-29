"""Ofertas mock que cumplen C6 y piezas del orquestador para los tests.

Clientes:
- C1 (banda alta): básica automática, préstamo al analista, hipoteca a
  analista y asesor, oro al asesor (preferencial), black no elegible.
- C2 (banda baja): préstamo no elegible con alternativa básica.
- C3: todas sus ofertas vencidas.
"""

import json
from datetime import UTC, datetime

import groq
import pandas as pd
import pytest
from tenacity import wait_none

from radia.backend.agent.tools import InMemoryOfferRepository, ToolBox
from radia.contracts.data import validate
from radia.contracts.data.active_offers import ActiveOffers

NOW = datetime(2026, 9, 29, 12, 0, tzinfo=UTC)
GENERATED = pd.Timestamp("2026-09-28 06:00")
EXPIRES = pd.Timestamp("2026-10-05 06:00")


def offer_row(offer_id, customer_id, product_code, level, **overrides):
    limit = overrides.pop("limit", None)
    row = {
        "offer_id": offer_id,
        "customer_id": customer_id,
        "product_code": product_code,
        "attention_level": level,
        "exposure": "low",
        "snapshot_date": pd.Timestamp("2026-09-27"),
        "score": 780,
        "band": "high",
        "offered_limit_usd": limit,
        "negotiation_min_usd": limit * 0.8 if limit else None,
        "negotiation_max_usd": limit * 1.2 if limit else None,
        "reasons_json": json.dumps(["band_high", "exposure_low"]),
        "alerts_json": "[]",
        "alternative_product_code": None,
        "policy_version": "synthetic-policy-0.1.0",
        "score_version": "score-0.1.0",
        "limit_model_version": "limit-0.1.0" if limit else None,
        "preferential": False,
        "synthetic_policy": True,
        "generated_at": GENERATED,
        "expires_at": EXPIRES,
    }
    row.update(overrides)
    return row


def demo_offers():
    rows = [
        offer_row("O1", "C1", "CC_BASIC", "automatic", limit=450.0),
        offer_row(
            "O2", "C1", "PERSONAL_LOAN", "analyst", limit=4200.0, exposure="medium"
        ),
        offer_row(
            "O3", "C1", "MORTGAGE", "analyst_and_advisor", limit=90000.0,
            exposure="high",
        ),
        offer_row(
            "O4", "C1", "CC_GOLD", "advisor", limit=2500.0, exposure="medium",
            preferential=True,
        ),
        offer_row(
            "O5", "C1", "CC_BLACK", "not_eligible", exposure="high",
            reasons_json=json.dumps(["band_high", "exposure_high"]),
        ),
        offer_row(
            "O6", "C2", "PERSONAL_LOAN", "not_eligible", exposure="medium",
            score=420, band="low", alternative_product_code="CC_BASIC",
            reasons_json=json.dumps(["band_low", "exposure_medium"]),
        ),
        offer_row(
            "O7", "C2", "CC_BASIC", "analyst", limit=300.0, score=420, band="low",
        ),
        offer_row(
            "O8", "C3", "CC_BASIC", "automatic", limit=500.0,
            expires_at=pd.Timestamp("2026-09-29 00:00"),
        ),
    ]  # fmt: skip
    return validate(ActiveOffers, pd.DataFrame(rows))


def clock():
    return NOW


class RealGroqForbidden(RuntimeError):
    """Un test intentó crear el cliente real de Groq (red y gasto)."""


@pytest.fixture(autouse=True)
def forbid_real_groq(monkeypatch):
    """Ningún test instancia `groq.Groq`: se usa un cliente falso inyectado."""

    def refuse(*args, **kwargs):
        raise RealGroqForbidden("los tests nunca llaman a Groq real")

    monkeypatch.setattr(groq.Groq, "__init__", refuse)


@pytest.fixture
def offers_df():
    return demo_offers()


@pytest.fixture
def tools(offers_df):
    return ToolBox(InMemoryOfferRepository(offers_df), clock=clock, wait=wait_none())
