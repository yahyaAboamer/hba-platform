"""Hiding a notice, muting one, and actually fixing the thing. A10.

Phase 08B. The rule is three distinctions that look alike and are not:

    temporary hide     comes back; the browser's business, not the server's
    item mute          persists, and **resolves nothing**
    resolution         the notice stops being generated at all

The failure this file guards is the middle one being mistaken for the last.
A muted problem is still a problem, and a platform that lets somebody quietly
turn off the reason payroll will not close is worse than one that nags.
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


@pytest.fixture(autouse=True)
def _mail_unconfigured(monkeypatch):
    """A notice that is true and not blocking, so it can be muted."""
    from app.config import settings

    # `mail_configured` is derived, so the thing it derives from is what moves.
    # Patching the property itself would test a stub rather than the rule.
    monkeypatch.setattr(settings, "mail_from_address", "", raising=False)
    monkeypatch.setattr(settings, "go_live_month", "2026-01", raising=False)


def _keys(client) -> list[str]:
    return [row["key"] for row in client.get("/api/operations/attention").json()["items"]]


def test_a_notice_appears_until_it_is_muted(client):
    assert "mail_not_configured" in _keys(client)

    client.post("/api/operations/notices/mute", json={"key": "mail_not_configured"})

    assert "mail_not_configured" not in _keys(client)


def test_a_mute_outlives_the_session_that_set_it(client):
    """**The difference from a temporary hide.** A hide lives in the browser
    and comes back; a mute is a decision somebody made and has to survive the
    tab being closed.
    """
    client.post("/api/operations/notices/mute", json={"key": "mail_not_configured"})

    with TestClient(app) as second:
        second.post("/api/auth/login", json={
            "email": BOOTSTRAP["email"], "password": BOOTSTRAP["password"]
        })
        assert "mail_not_configured" not in [
            row["key"]
            for row in second.get("/api/operations/attention").json()["items"]
        ]


def test_muting_resolves_nothing_and_says_so(client):
    """**The rule this file exists for.** The problem is still there and the
    notice is still true - it is listed back under `muted`, so somebody who did
    not mute it can still find it and a mute cannot become a thing nobody
    remembers turning off.
    """
    client.post("/api/operations/notices/mute", json={"key": "mail_not_configured"})

    body = client.get("/api/operations/attention").json()

    assert [row["key"] for row in body["muted"]] == ["mail_not_configured"]
    assert body["muted"][0]["muted"] is True


def test_unmuting_brings_it_back(client):
    client.post("/api/operations/notices/mute", json={"key": "mail_not_configured"})
    client.delete("/api/operations/notices/mute/mail_not_configured")

    assert "mail_not_configured" in _keys(client)


def test_resolving_the_issue_clears_it_whether_or_not_it_was_muted(
    client, monkeypatch
):
    """Resolution is the only one of the three that actually ends it. The
    notice stops being generated, so the mute becomes irrelevant rather than
    wrong - and nothing has to remember to clean it up.
    """
    from app.config import settings

    client.post("/api/operations/notices/mute", json={"key": "mail_not_configured"})
    # The issue is actually fixed: a From address, and something to send with.
    monkeypatch.setattr(settings, "mail_from_address", "pay@hbawear.store",
                        raising=False)
    monkeypatch.setattr(settings, "smtp_host", "smtp.example.com", raising=False)

    body = client.get("/api/operations/attention").json()

    assert "mail_not_configured" not in [row["key"] for row in body["items"]]
    assert "mail_not_configured" not in [row["key"] for row in body["muted"]]


def test_a_blocking_notice_cannot_be_muted(client, monkeypatch):
    """**A10 lets somebody stop seeing a notice, not a stop sign.**

    "Nothing can be approved" is not noise to be turned off; it is the reason
    the month will not close. Silencing it would make the platform quietly
    useless rather than loudly stuck.
    """
    from app.config import settings

    monkeypatch.setattr(settings, "go_live_month", "", raising=False)
    assert "go_live_month_unset" in _keys(client)

    refused = client.post(
        "/api/operations/notices/mute", json={"key": "go_live_month_unset"}
    )

    assert refused.status_code == 400
    assert "go_live_month_unset" in _keys(client)


def test_muting_twice_is_not_an_error(client):
    """What a double-click looks like. The second should be the same answer,
    not a constraint violation.
    """
    first = client.post(
        "/api/operations/notices/mute", json={"key": "mail_not_configured"}
    )
    second = client.post(
        "/api/operations/notices/mute", json={"key": "mail_not_configured"}
    )

    assert first.status_code == 201 and second.status_code == 201
    with engine.begin() as connection:
        assert connection.execute(
            text("SELECT count(*) FROM notice_mute")
        ).scalar() == 1


def test_unmuting_something_that_was_never_muted_is_not_an_error(client):
    assert (
        client.delete("/api/operations/notices/mute/mail_not_configured").status_code
        == 200
    )


def test_every_notice_says_where_to_go(client):
    """A10: a notice for one record opens that record, and a multi-record one
    opens a filtered list. Either way it points - a notice that only describes
    a problem leaves somebody hunting for it.
    """
    for row in client.get("/api/operations/attention").json()["items"]:
        assert row["where"], row
