"""App de prueba: clientes demo, modelo falso y traces en memoria.

- Nada toca disco: el sink es `InMemoryTraceSink` y `data_dir` no existe, así
  que las ofertas salen de `demo_offers()`.
- Ningún test instancia `groq.Groq` real (red y gasto).
"""

from pathlib import Path

import groq
import pytest
from fastapi.testclient import TestClient

from radia.backend.agent.tracing import InMemoryTraceSink
from radia.backend.api.app import create_app
from radia.backend.api.auth import ADVISOR_USERNAME, ANALYST_USERNAME, DEMO_PASSWORD
from radia.config import Settings

MISSING_DATA_DIR = Path("no-existe-data-dir-de-tests")


class RealGroqForbidden(RuntimeError):
    """Un test intentó crear el cliente real de Groq."""


@pytest.fixture(autouse=True)
def forbid_real_groq(monkeypatch):
    def refuse(*args, **kwargs):
        raise RealGroqForbidden("los tests nunca llaman a Groq real")

    monkeypatch.setattr(groq.Groq, "__init__", refuse)


def make_settings(**overrides) -> Settings:
    """Settings sin archivo de entorno y sin datos locales."""
    return Settings(_env_file=None, data_dir=MISSING_DATA_DIR, **overrides)


@pytest.fixture
def sink():
    return InMemoryTraceSink()


@pytest.fixture
def app(sink):
    return create_app(make_settings(), sink=sink)


@pytest.fixture
def client(app):
    return TestClient(app)


@pytest.fixture
def headers_for(client):
    """Login con la clave demo y cabecera Bearer del token."""

    def make(username: str) -> dict[str, str]:
        response = client.post(
            "/auth/login", json={"username": username, "password": DEMO_PASSWORD}
        )
        assert response.status_code == 200, response.text
        return {"Authorization": f"Bearer {response.json()['access_token']}"}

    return make


@pytest.fixture
def analyst(headers_for):
    return headers_for(ANALYST_USERNAME)


@pytest.fixture
def advisor(headers_for):
    return headers_for(ADVISOR_USERNAME)
