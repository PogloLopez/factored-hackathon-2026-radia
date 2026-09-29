"""Contrato C8: formas de la API hacia la web."""

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from radia.contracts.api import (
    MAX_MESSAGE_CHARS,
    AdvisorMessageRequest,
    ChatMessageRequest,
    ChatResponse,
    ChatState,
    LoginResponse,
    OffersResponse,
    UserRole,
)

NOW = datetime(2026, 9, 29, 12, 0, tzinfo=UTC)


def test_chat_response_matches_doc_example():
    """El ejemplo de [[trabajo_en_paralelo]], momento 4, valida."""
    response = ChatResponse.model_validate(
        {
            "session_id": "SES-0001",
            "reply": "Tienes preaprobada una Tarjeta Básica.",
            "state": "awaiting_confirmation",
            "pending_confirmation": {
                "confirmation_id": "CONF-1",
                "action": "create_application",
                "summary": "Solicitar Tarjeta Básica con cupo de 450 USD",
            },
            "handoff_case_id": None,
            "application_reference": None,
            "trace_id": "TRC-1",
        }
    )
    assert response.state == ChatState.AWAITING_CONFIRMATION


def test_chat_message_rejects_empty_and_too_long():
    with pytest.raises(ValidationError):
        ChatMessageRequest(message="")
    with pytest.raises(ValidationError):
        ChatMessageRequest(message="a" * (MAX_MESSAGE_CHARS + 1))


def test_chat_message_never_carries_customer_id():
    with pytest.raises(ValidationError):
        ChatMessageRequest.model_validate({"message": "hola", "customer_id": "X"})


def test_offers_response_is_always_synthetic():
    with pytest.raises(ValidationError):
        OffersResponse(customer_id="C1", offers=[], synthetic_policy=False)


def test_login_requires_aware_expiry():
    with pytest.raises(ValidationError):
        LoginResponse(
            access_token="t",
            role=UserRole.CUSTOMER,
            expires_at=NOW.replace(tzinfo=None),
        )
    assert LoginResponse(access_token="t", role="analyst", expires_at=NOW).role == (
        UserRole.ANALYST
    )


def test_advisor_amount_must_be_positive():
    with pytest.raises(ValidationError):
        AdvisorMessageRequest(message="hola", proposed_amount_usd=0)
