"""The activity log's filters (Settings audit R1-R3).

The box said "or a name" and searched only subjects, which never hold one:
*Sara* found nothing while a dozen entries were about her, and `affiliate:1`
also matched affiliates 10 to 19.
"""

import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.db import engine
from app.main import app
from app.shared.services.audit import KINDS, kind_of

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


def _model(name: str) -> int:
    with engine.begin() as connection:
        account = connection.execute(
            text(
                "INSERT INTO user_account (email, password_hash, status) "
                "VALUES (:e, 'x', 'active') RETURNING id"
            ),
            {"e": f"{name.replace(' ', '.').lower()}@example.com"},
        ).scalar_one()
        return connection.execute(
            text(
                "INSERT INTO affiliate_profile (user_account_id, name, status) "
                "VALUES (:u, :n, 'active') RETURNING id"
            ),
            {"u": account, "n": name},
        ).scalar_one()


def _event(
    action: str, subject: str, reason: str | None = None, *, by_owner: bool = False
) -> None:
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO audit_event (action, subject, actor_id, actor_email, reason) "
                "VALUES (:a, :s, CASE WHEN :o THEN (SELECT id FROM user_account "
                "WHERE email = 'owner@example.com') END, 'someone@example.com', :r)"
            ),
            {"a": action, "s": subject, "r": reason, "o": by_owner},
        )


def _subjects(client, query: str) -> list[str]:
    response = client.get(f"/api/audit?{query}")
    assert response.status_code == 200, response.text
    return [row["subject"] for row in response.json()["events"]]


def test_a_models_name_finds_the_entries_about_her(client):
    sara = _model("Sara Edrees")
    other = _model("Nour Eldin")
    _event("payment.recorded", f"affiliate:{sara}")
    _event("payment.recorded", f"affiliate:{other}")

    assert _subjects(client, "q=sara") == [f"affiliate:{sara}"]


def test_an_exact_subject_is_not_a_prefix(client):
    _event("payment.recorded", "affiliate:1")
    _event("payment.recorded", "affiliate:10")

    assert _subjects(client, "q=affiliate:1") == ["affiliate:1"]


def test_a_colleagues_name_finds_what_they_did(client):
    _event("payment.recorded", "affiliate:1", by_owner=True)
    _event("payment.recorded", "affiliate:2")

    found = _subjects(client, "q=Owner")
    assert "affiliate:1" in found
    assert "affiliate:2" not in found


def test_percent_is_a_letter_not_a_wildcard(client):
    _event("affiliate.details_updated", "affiliate:5", reason="Raised to 10%")
    _event("affiliate.details_updated", "affiliate:6", reason="Raised to 105")

    assert _subjects(client, "q=10%25") == ["affiliate:5"]


def test_sign_ins_can_be_left_out(client):
    _event("auth.login", "user:1")

    with_them = client.get("/api/audit").json()["events"]
    without = client.get("/api/audit?include_sign_ins=false").json()["events"]

    assert any(row["action"] == "auth.login" for row in with_them)
    assert all(row["action"] not in ("auth.login", "auth.logout") for row in without)


def test_a_kind_narrows_to_its_actions(client):
    _event("payment.recorded", "affiliate:1")
    _event("target.verified", "affiliate:1")

    rows = client.get("/api/audit?kind=money").json()["events"]

    assert [row["action"] for row in rows] == ["payment.recorded"]
    assert rows[0]["kind"] == "money"


def test_an_unknown_kind_is_refused(client):
    assert client.get("/api/audit?kind=gossip").status_code == 422


def test_show_older_pages_backwards(client):
    for number in range(5):
        _event("payment.recorded", f"affiliate:{number}")

    first = client.get("/api/audit?kind=money&limit=2").json()
    assert first["has_more"] is True
    last_id = first["events"][-1]["id"]
    second = client.get(f"/api/audit?kind=money&limit=2&before={last_id}").json()

    seen = [row["id"] for row in first["events"] + second["events"]]
    assert len(seen) == len(set(seen)) == 4
    assert seen == sorted(seen, reverse=True)


def test_the_filters_list_models_and_people(client):
    _model("Sara Edrees")

    body = client.get("/api/audit/filters").json()

    assert [model["name"] for model in body["models"]] == ["Sara Edrees"]
    assert [person["name"] for person in body["people"]] == ["Owner"]
    assert body["kinds"] == list(KINDS)


def test_every_recorded_action_has_a_kind():
    """A new action nobody sorted would vanish from every filtered view."""
    source = "\n".join(
        path.read_text(encoding="utf-8") for path in Path("app").rglob("*.py")
    )
    actions = set(re.findall(r'action="([a-z_]+\.[a-z_]+)"', source))

    assert actions, "the search found nothing - the pattern is wrong"
    assert sorted(action for action in actions if kind_of(action) is None) == []
