"""Authentication API.

Spec sections 6.2 and 6.3. These tests drive real HTTP requests, so they
exercise cookies, CSRF headers, status codes, and the permission gate exactly
as a browser would.

The fresh_database fixture rebuilds the schema. TRUNCATE is impossible here:
audit_event refuses it and truncating user_account cascades into it, which is
the append-only guard working as intended.
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.db import engine
from app.main import app

BOOTSTRAP = {
    "email": "owner@example.com",
    "display_name": "Owner",
    "password": "a-long-enough-password",
}


@pytest.fixture()
def client(fresh_database):
    with TestClient(app) as test_client:
        yield test_client


def _bootstrap(client) -> dict:
    response = client.post("/api/auth/bootstrap", json=BOOTSTRAP)
    assert response.status_code == 201, response.text
    return response.json()


def _audit_actions() -> list[str]:
    with engine.connect() as connection:
        return [
            row[0]
            for row in connection.execute(
                text("SELECT action FROM audit_event ORDER BY id")
            )
        ]


# ── Bootstrap ──────────────────────────────────────────────────────────────────


def test_status_reports_setup_is_required_before_any_account(client):
    assert client.get("/api/auth/status").json() == {"setup_required": True}


def test_bootstrap_creates_the_first_admin(client):
    body = _bootstrap(client)
    assert body["actor"]["role"] == "admin"
    assert body["actor"]["email"] == "owner@example.com"
    assert body["csrf"]


def test_status_reports_setup_complete_afterwards(client):
    _bootstrap(client)
    assert client.get("/api/auth/status").json() == {"setup_required": False}


def test_bootstrap_only_works_once(client):
    _bootstrap(client)
    second = client.post(
        "/api/auth/bootstrap", json={**BOOTSTRAP, "email": "second@example.com"}
    )
    assert second.status_code == 409


def test_bootstrap_signs_the_new_admin_in(client):
    _bootstrap(client)
    assert "hba_session" in client.cookies
    assert client.get("/api/auth/me").status_code == 200


def test_bootstrap_rejects_a_short_password(client):
    response = client.post(
        "/api/auth/bootstrap", json={**BOOTSTRAP, "password": "short"}
    )
    assert response.status_code == 422


def test_bootstrap_rejects_an_invalid_email(client):
    response = client.post(
        "/api/auth/bootstrap", json={**BOOTSTRAP, "email": "not-an-email"}
    )
    assert response.status_code == 422


# ── Login and logout ───────────────────────────────────────────────────────────


def test_login_succeeds_and_sets_a_session_cookie(client):
    _bootstrap(client)
    client.cookies.clear()
    response = client.post(
        "/api/auth/login",
        json={"email": BOOTSTRAP["email"], "password": BOOTSTRAP["password"]},
    )
    assert response.status_code == 200
    assert "hba_session" in response.cookies


def test_login_is_case_insensitive_on_email(client):
    _bootstrap(client)
    client.cookies.clear()
    response = client.post(
        "/api/auth/login",
        json={"email": "OWNER@EXAMPLE.COM", "password": BOOTSTRAP["password"]},
    )
    assert response.status_code == 200


def test_login_rejects_a_wrong_password(client):
    _bootstrap(client)
    client.cookies.clear()
    response = client.post(
        "/api/auth/login",
        json={"email": BOOTSTRAP["email"], "password": "definitely-wrong-password"},
    )
    assert response.status_code == 401


def test_login_gives_the_same_answer_for_unknown_and_wrong(client):
    """Different messages would confirm which addresses have accounts."""
    _bootstrap(client)
    client.cookies.clear()
    wrong = client.post(
        "/api/auth/login",
        json={"email": BOOTSTRAP["email"], "password": "definitely-wrong-password"},
    )
    unknown = client.post(
        "/api/auth/login",
        json={"email": "nobody@example.com", "password": "definitely-wrong-password"},
    )
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json()["detail"] == unknown.json()["detail"]


def test_the_session_cookie_is_httponly(client):
    """JavaScript must not be able to read the session token."""
    _bootstrap(client)
    client.cookies.clear()
    response = client.post(
        "/api/auth/login",
        json={"email": BOOTSTRAP["email"], "password": BOOTSTRAP["password"]},
    )
    assert "httponly" in response.headers["set-cookie"].lower()


def test_logout_ends_the_session(client):
    body = _bootstrap(client)
    logout = client.post("/api/auth/logout", headers={"X-CSRF-Token": body["csrf"]})
    assert logout.status_code == 200
    assert client.get("/api/auth/me").status_code == 401


# ── Session and CSRF enforcement ───────────────────────────────────────────────


def test_me_requires_a_session(client):
    assert client.get("/api/auth/me").status_code == 401


def test_me_returns_the_actor_and_permissions(client):
    _bootstrap(client)
    body = client.get("/api/auth/me").json()
    assert body["actor"]["email"] == BOOTSTRAP["email"]
    assert "payroll.approve" in body["permissions"]
    assert "payments.record" in body["permissions"]


def test_an_unsafe_request_without_csrf_is_rejected(client):
    """A cross-site form post must not be able to act on a live cookie."""
    _bootstrap(client)
    assert client.post("/api/auth/logout").status_code == 401


def test_an_unsafe_request_with_a_wrong_csrf_is_rejected(client):
    _bootstrap(client)
    response = client.post(
        "/api/auth/logout", headers={"X-CSRF-Token": "not-the-right-token"}
    )
    assert response.status_code == 401


def test_a_forged_session_cookie_is_rejected(client):
    client.cookies.set("hba_session", "a-completely-made-up-token")
    assert client.get("/api/auth/me").status_code == 401


# ── Invitations ────────────────────────────────────────────────────────────────


def test_an_admin_can_invite_staff(client):
    body = _bootstrap(client)
    response = client.post(
        "/api/auth/invitations",
        json={"email": "sara@example.com", "role": "content_manager"},
        headers={"X-CSRF-Token": body["csrf"]},
    )
    assert response.status_code == 201
    assert response.json()["invitation"]["role"] == "content_manager"
    assert response.json()["token"]


def test_inviting_requires_authentication(client):
    _bootstrap(client)
    client.cookies.clear()
    response = client.post(
        "/api/auth/invitations",
        json={"email": "sara@example.com", "role": "content_manager"},
        headers={"X-CSRF-Token": "anything"},
    )
    assert response.status_code == 401


def test_an_unknown_role_is_refused(client):
    body = _bootstrap(client)
    response = client.post(
        "/api/auth/invitations",
        json={"email": "sara@example.com", "role": "wizard"},
        headers={"X-CSRF-Token": body["csrf"]},
    )
    assert response.status_code == 422


def test_accepting_an_invitation_creates_a_working_account(client):
    body = _bootstrap(client)
    invite = client.post(
        "/api/auth/invitations",
        json={"email": "sara@example.com", "role": "content_manager"},
        headers={"X-CSRF-Token": body["csrf"]},
    ).json()

    client.cookies.clear()
    accepted = client.post(
        "/api/auth/invitations/accept",
        json={
            "token": invite["token"],
            "display_name": "Sara",
            "password": "sara-long-enough-password",
        },
    )
    assert accepted.status_code == 201
    assert accepted.json()["actor"]["role"] == "content_manager"


def test_the_invited_role_gets_exactly_its_permissions(client):
    """The permission gate is enforced by role, end to end over HTTP."""
    body = _bootstrap(client)
    invite = client.post(
        "/api/auth/invitations",
        json={"email": "sara@example.com", "role": "content_manager"},
        headers={"X-CSRF-Token": body["csrf"]},
    ).json()

    client.cookies.clear()
    client.post(
        "/api/auth/invitations/accept",
        json={
            "token": invite["token"],
            "display_name": "Sara",
            "password": "sara-long-enough-password",
        },
    )
    permissions = client.get("/api/auth/me").json()["permissions"]
    assert "targets.record" in permissions
    assert "compensation.manage" in permissions
    # The boundary that holds: she cannot approve payroll or move money.
    assert "payroll.approve" not in permissions
    assert "payments.record" not in permissions
    assert "invitations.send" not in permissions


def test_a_role_without_invitation_rights_cannot_invite(client):
    """Server-side enforcement, not a hidden button."""
    body = _bootstrap(client)
    invite = client.post(
        "/api/auth/invitations",
        json={"email": "sara@example.com", "role": "content_manager"},
        headers={"X-CSRF-Token": body["csrf"]},
    ).json()

    client.cookies.clear()
    accepted = client.post(
        "/api/auth/invitations/accept",
        json={
            "token": invite["token"],
            "display_name": "Sara",
            "password": "sara-long-enough-password",
        },
    ).json()

    forbidden = client.post(
        "/api/auth/invitations",
        json={"email": "someone@example.com", "role": "admin"},
        headers={"X-CSRF-Token": accepted["csrf"]},
    )
    assert forbidden.status_code == 403
    assert "invitations.send" in forbidden.json()["detail"]


def test_an_invitation_cannot_be_accepted_twice(client):
    body = _bootstrap(client)
    invite = client.post(
        "/api/auth/invitations",
        json={"email": "sara@example.com", "role": "content_manager"},
        headers={"X-CSRF-Token": body["csrf"]},
    ).json()

    client.cookies.clear()
    payload = {
        "token": invite["token"],
        "display_name": "Sara",
        "password": "sara-long-enough-password",
    }
    assert client.post("/api/auth/invitations/accept", json=payload).status_code == 201
    client.cookies.clear()
    assert client.post("/api/auth/invitations/accept", json=payload).status_code == 422


# ── Audit ──────────────────────────────────────────────────────────────────────


def test_bootstrap_login_and_logout_are_all_audited(client):
    body = _bootstrap(client)
    client.post("/api/auth/logout", headers={"X-CSRF-Token": body["csrf"]})
    client.post(
        "/api/auth/login",
        json={"email": BOOTSTRAP["email"], "password": BOOTSTRAP["password"]},
    )
    actions = _audit_actions()
    assert actions == ["auth.bootstrap", "auth.logout", "auth.login"]


def test_inviting_is_audited(client):
    body = _bootstrap(client)
    client.post(
        "/api/auth/invitations",
        json={"email": "sara@example.com", "role": "content_manager"},
        headers={"X-CSRF-Token": body["csrf"]},
    )
    assert "invitation.create" in _audit_actions()


def test_a_failed_login_creates_no_session_and_no_audit_entry(client):
    _bootstrap(client)
    before = len(_audit_actions())
    client.cookies.clear()
    client.post(
        "/api/auth/login",
        json={"email": BOOTSTRAP["email"], "password": "definitely-wrong-password"},
    )
    assert len(_audit_actions()) == before


# ── Response hygiene ───────────────────────────────────────────────────────────


def test_api_responses_are_never_cached(client):
    _bootstrap(client)
    response = client.get("/api/auth/me")
    assert response.headers["cache-control"] == "no-store"


def test_security_headers_are_present(client):
    response = client.get("/api/health/live")
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"


def test_no_response_ever_contains_a_password_hash(client):
    body = _bootstrap(client)
    assert "password" not in str(body).lower()
    me = client.get("/api/auth/me").text
    assert "password" not in me.lower()
    assert "pbkdf2" not in me.lower()
