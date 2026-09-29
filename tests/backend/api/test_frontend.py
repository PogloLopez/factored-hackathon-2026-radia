"""Web estática montada en la app: la raíz da el login y la API no cambia."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from radia.backend.agent.tracing import InMemoryTraceSink
from radia.backend.api.app import FRONTEND_DIR, create_app
from radia.backend.api.auth import DEMO_PASSWORD
from radia.config import Settings

OFFLINE = Path("no-existe-data-dir-de-tests")

API_PATHS = {
    "/auth/login",
    "/customers/me/offers",
    "/chat/messages",
    "/chat/confirm",
    "/analyst/cases",
    "/analyst/cases/{case_id}/decision",
    "/advisor/sessions",
    "/advisor/sessions/{case_id}/messages",
}
PAGES = [
    "index.html",
    "customer.html",
    "chat.html",
    "analyst.html",
    "advisor.html",
]


@pytest.fixture
def web_dir(tmp_path):
    """Carpeta mínima de frontend, aislada del repo."""
    (tmp_path / "index.html").write_text(
        "<!doctype html><title>Login</title><form id='login-form'></form>",
        encoding="utf-8",
    )
    (tmp_path / "app.js").write_text("console.log('ok');", encoding="utf-8")
    return tmp_path


def _client(frontend_dir):
    """App sin archivo de entorno, sin datos locales y con traces en memoria."""
    settings = Settings(_env_file=None, data_dir=OFFLINE)
    app = create_app(settings, sink=InMemoryTraceSink(), frontend_dir=frontend_dir)
    return TestClient(app)


def test_root_serves_login_html(web_dir):
    response = _client(web_dir).get("/")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "login-form" in response.text


def test_static_files_are_under_web(web_dir):
    client = _client(web_dir)
    assert client.get("/web/app.js").status_code == 200
    assert client.get("/web/").status_code == 200
    assert client.get("/web/no-existe.js").status_code == 404


def test_without_frontend_dir_only_api(tmp_path):
    client = _client(tmp_path / "no-existe")
    assert client.get("/").status_code == 404
    assert client.get("/web/index.html").status_code == 404
    # La API sigue igual.
    assert client.post("/auth/login", json={}).status_code == 422


def test_frontend_none_disables_web():
    assert _client(None).get("/").status_code == 404


def test_openapi_lists_same_endpoints(web_dir):
    with_web = _client(web_dir).get("/openapi.json").json()["paths"]
    without_web = _client(None).get("/openapi.json").json()["paths"]
    assert set(with_web) == API_PATHS
    assert with_web == without_web


def test_api_behaves_the_same_with_web(web_dir):
    client = _client(web_dir)
    login = client.post(
        "/auth/login", json={"username": "DEMO000001", "password": DEMO_PASSWORD}
    )
    assert login.status_code == 200
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    offers = client.get("/customers/me/offers", headers=headers)
    assert offers.status_code == 200
    assert offers.json()["synthetic_policy"] is True

    assert client.get("/customers/me/offers").status_code == 401
    assert client.get("/analyst/cases", headers=headers).status_code == 403
    assert client.get("/docs").status_code == 200


@pytest.mark.parametrize("page", PAGES)
def test_repo_frontend_pages_are_served(page):
    client = _client(FRONTEND_DIR)
    response = client.get(f"/web/{page}")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert '<html lang="es">' in response.text


def test_repo_root_is_login_page():
    response = _client(FRONTEND_DIR).get("/")
    assert response.status_code == 200
    assert 'id="login-form"' in response.text
