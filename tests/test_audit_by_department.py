"""The activity log by department (Phase 2, batch 2.3; contract §4).

The owner reads everything. Anybody else with `audit.view` reads only the
entries of the departments they hold, held as Today decides it, and never an
entry with no department; `department=` narrows to one of theirs and is
refused outside them; the filters' people are only those in entries they may
read. Every name and address here is made up.
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.core.passwords import hash_password
from app.core.permissions import DEPARTMENT_HELD_BY
from app.db import engine
from app.main import app
from app.shared.services.audit import DEPARTMENTS

PASSWORD = "quiet-harbour-lantern"


@pytest.fixture()
def owner(fresh_database):
    with TestClient(app) as client:
        response = client.post(
            "/api/auth/bootstrap",
            json={"email": "owner@example.com", "display_name": "Owner", "password": PASSWORD},
        )
        assert response.status_code == 201, response.text
        client.headers["X-CSRF-Token"] = response.json()["csrf"]
        yield client


def _account(email: str, *roles: str) -> int:
    with engine.begin() as connection:
        account = connection.execute(
            text(
                "INSERT INTO user_account (email, password_hash, status, display_name) "
                "VALUES (:e, :p, 'active', :e) RETURNING id"
            ),
            {"e": email, "p": hash_password(PASSWORD)},
        ).scalar_one()
        for role in roles:
            connection.execute(
                text("INSERT INTO role_assignment (user_account_id, role) VALUES (:u, :r)"),
                {"u": account, "r": role},
            )
    return account


def _signed_in(email: str) -> TestClient:
    client = TestClient(app)
    response = client.post("/api/auth/login", json={"email": email, "password": PASSWORD})
    assert response.status_code == 200, response.text
    client.headers["X-CSRF-Token"] = response.json()["csrf"]
    return client


def _as(*roles: str, email: str = "reader@example.com") -> TestClient:
    _account(email, *roles)
    return _signed_in(email)


def _event(action: str, department: str | None, *, actor: int | None = None, subject="x:1") -> None:
    """Written straight in, with the department named, as `record_audit` would."""
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO audit_event (action, subject, department, actor_id) "
                "VALUES (:a, :s, :d, :u)"
            ),
            {"a": action, "s": subject, "d": department, "u": actor},
        )


def _seed() -> dict[str, int]:
    """One entry in each department and two of the platform's own, each by
    a different person."""
    people = {
        name: _account(f"{name}@example.com")
        for name in ("amr", "layla", "boda", "hana", "omar")
    }
    _event("order_ops.key_saved", "operations", actor=people["amr"], subject="ops:1")
    _event("inbox.answer_set", "inbox", actor=people["layla"], subject="inbox:1")
    _event("payment.recorded", "affiliates", actor=people["boda"], subject="affiliate:1")
    _event("staff.role_given", None, actor=people["hana"], subject="user:9")
    _event("shopify.connection_saved", None, actor=people["omar"], subject="shopify:1")
    return people


def _actions(client, query: str = "") -> list[str]:
    response = client.get(f"/api/audit?limit=200{query}")
    assert response.status_code == 200, response.text
    return [row["action"] for row in response.json()["events"]]


def _people(client) -> list[str]:
    response = client.get("/api/audit/filters")
    assert response.status_code == 200, response.text
    return [person["name"] for person in response.json()["people"]]


SEEDED = {
    "order_ops.key_saved",
    "inbox.answer_set",
    "payment.recorded",
    "staff.role_given",
    "shopify.connection_saved",
}


def test_one_table_names_the_departments_for_today_and_the_log():
    """Who holds a department and which department an entry belongs to name
    the same three, so the log and Today can never disagree."""
    assert set(DEPARTMENT_HELD_BY) == set(DEPARTMENTS)


def test_the_owner_reads_everything_with_no_department_included(owner):
    _seed()

    actions = set(_actions(owner))
    assert SEEDED <= actions
    # Setting the platform up has no department and is still the owner's.
    assert "auth.bootstrap" in actions


@pytest.mark.parametrize("role", ["affiliate_manager", "content_manager"])
def test_an_affiliates_reader_sees_only_affiliates_entries(owner, role):
    _seed()
    reader = _as(role)

    assert _actions(reader) == ["payment.recorded"]
    # Sign-ins have no department: asking for them changes nothing.
    assert _actions(reader, "&include_sign_ins=true") == ["payment.recorded"]


def test_somebody_holding_affiliates_and_the_inbox_reads_both(owner):
    _seed()
    reader = _as("affiliate_manager", "customer_service")

    assert set(_actions(reader)) == {"payment.recorded", "inbox.answer_set"}


@pytest.mark.parametrize("role", ["operations_manager", "customer_service"])
def test_without_audit_view_the_log_is_refused(owner, role):
    reader = _as(role)

    assert reader.get("/api/audit").status_code == 403
    assert reader.get("/api/audit/filters").status_code == 403


def test_entries_no_department_claims_are_never_a_non_owners(owner):
    """Sign-ins, staff access and connections: the platform's own."""
    people = _seed()
    _event("auth.login", None, actor=people["boda"], subject="user:2")
    reader = _as("affiliate_manager")

    events = reader.get("/api/audit?limit=200&include_sign_ins=true").json()["events"]

    assert [row["action"] for row in events] == ["payment.recorded"]
    assert "auth.login" in _actions(owner, "&include_sign_ins=true")
    # And no department= reaches it either.
    for department in DEPARTMENTS:
        assert "auth.login" not in _actions(owner, f"&department={department}")


def test_an_entry_from_before_the_column_is_read_by_its_action(owner):
    """Entries written before migration c3e7a1f90019 carry no department.
    Read by their action, as `department_of` would have named them - and
    never rewritten."""
    people = _seed()
    _event("payment.recorded", None, actor=people["boda"], subject="affiliate:2")
    _event("inbox.answer_set", None, actor=people["layla"], subject="inbox:2")
    reader = _as("affiliate_manager")

    events = reader.get("/api/audit?limit=200").json()["events"]
    narrowed = reader.get("/api/audit?limit=200&department=affiliates").json()["events"]

    assert [row["subject"] for row in events] == ["affiliate:2", "affiliate:1"]
    assert [row["subject"] for row in narrowed] == ["affiliate:2", "affiliate:1"]
    with engine.connect() as connection:
        stored = connection.execute(
            text("SELECT department FROM audit_event WHERE subject = 'affiliate:2'")
        ).scalar_one()
    assert stored is None
    # Her filters name the person behind it.
    assert "boda@example.com" in _people(reader)


def test_a_pre_column_entry_is_narrowed_to_its_own_department_only(owner):
    people = _seed()
    _event("payment.recorded", None, actor=people["boda"], subject="affiliate:2")
    _event("inbox.answer_set", None, actor=people["layla"], subject="inbox:2")
    reader = _as("affiliate_manager", "customer_service")

    inbox = reader.get("/api/audit?limit=200&department=inbox").json()["events"]

    assert [row["subject"] for row in inbox] == ["inbox:2", "inbox:1"]


def test_a_prefix_is_matched_as_written_not_as_a_pattern(owner):
    """`order_ops.`: the `_` is a letter here, not LIKE's any-character."""
    people = _seed()
    _event("order_ops.key_saved", None, actor=people["amr"], subject="ops:2")
    _event("orderXops.key_saved", None, actor=people["amr"], subject="ops:3")

    subjects = [
        row["subject"]
        for row in owner.get("/api/audit?limit=200&department=operations").json()["events"]
    ]

    assert subjects == ["ops:2", "ops:1"]


def test_no_action_belongs_to_two_departments():
    """Deriving a department from an action is only one answer if the
    prefixes never overlap."""
    prefixes = [(name, prefix) for name, group in DEPARTMENTS.items() for prefix in group]
    for name, prefix in prefixes:
        for other, longer in prefixes:
            if other != name:
                assert not longer.startswith(prefix), (prefix, longer)


def test_the_narrowing_is_in_the_query_so_a_page_is_full(owner):
    """Fifty of the platform's own entries newer than hers must not leave an
    affiliates reader an empty first page."""
    people = _seed()
    for number in range(6):
        _event("staff.role_given", None, actor=people["hana"], subject=f"user:{number}")
    _event("payment.recorded", "affiliates", actor=people["boda"], subject="affiliate:3")
    reader = _as("affiliate_manager")

    first = reader.get("/api/audit?limit=1").json()
    older = reader.get(f"/api/audit?limit=1&before={first['events'][0]['id']}").json()

    assert [row["subject"] for row in first["events"]] == ["affiliate:3"]
    assert first["has_more"] is True
    assert [row["subject"] for row in older["events"]] == ["affiliate:1"]
    assert older["has_more"] is False


# ── department= ───────────────────────────────────────────────────────────────


def test_department_narrows_to_one_of_ones_own(owner):
    _seed()
    reader = _as("affiliate_manager", "customer_service")

    assert _actions(reader, "&department=affiliates") == ["payment.recorded"]
    assert _actions(reader, "&department=inbox") == ["inbox.answer_set"]


def test_department_outside_ones_own_is_refused(owner):
    _seed()
    reader = _as("affiliate_manager")

    response = reader.get("/api/audit?department=operations")

    assert response.status_code == 403
    assert response.json()["detail"] == "That department's activity is not yours to read."


def test_an_unknown_department_is_a_mistake(owner):
    reader = _as("affiliate_manager")

    assert reader.get("/api/audit?department=finance").status_code == 422
    assert owner.get("/api/audit?department=finance").status_code == 422


def test_the_owner_may_narrow_to_any_department(owner):
    _seed()

    assert _actions(owner, "&department=operations") == ["order_ops.key_saved"]
    assert _actions(owner, "&department=affiliates") == ["payment.recorded"]


# ── The filters ───────────────────────────────────────────────────────────────


def test_the_filters_name_only_people_in_entries_one_may_read(owner):
    _seed()
    reader = _as("affiliate_manager", "customer_service")

    assert _people(reader) == ["boda@example.com", "layla@example.com"]


def test_the_owners_filters_name_everybody_in_the_log(owner):
    _seed()

    assert {
        "amr@example.com", "layla@example.com", "boda@example.com",
        "hana@example.com", "omar@example.com",
    } <= set(_people(owner))


def test_the_filters_models_stay_the_roster(owner):
    _seed()
    with engine.begin() as connection:
        account = _account("nour@example.com", "affiliate")
        connection.execute(
            text(
                "INSERT INTO affiliate_profile (user_account_id, name, status) "
                "VALUES (:u, 'Nour Eldin', 'active')"
            ),
            {"u": account},
        )
    reader = _as("affiliate_manager")

    models = reader.get("/api/audit/filters").json()["models"]

    assert [model["name"] for model in models] == ["Nour Eldin"]


# ── A model's invitation is Affiliates' ───────────────────────────────────────


def _after(action: str, after: dict, *, actor: int | None = None, subject="invitation:x") -> None:
    """An entry with its `after`, written as `record_audit` writes an
    invitation's: no department, since `invitation.` is no department's."""
    import json

    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO audit_event (action, subject, actor_id, after_json) "
                "VALUES (:a, :s, :u, CAST(:j AS jsonb))"
            ),
            {"a": action, "s": subject, "u": actor, "j": json.dumps(after)},
        )


def test_a_model_invitation_sent_by_the_affiliate_manager_is_hers_to_read(owner):
    reader = _as("affiliate_manager")
    sent = reader.post("/api/auth/invitations", json={"email": "nour@example.com", "role": "affiliate"})
    assert sent.status_code == 201, sent.text
    staff = owner.post("/api/auth/invitations", json={"email": "layla@example.com", "role": "content_manager"})
    assert staff.status_code == 201, staff.text

    hers = reader.get("/api/audit?limit=200").json()["events"]
    narrowed = reader.get("/api/audit?limit=200&department=affiliates").json()["events"]

    assert [(row["action"], row["subject"]) for row in hers] == [
        ("invitation.create", "invitation:nour@example.com")
    ]
    assert narrowed == hers
    # The owner reads both, and the staff one is never Affiliates'.
    assert {row["subject"] for row in owner.get("/api/audit?limit=200").json()["events"]} >= {
        "invitation:nour@example.com",
        "invitation:layla@example.com",
    }
    assert "invitation:layla@example.com" not in {
        row["subject"]
        for row in owner.get("/api/audit?limit=200&department=affiliates").json()["events"]
    }


def test_every_step_of_a_model_invitation_is_affiliates_and_no_staff_one_is(owner):
    boda = _account("boda@example.com")
    for action in ("invitation.create", "invitation.resend", "invitation.revoked"):
        _after(action, {"email": "nour@example.com", "role": "affiliate"}, actor=boda,
               subject="invitation:nour@example.com")
        _after(action, {"email": "layla@example.com", "role": "content_manager"}, actor=boda,
               subject="invitation:layla@example.com")
    _after("invitation.accept", {"email": "nour@example.com", "roles": ["affiliate"]}, subject="user:41")
    _after("invitation.accept", {"email": "layla@example.com", "roles": ["content_manager"]}, subject="user:42")
    # Somebody who is both a model and staff is staff: not Affiliates' alone.
    _after("invitation.accept", {"email": "sara@example.com", "roles": ["affiliate", "content_manager"]},
           subject="user:43")
    _event("auth.login", None, actor=boda, subject="user:41")
    reader = _as("affiliate_manager")

    subjects = [row["subject"] for row in reader.get("/api/audit?limit=200&include_sign_ins=true").json()["events"]]

    assert sorted(subjects) == sorted(["invitation:nour@example.com"] * 3 + ["user:41"])


# ── The filters by department ─────────────────────────────────────────────────


def test_the_filters_kinds_are_only_those_ones_entries_can_hold(owner):
    reader = _as("affiliate_manager")

    kinds = reader.get("/api/audit/filters").json()["kinds"]

    # Inbox's and Operations' kinds could only match entries she cannot see.
    assert kinds == ["money", "access", "models", "content", "settings"]
    assert owner.get("/api/audit/filters").json()["kinds"] == [
        "money", "access", "models", "content", "settings", "inbox", "operations",
    ]


def test_the_filters_narrow_to_a_department_for_the_owner_too(owner):
    _seed()

    body = owner.get("/api/audit/filters?department=affiliates").json()

    assert [person["name"] for person in body["people"]] == ["boda@example.com"]
    assert "inbox" not in body["kinds"]
    operations = owner.get("/api/audit/filters?department=operations").json()
    assert [person["name"] for person in operations["people"]] == ["amr@example.com"]
    assert operations["kinds"] == ["settings", "operations"]


def test_the_filters_department_is_held_to_the_same_rule_as_the_log(owner):
    reader = _as("affiliate_manager")

    assert reader.get("/api/audit/filters?department=operations").status_code == 403
    assert reader.get("/api/audit/filters?department=finance").status_code == 422
    assert reader.get("/api/audit/filters?department=affiliates").status_code == 200
