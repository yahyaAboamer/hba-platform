"""Settings → Appearance's two switches, and what the weekly one sends.

Per staff account, saved on the server, absent means on (the export's
defaults). The reminder is a real email through the outbox, to staff who may
record achieved content and have not turned it off.
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.core.passwords import hash_password
from app.db import SessionLocal, engine
from app.main import app
from app.services.jobs import JobKind
from app.services.notifications import Event, render
from app.services.schedule import SCHEDULE
from app.worker import HANDLERS

BOOTSTRAP = {"email": "owner@example.com", "display_name": "Yahya Owner", "password": "quiet-harbour-lantern"}
URL = "/api/staff/me/preferences"


@pytest.fixture()
def client(fresh_database):
    with TestClient(app) as test_client:
        response = test_client.post("/api/auth/bootstrap", json=BOOTSTRAP)
        assert response.status_code == 201, response.text
        test_client.headers["X-CSRF-Token"] = response.json()["csrf"]
        yield test_client


def _staff(email: str, role: str) -> int:
    with engine.begin() as connection:
        account = connection.execute(text(
            "INSERT INTO user_account (email, password_hash, status, display_name) "
            "VALUES (:e, :p, 'active', :n) RETURNING id"
        ), {"e": email, "p": hash_password("quiet-harbour-lantern"), "n": email.split("@")[0].title()}).scalar()
        connection.execute(text(
            "INSERT INTO role_assignment (user_account_id, role) VALUES (:a, :r)"
        ), {"a": account, "r": role})
        return account


def _model(name: str, *, recorded: bool, month: str) -> None:
    with engine.begin() as connection:
        account = connection.execute(text(
            "INSERT INTO user_account (email, password_hash, status) VALUES (:e, 'x', 'active') RETURNING id"
        ), {"e": f"{name.lower()}@example.com"}).scalar()
        affiliate = connection.execute(text(
            "INSERT INTO affiliate_profile (user_account_id, name, status) VALUES (:a, :n, 'active') RETURNING id"
        ), {"a": account, "n": name}).scalar()
        connection.execute(text(
            "INSERT INTO monthly_target (affiliate_id, month, required_videos, required_stories, actual_videos, actual_stories) "
            "VALUES (:f, :m, 4, 8, :v, :s)"
        ), {"f": affiliate, "m": month, "v": 2 if recorded else None, "s": 3 if recorded else None})


def test_both_switches_start_on(client):
    body = client.get(URL).json()
    assert body["preferences"] == {"home_notices": True, "weekly_targets_reminder": True}
    assert body["labels"]["home_notices"] == "Show pop-up notices on Home"


def test_a_switch_saves_and_survives_a_new_session(client):
    response = client.put(URL, json={"key": "home_notices", "enabled": False})
    assert response.status_code == 200
    assert response.json()["preferences"]["home_notices"] is False

    with TestClient(app) as again:
        signed_in = again.post("/api/auth/login", json={"email": BOOTSTRAP["email"], "password": BOOTSTRAP["password"]})
        assert signed_in.status_code == 200, signed_in.text
        assert again.get(URL).json()["preferences"] == {"home_notices": False, "weekly_targets_reminder": True}

    client.put(URL, json={"key": "home_notices", "enabled": True})
    assert client.get(URL).json()["preferences"]["home_notices"] is True


def test_it_is_this_accounts_switch_and_nobody_elses(client):
    client.put(URL, json={"key": "weekly_targets_reminder", "enabled": False})
    other = _staff("nour@example.com", "affiliate_manager")
    with SessionLocal() as db:
        from app.services.staff_prefs import preferences_for
        assert preferences_for(db, other)["weekly_targets_reminder"] is True


def test_turning_one_off_is_audited_in_words(client):
    client.put(URL, json={"key": "weekly_targets_reminder", "enabled": False})
    client.put(URL, json={"key": "weekly_targets_reminder", "enabled": False})  # no change, no entry
    with engine.connect() as connection:
        rows = connection.execute(text(
            "SELECT action, after_json->>'switch', after_json->>'on' FROM audit_event "
            "WHERE action = 'staff.preference_changed'"
        )).all()
    assert rows == [("staff.preference_changed", "Weekly reminder to record achieved content", "false")]


def test_an_unknown_switch_is_refused(client):
    assert client.put(URL, json={"key": "dark_mode", "enabled": False}).status_code == 422


def test_a_model_has_no_staff_switches(client):
    with engine.begin() as connection:
        connection.execute(text("UPDATE role_assignment SET role = 'affiliate'"))
    assert client.get(URL).status_code == 403
    assert client.put(URL, json={"key": "home_notices", "enabled": False}).status_code == 403


# ── The weekly reminder ───────────────────────────────────────────────────────


def test_the_reminder_is_scheduled_and_handled():
    assert JobKind.TARGETS_REMINDER in SCHEDULE
    assert JobKind.TARGETS_REMINDER in HANDLERS


def test_the_reminder_goes_to_staff_who_record_targets_and_want_it(client):
    from app.core.businesstime import business_month, utcnow

    month = business_month(utcnow())
    _model("Sara", recorded=True, month=month)
    _model("Hana", recorded=False, month=month)
    _model("Laila", recorded=False, month=month)
    _staff("nour@example.com", "affiliate_manager")      # records targets, wants it
    muted = _staff("hazem@example.com", "content_manager")  # records targets, turned off
    _staff("gone@example.com", "affiliate")               # not staff
    with SessionLocal() as db:
        from app.models.identity import UserAccount
        from app.services.staff_prefs import set_preference
        set_preference(db, db.get(UserAccount, muted), "weekly_targets_reminder", False)
        db.commit()

    with SessionLocal() as db:
        HANDLERS[JobKind.TARGETS_REMINDER](db, {})
        db.commit()

    with engine.connect() as connection:
        rows = connection.execute(text(
            "SELECT recipient_email, payload FROM notification_outbox WHERE event = :e ORDER BY recipient_email"
        ), {"e": Event.TARGETS_REMINDER}).all()
    assert [email for email, _ in rows] == ["nour@example.com", "owner@example.com"]
    assert rows[0][1]["missing"] == 2 and rows[0][1]["total"] == 3

    message = render(Event.TARGETS_REMINDER, rows[0][1])
    assert message.subject.startswith("Record achieved content for ")
    assert "2 of 3 active models have nothing recorded for" in message.body
    assert "turn this reminder off in Settings → Appearance" in message.body
