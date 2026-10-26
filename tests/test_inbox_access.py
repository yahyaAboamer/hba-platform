"""Who reaches the inbox, and who may change its keys (ADR 0059).

Customer service, the operations manager and the admin use the inbox; nobody
else does. Only the admin sees or changes its connections.
"""

import pytest
from cryptography.fernet import Fernet
from fastapi import APIRouter
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.api import inbox
from app.db import engine
from app.main import app
from app.services.inbox import connection
from app.services.inbox.meta import NumberInfo
from app.services.invitations import create_invitation

BOOTSTRAP = {
    "email": "owner@example.com",
    "display_name": "Owner",
    "password": "quiet-harbour-lantern",
}

WHATSAPP = {
    "phone_number_id": "100200300400500",
    "business_account_id": "777888999000111",
    "access_token": "EAAG-made-up-access-key-0000a1b2",
    "app_secret": "made-up-app-secret-000000009f3c",
    "verify_token": "made-up-check-word-0001",
}


@pytest.fixture()
def probe():
    """A route behind exactly the guard every inbox route gets.

    The chats have no routes of their own until their screens arrive, so this
    mounts one with the router's own dependencies and removes it afterwards.
    """
    router = APIRouter(prefix="/api/inbox", dependencies=inbox.router.dependencies)

    @router.get("/_probe")
    def _probe() -> dict:
        return {"ok": True}

    before = list(app.router.routes)
    app.include_router(router)
    # Ahead of the app's catch-all, which would otherwise answer 404 first.
    added = app.router.routes[len(before):]
    app.router.routes[:] = added + before
    yield "/api/inbox/_probe"
    app.router.routes[:] = before


@pytest.fixture()
def client(fresh_database, probe, monkeypatch):
    monkeypatch.setattr(
        "app.config.settings.settings_encryption_key", Fernet.generate_key().decode()
    )
    with TestClient(app) as test_client:
        response = test_client.post("/api/auth/bootstrap", json=BOOTSTRAP)
        assert response.status_code == 201, response.text
        test_client.headers["X-CSRF-Token"] = response.json()["csrf"]
        yield test_client


def _demote_to(role: str) -> None:
    with engine.begin() as connection_:
        connection_.execute(text("UPDATE role_assignment SET role = :r"), {"r": role})

    # The operations manager *person* holds the Inbox as a second assignment
    # since ADR 0067 (migration c3e7a1f90019 gave it to whoever held the role).
    if role == "operations_manager":
        with engine.begin() as connection_:
            connection_.execute(
                text(
                    "INSERT INTO role_assignment (user_account_id, role) "
                    "SELECT user_account_id, 'customer_service' FROM role_assignment "
                    "WHERE role = 'operations_manager' AND revoked_at IS NULL"
                )
            )


# ── The inbox itself ──────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("role", "expected"),
    [
        ("admin", 200),
        ("customer_service", 200),
        ("operations_manager", 200),
        ("affiliate_manager", 403),
        ("content_manager", 403),
        ("affiliate", 403),
    ],
)
def test_only_customer_service_the_operations_manager_and_the_admin_reach_the_inbox(
    client, probe, role, expected
):
    if role != "admin":
        _demote_to(role)
    assert client.get(probe).status_code == expected


def test_nobody_signed_out_reaches_the_inbox(fresh_database, probe):
    with TestClient(app) as anonymous:
        assert anonymous.get(probe).status_code == 401


def test_every_inbox_route_carries_the_guard():
    assert inbox.router.routes
    for route in inbox.router.routes:
        assert any(
            dependency.call is inbox.GUARD for dependency in route.dependant.dependencies
        ), route.path


@pytest.mark.parametrize(
    ("role", "path", "expected"),
    [
        ("customer_service", "/api/order-ops/shopify", 403),
        ("customer_service", "/api/affiliates", 403),
        ("customer_service", "/api/staff", 403),
        ("operations_manager", "/api/affiliates", 403),
        ("operations_manager", "/api/staff", 403),
    ],
)
def test_the_inbox_opens_nothing_else(client, role, path, expected):
    _demote_to(role)
    assert client.get(path).status_code == expected


# ── Its keys ──────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("role", ["customer_service", "operations_manager"])
def test_the_people_who_use_the_inbox_never_see_or_change_its_keys(client, role):
    _demote_to(role)
    assert client.get("/api/inbox/connection").status_code == 403
    assert client.put("/api/inbox/connection/whatsapp", json=WHATSAPP).status_code == 403
    assert client.put("/api/inbox/connection/tags", json={}).status_code == 403
    assert client.put("/api/inbox/connection/sending", json={"enabled": True}).status_code == 403


def test_an_admin_saves_the_keys_and_is_never_shown_them(client, monkeypatch):
    monkeypatch.setattr(
        connection, "check_whatsapp", lambda *args: NumberInfo("+20 100 555 0100", "HBA Wear", "GREEN")
    )
    before = client.get("/api/inbox/connection").json()
    assert before["whatsapp"]["connected"] is False
    assert before["tags"]["connected"] is False

    saved = client.put("/api/inbox/connection/whatsapp", json=WHATSAPP)
    assert saved.status_code == 200, saved.text
    for secret in (WHATSAPP["access_token"], WHATSAPP["app_secret"], WHATSAPP["verify_token"]):
        assert secret not in saved.text
    assert saved.json()["whatsapp"]["connected"] is True
    assert saved.json()["whatsapp"]["sending_enabled"] is False

    on = client.put("/api/inbox/connection/sending", json={"enabled": True})
    assert on.json()["whatsapp"]["sending_enabled"] is True


def test_a_refusal_says_why_and_echoes_no_key(client):
    refused = client.put(
        "/api/inbox/connection/whatsapp", json=WHATSAPP | {"access_token": "two words here"}
    )
    assert refused.status_code == 422
    assert "doesn't look like a WhatsApp access key" in refused.json()["detail"]
    assert "two words here" not in refused.text
    assert client.get("/api/inbox/connection").json()["whatsapp"]["connected"] is False


def test_sending_cannot_be_turned_on_with_nothing_connected(client):
    refused = client.put("/api/inbox/connection/sending", json={"enabled": True})
    assert refused.status_code == 422
    assert "Connect WhatsApp before" in refused.json()["detail"]


# ── Giving the role ───────────────────────────────────────────────────────────


def test_several_people_can_hold_customer_service(db):
    """Unlike the operations manager, of whom there is one (ADR 0057)."""
    create_invitation(db, "mariam@example.com", "customer_service", None)
    create_invitation(db, "nada@example.com", "customer_service", None)
