"""Tests de la sesión y su máquina de estados."""

from datetime import UTC, datetime

import pytest

from radia.backend.agent.llm import ChatMessage, Role
from radia.backend.agent.session import (
    MAX_HISTORY,
    InvalidTransition,
    Session,
    SessionState,
)

EXPIRES = datetime(2026, 9, 29, 12, tzinfo=UTC)


def session():
    return Session(session_id="S1", customer_id="C1", expires_at=EXPIRES)


def test_transiciones_de_estado():
    s = session()
    s.move_to(SessionState.AWAITING_CONFIRMATION)
    s.move_to(SessionState.DONE)
    s.move_to(SessionState.HANDOFF)
    with pytest.raises(InvalidTransition):
        s.move_to(SessionState.IDLE)


def test_idle_no_salta_a_done():
    with pytest.raises(InvalidTransition):
        session().move_to(SessionState.DONE)


def test_sesion_vence():
    s = session()
    assert s.is_active(datetime(2026, 9, 29, 11, tzinfo=UTC))
    assert not s.is_active(EXPIRES)


def test_historial_acotado():
    s = session()
    for i in range(MAX_HISTORY + 5):
        s.remember(ChatMessage(role=Role.CUSTOMER, content=str(i)))
    assert len(s.history) == MAX_HISTORY
    assert s.history[-1].content == str(MAX_HISTORY + 4)
