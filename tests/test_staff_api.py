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
            {"e": email, "p": hash_password("quiet-harbour-lantern")},
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


# ── Giving and taking a role (ADR 0067) ─────────────────────────────────────


def _assignments(user_id: int) -> list[tuple[str, bool]]:
    with engine.connect() as connection:
        rows = connection.execute(
            text(
                "SELECT role, revoked_at IS NOT NULL AS revoked FROM role_assignment "
                "WHERE user_account_id = :u ORDER BY id"
            ),
            {"u": user_id},
        ).all()
    return [tuple(r) for r in rows]


def test_giving_a_role_adds_an_assignment_and_keeps_the_rest(client):
    sara = _second_staff_account("content_manager")

    response = client.post(f"/api/staff/{sara}/roles", json={"role": "customer_service"})

    assert response.status_code == 201, response.text
    assert response.json()["roles"] == ["content_manager", "customer_service"]
    assert _assignments(sara) == [
        ("content_manager", False),
        ("customer_service", False),
    ]
    assert "staff.role_given" in _audit_actions()
    row = next(r for r in client.get("/api/staff").json()["staff"] if r["id"] == sara)
    assert row["roles"] == ["content_manager", "customer_service"]


def test_taking_a_role_revokes_it_and_never_deletes_it(client):
    sara = _second_staff_account("content_manager")
    client.post(f"/api/staff/{sara}/roles", json={"role": "affiliate_manager"})

    response = client.post(f"/api/staff/{sara}/roles/content_manager/remove")

    assert response.status_code == 200, response.text
    assert response.json()["roles"] == ["affiliate_manager"]
    assert _assignments(sara) == [
        ("content_manager", True),
        ("affiliate_manager", False),
    ]
    assert "staff.role_removed" in _audit_actions()


def test_a_role_already_held_is_refused(client):
    sara = _second_staff_account("content_manager")
    response = client.post(f"/api/staff/{sara}/roles", json={"role": "content_manager"})
    assert response.status_code == 400
    assert "already holds" in response.json()["detail"]
    assert _assignments(sara) == [("content_manager", False)]


def test_a_role_not_held_cannot_be_taken(client):
    sara = _second_staff_account("content_manager")
    response = client.post(f"/api/staff/{sara}/roles/affiliate_manager/remove")
    assert response.status_code == 400


def test_the_last_staff_role_is_not_taken_suspending_is(client):
    """An account left holding nothing would be neither staff nor a model, and
    could apply to become one. Suspending is how all access goes."""
    sara = _second_staff_account("content_manager")
    response = client.post(f"/api/staff/{sara}/roles/content_manager/remove")
    assert response.status_code == 400
    assert "suspend" in response.json()["detail"]
    assert _assignments(sara) == [("content_manager", False)]


def test_an_unassignable_role_is_refused(client):
    sara = _second_staff_account("content_manager")
    assert client.post(f"/api/staff/{sara}/roles", json={"role": "affiliate"}).status_code == 400
    assert client.post(f"/api/staff/{sara}/roles", json={"role": "wizard"}).status_code == 400


def test_nobody_changes_their_own_access(client):
    """Settings audit T2. One mis-click demoting yourself locks you out of the
    screen that would undo it - with a second admin present, nothing else
    stopped it. Another admin changes yours. Giving yourself more is refused
    for the same reason it always was: nobody acts on their own access."""
    _second_staff_account("admin")
    body = client.get("/api/staff").json()
    owner_id = next(r["id"] for r in body["staff"] if r["email"] == "owner@example.com")

    taken = client.post(f"/api/staff/{owner_id}/roles/admin/remove")
    given = client.post(f"/api/staff/{owner_id}/roles", json={"role": "content_manager"})

    for response in (taken, given):
        assert response.status_code == 400
        assert "your own access" in response.json()["detail"]


def test_the_last_admin_guard_still_holds_below_the_api(client):
    """Unreachable over HTTP now that nobody may act on themselves, and kept
    anyway: it is the lock that matters if a second route ever changes roles."""
    from sqlalchemy.orm import Session as OrmSession

    from app.shared.models.identity import UserAccount
    from app.shared.services.staff import give_role, remove_role

    with OrmSession(engine) as db:
        owner = db.query(UserAccount).filter_by(email="owner@example.com").one()
        give_role(
            db, owner, "content_manager",
            actor_roles=frozenset({"admin"}), actor_id=None, actor_email=None,
        )
        with pytest.raises(ValueError, match="only active admin"):
            remove_role(
                db, owner, "admin",
                actor_roles=frozenset({"admin"}), actor_id=None, actor_email=None,
            )
        db.rollback()


def test_a_second_admin_can_lose_admin(client):
    """The guard is about the *count*, not about touching an admin at all."""
    sara = _second_staff_account("admin")
    client.post(f"/api/staff/{sara}/roles", json={"role": "content_manager"})

    response = client.post(f"/api/staff/{sara}/roles/admin/remove")

    assert response.status_code == 200, response.text
    assert response.json()["roles"] == ["content_manager"]


def test_nobody_gives_or_takes_a_role_they_do_not_hold(db):
    """`can_grant`, against everything the actor holds together. Over HTTP
    only an admin may change access today, so the rule is pinned below it."""
    from app.shared.models.identity import RoleAssignment, UserAccount
    from app.shared.services.staff import give_role, remove_role

    sara = UserAccount(email="sara2@example.com", password_hash="x", status="active")
    db.add(sara)
    db.flush()
    db.add(RoleAssignment(user_account_id=sara.id, role="content_manager"))
    db.add(RoleAssignment(user_account_id=sara.id, role="customer_service"))
    db.flush()
    boda = frozenset({"affiliate_manager"})
    with pytest.raises(ValueError, match="access you hold yourself"):
        give_role(db, sara, "admin", actor_roles=boda, actor_id=None, actor_email=None)
    with pytest.raises(ValueError, match="access you hold yourself"):
        remove_role(
            db, sara, "customer_service", actor_roles=boda, actor_id=None, actor_email=None
        )
    # Two roles together may give what each alone may not.
    both = frozenset({"affiliate_manager", "customer_service"})
    remove_role(db, sara, "customer_service", actor_roles=both, actor_id=None, actor_email=None)


def test_only_settings_manage_may_give_or_take(client):
    sara = _second_staff_account("content_manager")
    _demote_to("affiliate_manager")
    assert client.post(f"/api/staff/{sara}/roles", json={"role": "customer_service"}).status_code == 403
    assert client.post(f"/api/staff/{sara}/roles/content_manager/remove").status_code == 403


def test_the_old_replace_the_role_address_is_gone(client):
    sara = _second_staff_account("content_manager")
    response = client.post(f"/api/staff/{sara}/role", json={"role": "affiliate_manager"})
    assert response.status_code in (404, 405)


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


def test_nobody_suspends_themselves(client):
    _second_staff_account("admin")
    body = client.get("/api/staff").json()
    owner_id = next(r["id"] for r in body["staff"] if r["email"] == "owner@example.com")

    response = client.post(
        f"/api/staff/{owner_id}/suspend", json={"reason": "Testing."}
    )

    assert response.status_code == 400
    assert "your own account" in response.json()["detail"]


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
            "password": "quiet-harbour-lantern",
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
                "password": "quiet-harbour-lantern",
            },
        )
        assert accept.status_code == 201, accept.text

    response = client.post(f"/api/staff/invitations/{invitation_id}/revoke")

    assert response.status_code == 400


def _invite(client, email: str, role: str):
    return client.post("/api/auth/invitations", json={"email": email, "role": role})


def _invitation_id(email: str) -> int:
    with engine.connect() as connection:
        return connection.execute(
            text("SELECT max(id) FROM invitation WHERE email = :e"), {"e": email}
        ).scalar_one()


# ── Who may invite whom (Settings audit X1) ────────────────────────────────


def test_an_affiliate_manager_cannot_invite_an_admin(client):
    """The hole itself: invite a second address as admin, open the link, set
    the password - and an affiliate manager had made themselves an admin."""
    _demote_to("affiliate_manager")

    response = _invite(client, "second.me@example.com", "admin")

    assert response.status_code == 403
    assert "access you hold" in response.json()["detail"]
    with engine.connect() as connection:
        assert connection.execute(text("SELECT count(*) FROM invitation")).scalar_one() == 0


@pytest.mark.parametrize("role", ["affiliate_manager", "content_manager", "affiliate"])
def test_an_affiliate_manager_may_invite_what_they_hold(client, role):
    _demote_to("affiliate_manager")
    assert _invite(client, f"{role}@example.com", role).status_code == 201


def test_an_admin_may_invite_anyone(client):
    assert _invite(client, "new.admin@example.com", "admin").status_code == 201


def test_an_affiliate_manager_cannot_resend_or_withdraw_an_admin_invitation(client):
    """Resend hands back a working link. On an admin invitation that link sets
    the new admin's password - so it is a grant, held to the same rule."""
    _invite(client, "new.admin@example.com", "admin")
    invitation_id = _invitation_id("new.admin@example.com")
    _demote_to("affiliate_manager")

    resend = client.post(f"/api/staff/invitations/{invitation_id}/resend")
    revoke = client.post(f"/api/staff/invitations/{invitation_id}/revoke")

    assert resend.status_code == 403
    assert revoke.status_code == 403
    assert "link" not in resend.json()


def test_the_roster_says_which_roles_you_may_invite(client):
    assert client.get("/api/staff").json()["invitable_roles"] == [
        "admin",
        "affiliate_manager",
        "content_manager",
        "customer_service",
        "operations_manager",
    ]


def test_an_affiliate_manager_sees_the_invitations_they_may_act_on(client):
    """X2: they used to get the invite form and nothing else."""
    _invite(client, "new.admin@example.com", "admin")
    _invite(client, "layla@example.com", "content_manager")
    _demote_to("affiliate_manager")

    body = client.get("/api/staff/invitations").json()

    assert [row["email"] for row in body["invitations"]] == ["layla@example.com"]
    assert body["invitable_roles"] == ["affiliate_manager", "content_manager"]


def test_a_content_manager_may_not_list_or_send_invitations(client):
    _demote_to("content_manager")
    assert client.get("/api/staff/invitations").status_code == 403
    assert _invite(client, "x@example.com", "content_manager").status_code == 403


# ── One pending line per address (Settings audit T1) ────────────────────────


def _pending(client) -> list[str]:
    return [row["email"] for row in client.get("/api/staff").json()["invitations"]]


def test_resending_leaves_one_line_not_two(client):
    _invite(client, "layla@example.com", "content_manager")
    client.post(f"/api/staff/invitations/{_invitation_id('layla@example.com')}/resend")

    assert _pending(client) == ["layla@example.com"]


def test_a_withdrawn_invitation_leaves_the_list(client):
    _invite(client, "layla@example.com", "content_manager")
    client.post(f"/api/staff/invitations/{_invitation_id('layla@example.com')}/revoke")

    assert _pending(client) == []


def test_a_lapsed_invitation_can_be_removed(client):
    """It is shown so somebody can resend it - and until now nothing could take
    it away, since withdrawing refused a link that had already expired."""
    _invite(client, "layla@example.com", "content_manager")
    invitation_id = _invitation_id("layla@example.com")
    with engine.begin() as connection:
        connection.execute(
            text("UPDATE invitation SET expires_at = now() - interval '1 day' WHERE id = :i"),
            {"i": invitation_id},
        )
    assert client.get("/api/staff").json()["invitations"][0]["expired"] is True

    response = client.post(f"/api/staff/invitations/{invitation_id}/revoke")

    assert response.status_code == 200, response.text
    assert _pending(client) == []
    again = client.post(f"/api/staff/invitations/{invitation_id}/revoke")
    assert again.status_code == 400


def test_the_roster_says_what_each_access_can_do(client):
    """T4, from the server's own permission list."""
    from app.core.permissions import permissions_for

    body = client.get("/api/staff").json()["role_permissions"]

    assert set(body) == {
        "admin",
        "affiliate_manager",
        "content_manager",
        "customer_service",
        "operations_manager",
    }
    assert body["content_manager"] == sorted(permissions_for("content_manager"))
    # ADR 0067: the role is Operations alone; he holds the inbox (ADR 0059)
    # as a second assignment, customer service.
    assert body["operations_manager"] == ["order_ops.view"]
    assert body["customer_service"] == ["inbox.use"]
    assert "payments.record" in body["admin"]
    assert "payments.record" not in body["affiliate_manager"]


# ── One live link per address (review of the Settings changes) ─────────────


def test_a_new_invitation_closes_the_earlier_live_link(client):
    """Several live links for one address, with only the newest listed, meant
    withdrawing the visible one left an older one working out of sight."""
    first = _invite(client, "layla@example.com", "content_manager").json()["token"]
    _invite(client, "layla@example.com", "affiliate_manager")

    with TestClient(app) as other:
        accept = other.post(
            "/api/auth/invitations/accept",
            json={"token": first, "display_name": "Layla", "password": "quiet-harbour-lantern"},
        )
    assert accept.status_code == 422


def test_nobody_replaces_an_invitation_they_could_not_have_sent(client):
    _invite(client, "new.admin@example.com", "admin")
    _demote_to("affiliate_manager")

    response = _invite(client, "new.admin@example.com", "content_manager")

    assert response.status_code == 403
    assert "more access" in response.json()["detail"]
