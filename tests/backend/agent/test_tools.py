"""Tests de la capa de permisos, reintentos y fuentes de las tools."""

from datetime import UTC, datetime

import pytest
from tenacity import wait_none

from radia.backend.agent.session import PendingConfirmation, Session
from radia.backend.agent.tools import (
    InMemoryOfferRepository,
    ToolBox,
    ToolDenied,
    ToolFailed,
    TransientToolError,
)
from radia.contracts.common import AttentionLevel, ProductCode
from radia.contracts.handoff import HandoffType

# Los tests usan el reloj fijo del conftest (2026-09-29).
FUTURE = datetime(2030, 1, 1, tzinfo=UTC)
PAST = datetime(2020, 1, 1, tzinfo=UTC)


def session(customer_id="C1", **kw):
    return Session(
        session_id="S1",
        customer_id=customer_id,
        **({"expires_at": FUTURE} | kw),
    )


def accepted(offer_id="O1", confirmation_id="CONF-1", accepted=True):
    return PendingConfirmation(
        confirmation_id=confirmation_id,
        offer_id=offer_id,
        product_code=ProductCode.CC_BASIC,
        limit_usd=450,
        summary="Tarjeta Básica",
        accepted=accepted,
    )


class FlakyRepository:
    """Falla técnica las primeras `failures` llamadas."""

    def __init__(self, inner, failures):
        self.inner, self.failures, self.calls = inner, failures, 0

    def offers_for(self, customer_id):
        self.calls += 1
        if self.calls <= self.failures:
            raise TransientToolError("timeout")
        return self.inner.offers_for(customer_id)


def test_ofertas_del_propio_cliente(tools):
    lookup = tools.get_active_offers(session(), "C1")
    assert {o.offer_id for o in lookup.offers} == {"O1", "O2", "O3", "O4", "O5"}
    call = tools.drain_calls()[0]
    assert call.ok and call.attempt == 1


def test_otro_cliente_denegado(tools):
    with pytest.raises(ToolDenied, match="customer_mismatch"):
        tools.get_active_offers(session(), "C2")
    call = tools.drain_calls()[0]
    assert call.denied and not call.ok


def test_sesion_vencida_denegada(tools):
    old = session(expires_at=PAST)
    with pytest.raises(ToolDenied, match="session_expired"):
        tools.get_active_offers(old, "C1")


def test_ofertas_vencidas_no_se_usan(tools):
    lookup = tools.get_active_offers(session("C3"), "C3")
    assert lookup.offers == []
    assert lookup.expired_count == 1


def test_oferta_a_decision_de_politica(tools):
    offer = tools.get_active_offers(session(), "C1").offers[0]
    decision = offer.to_decision()
    assert decision.attention_level == AttentionLevel.AUTOMATIC
    assert decision.offered_limit_usd == 450


def test_reintento_acotado_se_recupera(offers_df, tools):
    repo = FlakyRepository(InMemoryOfferRepository(offers_df), failures=2)
    tools = ToolBox(repo, clock=tools.clock, wait=wait_none())
    tools.get_active_offers(session(), "C1")
    assert tools.drain_calls()[0].attempt == 3


def test_reintentos_agotados_fallan(offers_df, tools):
    repo = FlakyRepository(InMemoryOfferRepository(offers_df), failures=99)
    tools = ToolBox(repo, clock=tools.clock, wait=wait_none())
    with pytest.raises(ToolFailed):
        tools.get_active_offers(session(), "C1")
    call = tools.drain_calls()[0]
    assert not call.ok and not call.denied and call.attempt == 3
    assert repo.calls == 3


@pytest.mark.parametrize(
    "pending",
    [None, accepted(accepted=False), accepted(confirmation_id="OTRA")],
)
def test_solicitud_sin_confirmacion_denegada(tools, pending):
    with pytest.raises(ToolDenied, match="missing_confirmation"):
        tools.create_application(session(pending=pending), "O1", "CONF-1")
    assert tools.applications.applications == {}


def test_solicitud_solo_de_oferta_automatica(tools):
    s = session(pending=accepted(offer_id="O2"))
    with pytest.raises(ToolDenied, match="offer_not_automatic"):
        tools.create_application(s, "O2", "CONF-1")


def test_solicitud_de_oferta_ajena_denegada(tools):
    s = session(pending=accepted(offer_id="O6"))
    with pytest.raises(ToolDenied, match="offer_not_owned"):
        tools.create_application(s, "O6", "CONF-1")


def test_solicitud_confirmada_es_idempotente(tools):
    s = session(pending=accepted())
    first = tools.create_application(s, "O1", "CONF-1")
    again = tools.create_application(s, "O1", "CONF-1")
    assert first == again
    assert tools.get_application(s, first.reference) == first


def test_handoff_del_cliente_de_la_sesion(tools):
    s = session()
    offer = tools.get_active_offers(s, "C1").offers[1]
    case = tools.create_handoff(
        s,
        handoff_type=HandoffType.ANALYST_REVIEW,
        trigger_reason="analyst",
        request_summary="Préstamo personal",
        verified_facts=["Oferta O2 vigente"],
        policy_decision=offer.to_decision(),
    )
    assert tools.cases.get(case.case_id) == case
    other = tools.get_active_offers(session("C2"), "C2").offers[0]
    with pytest.raises(ToolDenied, match="customer_mismatch"):
        tools.create_handoff(
            s,
            handoff_type=HandoffType.ADVISOR,
            trigger_reason="x",
            request_summary="x",
            policy_decision=other.to_decision(),
        )
