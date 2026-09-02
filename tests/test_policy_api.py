"""The commission rules, in plain language, over HTTP.

Gated on `settings.manage`, the same permission app/api/staff.py already
proved out - recording what the platform's own rules mean belongs with the
other things only `admin` grants today.
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.core.passwords import hash_password
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


# ── Reachable only with settings.manage ─────────────────────────────────────


def test_endpoints_require_authentication():
    with TestClient(app) as anonymous:
        assert anonymous.get("/api/policy/versions").status_code == 401
        assert (
            anonymous.post(
                "/api/policy/versions",
                json={"effective_month": "2026-09", "summary_markdown": "x"},
            ).status_code
            == 401
        )


def test_a_role_without_settings_manage_is_refused(client):
    _demote_to("affiliate_manager")
    assert client.get("/api/policy/versions").status_code == 403
    assert (
        client.post(
            "/api/policy/versions",
            json={"effective_month": "2026-09", "summary_markdown": "x"},
        ).status_code
        == 403
    )


# ── Creating and listing ────────────────────────────────────────────────────


def test_creating_a_version(client):
    response = client.post(
        "/api/policy/versions",
        json={"effective_month": "2026-09", "summary_markdown": "Commission is..."},
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["effective_month"] == "2026-09"
    assert body["summary_markdown"] == "Commission is..."
    assert "id" in body


def test_a_second_version_must_be_later(client):
    client.post(
        "/api/policy/versions",
        json={"effective_month": "2026-09", "summary_markdown": "x"},
    )
    response = client.post(
        "/api/policy/versions",
        json={"effective_month": "2026-06", "summary_markdown": "y"},
    )
    assert response.status_code == 400


def test_listing_returns_every_version(client):
    client.post(
        "/api/policy/versions",
        json={"effective_month": "2026-09", "summary_markdown": "x"},
    )
    client.post(
        "/api/policy/versions",
        json={"effective_month": "2026-11", "summary_markdown": "y"},
    )

    response = client.get("/api/policy/versions")
    assert response.status_code == 200
    months = [v["effective_month"] for v in response.json()["versions"]]
    assert months == ["2026-09", "2026-11"]


def test_created_versions_carry_full_text(client):
    """The maintainer's list view shows every version's full text inline -
    there is no separate 'get one' route, deliberately: nothing ever needs to
    fetch a version alone once the list already carries it.
    """
    client.post(
        "/api/policy/versions",
        json={"effective_month": "2026-09", "summary_markdown": "x"},
    )

    response = client.get("/api/policy/versions")
    assert response.json()["versions"][0]["summary_markdown"] == "x"
