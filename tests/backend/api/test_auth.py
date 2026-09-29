"""Identidad mock: tokens opacos atados a rol y cliente, con vencimiento."""

from datetime import UTC, datetime, timedelta

import pytest

from radia.backend.api.auth import (
    ADVISOR_USERNAME,
    DEMO_PASSWORD,
    InvalidCredentials,
    TokenStore,
)
from radia.contracts.api import UserRole

START = datetime(2026, 9, 29, 12, 0, tzinfo=UTC)


class Clock:
    def __init__(self) -> None:
        self.now = START

    def __call__(self) -> datetime:
        return self.now


def test_token_is_bound_to_customer():
    store = TokenStore(["DEMO000001"], Clock())
    principal = store.login("DEMO000001", DEMO_PASSWORD)
    assert principal.role == UserRole.CUSTOMER
    assert store.resolve(principal.token) == principal


def test_tokens_are_unique_per_login():
    store = TokenStore(["DEMO000001"], Clock())
    first = store.login("DEMO000001", DEMO_PASSWORD)
    second = store.login("DEMO000001", DEMO_PASSWORD)
    assert first.token != second.token


def test_advisor_has_no_customer():
    principal = TokenStore([], Clock()).login(ADVISOR_USERNAME, DEMO_PASSWORD)
    assert principal.role == UserRole.ADVISOR
    assert principal.customer_id is None


@pytest.mark.parametrize(
    ("username", "password"),
    [("DEMO000001", "x"), ("DEMO000099", DEMO_PASSWORD)],
)
def test_bad_credentials_raise(username, password):
    with pytest.raises(InvalidCredentials):
        TokenStore(["DEMO000001"], Clock()).login(username, password)


def test_expired_token_does_not_resolve():
    clock = Clock()
    store = TokenStore(["DEMO000001"], clock, ttl=timedelta(minutes=5))
    token = store.login("DEMO000001", DEMO_PASSWORD).token
    clock.now = START + timedelta(minutes=5)
    assert store.resolve(token) is None
    assert store.resolve("desconocido") is None
