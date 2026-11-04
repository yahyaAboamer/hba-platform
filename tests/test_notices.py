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


# ── Where each notice goes since Settings split (Batch 2.3) ───────────────────


def _broken_everywhere(monkeypatch) -> None:
    """Every notice that used to open bare `/settings`, true at once."""
    from app.config import settings

    monkeypatch.setattr(settings, "go_live_month", "", raising=False)
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO notification_outbox (event, recipient_email, payload, state) "
                "VALUES ('application.approved', 'nour@example.com', '{}', 'failed')"
            )
        )
        connection.execute(
            text(
                "INSERT INTO background_job (kind, payload, status) "
                "VALUES ('shopify_sync_order', '{}', 'failed')"
            )
        )
        connection.execute(
            text(
                "INSERT INTO order_index (shopify_order_id, order_number, placed_at, "
                "business_month, discount_codes, subtotal_piastres, total_piastres, "
                "shipping_piastres, tax_piastres, currency) "
                "VALUES ('9001', '#9001', now(), '2026-08', ARRAY['NOBODY10'], 0, 0, 0, 0, 'EGP')"
            )
        )


#: Each notice and the page that fixes it.
HOMES = {
    "go_live_month_unset": "/settings/company",
    "mail_not_configured": "/settings/integrations",
    "notifications_failed": "/settings/integrations",
    "failed_jobs": "/settings/integrations",
    "unregistered_codes": "/affiliates/brand-codes",
}


def test_each_notice_opens_its_new_home_for_the_owner(client, monkeypatch):
    _broken_everywhere(monkeypatch)

    items = {row["key"]: row for row in client.get("/api/operations/attention").json()["items"]}

    assert {key: items[key]["where"] for key in HOMES} == HOMES
    assert not any(row["where"] == "/settings" for row in items.values())


def test_nobody_else_is_sent_to_an_owners_page(client, monkeypatch):
    """The affiliate manager reads the same notices; the Settings pages they
    would open are the owner's, so she gets no button, and the notice says who
    fixes it. Brand codes are hers, so that one keeps its link."""
    from app.core.passwords import hash_password

    _broken_everywhere(monkeypatch)
    with engine.begin() as connection:
        account = connection.execute(
            text(
                "INSERT INTO user_account (email, password_hash, status, display_name) "
                "VALUES ('boda@example.com', :p, 'active', 'Boda') RETURNING id"
            ),
            {"p": hash_password(BOOTSTRAP["password"])},
        ).scalar_one()
        connection.execute(
            text("INSERT INTO role_assignment (user_account_id, role) VALUES (:u, 'affiliate_manager')"),
            {"u": account},
        )
    with TestClient(app) as hers:
        signed_in = hers.post(
            "/api/auth/login", json={"email": "boda@example.com", "password": BOOTSTRAP["password"]}
        )
        assert signed_in.status_code == 200, signed_in.text
        hers.headers["X-CSRF-Token"] = signed_in.json()["csrf"]
        items = {row["key"]: row for row in hers.get("/api/operations/attention").json()["items"]}

    for key in ("go_live_month_unset", "mail_not_configured", "notifications_failed", "failed_jobs"):
        assert (items[key]["where"], items[key]["action"]) == (None, None), key
        assert items[key]["detail"].endswith("The owner fixes this in Settings."), key
    assert items["unregistered_codes"]["where"] == "/affiliates/brand-codes"
