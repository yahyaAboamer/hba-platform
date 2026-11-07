"""Team and access by department (Batch 2.4).

A level is one of today's roles in other words, so nothing about how access
is stored changes. These tests are the proof of the contract's §6: each level
is exactly its role and back; setting a department gives and takes the right
roles, audited, in one transaction, rolled back on any refusal; every rule
`give_role` and `remove_role` keep still refuses through it; levels not
offered are refused; the two-step reminder keeps its limits; an invitation by
level grants what the same invitation by role does; and nobody but the owner
reaches any of it.
"""

import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.core.passwords import hash_password
from app.core.permissions import (
    DEPARTMENT_LEVELS,
    GRANT_REFUSED,
    LEVELS,
    ROLE_WORDS,
    access_of,
    access_words,
    level_in,
    level_of_role,
    role_for_level,
)
from app.db import engine
from app.main import app
from app.shared.services.staff import ASSIGNABLE_ROLES

BOOTSTRAP = {
    "email": "owner@example.com",
    "display_name": "Owner",
    "password": "quiet-harbour-lantern",
}
PASSWORD = "quiet-harbour-lantern"


@pytest.fixture()
def client(fresh_database):
    with TestClient(app) as test_client:
        response = test_client.post("/api/auth/bootstrap", json=BOOTSTRAP)
        assert response.status_code == 201, response.text
        test_client.headers["X-CSRF-Token"] = response.json()["csrf"]
        yield test_client


def _person(email: str, name: str, *roles: str) -> int:
    """A member of staff written straight in, holding these roles."""
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


def _live(user_id: int) -> set[str]:
    with engine.connect() as connection:
        return set(
            connection.execute(
                text(
                    "SELECT role FROM role_assignment "
                    "WHERE user_account_id = :u AND revoked_at IS NULL"
                ),
                {"u": user_id},
            ).scalars()
        )


def _assignment_count() -> int:
    with engine.connect() as connection:
        return connection.execute(text("SELECT count(*) FROM role_assignment")).scalar_one()


def _audit(action_prefix: str = "staff.") -> list[tuple[str, str | None]]:
    with engine.connect() as connection:
        return [
            (row.action, (row.after_json or {}).get("role"))
            for row in connection.execute(
                text(
                    "SELECT action, after_json FROM audit_event "
                    "WHERE action LIKE :p ORDER BY id"
                ),
                {"p": action_prefix + "%"},
            )
        ]


def _set(client, user_id: int, department: str, level: str):
    return client.put(f"/api/staff/{user_id}/access/{department}", json={"level": level})


def _owner_id(client) -> int:
    rows = client.get("/api/staff").json()["staff"]
    return next(r["id"] for r in rows if r["email"] == "owner@example.com")


# ── The map: each level is exactly its role, and back ─────────────────────────


def test_each_level_is_exactly_its_role_and_back():
    seen = []
    for department, levels in DEPARTMENT_LEVELS.items():
        assert role_for_level(department, "none") is None
        for level in LEVELS[1:]:
            role = levels.get(level)
            if role is None:
                with pytest.raises(ValueError, match="Not offered yet"):
                    role_for_level(department, level)
                continue
            assert role_for_level(department, level) == role
            assert level_of_role(role) == (department, level)
            assert level_in(department, {role}) == level
            seen.append(role)
    # Every staff role but the owner's is one level of one department, once.
    assert sorted(seen) == sorted(ASSIGNABLE_ROLES - {"admin"})
    assert level_of_role("admin") is None
    assert level_of_role("affiliate") is None


def test_the_departments_are_the_sidebars_and_no_more():
    assert list(DEPARTMENT_LEVELS) == ["inbox", "operations", "affiliates", "production"]


def test_both_affiliates_roles_read_as_manager():
    assert level_in("affiliates", {"content_manager", "affiliate_manager"}) == "manager"
    assert access_of({"customer_service", "affiliate_manager"}) == {
        "inbox": "staff",
        "operations": "none",
        "affiliates": "manager",
        "production": "none",
    }


def test_the_small_line_under_a_name():
    """The widest level first, ties in the sidebar's order (frame 5:
    "Operations manager · Inbox staff")."""
    assert access_words({"customer_service", "affiliate_manager"}) == (
        "Affiliates manager · Inbox staff"
    )
    assert access_words({"operations_manager", "customer_service"}) == (
        "Operations manager · Inbox staff"
    )
    assert access_words({"operations_manager", "affiliate_manager"}) == (
        "Operations manager · Affiliates manager"
    )
    assert access_words({"customer_service", "content_manager"}) == (
        "Inbox staff · Affiliates staff"
    )
    assert access_words({"admin", "content_manager"}) == "Owner"
    assert access_words(set()) == "No access"
    assert access_words({"affiliate"}) == "No access"


def test_the_activity_log_says_the_new_words():
    from types import SimpleNamespace

    from app.shared.services.audit_words import _Names, sentence

    names = _Names.__new__(_Names)
    names.affiliates, names.users, names.months = {}, {7: "Mona"}, {}

    def said(action, role=None):
        event = SimpleNamespace(
            action=action, subject="user:7", before_json=None,
            after_json={"role": role} if role else {}, actor_id=None, actor_email=None,
        )
        return sentence(event, names)

    assert said("staff.role_given", "customer_service") == "Gave Mona Inbox staff access"
    assert said("staff.role_removed", "content_manager") == "Took Affiliates staff access from Mona"
    assert said("staff.role_given", "admin") == "Gave Mona Owner access"
    assert said("staff.two_step_reminded") == "Reminded Mona to turn on two-step sign-in"
    for role, words in ROLE_WORDS.items():
        assert words in said("staff.role_given", role)


# ── The roster's new fields ───────────────────────────────────────────────────


def test_the_roster_reads_access_by_department(client):
    mona = _person("mona@example.com", "Mona", "customer_service", "affiliate_manager")

    body = client.get("/api/staff").json()
    rows = {row["id"]: row for row in body["staff"]}

    assert rows[mona]["owner"] is False
    assert rows[mona]["access"] == {"inbox": "staff", "operations": "none", "affiliates": "manager", "production": "none"}
    assert rows[mona]["access_words"] == "Affiliates manager · Inbox staff"
    assert rows[mona]["two_step_required"] is False
    assert rows[mona]["joined_at"] == rows[mona]["created_at"]
    owner = rows[_owner_id(client)]
    assert owner["owner"] is True
    assert owner["access_words"] == "Owner"

    assert body["role_words"] == ROLE_WORDS
    assert [d["key"] for d in body["departments"]] == ["inbox", "operations", "affiliates", "production"]
    # Production alone offers QC (ADR 0076); the others keep their four.
    assert [level["level"] for level in body["departments"][3]["levels"]] == ["none", "viewer", "staff", "manager"]
    inbox = body["departments"][0]
    assert inbox["name"] == "Inbox"
    assert inbox["levels"] == [
        {"level": "none", "role": None, "offered": True},
        {"level": "viewer", "role": None, "offered": False},
        {"level": "staff", "role": "customer_service", "offered": True},
        {"level": "manager", "role": None, "offered": False},
    ]
    affiliates = body["departments"][2]["levels"]
    assert [(l["level"], l["role"]) for l in affiliates if l["offered"]] == [
        ("none", None),
        ("staff", "content_manager"),
        ("manager", "affiliate_manager"),
    ]


def test_an_invitation_row_says_its_access_in_words(client):
    client.post("/api/auth/invitations", json={"email": "nour@example.com", "role": "customer_service"})
    client.post("/api/auth/invitations", json={"email": "amr@example.com", "role": "operations_manager"})

    rows = {row["email"]: row for row in client.get("/api/staff").json()["invitations"]}

    assert rows["nour@example.com"]["access_words"] == "Inbox staff"
    # His invitation brings the Inbox with it, so it says so.
    assert rows["amr@example.com"]["access_words"] == "Operations manager · Inbox staff"
    assert rows["nour@example.com"]["sent_at"] == rows["nour@example.com"]["created_at"]


# ── Setting a department's level ──────────────────────────────────────────────


def test_a_new_level_is_given_before_the_old_one_is_taken(client):
    sara = _person("sara@example.com", "Sara", "content_manager")

    response = _set(client, sara, "affiliates", "manager")

    assert response.status_code == 200, response.text
    row = response.json()
    assert row["id"] == sara
    assert row["roles"] == ["affiliate_manager"]
    assert row["access"]["affiliates"] == "manager"
    assert row["access_words"] == "Affiliates manager"
    assert _live(sara) == {"affiliate_manager"}
    # Each step audited as today, giving first - so "the only access" never
    # trips on a change of level.
    assert _audit() == [
        ("staff.role_given", "affiliate_manager"),
        ("staff.role_removed", "content_manager"),
    ]


def test_choosing_a_level_takes_the_departments_other_role_away(client):
    sara = _person("sara@example.com", "Sara", "content_manager", "affiliate_manager")

    response = _set(client, sara, "affiliates", "manager")

    assert response.status_code == 200, response.text
    assert _live(sara) == {"affiliate_manager"}
    assert _audit() == [("staff.role_removed", "content_manager")]


def test_other_departments_are_left_alone(client):
    mona = _person("mona@example.com", "Mona", "customer_service", "content_manager")

    response = _set(client, mona, "affiliates", "none")

    assert response.status_code == 200, response.text
    assert _live(mona) == {"customer_service"}
    assert response.json()["access_words"] == "Inbox staff"


def test_the_same_level_writes_nothing(client):
    sara = _person("sara@example.com", "Sara", "content_manager")
    before = _assignment_count()

    response = _set(client, sara, "affiliates", "staff")
    nothing = _set(client, sara, "inbox", "none")

    assert response.status_code == 200, response.text
    assert nothing.status_code == 200, nothing.text
    assert _assignment_count() == before
    assert _audit() == []


def test_none_on_the_only_access_is_refused_in_todays_words(client):
    sara = _person("sara@example.com", "Sara", "content_manager")

    response = _set(client, sara, "affiliates", "none")

    assert response.status_code == 400
    assert response.json()["detail"] == (
        "This is the only access Sara has. Give them other access first, "
        "or suspend the account."
    )
    assert _live(sara) == {"content_manager"}
    assert _audit() == []


def test_a_level_not_offered_is_refused(client):
    sara = _person("sara@example.com", "Sara", "content_manager")

    for department, level in (("inbox", "manager"), ("inbox", "viewer"), ("operations", "staff")):
        response = _set(client, sara, department, level)
        assert response.status_code == 422, (department, level)
        assert response.json()["detail"] == "Not offered yet"
    # Not a level at all: refused by the body's own shape.
    assert _set(client, sara, "affiliates", "owner").status_code == 422
    assert _live(sara) == {"content_manager"}


def test_an_unknown_department_is_not_found(client):
    sara = _person("sara@example.com", "Sara", "content_manager")

    assert _set(client, sara, "people", "staff").status_code == 404
    assert _set(client, sara, "finance", "none").status_code == 404


def test_only_somebody_on_the_roster_is_set(client):
    model = _person("model@example.com", "Nour", "affiliate")

    assert _set(client, model, "inbox", "staff").status_code == 404
    assert _set(client, 99999, "inbox", "staff").status_code == 404
    assert _live(model) == {"affiliate"}


# ── Every existing rule still refuses through it ──────────────────────────────


def test_a_suspended_account_is_given_nothing_by_either_route(client):
    """Batch 2.4 review: access never slips back to somebody locked out.
    Reactivating comes first, and gives nothing back by itself."""
    sara = _person("sara@example.com", "Sara", "content_manager")
    assert client.post(f"/api/staff/{sara}/suspend", json={"reason": "Leaving."}).status_code == 200

    by_role = client.post(f"/api/staff/{sara}/roles", json={"role": "customer_service"})
    by_level = _set(client, sara, "inbox", "staff")

    for response in (by_role, by_level):
        assert response.status_code == 400
        assert response.json()["detail"] == "Sara is suspended. Reactivate the account first."
    assert _live(sara) == set()
    assert ("staff.role_given", "customer_service") not in _audit()

    back = client.post(f"/api/staff/{sara}/reactivate")
    assert back.status_code == 200, back.text
    assert back.json()["roles"] == []
    row = next(r for r in client.get("/api/staff").json()["staff"] if r["id"] == sara)
    assert row["access"] == {"inbox": "none", "operations": "none", "affiliates": "none", "production": "none"}
    assert row["access_words"] == "No access"
    # Given again deliberately, once reactivated.
    assert _set(client, sara, "inbox", "staff").status_code == 200
    assert _live(sara) == {"customer_service"}


def test_nobody_sets_their_own_level(client):
    _person("second.owner@example.com", "Second", "admin")
    me = _owner_id(client)

    for level in ("staff", "none"):
        response = _set(client, me, "affiliates", level)
        assert response.status_code == 400
        assert "your own access" in response.json()["detail"]
    assert _live(me) == {"admin"}


def test_there_is_one_operations_manager_at_a_time(client):
    _person("amr@example.com", "Amr", "operations_manager", "customer_service")
    sara = _person("sara@example.com", "Sara", "content_manager")

    response = _set(client, sara, "operations", "manager")

    assert response.status_code == 400
    assert response.json()["detail"].startswith("HBA already has an operations manager: Amr.")
    assert _live(sara) == {"content_manager"}


def test_a_level_never_touches_the_owner_line(client):
    """The owner's role is no department's level, so the last-owner rule can
    never be reached from here: setting an owner's departments leaves
    `admin` exactly where it is."""
    other = _person("second.owner@example.com", "Second", "admin", "content_manager")

    response = _set(client, other, "affiliates", "none")

    assert response.status_code == 200, response.text
    assert _live(other) == {"admin"}
    assert response.json()["owner"] is True
    assert response.json()["access_words"] == "Owner"


def test_a_refusal_after_the_give_takes_the_give_back(client, monkeypatch):
    """No half-changed department: the new role was given, the old one could
    not be taken, and the person ends exactly as they began."""
    from app.shared.services import staff

    def refuse(*args, **kwargs):
        raise ValueError("Refused for the test.")

    monkeypatch.setattr(staff, "remove_role", refuse)
    sara = _person("sara@example.com", "Sara", "content_manager")
    before = _assignment_count()

    response = _set(client, sara, "affiliates", "manager")

    assert response.status_code == 400
    assert response.json()["detail"] == "Refused for the test."
    assert _live(sara) == {"content_manager"}
    assert _assignment_count() == before
    assert _audit() == []


def test_can_grant_still_refuses_and_rolls_the_department_back(db):
    """Over HTTP only the owner may set a level, and the owner holds every
    permission, so `can_grant` is pinned below the route: somebody holding
    the affiliates staff role may give it, may not take the manager's - and
    the give is undone with the refusal."""
    from app.shared.models.identity import RoleAssignment, UserAccount
    from app.shared.services.access import live_roles
    from app.shared.services.staff import set_level

    boda = UserAccount(email="boda@example.com", password_hash="x", status="active")
    db.add(boda)
    db.flush()
    db.add(RoleAssignment(user_account_id=boda.id, role="affiliate_manager"))
    db.flush()
    sara_roles = frozenset({"content_manager"})

    with pytest.raises(ValueError, match="access you hold yourself"):
        set_level(db, boda, "affiliates", "staff", actor_roles=sara_roles, actor_id=None, actor_email=None)
    assert live_roles(db, boda.id) == {"affiliate_manager"}

    with pytest.raises(ValueError, match="access you hold yourself"):
        set_level(db, boda, "inbox", "staff", actor_roles=sara_roles, actor_id=None, actor_email=None)
    assert live_roles(db, boda.id) == {"affiliate_manager"}
    assert GRANT_REFUSED == "You can only give people access you hold yourself."

    # And what the actor does hold, all their roles together, goes through.
    both = frozenset({"affiliate_manager"})
    assert set_level(db, boda, "affiliates", "staff", actor_roles=both, actor_id=None, actor_email=None)
    assert live_roles(db, boda.id) == {"content_manager"}


# ── Two changes at once queue on the person (Batch 2.4 review) ────────────────


def _at_the_same_time(first, second) -> list:
    """Run `first` in one transaction and, while it is still open, `second`
    in another on its own thread. Proves the second waited (it is still
    running after half a second), then commits the first and lets the second
    finish. Returns what the second raised, or None."""
    import threading
    import time

    from sqlalchemy import text as sql

    from app.db import SessionLocal

    raised: list = []

    def run_second():
        with SessionLocal() as db:
            db.execute(sql("SET LOCAL lock_timeout = '10s'"))
            try:
                second(db)
                db.commit()
                raised.append(None)
            except ValueError as exc:
                db.rollback()
                raised.append(exc)

    with SessionLocal() as db:
        first(db)
        thread = threading.Thread(target=run_second)
        thread.start()
        time.sleep(0.5)
        assert thread.is_alive(), "the second change did not wait for the first"
        db.commit()
    thread.join(timeout=15)
    assert not thread.is_alive()
    return raised


def _account(db, user_id):
    from app.shared.models.identity import UserAccount

    return db.get(UserAccount, user_id)


ADMIN = frozenset({"admin"})


def test_two_removals_at_once_never_leave_nobody_anything(fresh_database):
    from app.shared.services.staff import remove_role

    sara = _person("sara@example.com", "Sara", "content_manager", "customer_service")

    raised = _at_the_same_time(
        lambda db: remove_role(db, _account(db, sara), "content_manager",
                               actor_roles=ADMIN, actor_id=None, actor_email=None),
        lambda db: remove_role(db, _account(db, sara), "customer_service",
                               actor_roles=ADMIN, actor_id=None, actor_email=None),
    )

    assert len(raised) == 1 and "only access Sara has" in str(raised[0])
    assert _live(sara) == {"customer_service"}


def test_two_level_changes_at_once_never_leave_both_affiliates_roles(fresh_database):
    from app.shared.services.staff import set_level

    mona = _person("mona@example.com", "Mona", "customer_service")

    raised = _at_the_same_time(
        lambda db: set_level(db, _account(db, mona), "affiliates", "manager",
                             actor_roles=ADMIN, actor_id=None, actor_email=None),
        lambda db: set_level(db, _account(db, mona), "affiliates", "staff",
                             actor_roles=ADMIN, actor_id=None, actor_email=None),
    )

    assert raised == [None]
    # The second read what the first left, and replaced it.
    assert _live(mona) == {"customer_service", "content_manager"}


# ── An invitation by level grants what it does by role ───────────────────────


@pytest.mark.parametrize(
    ("department", "level", "access"),
    [
        ("inbox", "staff", {"inbox": "staff", "operations": "none", "affiliates": "none", "production": "none"}),
        ("affiliates", "staff", {"inbox": "none", "operations": "none", "affiliates": "staff", "production": "none"}),
        ("affiliates", "manager", {"inbox": "none", "operations": "none", "affiliates": "manager", "production": "none"}),
        # His invitation brings the Inbox, by level exactly as by role.
        ("operations", "manager", {"inbox": "staff", "operations": "manager", "affiliates": "none", "production": "none"}),
    ],
)
def test_an_invitation_by_level_grants_the_same_as_by_role(client, department, level, access):
    role = role_for_level(department, level)
    invite = client.post("/api/auth/invitations", json={"email": "new@example.com", "role": role})
    assert invite.status_code == 201, invite.text

    with TestClient(app) as other:
        accept = other.post(
            "/api/auth/invitations/accept",
            json={"token": invite.json()["token"], "display_name": "New", "password": PASSWORD},
        )
        assert accept.status_code == 201, accept.text

    row = next(r for r in client.get("/api/staff").json()["staff"] if r["email"] == "new@example.com")
    assert row["access"] == access
    assert level_in(department, row["roles"]) == level


# ── The two-step reminder ─────────────────────────────────────────────────────


def _outbox(event: str) -> list[dict]:
    with engine.connect() as connection:
        return [
            {"to": row.recipient_email, **row.payload}
            for row in connection.execute(
                text("SELECT recipient_email, payload FROM notification_outbox WHERE event = :e ORDER BY id"),
                {"e": event},
            )
        ]


def test_a_reminder_is_emailed_and_audited(client):
    from app.config import settings
    from app.shared.services.notifications import Event

    mona = _person("mona@example.com", "Mona", "customer_service")

    response = client.post(f"/api/staff/{mona}/two-step/remind")

    assert response.status_code == 201, response.text
    assert response.json() == {"emailed": settings.mail_configured}
    assert Event.TWO_STEP_REMINDER == "two_step.reminder"
    assert _outbox(Event.TWO_STEP_REMINDER) == [
        {"to": "mona@example.com", "email": "mona@example.com", "name": "Mona", "required": False}
    ]
    assert _audit("staff.two_step") == [("staff.two_step_reminded", None)]


def test_one_reminder_a_day(client):
    mona = _person("mona@example.com", "Mona", "customer_service")
    assert client.post(f"/api/staff/{mona}/two-step/remind").status_code == 201

    again = client.post(f"/api/staff/{mona}/two-step/remind")

    assert again.status_code == 429
    assert again.json()["detail"].startswith("A reminder was sent at ")
    assert int(again.headers["Retry-After"]) > 0
    assert len(_outbox("two_step.reminder")) == 1

    # A day later, another may go. The trail is append-only, so its guard is
    # stood down for this one transaction to move the entry back in time.
    with engine.begin() as connection:
        connection.execute(text("SET LOCAL session_replication_role = replica"))
        connection.execute(
            text(
                "UPDATE audit_event SET created_at = now() - interval '25 hours' "
                "WHERE action = 'staff.two_step_reminded'"
            )
        )
    assert client.post(f"/api/staff/{mona}/two-step/remind").status_code == 201


def test_no_reminder_when_it_is_already_on(client):
    mona = _person("mona@example.com", "Mona", "customer_service")
    with engine.begin() as connection:
        connection.execute(
            text("UPDATE user_account SET two_step_email_at = now() WHERE id = :u"), {"u": mona}
        )

    response = client.post(f"/api/staff/{mona}/two-step/remind")

    assert response.status_code == 409
    assert response.json()["detail"] == "Two-step sign-in is already on for Mona."
    assert _outbox("two_step.reminder") == []


def test_never_a_reminder_to_yourself(client):
    response = client.post(f"/api/staff/{_owner_id(client)}/two-step/remind")

    assert response.status_code == 400
    assert _outbox("two_step.reminder") == []


def test_no_reminder_to_a_suspended_account_or_a_model(client):
    mona = _person("mona@example.com", "Mona", "customer_service")
    _person("spare@example.com", "Spare", "content_manager")
    client.post(f"/api/staff/{mona}/suspend", json={"reason": "Left."})
    model = _person("model@example.com", "Nour", "affiliate")

    assert client.post(f"/api/staff/{mona}/two-step/remind").status_code == 409
    assert client.post(f"/api/staff/{model}/two-step/remind").status_code == 404
    assert _outbox("two_step.reminder") == []


def test_the_screen_and_the_email_agree_on_required(client, monkeypatch):
    """`two_step_required` on the roster and `required` in the email are one
    answer (`two_step.required_now`), the owner's switch included."""
    from app.config import settings
    from app.shared.api import deps

    second = _person("second.owner@example.com", "Second", "admin")
    mona = _person("mona@example.com", "Mona", "customer_service")

    rows = {r["id"]: r for r in client.get("/api/staff").json()["staff"]}
    assert rows[second]["two_step_required"] is False  # the switch is off

    monkeypatch.setattr(settings, "two_step_enforced", True, raising=False)
    # Nobody here has the app set up; the gate would hold the owner at set-up.
    monkeypatch.setattr(deps, "must_set_up", lambda db, user: False)
    rows = {r["id"]: r for r in client.get("/api/staff").json()["staff"]}
    assert rows[second]["two_step_required"] is True
    assert rows[second]["two_step_enabled"] is False
    assert rows[mona]["two_step_required"] is False

    for person in (second, mona):
        assert client.post(f"/api/staff/{person}/two-step/remind").status_code == 201
    said = {row["to"]: row["required"] for row in _outbox("two_step.reminder")}
    assert said == {
        "second.owner@example.com": rows[second]["two_step_required"],
        "mona@example.com": rows[mona]["two_step_required"],
    }


def test_the_reminder_says_what_it_is_and_where_to_turn_it_on():
    from app.shared.services.notifications import Event, render

    optional = render(Event.TWO_STEP_REMINDER, {"email": "m@example.com", "name": "Mona Adel", "required": False})
    needed = render(Event.TWO_STEP_REMINDER, {"email": "m@example.com", "name": "Mona Adel", "required": True})
    nameless = render(Event.TWO_STEP_REMINDER, {"email": "m@example.com", "name": "", "required": False})

    assert optional.body.startswith("Hi Mona,")
    assert "does not require it" in optional.body
    assert "requires it" in needed.body and "does not require" not in needed.body
    for message in (optional, needed):
        assert "Settings → Me" in message.body
        assert "http" not in message.body
    # Never a bare "Hi,".
    assert nameless.body.startswith("Hello,")


# ── Nobody but the owner ──────────────────────────────────────────────────────


def test_non_owners_are_refused_every_new_route(client):
    sara = _person("sara@example.com", "Sara", "content_manager")
    with engine.begin() as connection:
        connection.execute(
            text("UPDATE role_assignment SET role = 'affiliate_manager' WHERE role = 'admin'")
        )

    assert _set(client, sara, "affiliates", "manager").status_code == 403
    assert client.post(f"/api/staff/{sara}/two-step/remind").status_code == 403
    assert client.get("/api/staff").status_code == 403
    assert _live(sara) == {"content_manager"}
    assert _outbox("two_step.reminder") == []


# ── The frontend's fixture is the server's own answer ────────────────────────

FIXTURE = Path(__file__).resolve().parents[1] / "frontend" / "src" / "screens" / "__tests__" / "teamFixture.ts"


def _ts_block(source: str, name: str) -> str:
    """The text of `export const NAME ... = {...};` or `= [...];`."""
    found = re.search(rf"export const {name}\b[^=]*=\s*([\[{{].*?)\n[\]}}];", source, re.S)
    assert found, f"{name} not found in {FIXTURE.name}"
    return found.group(1)


def _strings(text: str) -> list[str]:
    return re.findall(r'"([^"]*)"', text)


def test_the_screens_fixture_matches_what_the_server_says():
    """Batch 2.4 review: the frontend's tests read a copy of the roster
    (`teamFixture.ts`). Read back here, so a role's permissions, a word or a
    level changed on the server fails a test rather than drifting."""
    from app.shared.api.staff import _departments, _role_permissions

    source = FIXTURE.read_text(encoding="utf-8")
    everything = _strings(_ts_block(source, "ALL"))

    permissions: dict[str, list[str]] = {}
    for role, value in re.findall(r"(\w+):\s*(ALL|\[[^\]]*\])", _ts_block(source, "ROLE_PERMISSIONS")):
        permissions[role] = everything if value == "ALL" else _strings(value)
    assert {role: sorted(p) for role, p in permissions.items()} == _role_permissions()

    words = dict(re.findall(r'(\w+):\s*"([^"]*)"', _ts_block(source, "ROLE_WORDS")))
    assert words == ROLE_WORDS

    departments = []
    for key, name, levels in re.findall(
        r'\{\s*key:\s*"(\w+)",\s*name:\s*"([^"]*)",\s*levels:\s*\[(.*?)\]\s*\}',
        _ts_block(source, "DEPARTMENTS"),
        re.S,
    ):
        departments.append({
            "key": key,
            "name": name,
            "levels": [
                {"level": level, "role": None if role == "null" else role.strip('"'), "offered": offered == "true"}
                for level, role, offered in re.findall(
                    r'level\("(\w+)",\s*(null|"\w+"),\s*(true|false)\)', levels
                )
            ],
        })
    assert departments == _departments()
