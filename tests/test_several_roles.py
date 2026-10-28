"""Several roles per person (ADR 0067), and that nobody's access moved.

What a person may do is everything their live roles grant together. The
operations manager's Inbox stopped being part of his role and became a second
assignment (migration c3e7a1f90019). The proof that this changed nobody's
access is here, three ways:

- the roles as the code defined them before (`ROLES_BEFORE`, written out, not
  imported, so it cannot follow the code) against what each person holds
  after the migration, permission by permission;
- every route the platform serves, asked the same question before and after;
- a person of every kind, signed in after the migration, refused exactly
  where they were refused before.
"""

from collections.abc import Iterator

import pytest
from alembic import command
from alembic.config import Config
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as OrmSession

from app.shared.api.deps import permissions_of, roles_of
from app.core.businesstime import utcnow
from app.core.passwords import hash_password
from app.core.permissions import (
    ALL_PERMISSIONS,
    ROLES,
    Permission,
    can_grant,
    is_staff,
    permissions_of_roles,
)
from app.db import engine
from app.main import app
from app.shared.models.identity import RoleAssignment, UserAccount
from app.shared.services.audit import DEPARTMENTS, PLATFORM_WIDE, department_of, record_audit

#: The revision before several roles. Downgrading to it is the old schema.
BEFORE_REVISION = "a6c9e3f70018"
PASSWORD = "quiet-harbour-lantern"

P = Permission
#: Every role as `app/core/permissions.py` defined it on 25 October 2026,
#: before ADR 0067. Copied out on purpose: imported, it would change with the
#: code and prove nothing.
ROLES_BEFORE: dict[str, frozenset[str]] = {
    "admin": frozenset(ALL_PERMISSIONS),
    "affiliate_manager": frozenset(
        {
            P.AFFILIATES_VIEW, P.AFFILIATES_MANAGE, P.COMPENSATION_MANAGE,
            P.TARGETS_MANAGE, P.TARGETS_VERIFY, P.TARGETS_RECORD,
            P.PAYROLL_APPROVE, P.INVITATIONS_SEND, P.AUDIT_VIEW,
        }
    ),
    "content_manager": frozenset(
        {
            P.AFFILIATES_VIEW, P.AFFILIATES_MANAGE, P.COMPENSATION_MANAGE,
            P.TARGETS_RECORD, P.TARGETS_MANAGE, P.TARGETS_VERIFY, P.AUDIT_VIEW,
        }
    ),
    "operations_manager": frozenset({P.ORDER_OPS_VIEW, P.INBOX_USE}),
    "customer_service": frozenset({P.INBOX_USE}),
    "affiliate": frozenset(),
}


def test_the_snapshot_covers_every_role_there_is():
    """A role added later needs its own before-and-after; this says so."""
    assert set(ROLES_BEFORE) == set(ROLES)
    # Only the operations manager's role changed shape, and only by the Inbox.
    for role, granted in ROLES_BEFORE.items():
        if role == "operations_manager":
            assert ROLES[role] == granted - {P.INBOX_USE}
        else:
            assert ROLES[role] == granted, role


# ── The union ─────────────────────────────────────────────────────────────────


def _person(db, email: str, *roles: str) -> UserAccount:
    user = UserAccount(email=email, password_hash="x", status="active", display_name=email)
    db.add(user)
    db.flush()
    for role in roles:
        db.add(RoleAssignment(user_account_id=user.id, role=role))
    db.flush()
    return user


def test_two_roles_grant_everything_each_grants_and_nothing_more(db):
    nour = _person(db, "nour@example.com", "content_manager", "customer_service")

    assert roles_of(db, nour) == {"content_manager", "customer_service"}
    assert permissions_of(db, nour) == ROLES["content_manager"] | ROLES["customer_service"]
    assert P.INBOX_USE in permissions_of(db, nour)
    assert P.PAYROLL_APPROVE not in permissions_of(db, nour)
    assert P.ORDER_OPS_VIEW not in permissions_of(db, nour)


def test_a_revoked_role_grants_nothing(db):
    nour = _person(db, "nour@example.com", "content_manager", "customer_service")
    inbox = db.query(RoleAssignment).filter_by(
        user_account_id=nour.id, role="customer_service"
    ).one()
    inbox.revoked_at = utcnow()
    db.flush()
    assert roles_of(db, nour) == {"content_manager"}
    assert P.INBOX_USE not in permissions_of(db, nour)


def test_an_account_with_no_live_role_holds_nothing_and_is_not_staff(db):
    nobody = _person(db, "nobody@example.com")
    assert roles_of(db, nobody) == frozenset()
    assert permissions_of(db, nobody) == frozenset()
    assert not is_staff(roles_of(db, nobody))


def test_a_model_role_never_makes_somebody_staff():
    assert not is_staff({"affiliate"})
    assert is_staff({"affiliate", "customer_service"})
    assert is_staff({"customer_service"})


def test_a_bare_role_name_is_one_role_not_its_letters():
    assert permissions_of_roles("admin") == ALL_PERMISSIONS
    assert can_grant("admin", "content_manager")


def test_a_misspelt_permission_still_raises_for_several_roles():
    from app.core.permissions import has_permission

    with pytest.raises(ValueError):
        has_permission({"admin", "content_manager"}, "payroll.aprove")


# ── can_grant against several roles ───────────────────────────────────────────


def test_can_grant_reads_the_actors_roles_together():
    # Neither role alone holds what an operations manager *person* holds...
    assert not can_grant({"customer_service"}, "operations_manager")
    assert not can_grant({"affiliate_manager"}, "customer_service")
    # ...and two roles together may give what each covers.
    assert can_grant({"affiliate_manager", "customer_service"}, "customer_service")
    assert can_grant({"affiliate_manager", "customer_service"}, "content_manager")
    # Never a role whose grants are spread beyond the union.
    assert not can_grant({"affiliate_manager", "customer_service"}, "admin")
    assert not can_grant({"affiliate_manager", "customer_service"}, "operations_manager")
    assert not can_grant(frozenset(), "customer_service")
    assert can_grant(frozenset(), "affiliate")
    assert not can_grant({"admin"}, "wizard")


# ── The database ──────────────────────────────────────────────────────────────


def test_the_database_refuses_the_same_role_twice_at_once(db):
    nour = _person(db, "nour@example.com", "customer_service")
    db.add(RoleAssignment(user_account_id=nour.id, role="customer_service"))
    with pytest.raises(IntegrityError):
        db.flush()


def test_a_revoked_role_can_be_given_again(db):
    nour = _person(db, "nour@example.com", "customer_service")
    old = db.query(RoleAssignment).filter_by(user_account_id=nour.id).one()
    old.revoked_at = utcnow()
    db.flush()
    db.add(RoleAssignment(user_account_id=nour.id, role="customer_service"))
    db.flush()
    assert roles_of(db, nour) == {"customer_service"}


def test_the_service_refuses_the_same_role_twice_with_the_reason(db):
    from app.shared.services.staff import give_role

    nour = _person(db, "nour@example.com", "customer_service")
    with pytest.raises(ValueError, match="already holds"):
        give_role(
            db, nour, "customer_service",
            actor_roles=frozenset({"admin"}), actor_id=None, actor_email=None,
        )


def test_giving_and_taking_are_audited_with_every_role_before_and_after(db):
    from app.shared.models.audit import AuditEvent
    from app.shared.services.staff import give_role, remove_role

    nour = _person(db, "nour@example.com", "content_manager")
    admin = frozenset({"admin"})
    give_role(db, nour, "customer_service", actor_roles=admin, actor_id=None, actor_email=None)
    remove_role(db, nour, "content_manager", actor_roles=admin, actor_id=None, actor_email=None)
    db.flush()

    events = db.query(AuditEvent).filter_by(subject=f"user:{nour.id}").order_by(AuditEvent.id).all()
    assert [(e.action, e.before_json, e.after_json) for e in events] == [
        (
            "staff.role_given",
            {"roles": ["content_manager"]},
            {"role": "customer_service", "roles": ["content_manager", "customer_service"]},
        ),
        (
            "staff.role_removed",
            {"roles": ["content_manager", "customer_service"]},
            {"role": "content_manager", "roles": ["customer_service"]},
        ),
    ]
    # Access is platform-wide: no department.
    assert {e.department for e in events} == {None}


def test_the_last_admin_cannot_lose_admin_even_holding_another_role(db):
    from app.shared.services.staff import remove_role

    owner = _person(db, "owner@example.com", "admin", "customer_service")
    with pytest.raises(ValueError, match="only active admin"):
        remove_role(
            db, owner, "admin",
            actor_roles=frozenset({"admin"}), actor_id=None, actor_email=None,
        )


def test_nobody_gives_themselves_a_role(db):
    from app.shared.services.staff import give_role

    owner = _person(db, "owner@example.com", "admin")
    with pytest.raises(ValueError, match="your own access"):
        give_role(
            db, owner, "customer_service",
            actor_roles=frozenset({"admin"}), actor_id=owner.id, actor_email=owner.email,
        )


# ── The department of an audit entry ─────────────────────────────────────────


def test_an_entry_takes_its_department_from_its_action(db):
    cases = {
        "inbox.answer_set": "inbox",
        "order_ops.key_saved": "operations",
        "payroll.approved": "affiliates",
        "payment.recorded": "affiliates",
        "target.verified": "affiliates",
        "affiliate.created": "affiliates",
        "adjustment.bonus": "affiliates",
        "auth.login": None,
        "staff.role_given": None,
        "invitation.create": None,
    }
    for action, department in cases.items():
        assert department_of(action) == department, action
        event = record_audit(db, action=action, subject="probe:1")
        db.flush()
        assert event.department == department


def test_every_action_the_platform_records_has_a_place():
    """A new kind of entry must be put in a department, or named as the
    platform's own - never left out by accident."""
    import pathlib
    import re

    prefixes = set()
    for path in pathlib.Path("app").rglob("*.py"):
        for found in re.findall(r'action=f?"([a-z_]+)\.', path.read_text(encoding="utf-8")):
            prefixes.add(found + ".")
    known = {p for group in DEPARTMENTS.values() for p in group} | set(PLATFORM_WIDE)
    assert prefixes, "the walk found no actions at all"
    assert prefixes <= known, f"actions with no department: {sorted(prefixes - known)}"


# ── The migration, up and down, and every route before and after ──────────────

#: One person of every kind there was. The operations manager is the one whose
#: access is moved; everyone else must come through untouched.
PEOPLE = {
    "owner@example.com": "admin",
    "boda@example.com": "affiliate_manager",
    "sara@example.com": "content_manager",
    "amr@example.com": "operations_manager",
    "mona@example.com": "customer_service",
    "model@example.com": "affiliate",
}


def _config() -> Config:
    return Config("alembic.ini")


def _version() -> str:
    with engine.connect() as connection:
        return connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()


def _live(connection) -> dict[str, list[tuple[str, int | None]]]:
    rows = connection.execute(
        text(
            "SELECT u.email, r.role, r.granted_by FROM role_assignment r "
            "JOIN user_account u ON u.id = r.user_account_id "
            "WHERE r.revoked_at IS NULL ORDER BY u.email, r.id"
        )
    ).all()
    found: dict[str, list[tuple[str, int | None]]] = {}
    for email, role, granted_by in rows:
        found.setdefault(email, []).append((role, granted_by))
    return found


def _newest_live_role(connection, email: str) -> str:
    """How the code before ADR 0067 read a person's access: the newest live
    assignment, or the model's role when there was none."""
    role = connection.execute(
        text(
            "SELECT r.role FROM role_assignment r JOIN user_account u "
            "ON u.id = r.user_account_id WHERE u.email = :e AND r.revoked_at IS NULL "
            "ORDER BY r.id DESC LIMIT 1"
        ),
        {"e": email},
    ).scalar()
    return role or "affiliate"


def _seed_old_schema() -> None:
    with engine.begin() as connection:
        for email, role in PEOPLE.items():
            user_id = connection.execute(
                text(
                    "INSERT INTO user_account (email, password_hash, status, display_name) "
                    "VALUES (:e, :p, 'active', :e) RETURNING id"
                ),
                {"e": email, "p": hash_password(PASSWORD)},
            ).scalar_one()
            connection.execute(
                text("INSERT INTO role_assignment (user_account_id, role, granted_by) VALUES (:u, :r, NULL)"),
                {"u": user_id, "r": role},
            )


def _walk(routes) -> Iterator[APIRoute]:
    for route in routes:
        if isinstance(route, APIRoute):
            yield route
        elif hasattr(route, "original_router"):
            yield from _walk(route.original_router.routes)


def _gates(dependant, found: set[str]) -> set[str]:
    """Every permission a route asks for, and which person-gates it uses."""
    call = dependant.call
    if call is not None:
        permission = getattr(call, "permission", None)
        if permission:
            found.add(permission)
        name = getattr(call, "__name__", "")
        if name in ("require_staff", "current_affiliate", "_applicant"):
            found.add(f"<{name}>")
    for child in dependant.dependencies:
        _gates(child, found)
    return found


def _allowed(gates: set[str], permissions: frozenset[str], staff: bool, model: bool) -> bool:
    for gate in gates:
        if gate == "<require_staff>" and not staff:
            return False
        if gate == "<_applicant>" and staff:
            return False
        if gate == "<current_affiliate>" and not model:
            return False
        if not gate.startswith("<") and gate not in permissions:
            return False
    return True


@pytest.fixture()
def old_schema(fresh_database):
    """The database as it was before several roles, holding one person of
    every kind. Put back to head whatever happens, so no later test meets a
    half-migrated schema."""
    from tests.conftest import empty_the_database

    command.downgrade(_config(), BEFORE_REVISION)
    try:
        _seed_old_schema()
        yield
    finally:
        if _version() != BEFORE_REVISION:
            command.downgrade(_config(), BEFORE_REVISION)
        empty_the_database()
        command.upgrade(_config(), "head")
        assert _version() != BEFORE_REVISION


def test_the_migration_moves_the_inbox_and_changes_nobodys_access(old_schema):
    with engine.connect() as connection:
        before = {email: _newest_live_role(connection, email) for email in PEOPLE}
    assert before == PEOPLE

    command.upgrade(_config(), "head")

    with engine.connect() as connection:
        live = _live(connection)
    # Only the operations manager gained an assignment, and nobody granted it.
    assert live["amr@example.com"] == [("operations_manager", None), ("customer_service", None)]
    for email, role in PEOPLE.items():
        if email != "amr@example.com":
            assert live[email] == [(role, None)], email

    # Every person may do exactly what they could before, permission by
    # permission, and is staff exactly when they were.
    with OrmSession(engine) as db:
        accounts = {u.email: u for u in db.query(UserAccount)}
        after_roles = {email: roles_of(db, accounts[email]) for email in PEOPLE}
        after = {email: permissions_of(db, accounts[email]) for email in PEOPLE}
    for email, role in PEOPLE.items():
        assert after[email] == ROLES_BEFORE[role], email
        assert is_staff(after_roles[email]) == (role != "affiliate"), email

    # Every route the platform serves gives each of them the same answer.
    routes = [(route, _gates(route.dependant, set())) for route in _walk(app.routes)]
    assert len(routes) > 100, "the walk missed the routers"
    assert any(gates - {"<require_staff>", "<current_affiliate>", "<_applicant>"} for _, gates in routes)
    for email, role in PEOPLE.items():
        for model in (False, True):
            for route, gates in routes:
                was = _allowed(gates, ROLES_BEFORE[role], role != "affiliate", model)
                now = _allowed(gates, after[email], is_staff(after_roles[email]), model)
                assert was == now, (email, model, route.methods, route.path)

    # And over HTTP, signed in as each of them.
    _probe_over_http()

    # Down again: exactly the assignment the upgrade made is gone.
    command.downgrade(_config(), BEFORE_REVISION)
    with engine.connect() as connection:
        live = _live(connection)
        assert {email: _newest_live_role(connection, email) for email in PEOPLE} == PEOPLE
        columns = connection.execute(
            text(
                "SELECT count(*) FROM information_schema.columns "
                "WHERE table_name = 'audit_event' AND column_name = 'department'"
            )
        ).scalar_one()
    for email, role in PEOPLE.items():
        assert live[email] == [(role, None)], email
    assert columns == 0


#: One address behind each kind of gate the platform has. Each only reads.
PROBES = {
    "/api/auth/me": set(),
    "/api/staff/me/preferences": {"<require_staff>"},
    "/api/applications/mine": {"<_applicant>"},
    "/api/me": {"<current_affiliate>"},
    "/api/operations/counts": {P.AFFILIATES_VIEW},
    "/api/affiliates": {P.AFFILIATES_VIEW},
    "/api/audit": {P.AUDIT_VIEW},
    "/api/staff": {P.SETTINGS_MANAGE},
    "/api/staff/invitations": {P.INVITATIONS_SEND},
    "/api/payroll/historical/review": {P.PAYROLL_APPROVE},
    "/api/order-ops/shopify": {P.ORDER_OPS_VIEW},
    "/api/inbox/conversations": {P.INBOX_USE},
    "/api/inbox/connection": {P.INBOX_USE, P.SETTINGS_MANAGE},
}


def _probe_over_http() -> None:
    with TestClient(app, raise_server_exceptions=False) as client:
        for email, role in PEOPLE.items():
            client.cookies.clear()
            signed_in = client.post("/api/auth/login", json={"email": email, "password": PASSWORD})
            assert signed_in.status_code == 200, (email, signed_in.text)
            headers = {"X-CSRF-Token": signed_in.json()["csrf"]}
            me = client.get("/api/auth/me", headers=headers).json()
            assert sorted(me["permissions"]) == sorted(ROLES_BEFORE[role]), email
            assert me["actor"]["is_staff"] == (role != "affiliate"), email
            assert me["actor"]["is_model"] is False, email
            for path, gates in PROBES.items():
                expected = _allowed(gates, ROLES_BEFORE[role], role != "affiliate", False)
                status = client.get(path, headers=headers).status_code
                assert (status != 403) == expected, (email, path, status)
                assert status != 500, (email, path)


def test_the_upgrade_is_refused_while_somebody_holds_two_live_roles(old_schema):
    """Before, only the newest counted; reading both together would widen
    that person's access without anybody deciding it."""
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO role_assignment (user_account_id, role) "
                "SELECT id, 'customer_service' FROM user_account WHERE email = 'sara@example.com'"
            )
        )
    with pytest.raises(Exception, match="more than one live role"):
        command.upgrade(_config(), "head")
    assert _version() == BEFORE_REVISION
    with engine.connect() as connection:
        assert "customer_service" not in [r for r, _ in _live(connection)["amr@example.com"]]


def test_the_downgrade_is_refused_while_somebody_holds_two_live_roles(old_schema):
    """After it, the old code would read only the newest of them."""
    command.upgrade(_config(), "head")
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO role_assignment (user_account_id, role) "
                "SELECT id, 'customer_service' FROM user_account WHERE email = 'sara@example.com'"
            )
        )
    with pytest.raises(Exception, match="more than one live role"):
        command.downgrade(_config(), BEFORE_REVISION)
    assert _version() != BEFORE_REVISION
    # The refused downgrade took nothing with it.
    with engine.connect() as connection:
        assert [r for r, _ in _live(connection)["amr@example.com"]] == [
            "operations_manager",
            "customer_service",
        ]
    with engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE role_assignment SET revoked_at = now() WHERE role = 'customer_service' "
                "AND user_account_id = (SELECT id FROM user_account WHERE email = 'sara@example.com')"
            )
        )


def test_an_invitation_is_held_to_every_role_it_brings():
    """An operations manager's invitation brings the Inbox, so inviting one
    needs both to be the inviter's to give."""
    from app.core.permissions import can_invite

    assert can_invite({"admin"}, "operations_manager")
    assert not can_invite({"operations_manager"}, "operations_manager")
    assert can_invite({"operations_manager", "customer_service"}, "operations_manager")
    assert can_invite({"affiliate_manager"}, "content_manager")
    assert not can_invite({"affiliate_manager"}, "customer_service")
