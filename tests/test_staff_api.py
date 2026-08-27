"""Who has access to the platform, over HTTP.

`settings.manage` and `invitations.send` were defined in Phase 1 with no
screen for them until now. These tests are the proof that promise was kept:
inviting, changing a role, suspending, and reactivating all happen without a
line of code.
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
    "password": "a-long-enough-password",
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


def _second_staff_account(role: str, email: str = "sara@example.com") -> int:
    """A second staff account, written straight in - the invite-and-accept
    flow is Phase 1's own test file's job, not this one's.
    """
    with engine.begin() as connection:
        user_id = connection.execute(
            text(
                "INSERT INTO user_account (email, password_hash, status, display_name) "
                "VALUES (:e, :p, 'active', 'Sara') RETURNING id"
            ),
            {"e": email, "p": hash_password("a-long-enough-password")},
        ).scalar_one()
        connection.execute(
            text(
                "INSERT INTO role_assignment (user_account_id, role) VALUES (:u, :r)"
            ),
            {"u": user_id, "r": role},
        )
    return user_id


def _audit_actions() -> list[str]:
    with engine.connect() as connection:
        return [
            row[0]
            for row in connection.execute(
                text("SELECT action FROM audit_event ORDER BY id")
            )
        ]


# ── Permission ───────────────────────────────────────────────────────────────


def test_anonymous_access_is_refused(client):
    client.cookies.clear()
    assert client.get("/api/staff").status_code == 401


def test_only_settings_manage_may_see_the_roster(client):
    """Only `admin` grants `settings.manage` today - proven, not assumed."""
    _demote_to("affiliate_manager")
    assert client.get("/api/staff").status_code == 403


def test_invitations_send_alone_cannot_suspend_anyone(client):
    """`affiliate_manager` holds `invitations.send` but not `settings.manage` -
    inviting and administering the roster are different weights of action.
    """
    sara = _second_staff_account("affiliate_manager", "sara@example.com")
    _demote_to("affiliate_manager")
    response = client.post(f"/api/staff/{sara}/suspend", json={"reason": "Testing."})
    assert response.status_code == 403


# ── The roster ───────────────────────────────────────────────────────────────


def test_the_roster_lists_everyone_who_ever_held_a_role(client):
    _second_staff_account("content_manager")

    body = client.get("/api/staff").json()

    names = {row["email"] for row in body["staff"]}
    assert names == {"owner@example.com", "sara@example.com"}


def test_a_role_never_assigned_here_never_appears(client):
    """An account that only ever holds `affiliate` - the no-permission default
    - is not staff. Nothing writes that row today, but the roster must not
    claim otherwise if something someday does.
    """
    body = client.get("/api/staff").json()
    assert "affiliate" not in body["assignable_roles"]


# ── Changing a role ──────────────────────────────────────────────────────────


def test_changing_a_role_writes_a_new_assignment_not_an_edit(client):
    sara = _second_staff_account("content_manager")

    response = client.post(f"/api/staff/{sara}/role", json={"role": "affiliate_manager"})

    assert response.status_code == 200, response.text
    with engine.connect() as connection:
        rows = connection.execute(
            text(
                "SELECT role, revoked_at IS NOT NULL AS revoked FROM role_assignment "
                "WHERE user_account_id = :u ORDER BY id"
            ),
            {"u": sara},
        ).all()
    assert [tuple(r) for r in rows] == [
        ("content_manager", True),
        ("affiliate_manager", False),
    ]
    assert "staff.role_changed" in _audit_actions()


def test_an_unassignable_role_is_refused(client):
    sara = _second_staff_account("content_manager")
    response = client.post(f"/api/staff/{sara}/role", json={"role": "affiliate"})
    assert response.status_code == 400


def test_the_last_admin_cannot_be_demoted(client):
    """Bootstrap creates exactly one admin. Demoting them would leave nobody
    holding `settings.manage` to reverse it.
    """
    body = client.get("/api/staff").json()
    owner_id = next(r["id"] for r in body["staff"] if r["email"] == "owner@example.com")

    response = client.post(
        f"/api/staff/{owner_id}/role", json={"role": "content_manager"}
    )

    assert response.status_code == 400
    assert "only active admin" in response.json()["detail"]


def test_a_second_admin_can_be_demoted(client):
    """The guard is about the *count*, not about touching an admin at all."""
    sara = _second_staff_account("admin")

    response = client.post(f"/api/staff/{sara}/role", json={"role": "content_manager"})

    assert response.status_code == 200, response.text


# ── Suspending and reactivating ─────────────────────────────────────────────


def test_suspending_needs_a_written_reason(client):
    sara = _second_staff_account("content_manager")
    response = client.post(f"/api/staff/{sara}/suspend", json={"reason": ""})
    assert response.status_code == 422


def test_a_suspended_account_is_refused_immediately(client):
    """Not at next sign-in - `resolve_session` checks status on every request,
    so a suspension takes effect before this test's own next call.
    """
    sara = _second_staff_account("content_manager")

    response = client.post(
        f"/api/staff/{sara}/suspend", json={"reason": "Leaving the business."}
    )
    assert response.status_code == 200, response.text

    with engine.connect() as connection:
        status = connection.execute(
            text("SELECT status FROM user_account WHERE id = :u"), {"u": sara}
        ).scalar_one()
    assert status == "suspended"
    assert "staff.suspended" in _audit_actions()


def test_the_last_admin_cannot_suspend_themselves(client):
    body = client.get("/api/staff").json()
    owner_id = next(r["id"] for r in body["staff"] if r["email"] == "owner@example.com")

    response = client.post(
        f"/api/staff/{owner_id}/suspend", json={"reason": "Testing."}
    )

    assert response.status_code == 400
    assert "only active admin" in response.json()["detail"]


def test_reactivating_needs_no_reason(client):
    sara = _second_staff_account("content_manager")
    client.post(f"/api/staff/{sara}/suspend", json={"reason": "Testing."})

    response = client.post(f"/api/staff/{sara}/reactivate")

    assert response.status_code == 200, response.text
    with engine.connect() as connection:
        status = connection.execute(
            text("SELECT status FROM user_account WHERE id = :u"), {"u": sara}
        ).scalar_one()
    assert status == "active"


def test_reactivating_an_active_account_is_refused(client):
    sara = _second_staff_account("content_manager")
    response = client.post(f"/api/staff/{sara}/reactivate")
    assert response.status_code == 400


# ── Invitations ──────────────────────────────────────────────────────────────


def test_a_pending_invitation_appears_on_the_roster(client):
    invite = client.post(
        "/api/auth/invitations", json={"email": "layla@example.com", "role": "content_manager"}
    )
    assert invite.status_code == 201, invite.text

    body = client.get("/api/staff").json()

    assert len(body["invitations"]) == 1
    row = body["invitations"][0]
    assert row["email"] == "layla@example.com"
    assert row["expired"] is False


def test_revoking_an_invitation_closes_the_link(client):
    invite = client.post(
        "/api/auth/invitations", json={"email": "layla@example.com", "role": "content_manager"}
    ).json()
    token = invite["token"]
    invitation_id = client.get("/api/staff").json()["invitations"][0]["id"]

    response = client.post(f"/api/staff/invitations/{invitation_id}/revoke")
    assert response.status_code == 200, response.text

    accept = client.post(
        "/api/auth/invitations/accept",
        json={
            "token": token,
            "display_name": "Layla",
            "password": "a-long-enough-password",
        },
    )
    assert accept.status_code == 422
    assert "invitation.revoked" in _audit_actions()


def test_invitations_send_alone_may_revoke_its_own_invite(client):
    """The mirror of the permission that creates one - `affiliate_manager`
    holds `invitations.send` without `settings.manage`.
    """
    _demote_to("affiliate_manager")
    invite = client.post(
        "/api/auth/invitations", json={"email": "layla@example.com", "role": "content_manager"}
    ).json()

    with engine.connect() as connection:
        invitation_id = connection.execute(
            text("SELECT id FROM invitation WHERE email = 'layla@example.com'")
        ).scalar_one()

    response = client.post(f"/api/staff/invitations/{invitation_id}/revoke")
    assert response.status_code == 200, response.text


def test_revoking_an_already_used_invitation_is_refused(client):
    invite = client.post(
        "/api/auth/invitations", json={"email": "layla@example.com", "role": "content_manager"}
    ).json()
    invitation_id = client.get("/api/staff").json()["invitations"][0]["id"]

    # A separate client: accepting signs Layla in and replaces the session
    # cookie, and reusing `client` for it would leave the owner logged out of
    # their own test.
    with TestClient(app) as other:
        accept = other.post(
            "/api/auth/invitations/accept",
            json={
                "token": invite["token"],
                "display_name": "Layla",
                "password": "a-long-enough-password",
            },
        )
        assert accept.status_code == 201, accept.text

    response = client.post(f"/api/staff/invitations/{invitation_id}/revoke")

    assert response.status_code == 400
