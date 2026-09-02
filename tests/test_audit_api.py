"""The business audit trail, over HTTP. Read-only.

`audit.view` existed since Phase 1 with no screen. These tests are the read
side of that promise - the write side is already proven throughout the suite,
by every test that asserts an action recorded an audit event.
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.db import engine
from app.main import app

BOOTSTRAP = {
    "email": "owner@example.com",
    "display_name": "Owner",
    "password": "quiet-harbour-lantern",
}


@pytest.fixture()
def client(fresh_database):
    with TestClient(app) as test_client:
        response = test_client.post("/api/auth/bootstrap", json=BOOTSTRAP)
        assert response.status_code == 201, response.text
        test_client.headers["X-CSRF-Token"] = response.json()["csrf"]
        yield test_client


def _demote_to(role: str) -> None:
    with engine.begin() as connection:
        connection.execute(text("UPDATE role_assignment SET role = :r"), {"r": role})


def test_anonymous_access_is_refused(client):
    client.cookies.clear()
    assert client.get("/api/audit").status_code == 401


def test_an_affiliate_cannot_read_the_trail(client):
    _demote_to("affiliate")
    assert client.get("/api/audit").status_code == 403


def test_bootstrap_itself_is_the_first_event(client):
    """Proof the endpoint reads real rows, not a fixture: signing in to run
    this test is itself an audited action.
    """
    body = client.get("/api/audit").json()
    assert any(event["action"] == "auth.bootstrap" for event in body["events"])


def test_newest_first(client):
    client.post(
        "/api/auth/invitations", json={"email": "layla@example.com", "role": "content_manager"}
    )

    events = client.get("/api/audit").json()["events"]

    assert events[0]["action"] == "invitation.create"


def test_filtering_by_subject(client):
    client.post(
        "/api/auth/invitations", json={"email": "layla@example.com", "role": "content_manager"}
    )

    events = client.get("/api/audit?subject=layla").json()["events"]

    assert len(events) == 1
    assert events[0]["action"] == "invitation.create"


def test_a_sensitive_value_never_reaches_the_response_unmasked(client):
    """Masking happens at write time (app/services/audit.py). This proves the
    read side does not undo it by returning the raw column.
    """
    client.post(
        "/api/auth/invitations", json={"email": "layla@example.com", "role": "content_manager"}
    )

    events = client.get("/api/audit").json()["events"]
    raw = str(events)

    assert "quiet-harbour-lantern" not in raw
