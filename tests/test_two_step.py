"""Two-step sign-in, signed-in devices and suspending (ADR 0067, decisions 4-6;
Phase 1 batch 3).

What has to hold, and is proved here:

- a code is accepted for the step either side of now and no further, and only
  once;
- a recovery code works once;
- the half-way sign-in expires, works once, and opens nothing by itself;
- guessing codes is limited;
- somebody who must use it reaches nothing but setting it up while the
  owner's switch is on, and everything while it is off;
- turning it off is refused to whoever must use it, and the owner's reset of
  somebody else's needs the owner's own code and is audited;
- *Signed in on* only ever touches your own sessions;
- suspending leaves no session and no role, in one audit entry, and
  reactivating gives nothing back.
"""

import json

import pyotp
import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.config import settings
from app.core.passwords import hash_password
from app.core.user_agent import device_label
from app.db import engine
from app.main import app
from app.models.identity import RoleAssignment, UserAccount
from app.services import two_step

PASSWORD = "quiet-harbour-lantern"
OWNER = {"email": "owner@example.com", "display_name": "Owner", "password": PASSWORD}
#: A moment well inside one 30-second step, so "now" is the same step for the
#: whole of a test.
NOW = 1_800_000_015.0


@pytest.fixture(autouse=True)
def _key_and_clock(monkeypatch):
    """A usable Settings key, and a clock that stands still."""
    monkeypatch.setattr(
        settings, "settings_encryption_key", Fernet.generate_key().decode(), raising=False
    )
    monkeypatch.setattr(settings, "two_step_enforced", False, raising=False)
    monkeypatch.setattr(two_step, "_timestamp", lambda: NOW)


def _step(offset: int = 0) -> int:
    return int(NOW // two_step.STEP_SECONDS) + offset


def _code(secret: str, offset: int = 0) -> str:
    return pyotp.TOTP(secret).generate_otp(_step(offset))


@pytest.fixture()
def client(fresh_database):
    with TestClient(app) as test_client:
        response = test_client.post("/api/auth/bootstrap", json=OWNER)
        assert response.status_code == 201, response.text
        test_client.headers["X-CSRF-Token"] = response.json()["csrf"]
        yield test_client


def _person(email: str, *roles: str, name: str = "Sara") -> int:
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


def _sign_in(client: TestClient, email: str) -> dict:
    client.cookies.clear()
    client.headers.pop("X-CSRF-Token", None)
    response = client.post("/api/auth/login", json={"email": email, "password": PASSWORD})
    assert response.status_code == 200, response.text
    body = response.json()
    if "csrf" in body:
        client.headers["X-CSRF-Token"] = body["csrf"]
    return body


def _turn_on(client: TestClient) -> tuple[str, list[str]]:
    """Set two-step up for whoever `client` is signed in as. Returns the
    secret and the recovery codes."""
    started = client.post("/api/auth/two-step/start", json={"password": PASSWORD})
    assert started.status_code == 200, started.text
    secret = started.json()["secret"]
    confirmed = client.post("/api/auth/two-step/confirm", json={"code": _code(secret)})
    assert confirmed.status_code == 200, confirmed.text
    return secret, confirmed.json()["recovery_codes"]


def _audit(action: str | None = None) -> list[dict]:
    with engine.connect() as connection:
        rows = connection.execute(
            text(
                "SELECT action, subject, actor_id, before_json, after_json "
                "FROM audit_event ORDER BY id"
            )
        ).mappings().all()
    return [dict(r) for r in rows if action is None or r["action"] == action]


def _session_count(user_id: int, live: bool = True) -> int:
    with engine.connect() as connection:
        return connection.execute(
            text(
                "SELECT count(*) FROM auth_session WHERE user_account_id = :u"
                + (" AND revoked_at IS NULL" if live else "")
            ),
            {"u": user_id},
        ).scalar_one()


def _owner_id() -> int:
    with engine.connect() as connection:
        return connection.execute(
            text("SELECT id FROM user_account WHERE email = 'owner@example.com'")
        ).scalar_one()


# ── Codes: the window, and once only (the service) ────────────────────────────


@pytest.fixture()
def enrolled(db):
    """An account with two-step on, made through the service."""
    user = UserAccount(email="nour@example.com", password_hash="x", status="active")
    db.add(user)
    db.flush()
    shown = two_step.begin_setup(db, user)
    assert two_step.confirm_setup(db, user, _code(shown["secret"])) is not None
    # Confirming spent the current step; move the clock on so the window
    # tests start from a step nobody has used.
    return user, shown["secret"]


def test_a_code_from_the_step_either_side_of_now_is_accepted(db, enrolled, monkeypatch):
    user, secret = enrolled
    monkeypatch.setattr(two_step, "_timestamp", lambda: NOW + 300)
    later = lambda offset: pyotp.TOTP(secret).generate_otp(_step(10 + offset))  # noqa: E731
    # Oldest first: each accepted step closes every step before it.
    assert two_step.check_authenticator_code(db, user.id, later(-1))
    assert two_step.check_authenticator_code(db, user.id, later(0))
    assert two_step.check_authenticator_code(db, user.id, later(+1))


def test_a_code_two_steps_away_is_refused_either_way(db, enrolled, monkeypatch):
    user, secret = enrolled
    monkeypatch.setattr(two_step, "_timestamp", lambda: NOW + 300)
    later = lambda offset: pyotp.TOTP(secret).generate_otp(_step(10 + offset))  # noqa: E731
    assert not two_step.check_authenticator_code(db, user.id, later(+2))
    assert not two_step.check_authenticator_code(db, user.id, later(-2))
    assert two_step.check_authenticator_code(db, user.id, later(0))


def test_a_code_is_refused_the_second_time(db, enrolled, monkeypatch):
    user, secret = enrolled
    monkeypatch.setattr(two_step, "_timestamp", lambda: NOW + 300)
    code = pyotp.TOTP(secret).generate_otp(_step(10))
    assert two_step.check_authenticator_code(db, user.id, code)
    assert not two_step.check_authenticator_code(db, user.id, code)
    # And an older one still inside the window is closed by the newer one.
    assert not two_step.check_authenticator_code(
        db, user.id, pyotp.TOTP(secret).generate_otp(_step(9))
    )


def test_the_code_that_confirmed_it_does_not_work_again(db, enrolled):
    user, secret = enrolled
    assert not two_step.check_authenticator_code(db, user.id, _code(secret))


def test_spaces_are_ignored_and_anything_else_is_not_a_code(db, enrolled, monkeypatch):
    user, secret = enrolled
    monkeypatch.setattr(two_step, "_timestamp", lambda: NOW + 300)
    code = pyotp.TOTP(secret).generate_otp(_step(10))
    assert not two_step.check_authenticator_code(db, user.id, code[:5])
    assert not two_step.check_authenticator_code(db, user.id, f"{code}0")
    assert two_step.check_authenticator_code(db, user.id, f"{code[:3]} {code[3:]}")


def test_the_secret_is_stored_encrypted(db, enrolled):
    user, secret = enrolled
    stored = db.execute(
        text("SELECT secret_encrypted FROM two_step_secret WHERE user_account_id = :u"),
        {"u": user.id},
    ).scalar_one()
    assert secret not in stored
    assert Fernet(settings.settings_encryption_key.encode()).decrypt(stored.encode()).decode() == secret


def test_recovery_codes_are_stored_only_as_slow_salted_hashes(db, enrolled):
    user, _ = enrolled
    codes = two_step.new_recovery_codes(db, user.id)
    assert len(codes) == 10 and len(set(codes)) == 10
    for code in codes:
        assert len(code) == 11 and code[5] == "-"
        assert set(code.replace("-", "")) <= set(two_step.RECOVERY_ALPHABET)
    stored = db.execute(
        text("SELECT code_hash FROM recovery_code WHERE user_account_id = :u"), {"u": user.id}
    ).scalars().all()
    assert len(stored) == 10
    for code, row in zip(codes, stored):
        assert code.replace("-", "") not in row
        assert row.startswith("pbkdf2_sha256$20000$")


# ── Turning it on ─────────────────────────────────────────────────────────────


def test_starting_shows_a_secret_a_link_and_a_qr_code_made_here(client):
    body = client.post("/api/auth/two-step/start", json={"password": PASSWORD}).json()
    assert set(body) == {"secret", "otpauth_uri", "qr_svg"}
    assert body["otpauth_uri"].startswith("otpauth://totp/HBA:owner%40example.com?")
    assert "issuer=HBA" in body["otpauth_uri"]
    assert f"secret={body['secret']}" in body["otpauth_uri"]
    assert body["qr_svg"].startswith("<svg") and "viewBox" in body["qr_svg"]
    # Shown as an image, which a browser draws only with the namespace.
    assert 'xmlns="http://www.w3.org/2000/svg"' in body["qr_svg"]
    # Nothing is on until a code confirms it.
    assert client.get("/api/auth/two-step").json()["enabled"] is False


def test_starting_without_a_usable_key_is_refused_in_words(client, monkeypatch):
    monkeypatch.setattr(settings, "settings_encryption_key", "", raising=False)
    response = client.post("/api/auth/two-step/start", json={"password": PASSWORD})
    assert response.status_code == 503
    assert response.json()["detail"] == "SETTINGS_ENCRYPTION_KEY is not set"
    monkeypatch.setattr(settings, "settings_encryption_key", "half-a-key", raising=False)
    response = client.post("/api/auth/two-step/start", json={"password": PASSWORD})
    assert response.status_code == 503
    assert "not a valid key" in response.json()["detail"]
    assert "half-a-key" not in response.text


def test_confirming_with_a_wrong_code_turns_nothing_on(client):
    secret = client.post("/api/auth/two-step/start", json={"password": PASSWORD}).json()["secret"]
    wrong = _code(secret, 5)
    response = client.post("/api/auth/two-step/confirm", json={"code": wrong})
    assert response.status_code == 400
    assert response.json()["detail"] == (
        "That code did not work. Check the time on your phone and try again."
    )
    assert client.get("/api/auth/two-step").json()["enabled"] is False


def test_confirming_turns_it_on_and_shows_ten_codes_once(client):
    _, codes = _turn_on(client)
    assert len(codes) == 10
    state = client.get("/api/auth/two-step").json()
    assert state["enabled"] is True and state["recovery_codes_left"] == 10
    assert state["enabled_at"]
    assert client.post("/api/auth/two-step/start", json={"password": PASSWORD}).status_code == 409
    assert [e["action"] for e in _audit("auth.two_step.enabled")] == ["auth.two_step.enabled"]


def test_the_session_payload_says_on_required_and_made_to(client, monkeypatch):
    assert client.get("/api/auth/me").json()["actor"]["two_step"] == {
        "enabled": False, "required": True, "must_set_up": False,
    }
    monkeypatch.setattr(settings, "two_step_enforced", True, raising=False)
    assert client.get("/api/auth/me").json()["actor"]["two_step"]["must_set_up"] is True
    _turn_on(client)
    assert client.get("/api/auth/me").json()["actor"]["two_step"] == {
        "enabled": True, "required": True, "must_set_up": False,
    }


def test_who_must_use_it():
    assert two_step.is_required(frozenset({"admin"}))
    assert two_step.is_required(frozenset({"affiliate_manager"}))
    assert two_step.is_required(frozenset({"customer_service", "affiliate_manager"}))
    for role in ("content_manager", "operations_manager", "customer_service", "affiliate"):
        assert not two_step.is_required(frozenset({role})), role
    assert not two_step.is_required(frozenset())


# ── Signing in with it ────────────────────────────────────────────────────────


def test_the_password_alone_opens_nothing_when_two_step_is_on(client):
    _turn_on(client)
    owner = _owner_id()
    sessions_before = _session_count(owner, live=False)
    logins_before = len(_audit("auth.login"))

    client.cookies.clear()
    client.headers.pop("X-CSRF-Token", None)
    response = client.post("/api/auth/login", json={"email": OWNER["email"], "password": PASSWORD})
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"two_step", "pending", "expires_in"}
    assert body["two_step"] == "code" and body["expires_in"] == 300
    assert "set-cookie" not in response.headers
    assert _session_count(owner, live=False) == sessions_before
    assert len(_audit("auth.login")) == logins_before
    assert client.get("/api/auth/me").status_code == 401
    # Only the hash of the pending token is kept.
    with engine.connect() as connection:
        stored = connection.execute(text("SELECT token_hash FROM pending_sign_in")).scalars().all()
    assert body["pending"] not in stored and len(stored) == 1


def test_the_code_finishes_the_sign_in(client):
    secret, _ = _turn_on(client)
    pending = _sign_in(client, OWNER["email"])["pending"]
    response = client.post(
        "/api/auth/login/two-step", json={"pending": pending, "code": _code(secret, 1)}
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body) == {"actor", "csrf"}
    assert body["actor"]["two_step"]["enabled"] is True
    client.headers["X-CSRF-Token"] = body["csrf"]
    assert client.get("/api/staff").status_code == 200
    login = _audit("auth.login")[-1]
    assert login["after_json"] == {"two_step": "code"}


def test_a_wrong_code_is_refused_and_the_pending_sign_in_stays_usable(client):
    secret, _ = _turn_on(client)
    pending = _sign_in(client, OWNER["email"])["pending"]
    wrong = client.post("/api/auth/login/two-step", json={"pending": pending, "code": "000000"})
    if _code(secret, 1) == "000000":  # pragma: no cover - one in a million
        pytest.skip("the right code happened to be 000000")
    assert wrong.status_code == 401
    assert wrong.json()["detail"] == "That code did not work."
    right = client.post(
        "/api/auth/login/two-step", json={"pending": pending, "code": _code(secret, 1)}
    )
    assert right.status_code == 200


def test_a_pending_sign_in_works_once(client):
    secret, _ = _turn_on(client)
    pending = _sign_in(client, OWNER["email"])["pending"]
    first = client.post(
        "/api/auth/login/two-step", json={"pending": pending, "code": _code(secret, 1)}
    )
    assert first.status_code == 200
    again = client.post(
        "/api/auth/login/two-step", json={"pending": pending, "code": _code(secret, -1)}
    )
    assert again.status_code == 410
    assert again.json()["detail"] == "Sign-in took too long. Start again."


def test_a_pending_sign_in_expires(client):
    secret, _ = _turn_on(client)
    pending = _sign_in(client, OWNER["email"])["pending"]
    with engine.begin() as connection:
        connection.execute(
            text("UPDATE pending_sign_in SET expires_at = now() - interval '1 second'")
        )
    response = client.post(
        "/api/auth/login/two-step", json={"pending": pending, "code": _code(secret, 1)}
    )
    assert response.status_code == 410
    unknown = client.post(
        "/api/auth/login/two-step", json={"pending": "made-up", "code": _code(secret, 1)}
    )
    assert unknown.status_code == 410


def test_a_suspension_ends_a_sign_in_waiting_on_its_code(client):
    _person("boda@example.com", "affiliate_manager", name="Boda")
    owner_headers = dict(client.headers)
    with TestClient(app) as boda:
        _sign_in(boda, "boda@example.com")
        secret, _ = _turn_on(boda)
        pending = _sign_in(boda, "boda@example.com")["pending"]

        boda_id = _person_id("boda@example.com")
        suspended = client.post(
            f"/api/staff/{boda_id}/suspend", json={"reason": "Leaving."}, headers=owner_headers
        )
        assert suspended.status_code == 200, suspended.text
        late = boda.post(
            "/api/auth/login/two-step", json={"pending": pending, "code": _code(secret, 1)}
        )
        assert late.status_code == 410


def _person_id(email: str) -> int:
    with engine.connect() as connection:
        return connection.execute(
            text("SELECT id FROM user_account WHERE email = :e"), {"e": email}
        ).scalar_one()


def test_a_recovery_code_works_once(client):
    _, codes = _turn_on(client)
    pending = _sign_in(client, OWNER["email"])["pending"]
    # Without the dash and in capitals is the same code.
    typed = codes[3].replace("-", "").upper()
    first = client.post("/api/auth/login/two-step", json={"pending": pending, "code": typed})
    assert first.status_code == 200, first.text
    assert first.json()["recovery_codes_left"] == 9
    assert _audit("auth.two_step.recovery_used")[-1]["after_json"] == {"recovery_codes_left": 9}
    assert _audit("auth.login")[-1]["after_json"] == {"two_step": "recovery"}

    pending = _sign_in(client, OWNER["email"])["pending"]
    again = client.post("/api/auth/login/two-step", json={"pending": pending, "code": codes[3]})
    assert again.status_code == 401
    other = client.post("/api/auth/login/two-step", json={"pending": pending, "code": codes[4]})
    assert other.status_code == 200
    assert other.json()["recovery_codes_left"] == 8


def test_a_recovery_code_still_works_when_the_key_is_gone(client, monkeypatch):
    secret, codes = _turn_on(client)
    pending = _sign_in(client, OWNER["email"])["pending"]
    monkeypatch.setattr(settings, "settings_encryption_key", "", raising=False)
    by_app = client.post(
        "/api/auth/login/two-step", json={"pending": pending, "code": _code(secret, 1)}
    )
    assert by_app.status_code == 503
    # Not signed in yet: why the key cannot be used is not theirs to read.
    assert by_app.json()["detail"] == (
        "Two-step sign-in is unavailable right now. Try again shortly."
    )
    assert "SETTINGS_ENCRYPTION_KEY" not in by_app.text
    by_recovery = client.post(
        "/api/auth/login/two-step", json={"pending": pending, "code": codes[0]}
    )
    assert by_recovery.status_code == 200


def test_guessing_codes_is_paused_and_the_right_code_is_refused_while_paused(client):
    secret, _ = _turn_on(client)
    pending = _sign_in(client, OWNER["email"])["pending"]
    right = _code(secret, 1)
    wrong = "111111" if right != "111111" else "222222"
    for _ in range(throttle_pair_limit()):
        response = client.post("/api/auth/login/two-step", json={"pending": pending, "code": wrong})
        assert response.status_code == 401
    paused = client.post("/api/auth/login/two-step", json={"pending": pending, "code": right})
    assert paused.status_code == 429
    assert paused.headers["Retry-After"]
    assert paused.json()["detail"].startswith("Too many attempts. Try again in")


def throttle_pair_limit() -> int:
    from app.core import throttle

    return throttle.TWO_STEP_PER_PAIR.limit


def test_a_stranger_without_the_password_cannot_reach_the_code_limits(client):
    """Wrong passwords never count against the code limits, so nobody can use
    them to keep the owner out."""
    from app.core import throttle

    secret, _ = _turn_on(client)
    client.cookies.clear()
    for _ in range(5):
        client.post("/api/auth/login", json={"email": OWNER["email"], "password": "nope-nope-nope"})
    owner = f"user:{_owner_id()}"
    assert throttle.TWO_STEP_PER_ACCOUNT.acquire(owner) == 0  # untouched
    throttle.TWO_STEP_PER_ACCOUNT.release(owner)


def test_a_password_reset_asks_for_the_code_when_two_step_is_on(client):
    """A reset link proves the mailbox, not the phone."""
    from app.services.password_resets import request_reset

    secret, _ = _turn_on(client)
    from app.db import SessionLocal

    with SessionLocal() as db:
        token, _account = request_reset(db, OWNER["email"])
        db.commit()
    client.cookies.clear()
    client.headers.pop("X-CSRF-Token", None)
    response = client.post(
        "/api/auth/password-reset", json={"token": token, "password": "a-brand-new-harbour-lamp"}
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["two_step"] == "code" and "csrf" not in body
    assert "set-cookie" not in response.headers
    assert _session_count(_owner_id()) == 0
    done = client.post(
        "/api/auth/login/two-step", json={"pending": body["pending"], "code": _code(secret, 1)}
    )
    assert done.status_code == 200


# ── The gate ──────────────────────────────────────────────────────────────────


def test_while_enforced_somebody_who_must_use_it_reaches_only_setting_it_up(client, monkeypatch):
    monkeypatch.setattr(settings, "two_step_enforced", True, raising=False)
    refused = client.get("/api/staff")
    assert refused.status_code == 403
    assert refused.json() == {"detail": "Set up two-step sign-in to continue."}
    for path in ("/api/affiliates", "/api/audit", "/api/auth/sessions", "/api/staff/me/preferences"):
        assert client.get(path).status_code == 403, path
    assert client.post("/api/auth/sessions/end-others").status_code == 403

    # What is left open: who they are, setting it up, signing out, the public.
    assert client.get("/api/auth/me").status_code == 200
    assert client.get("/api/auth/two-step").status_code == 200
    assert client.get("/api/client-config").status_code == 200
    assert client.get("/api/health/live").status_code == 200

    _turn_on(client)
    assert client.get("/api/staff").status_code == 200
    assert client.get("/api/auth/sessions").status_code == 200


def test_while_enforced_signing_out_still_works(client, monkeypatch):
    monkeypatch.setattr(settings, "two_step_enforced", True, raising=False)
    assert client.post("/api/auth/logout").status_code == 200
    assert client.get("/api/auth/me").status_code == 401


def test_while_not_enforced_nobody_is_held(client):
    assert client.get("/api/staff").status_code == 200
    assert client.get("/api/auth/me").json()["actor"]["two_step"]["must_set_up"] is False


def test_the_gate_holds_nobody_whose_access_does_not_need_it(client, monkeypatch):
    monkeypatch.setattr(settings, "two_step_enforced", True, raising=False)
    _person("mona@example.com", "customer_service", name="Mona")
    with TestClient(app) as mona:
        _sign_in(mona, "mona@example.com")
        assert mona.get("/api/auth/me").json()["actor"]["two_step"] == {
            "enabled": False, "required": False, "must_set_up": False,
        }
        assert mona.get("/api/inbox/conversations").status_code != 403
        assert mona.get("/api/auth/sessions").status_code == 200


def test_the_gate_covers_an_affiliate_manager_signed_in_before_it_was_switched_on(client, monkeypatch):
    _person("boda@example.com", "affiliate_manager", name="Boda")
    with TestClient(app) as boda:
        _sign_in(boda, "boda@example.com")
        assert boda.get("/api/affiliates").status_code == 200
        monkeypatch.setattr(settings, "two_step_enforced", True, raising=False)
        assert boda.get("/api/affiliates").status_code == 403


# ── Turning it off, renewing codes ────────────────────────────────────────────


def test_turning_it_off_is_refused_to_whoever_must_use_it(client):
    secret, _ = _turn_on(client)
    response = client.post("/api/auth/two-step/turn-off", json={"code": _code(secret, 1)})
    assert response.status_code == 403
    assert response.json()["detail"] == (
        "Your access needs two-step sign-in. If you lost your phone, the owner can reset it."
    )
    assert client.get("/api/auth/two-step").json()["enabled"] is True


def test_somebody_who_may_turn_it_off_does_so_with_a_code(client):
    _person("sara@example.com", "content_manager")
    with TestClient(app) as sara:
        _sign_in(sara, "sara@example.com")
        secret, _ = _turn_on(sara)
        wrong = sara.post("/api/auth/two-step/turn-off", json={"code": "12345a"})
        assert wrong.status_code == 400
        done = sara.post("/api/auth/two-step/turn-off", json={"code": _code(secret, 1)})
        assert done.status_code == 200 and done.json() == {"enabled": False}
        assert sara.get("/api/auth/two-step").json() == {
            "enabled": False, "required": False, "must_set_up": False,
            "enabled_at": None, "recovery_codes_left": 0,
        }
    assert [e["action"] for e in _audit("auth.two_step.turned_off")] == ["auth.two_step.turned_off"]


def test_renewing_recovery_codes_replaces_every_one(client):
    secret, old = _turn_on(client)
    response = client.post("/api/auth/two-step/recovery-codes", json={"code": _code(secret, 1)})
    assert response.status_code == 200
    new = response.json()["recovery_codes"]
    assert len(new) == 10 and not set(new) & set(old)
    pending = _sign_in(client, OWNER["email"])["pending"]
    assert client.post(
        "/api/auth/login/two-step", json={"pending": pending, "code": old[0]}
    ).status_code == 401
    assert _audit("auth.two_step.recovery_renewed")


def test_codes_typed_while_signed_in_are_limited_too(client):
    secret = client.post("/api/auth/two-step/start", json={"password": PASSWORD}).json()["secret"]
    right = _code(secret)
    wrong = "111111" if right != "111111" else "222222"
    for _ in range(5):
        assert client.post("/api/auth/two-step/confirm", json={"code": wrong}).status_code == 400
    assert client.post("/api/auth/two-step/confirm", json={"code": right}).status_code == 429


# ── The owner's reset of somebody else's ──────────────────────────────────────


def test_the_owners_reset_needs_the_owners_own_code_and_is_audited(client):
    sara = _person("sara@example.com", "content_manager")
    with TestClient(app) as sara_client:
        _sign_in(sara_client, "sara@example.com")
        _turn_on(sara_client)
        sara_session = sara_client.get("/api/auth/sessions")
        assert sara_session.status_code == 200

    # The owner has none of their own yet.
    response = client.post(f"/api/staff/{sara}/two-step/reset", json={"code": "123456"})
    assert response.status_code == 409
    assert response.json()["detail"] == "Turn on your own two-step sign-in first."

    owner_secret, owner_codes = _turn_on(client)
    wrong = client.post(f"/api/staff/{sara}/two-step/reset", json={"code": "12345x"})
    assert wrong.status_code == 400
    # A recovery code is not the owner proving it is them.
    by_recovery = client.post(f"/api/staff/{sara}/two-step/reset", json={"code": owner_codes[0]})
    assert by_recovery.status_code == 400

    done = client.post(
        f"/api/staff/{sara}/two-step/reset", json={"code": _code(owner_secret, 1)}
    )
    assert done.status_code == 200, done.text
    assert done.json() == {"enabled": False}

    entries = _audit("auth.two_step.reset")
    assert len(entries) == 1
    assert entries[0]["subject"] == f"user:{sara}"
    assert entries[0]["actor_id"] == _owner_id()
    staff = {row["email"]: row for row in client.get("/api/staff").json()["staff"]}
    assert staff["sara@example.com"]["two_step_enabled"] is False
    assert staff["owner@example.com"]["two_step_enabled"] is True


def test_the_owner_cannot_reset_their_own(client):
    secret, _ = _turn_on(client)
    response = client.post(
        f"/api/staff/{_owner_id()}/two-step/reset", json={"code": _code(secret, 1)}
    )
    assert response.status_code == 400
    assert client.get("/api/auth/two-step").json()["enabled"] is True


def test_only_settings_manage_may_reset_somebody(client):
    _person("boda@example.com", "affiliate_manager", name="Boda")
    sara = _person("sara@example.com", "content_manager")
    with TestClient(app) as boda:
        _sign_in(boda, "boda@example.com")
        secret, _ = _turn_on(boda)
        response = boda.post(f"/api/staff/{sara}/two-step/reset", json={"code": _code(secret, 1)})
        assert response.status_code == 403
        assert boda.get(f"/api/staff/{sara}/sessions").status_code == 403


# ── Signed in on ──────────────────────────────────────────────────────────────


def test_my_sessions_are_mine_only_and_say_which_is_this_one(client):
    _person("sara@example.com", "content_manager")
    with TestClient(app) as sara, TestClient(app) as second:
        _sign_in(sara, "sara@example.com")
        second.headers["User-Agent"] = (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
        )
        _sign_in(second, "owner@example.com")

        mine = client.get("/api/auth/sessions").json()["sessions"]
        assert len(mine) == 2
        assert [row["current"] for row in mine].count(True) == 1
        assert {row["device"] for row in mine} >= {"Chrome on Windows"}
        assert set(mine[0]) == {"id", "device", "ip_address", "created_at", "last_seen_at", "current"}

        saras = sara.get("/api/auth/sessions").json()["sessions"]
        assert len(saras) == 1
        # Somebody else's session reads as not there.
        assert client.post(f"/api/auth/sessions/{saras[0]['id']}/end").status_code == 404
        assert sara.get("/api/auth/me").status_code == 200


def test_ending_one_session_and_every_other(client):
    with TestClient(app) as second, TestClient(app) as third:
        _sign_in(second, "owner@example.com")
        _sign_in(third, "owner@example.com")
        _person("sara@example.com", "content_manager")
        with TestClient(app) as sara:
            _sign_in(sara, "sara@example.com")

            mine = client.get("/api/auth/sessions").json()["sessions"]
            other = next(row for row in mine if not row["current"])
            ended = client.post(f"/api/auth/sessions/{other['id']}/end")
            assert ended.json() == {"ended": True}
            assert client.post(f"/api/auth/sessions/{other['id']}/end").status_code == 404

            assert client.post("/api/auth/sessions/end-others").json() == {"ended": 1}
            assert second.get("/api/auth/me").status_code == 401
            assert third.get("/api/auth/me").status_code == 401
            assert client.get("/api/auth/me").status_code == 200
            # Nobody else's were touched.
            assert sara.get("/api/auth/me").status_code == 200
    assert len(_audit("auth.sessions.ended")) == 2


def test_the_owner_sees_and_ends_somebody_elses_sessions(client):
    sara = _person("sara@example.com", "content_manager")
    with TestClient(app) as one, TestClient(app) as two:
        _sign_in(one, "sara@example.com")
        _sign_in(two, "sara@example.com")
        theirs = client.get(f"/api/staff/{sara}/sessions").json()["sessions"]
        assert len(theirs) == 2 and not any(row["current"] for row in theirs)
        assert client.post(f"/api/staff/{sara}/sessions/end-all").json() == {"ended": 2}
        assert one.get("/api/auth/me").status_code == 401
    entry = _audit("auth.sessions.ended")[-1]
    assert entry["subject"] == f"user:{sara}" and entry["actor_id"] == _owner_id()
    # The owner's own session is untouched.
    assert client.get("/api/auth/me").status_code == 200


@pytest.mark.parametrize(
    "header, label",
    [
        ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
         "Chrome/131.0.0.0 Safari/537.36", "Chrome on Windows"),
        ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
         "Chrome/131.0.0.0 Safari/537.36 Edg/131.0.0.0", "Edge on Windows"),
        ("Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 "
         "(KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1", "Safari on iPhone"),
        ("Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 "
         "(KHTML, like Gecko) CriOS/131.0 Mobile/15E148 Safari/604.1", "Chrome on iPhone"),
        ("Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5) AppleWebKit/605.1.15 (KHTML, like Gecko) "
         "Version/17.5 Safari/605.1.15", "Safari on Mac"),
        ("Mozilla/5.0 (Linux; Android 14; SM-S918B) AppleWebKit/537.36 (KHTML, like Gecko) "
         "SamsungBrowser/25.0 Chrome/121.0.0.0 Mobile Safari/537.36", "Samsung Internet on Android"),
        ("Mozilla/5.0 (X11; Linux x86_64; rv:128.0) Gecko/20100101 Firefox/128.0", "Firefox on Linux"),
        ("testclient", "Unknown browser"),
        ("", "Unknown browser"),
        (None, "Unknown browser"),
    ],
)
def test_a_device_is_named_from_its_header(header, label):
    assert device_label(header) == label


# ── Suspending ────────────────────────────────────────────────────────────────


def test_suspending_ends_every_session_and_takes_every_role_in_one_entry(client):
    sara = _person("sara@example.com", "content_manager", "customer_service")
    with TestClient(app) as one, TestClient(app) as two:
        _sign_in(one, "sara@example.com")
        _sign_in(two, "sara@example.com")
        response = client.post(f"/api/staff/{sara}/suspend", json={"reason": "Leaving."})
        assert response.status_code == 200, response.text
        assert response.json() == {
            "id": sara, "status": "suspended", "roles": [], "sessions_ended": 2,
        }
        assert one.get("/api/auth/me").status_code == 401

    assert _session_count(sara) == 0
    with engine.connect() as connection:
        live = connection.execute(
            text(
                "SELECT count(*) FROM role_assignment "
                "WHERE user_account_id = :u AND revoked_at IS NULL"
            ),
            {"u": sara},
        ).scalar_one()
        kept = connection.execute(
            text("SELECT count(*) FROM role_assignment WHERE user_account_id = :u"),
            {"u": sara},
        ).scalar_one()
    assert live == 0
    assert kept == 2, "revoked, never deleted"

    # Her own two sign-ins aside, the suspension is one entry - not a
    # role_removed per role beside it.
    entries = [
        e for e in _audit()
        if e["subject"] == f"user:{sara}" and e["action"] != "auth.login"
    ]
    assert [e["action"] for e in entries] == ["staff.suspended"]
    assert entries[0]["before_json"] == {
        "status": "active", "roles": ["content_manager", "customer_service"],
    }
    assert entries[0]["after_json"] == {"status": "suspended", "roles": [], "sessions_ended": 2}

    row = next(r for r in client.get("/api/staff").json()["staff"] if r["id"] == sara)
    assert row["status"] == "suspended" and row["roles"] == []


def test_reactivating_gives_no_role_back(client):
    sara = _person("sara@example.com", "content_manager")
    client.post(f"/api/staff/{sara}/suspend", json={"reason": "Leaving."})
    response = client.post(f"/api/staff/{sara}/reactivate")
    assert response.status_code == 200
    assert response.json() == {"id": sara, "status": "active", "roles": []}
    with TestClient(app) as back:
        body = _sign_in(back, "sara@example.com")
        assert body["actor"]["roles"] == []
        assert back.get("/api/affiliates").status_code == 403
        # Holding no role does not make a former member of staff an applicant.
        assert back.get("/api/applications/mine").status_code == 403
    # Given again deliberately.
    assert client.post(f"/api/staff/{sara}/roles", json={"role": "content_manager"}).status_code == 201


def test_the_last_admin_still_cannot_be_suspended(db):
    from app.services.staff import suspend_staff

    owner = UserAccount(email="solo@example.com", password_hash="x", status="active")
    db.add(owner)
    db.flush()
    db.add(RoleAssignment(user_account_id=owner.id, role="admin"))
    db.flush()
    with pytest.raises(ValueError, match="only active admin"):
        suspend_staff(db, owner, reason="Testing.", actor_id=None, actor_email=None)
    assert owner.status == "active"


def test_suspending_keeps_a_models_own_role(client):
    """A model's role grants nothing and is never given or taken here; her
    portal is reached by owning her record."""
    both = _person("both@example.com", "affiliate", "customer_service", name="Both")
    response = client.post(f"/api/staff/{both}/suspend", json={"reason": "Testing."})
    assert response.status_code == 200
    with engine.connect() as connection:
        live = connection.execute(
            text(
                "SELECT role FROM role_assignment WHERE user_account_id = :u "
                "AND revoked_at IS NULL"
            ),
            {"u": both},
        ).scalars().all()
    assert live == ["affiliate"]


# ── Nothing secret is written down ────────────────────────────────────────────


def test_no_secret_code_or_token_reaches_the_audit_trail(client):
    secret, codes = _turn_on(client)
    pending = _sign_in(client, OWNER["email"])["pending"]
    code = _code(secret, 1)
    client.post("/api/auth/login/two-step", json={"pending": pending, "code": code})
    pending = _sign_in(client, OWNER["email"])["pending"]
    signed = client.post("/api/auth/login/two-step", json={"pending": pending, "code": codes[0]})
    client.headers["X-CSRF-Token"] = signed.json()["csrf"]
    client.post("/api/auth/two-step/recovery-codes", json={"code": codes[1]})

    with engine.connect() as connection:
        rows = connection.execute(text("SELECT * FROM audit_event")).mappings().all()
    written = json.dumps([dict(r) for r in rows], default=str)
    for value in [secret, code, pending, *codes, *(c.replace("-", "") for c in codes)]:
        assert value not in written


# ── Security review fixes (H1, M1, M2, L1, L3) ────────────────────────────────


def _reset_password(client: TestClient, new_password: str) -> dict:
    from app.db import SessionLocal
    from app.services.password_resets import request_reset

    with SessionLocal() as session:
        token, _account = request_reset(session, OWNER["email"])
        session.commit()
    client.cookies.clear()
    client.headers.pop("X-CSRF-Token", None)
    response = client.post(
        "/api/auth/password-reset", json={"token": token, "password": new_password}
    )
    assert response.status_code == 200, response.text
    return response.json()


def _wrong(secret: str) -> str:
    right = {_code(secret, offset) for offset in (-1, 0, 1)}
    return next(c for c in ("111111", "222222", "333333", "444444") if c not in right)


def test_guesses_before_a_password_reset_still_count_after_it(client):
    """H1: a reset proves the mailbox, so it must not hand out fresh guesses."""
    secret, _ = _turn_on(client)
    pending = _sign_in(client, OWNER["email"])["pending"]
    wrong = _wrong(secret)
    for _ in range(throttle_pair_limit()):
        assert client.post(
            "/api/auth/login/two-step", json={"pending": pending, "code": wrong}
        ).status_code == 401

    owed = _reset_password(client, "a-brand-new-harbour-lamp")
    assert owed["two_step"] == "code"
    paused = client.post(
        "/api/auth/login/two-step", json={"pending": owed["pending"], "code": _code(secret, 1)}
    )
    assert paused.status_code == 429


def test_wrong_codes_are_capped_for_the_day_and_a_reset_does_not_lift_it(client):
    """M1: past the short limits, a ceiling over the day, counted wherever
    the wrong code was typed, and not lifted by a password reset."""
    from app.core import throttle

    secret, _ = _turn_on(client)
    owner = f"user:{_owner_id()}"
    # Pretend the day is nearly used up, without fifty requests.
    for _ in range(throttle.TWO_STEP_PER_DAY.limit - 2):
        assert throttle.TWO_STEP_PER_DAY.acquire(owner) == 0

    # One wrong code while signed in counts toward it...
    wrong = _wrong(secret)
    assert client.post(
        "/api/auth/two-step/recovery-codes", json={"code": wrong}
    ).status_code == 400
    # ...as does one at the sign-in step...
    pending = _sign_in(client, OWNER["email"])["pending"]
    assert client.post(
        "/api/auth/login/two-step", json={"pending": pending, "code": wrong}
    ).status_code == 401
    # ...and now even the right code is refused, here and after a reset.
    right = client.post(
        "/api/auth/login/two-step", json={"pending": pending, "code": _code(secret, 1)}
    )
    assert right.status_code == 429
    owed = _reset_password(client, "a-brand-new-harbour-lamp")
    assert client.post(
        "/api/auth/login/two-step", json={"pending": owed["pending"], "code": _code(secret, 1)}
    ).status_code == 429


def test_a_recovery_code_still_gets_in_once_the_days_cap_is_spent(client):
    """Somebody holding the owner's password can spend the day's fifty wrong
    codes; the owner cannot reset their own two-step, so a recovery code -
    which no one can guess - must still be the way in."""
    from app.core import throttle

    secret, codes = _turn_on(client)
    owner = f"user:{_owner_id()}"
    for _ in range(throttle.TWO_STEP_PER_DAY.limit):
        throttle.TWO_STEP_PER_DAY.acquire(owner)

    pending = _sign_in(client, OWNER["email"])["pending"]
    assert client.post(
        "/api/auth/login/two-step", json={"pending": pending, "code": _code(secret, 1)}
    ).status_code == 429
    used = client.post(
        "/api/auth/login/two-step", json={"pending": pending, "code": codes[0]}
    )
    assert used.status_code == 200
    assert used.json()["recovery_codes_left"] == 9


def test_a_right_code_does_not_count_toward_the_days_cap(client):
    from app.core import throttle

    secret, _ = _turn_on(client)
    owner = f"user:{_owner_id()}"
    pending = _sign_in(client, OWNER["email"])["pending"]
    assert client.post(
        "/api/auth/login/two-step", json={"pending": pending, "code": _code(secret, 1)}
    ).status_code == 200
    # Nothing counted: confirming and signing in were both right, so the
    # whole day's allowance is still there.
    for _ in range(throttle.TWO_STEP_PER_DAY.limit):
        assert throttle.TWO_STEP_PER_DAY.acquire(owner) == 0


def test_only_the_owners_reset_lifts_somebodys_day_of_wrong_codes(client):
    from app.core import throttle

    sara = _person("sara@example.com", "content_manager")
    with TestClient(app) as sara_client:
        _sign_in(sara_client, "sara@example.com")
        _turn_on(sara_client)
    key = f"user:{sara}"
    for _ in range(throttle.TWO_STEP_PER_DAY.limit):
        throttle.TWO_STEP_PER_DAY.acquire(key)
    assert throttle.TWO_STEP_PER_DAY.acquire(key) > 0

    owner_secret, _ = _turn_on(client)
    done = client.post(f"/api/staff/{sara}/two-step/reset", json={"code": _code(owner_secret, 1)})
    assert done.status_code == 200
    assert throttle.TWO_STEP_PER_DAY.acquire(key) == 0
    assert _audit("auth.two_step.reset")


def test_starting_two_step_needs_the_password_again(client):
    """M2: an open session alone cannot put somebody else's phone on it."""
    wrong = client.post("/api/auth/two-step/start", json={"password": "not-my-password"})
    assert wrong.status_code == 400
    assert wrong.json() == {"detail": "That password is not right"}
    assert client.post("/api/auth/two-step/start").status_code == 422
    with engine.connect() as connection:
        assert connection.execute(text("SELECT count(*) FROM two_step_secret")).scalar_one() == 0

    # Limited like the payout re-check: five tries, then even the right one waits.
    for _ in range(4):
        client.post("/api/auth/two-step/start", json={"password": "not-my-password"})
    assert client.post(
        "/api/auth/two-step/start", json={"password": PASSWORD}
    ).status_code == 429


def test_confirming_without_starting_is_refused(client):
    response = client.post("/api/auth/two-step/confirm", json={"code": "123456"})
    assert response.status_code == 409
    assert response.json()["detail"] == "Start setting up two-step sign-in first."
    assert client.get("/api/auth/two-step").json()["enabled"] is False


def test_starting_a_sign_in_clears_out_spent_pending_rows(client):
    """L3: used and expired half-way sign-ins do not pile up."""
    secret, _ = _turn_on(client)
    first = _sign_in(client, OWNER["email"])["pending"]
    assert client.post(
        "/api/auth/login/two-step", json={"pending": first, "code": _code(secret, 1)}
    ).status_code == 200
    _sign_in(client, OWNER["email"])  # left to expire, below
    with engine.connect() as connection:
        # Starting that one already cleared the first, which had been used.
        assert connection.execute(text("SELECT count(*) FROM pending_sign_in")).scalar_one() == 1
    other = _person("sara@example.com", "content_manager")
    with engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE pending_sign_in SET expires_at = now() - interval '1 minute' "
                "WHERE used_at IS NULL"
            )
        )
        # Somebody else's, expired two days ago, and one of theirs from today.
        connection.execute(
            text(
                "INSERT INTO pending_sign_in (user_account_id, token_hash, expires_at) "
                "VALUES (:u, 'old', now() - interval '2 days'), "
                "(:u, 'recent', now() - interval '1 hour')"
            ),
            {"u": other},
        )
        assert connection.execute(text("SELECT count(*) FROM pending_sign_in")).scalar_one() == 3

    _sign_in(client, OWNER["email"])
    with engine.connect() as connection:
        left = connection.execute(
            text("SELECT user_account_id, token_hash FROM pending_sign_in ORDER BY id")
        ).all()
    # The owner's new one, and the other person's from today (kept a day to
    # trace by); the owner's used and expired ones and the two-day-old one gone.
    assert len(left) == 2
    assert (other, "recent") in [tuple(r) for r in left]
    assert all(r[1] != "old" for r in left)


def test_two_admins_suspending_each_other_cannot_both_go(fresh_database):
    """L1: the admins are counted under lock, so the second suspension waits
    for the first and is then refused - never zero admins."""
    from sqlalchemy.exc import OperationalError
    from sqlalchemy.orm import Session as OrmSession

    from app.services.staff import suspend_staff

    a = _person("a@example.com", "admin", name="A")
    b = _person("b@example.com", "admin", name="B")
    first = OrmSession(engine)
    second = OrmSession(engine)
    try:
        suspend_staff(
            first, first.get(UserAccount, b), reason="One.", actor_id=a, actor_email="a@example.com"
        )
        # The first has not committed: the second must wait on its locks.
        second.execute(text("SET LOCAL lock_timeout = '300ms'"))
        with pytest.raises(OperationalError, match="lock"):
            suspend_staff(
                second, second.get(UserAccount, a), reason="Two.", actor_id=b,
                actor_email="b@example.com",
            )
        second.rollback()
        first.commit()

        # Once the first is in, the second is refused outright.
        with pytest.raises(ValueError, match="only active admin"):
            suspend_staff(
                second, second.get(UserAccount, a), reason="Two.", actor_id=b,
                actor_email="b@example.com",
            )
        second.rollback()
    finally:
        first.close()
        second.close()
    with engine.connect() as connection:
        active = connection.execute(
            text("SELECT count(*) FROM user_account WHERE status = 'active'")
        ).scalar_one()
    assert active == 1
