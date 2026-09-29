"""Endpoints C8 con TestClient, sobre el orquestador real y el modelo falso."""

import threading
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
import pytest
from pydantic import SecretStr

from radia.backend.agent.llm import FakeLanguageModel
from radia.backend.agent.session import Currency
from radia.backend.agent.tracing import JsonlTraceSink
from radia.backend.api.app import create_app
from radia.backend.api.auth import ANALYST_USERNAME, DEMO_PASSWORD
from radia.backend.api.state import ApiState, load_offers
from radia.config import Settings
from radia.contracts.api import ChatResponse
from radia.contracts.handoff import HandoffCase, HandoffType
from radia.etl.offers import OFFERS_FILE
from radia.eval.demo_customers import demo_offers

AUTOMATIC_CUSTOMER = "DEMO000001"  # Tarjeta básica automática (México).
ANALYST_CUSTOMER = "DEMO000008"  # Préstamo personal al analista.
ADVISOR_CUSTOMER = "DEMO000018"  # Premium: tarjeta oro al asesor.
OFFLINE = Path("no-existe-data-dir-de-tests")


def _chat(client, headers, message, session_id=None):
    body = {"message": message, "session_id": session_id}
    return client.post("/chat/messages", headers=headers, json=body)


# --- Login y permisos --------------------------------------------------------


def test_login_ok_returns_customer_token(client):
    response = client.post(
        "/auth/login", json={"username": AUTOMATIC_CUSTOMER, "password": DEMO_PASSWORD}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["role"] == "customer"
    assert body["customer_id"] == AUTOMATIC_CUSTOMER
    assert body["token_type"] == "bearer"
    assert len(body["access_token"]) >= 32


@pytest.mark.parametrize(
    ("username", "password"),
    [
        (AUTOMATIC_CUSTOMER, "otra-clave"),
        ("NOEXISTE01", DEMO_PASSWORD),
        (ANALYST_USERNAME, "otra-clave"),
    ],
)
def test_login_fails_with_bad_credentials(client, username, password):
    response = client.post(
        "/auth/login", json={"username": username, "password": password}
    )
    assert response.status_code == 401


def test_analyst_login_has_no_customer(client):
    response = client.post(
        "/auth/login", json={"username": ANALYST_USERNAME, "password": DEMO_PASSWORD}
    )
    assert response.json()["role"] == "analyst"
    assert response.json()["customer_id"] is None


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("get", "/customers/me/offers"),
        ("post", "/chat/messages"),
        ("post", "/chat/confirm"),
        ("get", "/analyst/cases"),
        ("get", "/advisor/sessions"),
    ],
)
def test_routes_require_token(client, method, path):
    response = getattr(client, method)(path)
    assert response.status_code == 401


def test_invalid_token_is_401(client):
    headers = {"Authorization": "Bearer inventado"}
    assert client.get("/customers/me/offers", headers=headers).status_code == 401


def test_customer_cannot_use_analyst_routes(client, headers_for):
    headers = headers_for(AUTOMATIC_CUSTOMER)
    assert client.get("/analyst/cases", headers=headers).status_code == 403
    assert client.get("/advisor/sessions", headers=headers).status_code == 403


def test_analyst_cannot_chat(client, analyst):
    assert _chat(client, analyst, "hola").status_code == 403


def test_other_customer_session_is_404(client, headers_for):
    owner = headers_for(AUTOMATIC_CUSTOMER)
    intruder = headers_for(ANALYST_CUSTOMER)
    first = _chat(client, owner, "Quiero una tarjeta básica").json()
    session_id = first["session_id"]

    assert _chat(client, intruder, "hola", session_id).status_code == 404
    confirm = client.post(
        "/chat/confirm",
        headers=intruder,
        json={
            "session_id": session_id,
            "confirmation_id": first["pending_confirmation"]["confirmation_id"],
            "accept": True,
        },
    )
    assert confirm.status_code == 404


def test_unknown_session_is_404(client, headers_for):
    headers = headers_for(AUTOMATIC_CUSTOMER)
    assert _chat(client, headers, "hola", "SES-NOEXISTE").status_code == 404


def test_body_cannot_carry_customer_id(client, headers_for):
    headers = headers_for(AUTOMATIC_CUSTOMER)
    body = {"message": "hola", "customer_id": ANALYST_CUSTOMER}
    assert client.post("/chat/messages", headers=headers, json=body).status_code == 422


# --- Ofertas -----------------------------------------------------------------


def test_offers_are_from_c6_without_negotiation_range(client, headers_for):
    response = client.get(
        "/customers/me/offers", headers=headers_for(AUTOMATIC_CUSTOMER)
    )
    body = response.json()
    assert response.status_code == 200
    assert body["customer_id"] == AUTOMATIC_CUSTOMER
    assert body["synthetic_policy"] is True
    ids = {o["offer_id"] for o in body["offers"]}
    assert body["highlighted_offer_id"] in ids
    basic = next(o for o in body["offers"] if o["product_code"] == "CC_BASIC")
    assert basic["attention_level"] == "automatic"
    assert "negotiation_min_usd" not in basic


# --- Flujo automático --------------------------------------------------------


def test_automatic_flow_ends_with_verified_application(client, headers_for, sink):
    headers = headers_for(AUTOMATIC_CUSTOMER)
    first = _chat(client, headers, "Quiero una tarjeta básica")
    assert first.status_code == 200
    reply = ChatResponse.model_validate(first.json())
    assert reply.state == "awaiting_confirmation"
    assert reply.pending_confirmation is not None
    assert reply.application_reference is None

    done = client.post(
        "/chat/confirm",
        headers=headers,
        json={
            "session_id": reply.session_id,
            "confirmation_id": reply.pending_confirmation.confirmation_id,
            "accept": True,
        },
    )
    assert done.status_code == 200
    result = ChatResponse.model_validate(done.json())
    assert result.state == "done"
    assert result.application_reference
    # Un trace por turno: mensaje y confirmación.
    assert [t.trace_id for t in sink.traces] == [reply.trace_id, result.trace_id]


def test_session_currency_follows_customer_country(app, client, headers_for):
    reply = _chat(client, headers_for(AUTOMATIC_CUSTOMER), "hola").json()
    session = app.state.api.orchestrator.sessions[reply["session_id"]]
    assert session.customer_id == AUTOMATIC_CUSTOMER
    assert session.currency == Currency.MXN
    assert session.usd_per_unit is not None


# --- Analista ------------------------------------------------------------------


def _analyst_case(client, headers_for) -> str:
    reply = _chat(client, headers_for(ANALYST_CUSTOMER), "Quiero un préstamo personal")
    body = reply.json()
    assert body["state"] == "handoff", body
    return body["handoff_case_id"]


def test_handoff_is_visible_in_analyst_inbox(client, headers_for, analyst):
    case_id = _analyst_case(client, headers_for)
    cases = client.get("/analyst/cases", headers=analyst).json()["cases"]
    case = next(c for c in cases if c["case_id"] == case_id)
    assert case["handoff_type"] == "analyst_review"
    assert case["customer_id"] == ANALYST_CUSTOMER
    assert case["status"] == "pending"
    assert case["policy_decision"]["attention_level"] == "analyst"


def test_analyst_decision_updates_case(client, headers_for, analyst):
    case_id = _analyst_case(client, headers_for)
    url = f"/analyst/cases/{case_id}/decision"
    response = client.post(
        url, headers=analyst, json={"decision": "approve", "note": "Ok"}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "approved"
    assert body["case"]["status"] == "approved"
    # Decidido: sale de la bandeja y no se decide dos veces.
    cases = client.get("/analyst/cases", headers=analyst).json()["cases"]
    assert case_id not in {c["case_id"] for c in cases}
    again = client.post(url, headers=analyst, json={"decision": "reject"})
    assert again.status_code == 409


def test_request_info_keeps_case_in_inbox(client, headers_for, analyst):
    case_id = _analyst_case(client, headers_for)
    response = client.post(
        f"/analyst/cases/{case_id}/decision",
        headers=analyst,
        json={"decision": "request_info"},
    )
    assert response.json()["status"] == "info_requested"
    cases = client.get("/analyst/cases", headers=analyst).json()["cases"]
    assert case_id in {c["case_id"] for c in cases}


def test_analyst_decision_unknown_case_is_404(client, analyst):
    response = client.post(
        "/analyst/cases/CASE-NOEXISTE/decision",
        headers=analyst,
        json={"decision": "approve"},
    )
    assert response.status_code == 404


# --- Asesor --------------------------------------------------------------------


def _advisor_case(client, headers_for, advisor) -> dict:
    reply = _chat(client, headers_for(ADVISOR_CUSTOMER), "Quiero una tarjeta oro")
    body = reply.json()
    assert body["state"] == "handoff", body
    sessions = client.get("/advisor/sessions", headers=advisor).json()["sessions"]
    return next(s for s in sessions if s["case"]["case_id"] == body["handoff_case_id"])


def test_advisor_sees_handoff_and_sends_amount_in_range(client, headers_for, advisor):
    session = _advisor_case(client, headers_for, advisor)
    decision = session["case"]["policy_decision"]
    amount = decision["negotiation_min_usd"]
    case_id = session["case"]["case_id"]

    response = client.post(
        f"/advisor/sessions/{case_id}/messages",
        headers=advisor,
        json={"message": "Te propongo este cupo", "proposed_amount_usd": amount},
    )
    assert response.status_code == 200
    assert response.json()["proposed_amount_usd"] == amount
    sessions = client.get("/advisor/sessions", headers=advisor).json()["sessions"]
    stored = next(s for s in sessions if s["case"]["case_id"] == case_id)
    assert len(stored["messages"]) == 1


@pytest.mark.parametrize("side", ["below", "above"])
def test_advisor_amount_out_of_range_is_422(client, headers_for, advisor, side):
    session = _advisor_case(client, headers_for, advisor)
    decision = session["case"]["policy_decision"]
    amount = (
        decision["negotiation_min_usd"] - 1
        if side == "below"
        else decision["negotiation_max_usd"] + 1
    )
    case_id = session["case"]["case_id"]
    response = client.post(
        f"/advisor/sessions/{case_id}/messages",
        headers=advisor,
        json={"message": "Te propongo este cupo", "proposed_amount_usd": amount},
    )
    assert response.status_code == 422
    sessions = client.get("/advisor/sessions", headers=advisor).json()["sessions"]
    stored = next(s for s in sessions if s["case"]["case_id"] == case_id)
    assert stored["messages"] == []


def test_advisor_cannot_write_on_analyst_case(client, headers_for, advisor):
    case_id = _analyst_case(client, headers_for)
    response = client.post(
        f"/advisor/sessions/{case_id}/messages",
        headers=advisor,
        json={"message": "hola"},
    )
    assert response.status_code == 404


def test_advisor_cannot_write_on_closed_case(app, client, headers_for, advisor):
    from radia.contracts.handoff import CaseStatus

    case_id = _advisor_case(client, headers_for, advisor)["case"]["case_id"]
    cases = app.state.api.cases
    cases.save(cases.get(case_id).model_copy(update={"status": CaseStatus.APPROVED}))
    response = client.post(
        f"/advisor/sessions/{case_id}/messages",
        headers=advisor,
        json={"message": "hola"},
    )
    assert response.status_code == 409


# --- Concurrencia -------------------------------------------------------------


def _bare_case(n: int, kind: HandoffType) -> HandoffCase:
    return HandoffCase(
        case_id=f"CASE-T{n:06d}",
        handoff_type=kind,
        trigger_reason="prueba",
        customer_id=AUTOMATIC_CUSTOMER,
        session_id="SES-TEST",
        request_summary="prueba",
        open_questions=["¿qué falta?"],
        created_at=datetime(2026, 9, 29, tzinfo=UTC),
    )


def test_inboxes_list_while_chat_adds_cases(app, client, analyst, advisor):
    """Hilos que guardan casos mientras las bandejas listan: sin errores."""
    cases = app.state.api.cases
    per_writer = 200
    errors: list[BaseException] = []

    def writer(offset: int) -> None:
        try:
            for i in range(per_writer):
                n = offset + 4 * i
                kind = HandoffType.ADVISOR if n % 2 else HandoffType.ANALYST_REVIEW
                cases.save(_bare_case(n, kind))
        except BaseException as exc:  # noqa: BLE001 - se reporta en el assert
            errors.append(exc)

    writers = [threading.Thread(target=writer, args=(i,)) for i in range(4)]
    for t in writers:
        t.start()
    try:
        for _ in range(10):
            assert client.get("/analyst/cases", headers=analyst).status_code == 200
            assert client.get("/advisor/sessions", headers=advisor).status_code == 200
    finally:
        for t in writers:
            t.join()
    assert errors == []
    assert len(cases.list_cases()) == 4 * per_writer


def test_list_cases_returns_a_copy(app):
    cases = app.state.api.cases
    cases.save(_bare_case(1, HandoffType.ADVISOR))
    listed = cases.list_cases()
    cases.save(_bare_case(2, HandoffType.ADVISOR))
    assert [c.case_id for c in listed] == ["CASE-T000001"]
    assert len(cases.list_cases()) == 2


# --- Ofertas con Gold ------------------------------------------------------------

FIXED_NOW = datetime(2026, 9, 29, 12, tzinfo=UTC)


def test_gold_offers_keep_demo_customers(monkeypatch):
    """Con el parquet de Gold, los clientes demo siguen con sus ofertas."""
    demo = demo_offers(FIXED_NOW)
    gold = demo.head(2).copy()
    gold.loc[0, ["offer_id", "customer_id"]] = ["GOLD-OFFER-1", "C000000001"]
    gold.loc[1, "offered_limit_usd"] = 1234.0  # Mismo id que un demo: gana Gold.
    shared_id = gold.loc[1, "offer_id"]

    real_exists = Path.exists
    monkeypatch.setattr(
        Path, "exists", lambda p: p.name == OFFERS_FILE or real_exists(p)
    )
    monkeypatch.setattr(pd, "read_parquet", lambda path: gold)

    offers = load_offers(Settings(_env_file=None, data_dir=OFFLINE), lambda: FIXED_NOW)

    assert offers["offer_id"].is_unique
    assert "GOLD-OFFER-1" in set(offers["offer_id"])
    assert set(demo["offer_id"]) <= set(offers["offer_id"])
    shared = offers.loc[offers["offer_id"] == shared_id, "offered_limit_usd"]
    assert shared.tolist() == [1234.0]
    assert set(demo["customer_id"]) <= set(offers["customer_id"])


# --- Configuración -------------------------------------------------------------


def test_app_uses_fake_llm_even_with_groq_key():
    settings = Settings(
        _env_file=None, data_dir=OFFLINE, groq_api_key=SecretStr("no-real")
    )
    app = create_app(settings)
    assert isinstance(app.state.api.orchestrator.llm, FakeLanguageModel)


def test_use_groq_is_the_only_switch_to_groq():
    """Con `use_groq`, se intenta Groq: el fixture lo corta antes de la red."""
    settings = Settings(
        _env_file=None,
        data_dir=OFFLINE,
        groq_api_key=SecretStr("no-real"),
        use_groq=True,
    )
    with pytest.raises(RuntimeError, match="Groq real"):
        ApiState(settings)


def test_default_traces_go_to_settings_traces_dir():
    settings = Settings(_env_file=None, data_dir=OFFLINE)
    sink = ApiState(settings).orchestrator.sink
    assert isinstance(sink, JsonlTraceSink)
    assert sink.directory == settings.traces_dir
