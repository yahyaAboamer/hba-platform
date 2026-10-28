"""Codes by email and remembered browsers (ADR 0067, decision 5 as amended by
the owner on 27 October 2026; Phase 1 batch 1.3b).

What has to hold, and is proved here:

- which second step a new browser asks: the app for the owner (or anybody
  with it on), a code by email for whoever's access needs it while the switch
  is on or who turned it on, nothing for anybody else - and never a model;
- a remembered browser skips the code, only for its own account, until it
  expires or is forgotten - and it is forgotten on every event listed;
- an emailed code works once, for ten minutes, and a new one replaces it;
- the outbox forgets the code once the email has gone;
- a password reset signs an email person straight in and asks an app person
  for the code;
- only the owner can be held by the set-up gate.
"""

import json

import pyotp
import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.config import settings
from app.core import throttle
from app.core.passwords import hash_password
from app.db import SessionLocal, engine
from app.main import app
from app.services import two_step

PASSWORD = "quiet-harbour-lantern"
OWNER = {"email": "owner@example.com", "display_name": "Owner", "password": PASSWORD}
NOW = 1_800_000_015.0
TRUSTED = "hba_trusted"


@pytest.fixture(autouse=True)
def _key_and_clock(monkeypatch):
    monkeypatch.setattr(
        settings, "settings_encryption_key", Fernet.generate_key().decode(), raising=False
    )
    monkeypatch.setattr(settings, "two_step_enforced", False, raising=False)
    monkeypatch.setattr(two_step, "_timestamp", lambda: NOW)


def _code(secret: str, offset: int = 0) -> str:
    return pyotp.TOTP(secret).generate_otp(int(NOW // two_step.STEP_SECONDS) + offset)


@pytest.fixture()
def client(fresh_database):
    with TestClient(app) as test_client:
        response = test_client.post("/api/auth/bootstrap", json=OWNER)
        assert response.status_code == 201, response.text
        test_client.headers["X-CSRF-Token"] = response.json()["csrf"]
        yield test_client


def _person(email: str, *roles: str, name: str = "Boda") -> int:
    with engine.begin() as connection:
        user_id = connection.execute(
            text(
                "INSERT INTO user_account (email, password_hash, status, display_name) "
                "VALUES (:e, :p, 'active', :n) RETURNING id"
            ),
            {"e": email, "p": hash_password(PASSWORD), "n": name},
        ).scalar_one()
        for role in roles:
            connection.execute(
                text("INSERT INTO role_assignment (user_account_id, role) VALUES (:u, :r)"),
                {"u": user_id, "r": role},
            )
    return user_id


def _login(client: TestClient, email: str, password: str = PASSWORD):
    """The password step, keeping any remembered-browser cookie the client
    holds - only the session's own cookies are dropped."""
    for name in ("hba_session", "hba_csrf"):
        client.cookies.delete(name)
    client.headers.pop("X-CSRF-Token", None)
    return client.post("/api/auth/login", json={"email": email, "password": password})


def _signed_in(client: TestClient, response) -> dict:
    assert response.status_code == 200, response.text
    body = response.json()
    assert "csrf" in body, body
    client.headers["X-CSRF-Token"] = body["csrf"]
    return body


def _last_emailed_code() -> str:
    with engine.connect() as connection:
        payload = connection.execute(
            text(
                "SELECT payload FROM notification_outbox WHERE event = 'sign_in.code' "
                "ORDER BY id DESC LIMIT 1"
            )
        ).scalar_one()
    return payload["_secret"]["code"]


def _finish(client: TestClient, pending: str, code: str, remember: bool = False):
    return client.post(
        "/api/auth/login/two-step", json={"pending": pending, "code": code, "remember": remember}
    )


def _email_sign_in(client: TestClient, email: str, remember: bool = False) -> dict:
    owed = _login(client, email).json()
    assert owed["method"] == "email", owed
    return _signed_in(client, _finish(client, owed["pending"], _last_emailed_code(), remember))


def _turn_on_app(client: TestClient) -> str:
    secret = client.post("/api/auth/two-step/start", json={"password": PASSWORD}).json()["secret"]
    confirmed = client.post("/api/auth/two-step/confirm", json={"code": _code(secret)})
    assert confirmed.status_code == 200, confirmed.text
    return secret


def _audit(action: str) -> list[dict]:
    with engine.connect() as connection:
        rows = connection.execute(
            text(
                "SELECT subject, actor_id, after_json FROM audit_event "
                "WHERE action = :a ORDER BY id"
            ),
            {"a": action},
        ).mappings().all()
    return [dict(r) for r in rows]


def _live_browsers(user_id: int) -> int:
    with engine.connect() as connection:
        return connection.execute(
            text(
                "SELECT count(*) FROM trusted_browser WHERE user_account_id = :u "
                "AND revoked_at IS NULL AND expires_at > now()"
            ),
            {"u": user_id},
        ).scalar_one()


def _id(email: str) -> int:
    with engine.connect() as connection:
        return connection.execute(
            text("SELECT id FROM user_account WHERE email = :e"), {"e": email}
        ).scalar_one()


@pytest.fixture()
def boda(client, monkeypatch):
    """The affiliate manager, with the owner's switch on: a code by email."""
    monkeypatch.setattr(settings, "two_step_enforced", True, raising=False)
    _person("boda@example.com", "affiliate_manager")
    with TestClient(app) as boda_client:
        yield boda_client


# ── Which second step ─────────────────────────────────────────────────────────


def test_the_method_follows_the_role_the_switch_and_the_choice(client, monkeypatch):
    _person("boda@example.com", "affiliate_manager")
    _person("sara@example.com", "content_manager", name="Sara")
    _person("model@example.com", "affiliate", name="Nour")

    def asked(email: str):
        response = _login(client, email)
        assert response.status_code == 200, response.text
        return response.json().get("method")

    # Switch off: nobody is required, nobody has chosen anything.
    for email in ("owner@example.com", "boda@example.com", "sara@example.com", "model@example.com"):
        assert asked(email) is None, email

    monkeypatch.setattr(settings, "two_step_enforced", True, raising=False)
    assert asked("boda@example.com") == "email"
    assert asked("sara@example.com") is None
    assert asked("model@example.com") is None
    # The owner without the app is let in by the password and then held by
    # the set-up gate - never sent an email code.
    assert asked("owner@example.com") is None
    assert client.get("/api/staff").status_code == 403


def test_other_staff_may_choose_email_codes_with_their_password(client):
    _person("sara@example.com", "content_manager", name="Sara")
    with TestClient(app) as sara:
        _signed_in(sara, _login(sara, "sara@example.com"))
        wrong = sara.post("/api/auth/two-step/email", json={"on": True, "password": "nope-nope"})
        assert wrong.status_code == 400
        assert wrong.json()["detail"] == "That password is not right"

        on = sara.post("/api/auth/two-step/email", json={"on": True, "password": PASSWORD})
        assert on.status_code == 200, on.text
        assert on.json() == {
            "enabled": False, "required": False, "must_set_up": False,
            "method": "email", "email_on": True, "required_method": None,
            "enabled_at": None, "recovery_codes_left": 0,
        }
        _email_sign_in(sara, "sara@example.com")

        off = sara.post("/api/auth/two-step/email", json={"on": False, "password": PASSWORD})
        assert off.json()["email_on"] is False and off.json()["method"] is None
    assert len(_audit("auth.two_step.email_on")) == 1
    assert len(_audit("auth.two_step.email_off")) == 1


def test_whoever_needs_email_codes_cannot_turn_them_off(boda):
    _email_sign_in(boda, "boda@example.com")
    refused = boda.post("/api/auth/two-step/email", json={"on": False, "password": PASSWORD})
    assert refused.status_code == 403
    assert refused.json()["detail"] == (
        "Your access needs a code by email on a new browser, so it cannot be turned off."
    )


def test_anybody_with_the_app_is_asked_for_the_app(client):
    _person("boda@example.com", "affiliate_manager")
    with TestClient(app) as boda:
        _signed_in(boda, _login(boda, "boda@example.com"))
        _turn_on_app(boda)
        answer = _login(boda, "boda@example.com").json()
        assert answer["method"] == "authenticator" and "sent_to" not in answer
        assert answer["expires_in"] == 300


def test_a_model_is_never_asked_and_cannot_turn_either_on(client, monkeypatch):
    monkeypatch.setattr(settings, "two_step_enforced", True, raising=False)
    _person("model@example.com", "affiliate", name="Nour")
    with TestClient(app) as model:
        body = _signed_in(model, _login(model, "model@example.com"))
        assert body["actor"]["two_step"]["method"] is None
        assert body["actor"]["two_step"]["required_method"] is None
        for path, payload in (
            ("/api/auth/two-step/email", {"on": True, "password": PASSWORD}),
            ("/api/auth/two-step/start", {"password": PASSWORD}),
        ):
            refused = model.post(path, json=payload)
            assert refused.status_code == 403, path
            assert refused.json()["detail"] == "Two-step sign-in is for staff accounts."


def test_only_the_owner_can_be_held_by_the_set_up_gate(client, monkeypatch):
    monkeypatch.setattr(settings, "two_step_enforced", True, raising=False)
    _person("boda@example.com", "affiliate_manager")
    with TestClient(app) as boda:
        _email_sign_in(boda, "boda@example.com")
        assert boda.get("/api/affiliates").status_code == 200
        assert boda.get("/api/auth/me").json()["actor"]["two_step"]["must_set_up"] is False
    me = client.get("/api/auth/me").json()["actor"]["two_step"]
    assert me["must_set_up"] is True and me["required_method"] == "authenticator"
    assert client.get("/api/affiliates").status_code == 403


def test_the_roster_says_what_a_new_browser_asks_each_person(client, monkeypatch):
    monkeypatch.setattr(settings, "two_step_enforced", True, raising=False)
    _person("boda@example.com", "affiliate_manager")
    _person("sara@example.com", "content_manager", name="Sara")
    _turn_on_app(client)
    rows = {r["email"]: r for r in client.get("/api/staff").json()["staff"]}
    assert (rows["owner@example.com"]["two_step_method"], rows["owner@example.com"]["two_step_enabled"]) == ("authenticator", True)
    assert (rows["boda@example.com"]["two_step_method"], rows["boda@example.com"]["two_step_enabled"]) == ("email", True)
    assert (rows["sara@example.com"]["two_step_method"], rows["sara@example.com"]["two_step_enabled"]) == (None, False)


# ── Codes by email ────────────────────────────────────────────────────────────


def test_an_emailed_code_signs_in_once(boda):
    answer = _login(boda, "boda@example.com").json()
    assert answer["two_step"] == "code" and answer["method"] == "email"
    assert answer["expires_in"] == 600
    assert answer["sent_to"] == "b•••@example.com"
    code = _last_emailed_code()
    assert len(code) == 6 and code.isdigit()

    wrong = "000000" if code != "000000" else "111111"
    refused = _finish(boda, answer["pending"], wrong)
    assert refused.status_code == 401
    assert refused.json()["detail"] == "That code did not work."
    # A recovery-shaped code is no use for an emailed sign-in.
    assert _finish(boda, answer["pending"], "abcde-fghjk").status_code == 401

    done = _finish(boda, answer["pending"], code)
    assert done.status_code == 200 and "csrf" in done.json()
    assert _audit("auth.login")[-1]["after_json"] == {"two_step": "email"}
    again = _finish(boda, answer["pending"], code)
    assert again.status_code == 410
    assert again.json()["detail"] == "Sign-in took too long. Start again."


def test_an_emailed_code_expires(boda):
    answer = _login(boda, "boda@example.com").json()
    code = _last_emailed_code()
    with engine.begin() as connection:
        connection.execute(
            text("UPDATE pending_sign_in SET expires_at = now() - interval '1 second'")
        )
    assert _finish(boda, answer["pending"], code).status_code == 410


def test_the_code_is_stored_only_keyed_by_the_token_the_browser_holds(boda):
    answer = _login(boda, "boda@example.com").json()
    code = _last_emailed_code()
    with engine.connect() as connection:
        row = connection.execute(
            text("SELECT token_hash, email_code_hash, method FROM pending_sign_in")
        ).mappings().one()
    assert row["method"] == "email"
    assert code not in row["email_code_hash"]
    import hashlib

    # Not a plain hash of the code, so a copy of the table cannot try a million.
    assert row["email_code_hash"] != hashlib.sha256(code.encode()).hexdigest()
    assert answer["pending"] not in row["token_hash"]


def test_a_new_code_replaces_the_old_and_is_limited(boda):
    answer = _login(boda, "boda@example.com").json()
    first = _last_emailed_code()

    soon = boda.post("/api/auth/login/resend", json={"pending": answer["pending"]})
    assert soon.status_code == 429
    assert soon.json()["detail"] == "Too many attempts. Try again in 1 minute."
    assert soon.headers["Retry-After"]

    def a_minute_passes():
        with engine.begin() as connection:
            connection.execute(
                text("UPDATE pending_sign_in SET email_code_sent_at = now() - interval '61 seconds'")
            )

    a_minute_passes()
    sent = boda.post("/api/auth/login/resend", json={"pending": answer["pending"]})
    assert sent.status_code == 200, sent.text
    assert sent.json()["sent_to"] == "b•••@example.com"
    assert 595 <= sent.json()["expires_in"] <= 600
    second = _last_emailed_code()
    if second != first:
        assert _finish(boda, answer["pending"], first).status_code == 401

    for _ in range(3):  # codes three, four and five
        a_minute_passes()
        assert boda.post("/api/auth/login/resend", json={"pending": answer["pending"]}).status_code == 200
    a_minute_passes()
    spent = boda.post("/api/auth/login/resend", json={"pending": answer["pending"]})
    assert spent.status_code == 429
    assert spent.json()["detail"] == "That is as many codes as one sign-in can send. Start again."
    assert spent.headers["Retry-After"]

    assert _finish(boda, answer["pending"], _last_emailed_code()).status_code == 200
    assert boda.post("/api/auth/login/resend", json={"pending": answer["pending"]}).status_code == 410


def test_a_new_code_is_only_for_an_emailed_sign_in(client):
    secret = _turn_on_app(client)
    answer = _login(client, OWNER["email"]).json()
    assert answer["method"] == "authenticator"
    refused = client.post("/api/auth/login/resend", json={"pending": answer["pending"]})
    assert refused.status_code == 409
    assert refused.json()["detail"] == "This sign-in does not use a code by email."
    assert _finish(client, answer["pending"], _code(secret, 1)).status_code == 200


def test_emailed_codes_count_toward_the_days_cap(boda):
    answer = _login(boda, "boda@example.com").json()
    code = _last_emailed_code()
    key = f"user:{_id('boda@example.com')}"
    for _ in range(throttle.TWO_STEP_PER_DAY.limit - 1):
        assert throttle.TWO_STEP_PER_DAY.acquire(key) == 0
    wrong = "000000" if code != "000000" else "111111"
    assert _finish(boda, answer["pending"], wrong).status_code == 401
    assert _finish(boda, answer["pending"], code).status_code == 429


def test_the_outbox_forgets_the_code_once_the_email_has_gone(boda):
    from app.models.notifications import NotificationOutbox
    from app.services.notifications import send_notification

    _login(boda, "boda@example.com")
    code = _last_emailed_code()
    from sqlalchemy import select

    with SessionLocal() as db:
        row = db.scalars(
            select(NotificationOutbox).where(
                NotificationOutbox.event == "sign_in.code"
            )
        ).one()
        send_notification(db, {"outbox_id": row.id})
        db.commit()
    with engine.connect() as connection:
        payload = connection.execute(
            text("SELECT payload FROM notification_outbox WHERE event = 'sign_in.code'")
        ).scalar_one()
    assert "_secret" not in payload
    assert code not in json.dumps(payload)


def test_the_email_says_the_code_and_how_long_it_lasts():
    from app.services.notifications import Event, render

    message = render(
        Event.SIGN_IN_CODE,
        {"email": "boda@example.com", "name": "Boda Ali", "_secret": {"code": "042917"}},
    )
    assert message.subject == "Your HBA sign-in code"
    assert "042917" in message.body
    assert "It works for 10 minutes. If you did not just try to sign in, change your password." in message.body
    assert message.body.startswith("Hi Boda,")


# ── Remembered browsers ──────────────────────────────────────────────────────


def test_a_remembered_browser_skips_the_code_for_its_own_account_only(boda):
    _email_sign_in(boda, "boda@example.com", remember=True)
    assert boda.cookies.get(TRUSTED)
    with engine.connect() as connection:
        stored = connection.execute(text("SELECT token_hash FROM trusted_browser")).scalar_one()
    assert boda.cookies.get(TRUSTED) not in stored

    again = _login(boda, "boda@example.com")
    body = _signed_in(boda, again)
    assert body["actor"]["email"] == "boda@example.com"
    assert _audit("auth.login")[-1]["after_json"] == {"remembered_browser": True}
    # The password is still asked.
    assert _login(boda, "boda@example.com", "wrong-wrong-wrong").status_code == 401

    # The same cookie meeting somebody else's right password skips nothing.
    _person("mai@example.com", "affiliate_manager", name="Mai")
    other = _login(boda, "mai@example.com").json()
    assert other["two_step"] == "code" and other["method"] == "email"


def test_the_remember_cookie_is_httponly_lax_and_lasts_thirty_days(boda):
    answer = _login(boda, "boda@example.com").json()
    response = _finish(boda, answer["pending"], _last_emailed_code(), remember=True)
    cookie = next(
        c for c in response.headers.get_list("set-cookie") if c.startswith(f"{TRUSTED}=")
    ).lower()
    assert "httponly" in cookie and "samesite=lax" in cookie and "path=/" in cookie
    assert f"max-age={30 * 24 * 3600}" in cookie


def test_not_ticking_remember_remembers_nothing(boda):
    _email_sign_in(boda, "boda@example.com", remember=False)
    assert not boda.cookies.get(TRUSTED)
    assert _login(boda, "boda@example.com").json()["method"] == "email"


def test_a_remembered_browser_expires(boda):
    _email_sign_in(boda, "boda@example.com", remember=True)
    with engine.begin() as connection:
        connection.execute(text("UPDATE trusted_browser SET expires_at = now() - interval '1 second'"))
    assert _login(boda, "boda@example.com").json()["method"] == "email"


def test_listing_and_forgetting_my_remembered_browsers(boda):
    _email_sign_in(boda, "boda@example.com", remember=True)
    with TestClient(app) as laptop:
        _email_sign_in(laptop, "boda@example.com", remember=True)
        listed = boda.get("/api/auth/trusted-browsers").json()["browsers"]
        assert len(listed) == 2
        assert set(listed[0]) == {
            "id", "device", "ip_address", "created_at", "last_used_at", "expires_at", "current",
        }
        mine = next(r for r in listed if r["current"])
        theirs = next(r for r in listed if not r["current"])

        # Somebody else's reads as not there.
        assert client_for_owner_forget(theirs["id"]) == 404

        assert boda.post(f"/api/auth/trusted-browsers/{theirs['id']}/forget").json() == {"forgotten": True}
        assert boda.post(f"/api/auth/trusted-browsers/{theirs['id']}/forget").status_code == 404
        assert _login(laptop, "boda@example.com").json()["method"] == "email"

        forgot = boda.post("/api/auth/trusted-browsers/forget-all")
        assert forgot.json() == {"forgotten": 1}
        assert mine["id"]
    assert _live_browsers(_id("boda@example.com")) == 0
    assert [a["after_json"]["forgotten"] for a in _audit("auth.trusted_browser.forgotten")] == [1, 1]


def client_for_owner_forget(browser_id: int) -> int:
    """Somebody else asking to forget a browser that is not theirs."""
    _person("sara@example.com", "content_manager", name="Sara")
    with TestClient(app) as sara:
        _signed_in(sara, _login(sara, "sara@example.com"))
        return sara.post(f"/api/auth/trusted-browsers/{browser_id}/forget").status_code


def test_signing_out_of_one_session_does_not_forget_the_browser(boda):
    _email_sign_in(boda, "boda@example.com", remember=True)
    assert boda.post("/api/auth/logout").status_code == 200
    assert _live_browsers(_id("boda@example.com")) == 1
    _signed_in(boda, _login(boda, "boda@example.com"))


def test_sign_out_everywhere_else_forgets_every_other_browser(boda):
    _email_sign_in(boda, "boda@example.com", remember=True)
    with TestClient(app) as laptop:
        _email_sign_in(laptop, "boda@example.com", remember=True)
        assert boda.post("/api/auth/sessions/end-others").status_code == 200
        assert _live_browsers(_id("boda@example.com")) == 1
        assert _login(laptop, "boda@example.com").json()["method"] == "email"
        _signed_in(boda, _login(boda, "boda@example.com"))


def test_a_password_reset_signs_an_email_person_in_and_forgets_their_browsers(boda):
    from app.services.password_resets import request_reset

    boda_id = _id("boda@example.com")
    _email_sign_in(boda, "boda@example.com", remember=True)
    with SessionLocal() as db:
        token, _ = request_reset(db, "boda@example.com")
        db.commit()
    response = boda.post(
        "/api/auth/password-reset", json={"token": token, "password": "a-brand-new-harbour-lamp"}
    )
    assert response.status_code == 200, response.text
    assert "csrf" in response.json() and "two_step" not in response.json()
    assert _live_browsers(boda_id) == 0
    assert _audit("auth.trusted_browser.forgotten")[-1]["after_json"] == {
        "forgotten": 1, "why": "password_reset",
    }


def test_a_password_reset_asks_an_app_person_for_the_code(client):
    from app.services.password_resets import request_reset

    secret = _turn_on_app(client)
    with SessionLocal() as db:
        token, _ = request_reset(db, OWNER["email"])
        db.commit()
    client.cookies.clear()
    client.headers.pop("X-CSRF-Token", None)
    response = client.post(
        "/api/auth/password-reset", json={"token": token, "password": "a-brand-new-harbour-lamp"}
    )
    body = response.json()
    assert body["two_step"] == "code" and body["method"] == "authenticator"
    assert _finish(client, body["pending"], _code(secret, 1)).status_code == 200


def test_suspending_forgets_their_browsers(client, boda, monkeypatch):
    boda_id = _id("boda@example.com")
    _email_sign_in(boda, "boda@example.com", remember=True)
    # The owner here has no app, so the gate would hold them with the switch on.
    monkeypatch.setattr(settings, "two_step_enforced", False, raising=False)
    suspended = client.post(f"/api/staff/{boda_id}/suspend", json={"reason": "Leaving."})
    assert suspended.status_code == 200, suspended.text
    assert _live_browsers(boda_id) == 0
    with engine.connect() as connection:
        after = connection.execute(
            text("SELECT after_json FROM audit_event WHERE action = 'staff.suspended'")
        ).scalar_one()
    assert after["browsers_forgotten"] == 1


def test_the_owners_end_all_and_reset_forget_their_browsers(client, monkeypatch):
    boda_id = _person("boda@example.com", "affiliate_manager")
    with TestClient(app) as boda:
        _signed_in(boda, _login(boda, "boda@example.com"))
        _turn_on_app(boda)
        answer = _login(boda, "boda@example.com").json()
    # Her app code for this step: the step after the one that confirmed it.
    with engine.connect() as connection:
        enc = connection.execute(
            text("SELECT secret_encrypted FROM two_step_secret WHERE user_account_id = :u"),
            {"u": boda_id},
        ).scalar_one()
    boda_secret = Fernet(settings.settings_encryption_key.encode()).decrypt(enc.encode()).decode()
    with TestClient(app) as boda:
        _signed_in(boda, _finish(boda, answer["pending"], _code(boda_secret, 1), remember=True))
        assert _live_browsers(boda_id) == 1

        listed = client.get(f"/api/staff/{boda_id}/trusted-browsers").json()["browsers"]
        assert len(listed) == 1 and listed[0]["current"] is False

        assert client.post(f"/api/staff/{boda_id}/sessions/end-all").status_code == 200
        assert _live_browsers(boda_id) == 0
        assert _audit("auth.trusted_browser.forgotten")[-1]["after_json"]["why"] == "ended_by_owner"

        # Remembered again, then the owner resets her app.
        answer = _login(boda, "boda@example.com").json()
        # A minute later, so her app shows a code not yet used.
        monkeypatch.setattr(two_step, "_timestamp", lambda: NOW + 60)
        _signed_in(boda, _finish(boda, answer["pending"], _code(boda_secret, 2), remember=True))
        assert _live_browsers(boda_id) == 1
    monkeypatch.setattr(two_step, "_timestamp", lambda: NOW)
    owner_secret = _turn_on_app(client)
    reset = client.post(f"/api/staff/{boda_id}/two-step/reset", json={"code": _code(owner_secret, 1)})
    assert reset.status_code == 200, reset.text
    assert _live_browsers(boda_id) == 0
    assert _audit("auth.trusted_browser.forgotten")[-1]["after_json"]["why"] == "two_step_reset"


def test_turning_two_step_off_forgets_every_browser(client, monkeypatch):
    _person("sara@example.com", "content_manager", name="Sara")
    sara_id = _id("sara@example.com")
    with TestClient(app) as sara:
        _signed_in(sara, _login(sara, "sara@example.com"))
        sara.post("/api/auth/two-step/email", json={"on": True, "password": PASSWORD})
        _email_sign_in(sara, "sara@example.com", remember=True)
        assert _live_browsers(sara_id) == 1
        sara.post("/api/auth/two-step/email", json={"on": False, "password": PASSWORD})
        assert _live_browsers(sara_id) == 0

        # And turning the app off.
        secret = _turn_on_app(sara)
        answer = _login(sara, "sara@example.com").json()
        _signed_in(sara, _finish(sara, answer["pending"], _code(secret, 1), remember=True))
        assert _live_browsers(sara_id) == 1
        monkeypatch.setattr(two_step, "_timestamp", lambda: NOW + 60)
        assert sara.post("/api/auth/two-step/turn-off", json={"code": _code(secret, 2)}).status_code == 200
        assert _live_browsers(sara_id) == 0


def test_an_app_person_who_is_not_the_owner_may_turn_the_app_off(boda):
    """The affiliate manager's requirement is email: turning the app off sends
    her back to email codes rather than being refused."""
    _email_sign_in(boda, "boda@example.com")
    secret = _turn_on_app(boda)
    done = boda.post("/api/auth/two-step/turn-off", json={"code": _code(secret, 1)})
    assert done.status_code == 200, done.text
    assert _login(boda, "boda@example.com").json()["method"] == "email"


def test_no_emailed_code_or_remember_token_reaches_the_audit_trail(boda):
    answer = _login(boda, "boda@example.com").json()
    code = _last_emailed_code()
    _finish(boda, answer["pending"], code, remember=True)
    trusted = boda.cookies.get(TRUSTED)
    with engine.connect() as connection:
        rows = connection.execute(text("SELECT * FROM audit_event")).mappings().all()
    written = json.dumps([dict(r) for r in rows], default=str)
    for value in (code, trusted, answer["pending"]):
        assert value not in written


# ── Security review of 1.3b (M1, L1-L4) ───────────────────────────────────────


def _rows(table: str) -> int:
    with engine.connect() as connection:
        return connection.execute(text(f"SELECT count(*) FROM {table}")).scalar_one()


def _code_emails() -> int:
    with engine.connect() as connection:
        return connection.execute(
            text("SELECT count(*) FROM notification_outbox WHERE event = 'sign_in.code'")
        ).scalar_one()


def test_code_emails_are_capped_per_account_before_anything_is_written(boda):
    """M1: somebody holding the password cannot fill the inbox."""
    answer = _login(boda, "boda@example.com").json()
    for _ in range(3):
        assert _login(boda, "boda@example.com").json()["method"] == "email"
    # A resend counts as well: this is the fifth email in the window.
    with engine.begin() as connection:
        connection.execute(
            text("UPDATE pending_sign_in SET email_code_sent_at = now() - interval '61 seconds'")
        )
    assert boda.post("/api/auth/login/resend", json={"pending": answer["pending"]}).status_code == 200
    assert _code_emails() == 5

    pendings = _rows("pending_sign_in")
    refused = _login(boda, "boda@example.com")
    assert refused.status_code == 429
    assert refused.json()["detail"].startswith("Too many attempts. Try again in")
    assert refused.headers["Retry-After"]
    assert _code_emails() == 5
    assert _rows("pending_sign_in") == pendings

    # And a resend past the limit sends nothing either.
    with engine.begin() as connection:
        connection.execute(
            text("UPDATE pending_sign_in SET email_code_sent_at = now() - interval '61 seconds'")
        )
    late = boda.post("/api/auth/login/resend", json={"pending": answer["pending"]})
    assert late.status_code == 429
    assert late.json()["detail"].startswith("Too many attempts. Try again in")
    assert _code_emails() == 5


def test_code_emails_are_capped_per_day(boda):
    key = f"user:{_id('boda@example.com')}"
    for _ in range(throttle.SIGN_IN_CODE_SENDS_DAY.limit - 1):
        assert throttle.SIGN_IN_CODE_SENDS_DAY.acquire(key) == 0
    assert _login(boda, "boda@example.com").status_code == 200
    assert _login(boda, "boda@example.com").status_code == 429
    assert _code_emails() == 1


def test_an_email_proved_browser_stops_skipping_once_the_app_is_on(boda):
    """L1: a browser is only as strong as the code that proved it."""
    _email_sign_in(boda, "boda@example.com", remember=True)
    with engine.connect() as connection:
        assert connection.execute(text("SELECT method FROM trusted_browser")).scalar_one() == "email"
    _signed_in(boda, _login(boda, "boda@example.com"))  # still skipped
    secret = _turn_on_app(boda)

    asked = _login(boda, "boda@example.com").json()
    assert asked["two_step"] == "code" and asked["method"] == "authenticator"
    # Proved by the app this time, it is remembered as such and skips again.
    _signed_in(boda, _finish(boda, asked["pending"], _code(secret, 1), remember=True))
    _signed_in(boda, _login(boda, "boda@example.com"))


def test_an_email_proved_browser_never_skips_for_the_owner(client):
    """An owner who chose email codes before setting the app up."""
    client.post("/api/auth/two-step/email", json={"on": True, "password": PASSWORD})
    _email_sign_in(client, OWNER["email"], remember=True)
    asked = _login(client, OWNER["email"]).json()
    assert asked["two_step"] == "code" and asked["method"] == "email"


def test_being_made_owner_forgets_every_remembered_browser(client):
    boda_id = _person("boda@example.com", "content_manager")
    with TestClient(app) as boda:
        _signed_in(boda, _login(boda, "boda@example.com"))
        boda.post("/api/auth/two-step/email", json={"on": True, "password": PASSWORD})
        _email_sign_in(boda, "boda@example.com", remember=True)
    assert _live_browsers(boda_id) == 1
    given = client.post(f"/api/staff/{boda_id}/roles", json={"role": "admin"})
    assert given.status_code == 201, given.text
    assert _live_browsers(boda_id) == 0
    with engine.connect() as connection:
        after = connection.execute(
            text("SELECT after_json FROM audit_event WHERE action = 'staff.role_given'")
        ).scalar_one()
    assert after["browsers_forgotten"] == 1


def test_resending_never_keeps_a_sign_in_open_past_twenty_minutes(boda):
    """L2."""
    answer = _login(boda, "boda@example.com").json()
    with engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE pending_sign_in SET created_at = now() - interval '15 minutes', "
                "email_code_sent_at = now() - interval '2 minutes'"
            )
        )
    sent = boda.post("/api/auth/login/resend", json={"pending": answer["pending"]})
    assert sent.status_code == 200, sent.text
    assert 295 <= sent.json()["expires_in"] <= 300
    with engine.connect() as connection:
        left = connection.execute(
            text("SELECT extract(epoch FROM expires_at - created_at) FROM pending_sign_in")
        ).scalar_one()
    assert float(left) == pytest.approx(20 * 60, abs=1)


def test_a_code_email_queued_too_long_is_never_sent(boda):
    """L3: a code that has stopped working is not delivered late."""
    from sqlalchemy import select

    from app.models.notifications import NotificationOutbox, NotificationState
    from app.services.notifications import send_notification

    _login(boda, "boda@example.com")
    code = _last_emailed_code()
    with engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE notification_outbox SET created_at = now() - interval '11 minutes' "
                "WHERE event = 'sign_in.code'"
            )
        )
    with SessionLocal() as db:
        row = db.scalars(
            select(NotificationOutbox).where(NotificationOutbox.event == "sign_in.code")
        ).one()
        send_notification(db, {"outbox_id": row.id})
        db.commit()
        db.refresh(row)
        assert row.state == NotificationState.FAILED
        assert row.attempts == 0
        assert row.last_error == "Not sent: the sign-in code had already expired."
        assert "_secret" not in row.payload
        assert code not in json.dumps(row.payload)


def test_ten_wrong_codes_end_the_sign_in(boda):
    """L4: going on needs the password again, and a new email the inbox's
    owner sees."""
    answer = _login(boda, "boda@example.com").json()
    code = _last_emailed_code()
    wrong = "000000" if code != "000000" else "111111"
    for attempt in range(1, 11):
        # As if from many addresses, so the per-address pause is not met.
        throttle.TWO_STEP_PER_PAIR.reset()
        response = _finish(boda, answer["pending"], wrong)
        if attempt < 10:
            assert response.status_code == 401, (attempt, response.text)
        else:
            assert response.status_code == 410
            assert response.json()["detail"] == "Too many wrong codes. Start again."
    throttle.TWO_STEP_PER_PAIR.reset()
    after = _finish(boda, answer["pending"], code)
    assert after.status_code == 410
    assert after.json()["detail"] == "Sign-in took too long. Start again."
