"""Who reaches the operations dashboard, and that there is only ever one
operations manager (ADR 0057).

The database refuses a second live holder outright
(`test_identity_models`); these pin the readable refusal that comes first,
everywhere a person can be given the role: an invitation, accepting one, and
a change of access.
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text

from app.core.businesstime import utcnow
from app.db import engine
from app.main import app
from app.models.identity import RoleAssignment, UserAccount
from app.services.invitations import accept_invitation, create_invitation
from app.services.staff import change_role

PASSWORD = "quiet-harbour-lantern"
BOOTSTRAP = {
    "email": "owner@example.com",
    "display_name": "Owner",
    "password": PASSWORD,
}


def _account(db, email: str, role: str, name: str) -> UserAccount:
    user = UserAccount(email=email, password_hash="x", status="active", display_name=name)
    db.add(user)
    db.flush()
    db.add(RoleAssignment(user_account_id=user.id, role=role))
    db.flush()
    return user


# ── One at a time ─────────────────────────────────────────────────────────────


def test_a_second_operations_manager_cannot_be_invited(db):
    _account(db, "amr@example.com", "operations_manager", "Amr")
    with pytest.raises(ValueError, match="already has an operations manager: Amr"):
        create_invitation(db, "second@example.com", "operations_manager", None)


def test_an_open_invitation_holds_the_role(db):
    create_invitation(db, "first@example.com", "operations_manager", None)
    with pytest.raises(ValueError, match="first@example.com"):
        create_invitation(db, "second@example.com", "operations_manager", None)


def test_a_withdrawn_or_lapsed_invitation_frees_the_role(db):
    _, withdrawn = create_invitation(db, "gone@example.com", "operations_manager", None)
    withdrawn.withdrawn_at = utcnow()
    _, lapsed = create_invitation(db, "next@example.com", "operations_manager", None)
    lapsed.expires_at = utcnow()
    create_invitation(db, "third@example.com", "operations_manager", None)


def test_other_staff_roles_are_not_limited(db):
    _account(db, "boda@example.com", "affiliate_manager", "Boda")
    create_invitation(db, "another@example.com", "affiliate_manager", None)
    create_invitation(db, "yet@example.com", "affiliate_manager", None)


def test_nobody_is_moved_onto_the_role_while_it_is_held(db):
    _account(db, "amr@example.com", "operations_manager", "Amr")
    sara = _account(db, "sara@example.com", "content_manager", "Sara")
    with pytest.raises(ValueError, match="already has an operations manager: Amr"):
        change_role(db, sara, "operations_manager", actor_id=None, actor_email=None)


def test_nobody_is_moved_onto_the_role_while_an_invitation_is_open(db):
    create_invitation(db, "pending@example.com", "operations_manager", None)
    sara = _account(db, "sara@example.com", "content_manager", "Sara")
    with pytest.raises(ValueError, match="pending@example.com"):
        change_role(db, sara, "operations_manager", actor_id=None, actor_email=None)


def test_the_holder_can_be_moved_off_and_another_moved_on(db):
    amr = _account(db, "amr@example.com", "operations_manager", "Amr")
    sara = _account(db, "sara@example.com", "content_manager", "Sara")
    change_role(db, amr, "content_manager", actor_id=None, actor_email=None)
    change_role(db, sara, "operations_manager", actor_id=None, actor_email=None)


def test_the_open_invitation_itself_can_be_accepted(db):
    token, _ = create_invitation(db, "amr@example.com", "operations_manager", None)
    db.flush()
    user = accept_invitation(db, token, PASSWORD, "Amr")
    db.flush()
    role = db.scalar(
        select(RoleAssignment.role).where(RoleAssignment.user_account_id == user.id)
    )
    assert role == "operations_manager"


def test_accepting_is_refused_if_the_role_was_taken_meanwhile(db):
    token, _ = create_invitation(db, "late@example.com", "operations_manager", None)
    # Given directly, as a race between two requests would: no service check
    # stood between them.
    sara = _account(db, "sara@example.com", "content_manager", "Sara")
    db.add(RoleAssignment(user_account_id=sara.id, role="operations_manager"))
    db.flush()
    with pytest.raises(ValueError, match="already has an operations manager: Sara"):
        accept_invitation(db, token, PASSWORD, "Late")


# ── Through the API ───────────────────────────────────────────────────────────


@pytest.fixture()
def client(fresh_database):
    with TestClient(app) as test_client:
        response = test_client.post("/api/auth/bootstrap", json=BOOTSTRAP)
        assert response.status_code == 201, response.text
        test_client.headers["X-CSRF-Token"] = response.json()["csrf"]
        yield test_client


def _demote_to(role: str) -> None:
    """Change the signed-in account's role without touching its session."""
    with engine.begin() as connection:
        connection.execute(text("UPDATE role_assignment SET role = :r"), {"r": role})


def _invite(client, email: str, role: str = "operations_manager"):
    return client.post("/api/auth/invitations", json={"email": email, "role": role})


def test_a_second_operations_manager_is_refused_with_the_reason(client):
    assert _invite(client, "amr@example.com").status_code == 201
    second = _invite(client, "other@example.com")
    assert second.status_code == 409
    assert "amr@example.com" in second.json()["detail"]


def test_resending_the_open_invitation_is_not_a_second_one(client):
    assert _invite(client, "amr@example.com").status_code == 201
    with engine.connect() as connection:
        invitation_id = connection.execute(
            text("SELECT id FROM invitation WHERE email = 'amr@example.com'")
        ).scalar_one()
    resent = client.post(f"/api/staff/invitations/{invitation_id}/resend")
    assert resent.status_code == 201, resent.text


def test_an_operations_manager_invites_nobody(client):
    _demote_to("operations_manager")
    assert _invite(client, "model@example.com", role="affiliate").status_code == 403


# ── His own theme, and nothing of the affiliate side ──────────────────────────


def test_an_operations_manager_keeps_a_theme_of_his_own(client):
    _demote_to("operations_manager")

    changed = client.put("/api/staff/me/theme", json={"theme": "light"})
    read = client.get("/api/staff/me/preferences")

    assert changed.status_code == 200, changed.text
    assert read.status_code == 200, read.text
    assert read.json()["theme"] == "light"


def test_an_operations_manager_is_offered_none_of_the_affiliate_switches(client):
    _demote_to("operations_manager")

    body = client.get("/api/staff/me/preferences").json()
    switched = client.put(
        "/api/staff/me/preferences", json={"key": "home_notices", "enabled": False}
    )

    assert body["preferences"] == {}
    assert body["labels"] == {}
    assert switched.status_code == 403


def test_a_model_has_no_staff_theme(client):
    _demote_to("affiliate")
    assert client.get("/api/staff/me/preferences").status_code == 403
    assert client.put("/api/staff/me/theme", json={"theme": "light"}).status_code == 403
