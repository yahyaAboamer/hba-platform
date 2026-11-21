"""The factory's own login (ADR 0084, batch 6b; build plan
docs/plans/2026-11-16-production-factory-login-build.md).

A factory signs in, sees its own orders only, reports what it cut (which waits
for the QC manager) and moves its delivery date. It reaches nothing else on
the platform: the route walk below calls every route the app serves as a
signed-in factory and expects a refusal everywhere but an explicit allow-list.

Every name and figure here is invented; the real data never enters the
repository.
"""

import re
from datetime import timedelta

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from sqlalchemy import select, text

from app.core.permissions import FACTORY_ROLE, can_grant, can_invite, is_staff
from app.db import SessionLocal, engine
from app.main import app
from app.modules.production.models import ProductionSupplier
from app.modules.production.orders.models import ProdCutReport, ProdFactoryAccess, ProdOrderDateChange
from app.shared.api.deps import FACTORY_REACHES, current_user, signed_in
from app.shared.models.audit import AuditEvent
from app.shared.models.identity import Invitation, UserAccount
from tests.conftest import alembic_head
from tests.test_prod_orders import (  # noqa: F401  (fixtures)
    CUT,
    PASSWORD,
    PLANNED,
    TARGET,
    TODAY,
    _cut,
    _day,
    _new,
    _no_money,
    _ok,
    _person,
    _to_cutting,
    owner,
    staff,
    viewer,
)

FACTORY_EMAIL = "cutting.room@example.com"
HEAD = alembic_head()
OWNER_NOTE = "Owner-only remark about margins"
SAMPLE_NOTE = "Owner sample remark"


# ── People ────────────────────────────────────────────────────────────────────


@pytest.fixture()
def manager(owner):
    return _person("pm@example.com", "production_manager", name="Production Manager")


@pytest.fixture()
def second_factory(owner):
    with SessionLocal() as db:
        db.add(ProductionSupplier(id="fac2", code="FAC2", name="Rival workshop", category_id="cat-make", active=True))
        db.commit()
    return "fac2"


def _invite(client: TestClient, supplier: str = "fac", email: str = FACTORY_EMAIL, name: str = "Main factory"):
    return client.post(f"/api/prod/suppliers/{supplier}/factory-login", json={"email": email, "name": name})


def _accept(token: str) -> TestClient:
    client = TestClient(app)
    response = client.post(
        "/api/auth/invitations/accept", json={"token": token, "password": PASSWORD, "display_name": "Cutting room"}
    )
    assert response.status_code == 201, response.text
    client.headers["X-CSRF-Token"] = response.json()["csrf"]
    return client


def _factory(client: TestClient, supplier: str = "fac", email: str = FACTORY_EMAIL) -> TestClient:
    response = _invite(client, supplier, email)
    assert response.status_code == 201, response.text
    return _accept(response.json()["token"])


@pytest.fixture()
def factory(owner):
    return _factory(owner)


def _order(client: TestClient, **over) -> dict:
    return _new(client, notes=OWNER_NOTE, **over)


def _at_cutting(client: TestClient, **over) -> dict:
    order = _order(client, **over)
    _ok(client.post(f"/api/prod/orders/{order['id']}/sample", json={"decision": "approved", "note": SAMPLE_NOTE}))
    _to_cutting(client, order["id"], repeat=True)
    return order


REPORT = {"S": 148, "M": 290, "L": 290, "XL": 176, "XXL": 66}


def _report(client: TestClient, oid: int, sizes: dict | None = None, note: str | None = "Short on fabric"):
    return client.put(f"/api/factory/orders/{oid}/cut-report", json={"sizes": sizes or REPORT, "note": note})


def _tasks(client: TestClient, oid: int) -> list[dict]:
    response = client.get("/api/prod/tasks")
    assert response.status_code == 200, response.text
    return [t for t in response.json()["tasks"] if t["order"] and t["order"]["id"] == oid]


# ── The route walk: a factory reaches its own desk and nothing else ───────────

#: Routes that resolve **nobody**: reachable signed out, so a factory's
#: session neither helps nor matters. Each is checked below to resolve no
#: person at all, so an authenticated route cannot hide in this list.
PUBLIC = {
    # Railway's health checks.
    ("GET", "/api/health/live"),
    ("GET", "/api/health/ready"),
    # What the sign-in page needs before anybody is signed in.
    ("GET", "/api/client-config"),
    ("GET", "/api/auth/needs-setup"),
    ("GET", "/api/auth/status"),
    # The very first account; refused once any account exists.
    ("POST", "/api/auth/bootstrap"),
    # Signing in, its second step and a fresh code.
    ("POST", "/api/auth/login"),
    ("POST", "/api/auth/login/two-step"),
    ("POST", "/api/auth/login/resend"),
    # Signing out: resolves its own session and never checks CSRF (see its
    # docstring); ending your own session is always allowed.
    ("POST", "/api/auth/logout"),
    # The password meter on the accept and reset pages.
    ("POST", "/api/auth/password-quality"),
    # A lost password, by emailed link (the token is the credential).
    ("POST", "/api/auth/password-reset/request"),
    ("GET", "/api/auth/password-reset/preview"),
    ("POST", "/api/auth/password-reset"),
    # Opening and accepting an invitation (the token is the credential).
    ("GET", "/api/auth/invitations/preview"),
    ("POST", "/api/auth/invitations/accept"),
    # Called by Meta and Shopify, signed by them, never by a session.
    ("GET", "/api/webhooks/meta"),
    ("POST", "/api/webhooks/meta"),
    ("POST", "/api/webhooks/shopify"),
}

#: The factory's own account routes, beside its desk: who it is, and its own
#: sessions (the same list `signed_in` lets a factory through; asserted equal).
OWN_ACCOUNT = {
    # Who is signed in: the screens route a factory to /factory from it.
    ("GET", "/api/auth/me"),
    # Its own sessions: see them, end one, end the others.
    ("GET", "/api/auth/sessions"),
    ("POST", "/api/auth/sessions/end-others"),
    ("POST", "/api/auth/sessions/{session_id}/end"),
}

#: The factory's desk itself: `current_factory` on the router.
FACTORY_DESK = "/api/factory/"


def _walk(routes):
    for route in routes:
        if isinstance(route, APIRoute):
            yield route
        elif hasattr(route, "original_router"):
            yield from _walk(route.original_router.routes)


def _calls(dependant) -> set:
    found = {dependant.call} if dependant.call is not None else set()
    for child in dependant.dependencies:
        found |= _calls(child)
    return found


def _filled(path: str) -> str:
    """Every path parameter given a harmless dummy value."""
    return re.sub(r"\{[^}]+\}", "1", path)


def test_a_signed_in_factory_is_refused_everywhere_but_its_allow_list(factory):
    assert OWN_ACCOUNT == FACTORY_REACHES, "the test's allow-list and the server's must be the same list"
    routes = list(_walk(app.routes))
    assert len(routes) > 150, "the walk missed the routers"

    seen_desk = set()
    called = 0
    with TestClient(app, raise_server_exceptions=False) as client:
        client.cookies.update(factory.cookies)
        headers = {"X-CSRF-Token": factory.headers["X-CSRF-Token"]}
        for route in routes:
            for method in sorted(route.methods - {"HEAD"}):
                key = (method, route.path)
                if not route.path.startswith("/api/"):
                    # The page shell, the logo, Production's old screens:
                    # static files, the same for everybody.
                    assert not ({current_user, signed_in} & _calls(route.dependant)), key
                    continue
                if key in PUBLIC:
                    assert not ({current_user, signed_in} & _calls(route.dependant)), (
                        f"{key} is listed as public but resolves a person"
                    )
                    continue
                if key in OWN_ACCOUNT:
                    continue
                if route.path.startswith(FACTORY_DESK):
                    seen_desk.add(key)
                    continue
                response = client.request(method, _filled(route.path), headers=headers)
                called += 1
                assert response.status_code in (401, 403), (
                    f"{method} {route.path} answered a factory {response.status_code}: {response.text[:200]}"
                )
        # Still signed in after the walk: nothing above ended the session.
        me = client.get("/api/auth/me")
    assert called > 150
    assert me.status_code == 200 and me.json()["actor"]["is_factory"] is True
    assert seen_desk == {
        ("GET", "/api/factory/orders"),
        ("GET", "/api/factory/orders/{order_id}"),
        ("PUT", "/api/factory/orders/{order_id}/cut-report"),
        ("POST", "/api/factory/orders/{order_id}/delivery-date"),
    }


def test_the_factory_desk_is_behind_current_factory_on_every_route():
    from app.shared.api.deps import current_factory, require_permission  # noqa: F401

    for route in _walk(app.routes):
        if route.path.startswith(FACTORY_DESK) or route.path == "/api/factory":
            calls = _calls(route.dependant)
            assert current_factory in calls, route.path
            # Never mixed with a permission (`require_permission`).
            assert not any(getattr(call, "permission", None) for call in calls), route.path


def test_the_allowed_own_account_routes_answer_the_factory(factory):
    me = factory.get("/api/auth/me")
    assert me.status_code == 200
    actor = me.json()["actor"]
    assert actor["is_factory"] is True
    assert actor["is_staff"] is False
    assert actor["is_model"] is False
    assert actor["roles"] == [FACTORY_ROLE]
    assert me.json()["permissions"] == []
    assert factory.get("/api/auth/sessions").status_code == 200
    assert factory.get("/api/factory/orders").status_code == 200


def test_staff_and_models_are_not_factories(owner, staff):
    assert owner.get("/api/auth/me").json()["actor"]["is_factory"] is False
    assert owner.get("/api/factory/orders").status_code == 403
    assert staff.get("/api/factory/orders").status_code == 403
    assert TestClient(app).get("/api/factory/orders").status_code == 401


# ── Not staff, not a model ────────────────────────────────────────────────────


def test_the_factory_role_grants_nothing_and_makes_nobody_staff():
    assert not is_staff({FACTORY_ROLE})
    assert not is_staff({FACTORY_ROLE, "affiliate"})
    assert is_staff({FACTORY_ROLE, "production_viewer"})
    # Nobody gives it through Settings or an invitation, not even the owner.
    assert not can_grant("admin", FACTORY_ROLE)
    assert not can_invite("admin", FACTORY_ROLE)


def test_a_factory_is_refused_today_staff_preferences_two_step_and_the_model_application(factory):
    for path in ("/api/today", "/api/staff/me/preferences", "/api/applications/mine", "/api/auth/two-step", "/api/me"):
        assert factory.get(path).status_code == 403, path
    assert factory.post("/api/applications", json={}).status_code == 403
    assert factory.post("/api/auth/two-step/start", json={"password": PASSWORD}).status_code == 403
    assert factory.put("/api/staff/me/theme", json={"theme": "dark"}).status_code == 403


def test_the_general_invitation_refuses_the_factory_role(owner):
    response = owner.post("/api/auth/invitations", json={"email": "x@example.com", "role": FACTORY_ROLE})
    assert response.status_code == 422
    assert "supplier" in response.json()["detail"]


def test_a_factory_invitation_cannot_be_resent_or_withdrawn_from_settings(owner):
    _invite(owner)
    with SessionLocal() as db:
        invitation_id = db.scalar(select(Invitation.id).where(Invitation.role == FACTORY_ROLE))
    assert owner.post(f"/api/staff/invitations/{invitation_id}/resend").status_code == 403
    assert owner.post(f"/api/staff/invitations/{invitation_id}/revoke").status_code == 403
    # Nor replaced by inviting the same address to something else.
    other = owner.post("/api/auth/invitations", json={"email": FACTORY_EMAIL, "role": "production_viewer"})
    assert other.status_code == 403
    # And it is not on Team and access's list of waiting invitations.
    roster = owner.get("/api/staff").json()
    assert FACTORY_EMAIL not in [i["email"] for i in roster["invitations"]]
    assert FACTORY_ROLE not in roster["assignable_roles"]
    assert FACTORY_ROLE not in roster["invitable_roles"]


def test_a_factory_login_is_not_on_team_and_cannot_be_given_staff_access(owner, factory):
    roster = owner.get("/api/staff").json()
    assert FACTORY_EMAIL not in [person["email"] for person in roster["staff"]]
    with SessionLocal() as db:
        account_id = db.scalar(select(UserAccount.id).where(UserAccount.email == FACTORY_EMAIL))
    response = owner.post(f"/api/staff/{account_id}/roles", json={"role": "production_viewer"})
    assert response.status_code == 400
    assert "factory" in response.json()["detail"]
    assert owner.put(f"/api/staff/{account_id}/access/production", json={"level": "viewer"}).status_code == 404
    # Still only the factory's own desk.
    assert factory.get("/api/prod/orders").status_code == 403


# ── Inviting, accepting, resending, switching off ─────────────────────────────


def test_whoever_manages_suppliers_invites_and_nobody_else(owner, manager, staff, viewer):
    assert _invite(staff).status_code == 403
    assert _invite(viewer).status_code == 403
    response = _invite(manager)
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["token"]
    assert body["supplier"]["factory_login"]["state"] == "invited"
    assert body["supplier"]["factory_login"]["email"] == FACTORY_EMAIL
    with SessionLocal() as db:
        access = db.scalar(select(ProdFactoryAccess))
        invitation = db.get(Invitation, access.invitation_id)
        assert access.supplier_id == "fac" and access.user_account_id is None
        assert invitation.role == FACTORY_ROLE and invitation.email == FACTORY_EMAIL
        events = [e.action for e in db.scalars(select(AuditEvent).where(AuditEvent.subject == "production:supplier:fac"))]
    assert "production.factory_login_invited" in events


def test_the_login_card_is_shown_only_to_whoever_manages_suppliers(owner, manager, staff, viewer):
    assert owner.get("/api/prod/suppliers/fac").json()["supplier"]["factory_login"] is None
    _invite(owner)
    assert manager.get("/api/prod/suppliers/fac").json()["supplier"]["factory_login"]["state"] == "invited"
    for client in (staff, viewer):
        assert "factory_login" not in client.get("/api/prod/suppliers/fac").json()["supplier"]


def test_accepting_links_the_account_to_the_supplier(owner):
    token = _invite(owner).json()["token"]
    preview = TestClient(app).get("/api/auth/invitations/preview", params={"token": token})
    assert preview.status_code == 200 and preview.json()["role"] == FACTORY_ROLE
    client = _accept(token)
    with SessionLocal() as db:
        account = db.scalar(select(UserAccount).where(UserAccount.email == FACTORY_EMAIL))
        access = db.scalar(select(ProdFactoryAccess))
        assert access.user_account_id == account.id
    card = owner.get("/api/prod/suppliers/fac").json()["supplier"]["factory_login"]
    assert card["state"] == "active"
    assert card["last_seen_at"] is not None
    assert client.get("/api/factory/orders").json()["factory"] == {"name": "Main factory"}


def test_an_address_already_somebodys_is_refused_without_saying_whose(owner, staff):
    for email in ("owner@example.com", "qc@example.com"):
        response = _invite(owner, email=email)
        assert response.status_code == 422
        assert response.json()["detail"] == "This address cannot be used for a factory login. Use another one."
    # A link waiting for somebody else is not replaced from here.
    assert owner.post("/api/auth/invitations", json={"email": "new.hire@example.com", "role": "production_viewer"}).status_code == 201
    response = _invite(owner, email="new.hire@example.com")
    assert response.status_code == 422
    assert response.json()["detail"] == "This address cannot be used for a factory login. Use another one."


def test_one_live_login_per_supplier(owner, second_factory):
    assert _invite(owner).status_code == 201
    second = _invite(owner, email="another@example.com")
    assert second.status_code == 409
    # Another supplier may have its own, but not at the same address.
    assert _invite(owner, supplier="fac2", email=FACTORY_EMAIL).status_code == 422
    assert _invite(owner, supplier="fac2", email="rival@example.com").status_code == 201


def test_resend_sends_a_new_link_and_the_old_one_stops_working(owner):
    old = _invite(owner).json()["token"]
    response = owner.post("/api/prod/suppliers/fac/factory-login/resend")
    assert response.status_code == 201, response.text
    new = response.json()["token"]
    assert new != old
    assert TestClient(app).get("/api/auth/invitations/preview", params={"token": old}).status_code == 410
    client = _accept(new)
    assert client.get("/api/factory/orders").status_code == 200
    # Once accepted there is nothing to resend.
    assert owner.post("/api/prod/suppliers/fac/factory-login/resend").status_code == 409


def test_switching_off_a_waiting_link_kills_it(owner):
    token = _invite(owner).json()["token"]
    response = owner.delete("/api/prod/suppliers/fac/factory-login")
    assert response.status_code == 200, response.text
    assert response.json()["supplier"]["factory_login"]["state"] == "off"
    assert TestClient(app).get("/api/auth/invitations/preview", params={"token": token}).status_code == 410
    accepted = TestClient(app).post(
        "/api/auth/invitations/accept", json={"token": token, "password": PASSWORD, "display_name": "x"}
    )
    assert accepted.status_code == 422
    # A new login may be invited after.
    assert _invite(owner, email="fresh@example.com").status_code == 201


def test_switching_off_ends_the_factorys_access_on_its_very_next_request(owner, manager):
    client = _factory(manager)
    assert client.get("/api/factory/orders").status_code == 200
    response = manager.delete("/api/prod/suppliers/fac/factory-login")
    assert response.status_code == 200, response.text
    assert response.json()["supplier"]["factory_login"]["state"] == "off"
    assert client.get("/api/factory/orders").status_code == 401
    assert client.get("/api/auth/me").status_code == 401
    # Nor can it sign in again.
    login = TestClient(app).post("/api/auth/login", json={"email": FACTORY_EMAIL, "password": PASSWORD})
    assert login.status_code != 200
    with SessionLocal() as db:
        account = db.scalar(select(UserAccount).where(UserAccount.email == FACTORY_EMAIL))
        assert account.status == "suspended"
        live = db.execute(
            text("SELECT count(*) FROM role_assignment WHERE user_account_id = :u AND revoked_at IS NULL"),
            {"u": account.id},
        ).scalar_one()
        assert live == 0
        events = [e.action for e in db.scalars(select(AuditEvent).where(AuditEvent.subject == "production:supplier:fac"))]
    assert "production.factory_login_off" in events
    assert manager.delete("/api/prod/suppliers/fac/factory-login").status_code == 409


def test_a_switched_off_row_refuses_even_an_active_account(owner, factory):
    """`current_factory` reads the row itself: an account whose login row is
    off is refused even if, somehow, the account were still active."""
    with engine.begin() as connection:
        connection.execute(text("UPDATE prod_factory_access SET switched_off_at = now()"))
    assert factory.get("/api/factory/orders").status_code == 403
    assert factory.get("/api/auth/me").status_code == 200


def test_a_reactivated_former_factory_still_reaches_nothing_else(owner, factory):
    owner.delete("/api/prod/suppliers/fac/factory-login")
    with SessionLocal() as db:
        account_id = db.scalar(select(UserAccount.id).where(UserAccount.email == FACTORY_EMAIL))
    assert owner.post(f"/api/staff/{account_id}/reactivate").status_code in (200, 404)
    with engine.begin() as connection:
        connection.execute(text("UPDATE user_account SET status = 'active' WHERE id = :u"), {"u": account_id})
    client = TestClient(app)
    login = client.post("/api/auth/login", json={"email": FACTORY_EMAIL, "password": PASSWORD})
    assert login.status_code == 200, login.text
    client.headers["X-CSRF-Token"] = login.json()["csrf"]
    assert client.get("/api/auth/me").json()["actor"]["is_factory"] is True
    for path in ("/api/factory/orders", "/api/applications/mine", "/api/prod/orders", "/api/auth/two-step"):
        assert client.get(path).status_code == 403, path


def test_a_factory_invitation_with_no_login_behind_it_gives_no_account(owner):
    """Fails closed: a `factory` invitation made any other way is refused."""
    from app.shared.services.invitations import create_invitation

    with SessionLocal() as db:
        token, _ = create_invitation(db, "stray@example.com", FACTORY_ROLE, None)
        db.commit()
    assert TestClient(app).get("/api/auth/invitations/preview", params={"token": token}).status_code == 410
    response = TestClient(app).post(
        "/api/auth/invitations/accept", json={"token": token, "password": PASSWORD, "display_name": "x"}
    )
    assert response.status_code == 422
    with SessionLocal() as db:
        assert db.scalar(select(UserAccount.id).where(UserAccount.email == "stray@example.com")) is None


# ── Its own orders only ───────────────────────────────────────────────────────


def _close(oid: int, days_ago: int) -> None:
    with engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE prod_order SET status = 'closed', settled_payable_piastres = 0, "
                "settled_at = now() - make_interval(days => :d) WHERE id = :id"
            ),
            {"d": days_ago, "id": oid},
        )


def test_the_factory_sees_its_own_open_orders_newest_delivery_date_last(owner, factory, second_factory):
    later = _order(owner, target_date=(TARGET + timedelta(days=10)).isoformat())
    sooner = _order(owner)
    _order(owner, factory_id="fac2")
    cancelled = _order(owner)
    assert owner.post(f"/api/prod/orders/{cancelled['id']}/cancel", json={"reason": "Dropped"}).status_code == 200
    closed = _order(owner)
    _close(closed["id"], 3)
    body = factory.get("/api/factory/orders").json()
    assert [o["id"] for o in body["orders"]] == [sooner["id"], later["id"]]
    row = body["orders"][0]
    assert set(row) == {
        "id", "code", "style_name", "colour", "printing", "planned_total", "cut", "status_words",
        "delivery_date", "moved", "moved_from",
    }
    assert row["planned_total"] == sum(PLANNED.values())
    assert row["cut"] == {"reported_total": None, "confirmed_total": None}
    assert row["printing"] == "at your factory"
    assert row["moved"] is False and row["moved_from"] is None
    assert row["status_words"] == "sample with HBA"


def test_another_suppliers_cancelled_old_or_missing_order_is_403_on_every_route(owner, factory, second_factory):
    theirs = _at_cutting(owner, factory_id="fac2")
    cancelled = _at_cutting(owner)
    assert owner.post(f"/api/prod/orders/{cancelled['id']}/cancel", json={"reason": "Dropped"}).status_code == 200
    old = _order(owner)
    _close(old["id"], 31)
    for oid in (theirs["id"], cancelled["id"], old["id"], 999_999):
        responses = [
            factory.get(f"/api/factory/orders/{oid}"),
            _report(factory, oid),
            factory.post(f"/api/factory/orders/{oid}/delivery-date", json={"date": _day(70), "reason": "Late"}),
        ]
        for response in responses:
            assert response.status_code == 403, (oid, response.status_code, response.text)
            assert response.json()["detail"] == "This order is not one of yours."
    with SessionLocal() as db:
        assert db.scalar(select(ProdCutReport.id)) is None


def test_a_recently_closed_order_reads_but_changes_nothing(owner, factory):
    order = _order(owner)
    _close(order["id"], 5)
    detail = factory.get(f"/api/factory/orders/{order['id']}")
    assert detail.status_code == 200
    body = detail.json()["order"]
    assert body["can_report_cut"] is False and body["can_move_date"] is False
    assert body["status_words"] == "finished"
    assert _report(factory, order["id"]).status_code == 409
    moved = factory.post(f"/api/factory/orders/{order['id']}/delivery-date", json={"date": _day(70), "reason": "x"})
    assert moved.status_code == 409


def _strings(payload) -> list[str]:
    if isinstance(payload, dict):
        return [k for k in payload] + [s for v in payload.values() for s in _strings(v)]
    if isinstance(payload, list):
        return [s for v in payload for s in _strings(v)]
    return [str(payload)] if payload is not None else []


def _leaks_nothing(payload) -> None:
    """Recursively: no money, no other supplier, no rating, no HBA note and
    no HBA person - on every key and value of a factory's answer."""
    _no_money(payload)
    for value in _strings(payload):
        lowered = value.lower()
        assert not value.endswith("_piastres"), value
        assert "egp" not in lowered, value
        assert "rating" not in lowered and "stars" not in lowered, value
        for forbidden in (
            "fac2", "Rival workshop", "prt", "Print house A", OWNER_NOTE, SAMPLE_NOTE,
            "owner@example.com", "Owner remark", "QC Manager", "qc@example.com", "Production Manager",
        ):
            assert forbidden.lower() not in lowered, (forbidden, value)


def test_no_answer_carries_money_another_supplier_or_hba_notes(owner, staff, factory, second_factory):
    order = _at_cutting(owner, printing="outside", print_supplier_id="prt")
    _order(owner, factory_id="fac2")
    # HBA moves the date with its own words, a stage carries an HBA note.
    _ok(owner.post(
        f"/api/prod/orders/{order['id']}/delivery-date",
        json={"new_date": _day(70), "set_by": "owner", "reason": "Print queue"},
    ))
    answers = [factory.get("/api/factory/orders").json()]
    answers.append(factory.get(f"/api/factory/orders/{order['id']}").json())
    answers.append(_report(factory, order["id"]).json())
    answers.append(
        factory.post(
            f"/api/factory/orders/{order['id']}/delivery-date", json={"date": _day(75), "reason": "Fabric late"}
        ).json()
    )
    for answer in answers:
        _leaks_nothing(answer)
    detail = answers[-1]["order"]
    assert detail["printing"] == "at a print house"
    assert set(detail) == {
        "id", "code", "style_name", "colour", "printing", "planned_total", "cut", "status_words",
        "delivery_date", "moved", "moved_from", "sizes", "report", "can_report_cut", "can_move_date", "dates",
    }
    assert set(detail["sizes"][0]) == {"size", "planned", "reported", "confirmed"}
    assert set(detail["dates"][0]) == {"on", "date", "by", "reason"}
    assert {d["by"] for d in detail["dates"]} == {"HBA", "You"}


# ── The cut report ────────────────────────────────────────────────────────────


def test_the_cut_report_waits_for_the_qc_manager_and_the_task_says_so(owner, staff, factory):
    order = _at_cutting(owner)
    oid = order["id"]
    assert [t["title"] for t in _tasks(owner, oid)] == ["Record cut quantities"]

    response = _report(factory, oid)
    assert response.status_code == 200, response.text
    mine = response.json()["order"]
    assert mine["cut"] == {"reported_total": sum(REPORT.values()), "confirmed_total": None}
    assert mine["status_words"] == "waiting for HBA to confirm your cut"
    assert mine["report"] == {"reported_on": TODAY.isoformat(), "note": "Short on fabric"}
    assert {s["size"]: s["reported"] for s in mine["sizes"]} == REPORT
    assert all(s["confirmed"] is None for s in mine["sizes"])
    assert mine["can_report_cut"] is True

    # HBA's side: the task replaces "Record cut quantities"; the order page
    # and the cut form carry the report.
    tasks = _tasks(owner, oid)
    assert [(t["title"], t["who"], t["due"], t["open"]) for t in tasks] == [
        ("Confirm the factory's cut", "qc", TODAY.isoformat(), "cut")
    ]
    seen = staff.get(f"/api/prod/orders/{oid}").json()["order"]
    assert seen["cut_report"]["sizes"] == REPORT
    assert seen["cut_report"]["total"] == sum(REPORT.values())
    assert seen["cut_report"]["reported_on"] == TODAY.isoformat()
    assert seen["cut_report"]["note"] == "Short on fabric"

    # Audited with the factory's own account as the actor.
    with SessionLocal() as db:
        event = db.scalar(select(AuditEvent).where(AuditEvent.action == "production.order_cut_reported"))
        account = db.scalar(select(UserAccount).where(UserAccount.email == FACTORY_EMAIL))
        assert event.actor_id == account.id
        assert event.subject == f"production:order:{oid}"

    # The QC manager saves what was counted; that confirms the report.
    _cut(staff, oid)
    assert all(t["title"] != "Confirm the factory's cut" for t in _tasks(owner, oid))
    assert staff.get(f"/api/prod/orders/{oid}").json()["order"]["cut_report"] is None
    mine = factory.get(f"/api/factory/orders/{oid}").json()["order"]
    assert mine["cut"] == {"reported_total": sum(REPORT.values()), "confirmed_total": sum(CUT.values())}
    assert {s["size"]: s["confirmed"] for s in mine["sizes"]} == CUT
    assert mine["can_report_cut"] is False
    assert mine["report"] is None
    assert mine["status_words"] == "being made"
    with SessionLocal() as db:
        assert db.scalar(select(ProdCutReport)).confirmed_at is not None
    # Refused once cutting is recorded.
    assert _report(factory, oid).status_code == 409


def test_a_second_report_replaces_one_not_yet_confirmed(owner, factory):
    oid = _at_cutting(owner)["id"]
    assert _report(factory, oid).status_code == 200
    corrected = {**REPORT, "S": 140}
    response = _report(factory, oid, corrected, note=None)
    assert response.status_code == 200
    assert {s["size"]: s["reported"] for s in response.json()["order"]["sizes"]} == corrected
    assert response.json()["order"]["report"]["note"] is None
    with SessionLocal() as db:
        rows = list(db.scalars(select(ProdCutReport).order_by(ProdCutReport.id)))
        assert len(rows) == 2
        assert rows[0].replaced_at is not None and rows[1].replaced_at is None
    assert owner.get(f"/api/prod/orders/{oid}").json()["order"]["cut_report"]["sizes"] == corrected
    assert len([t for t in _tasks(owner, oid) if t["title"] == "Confirm the factory's cut"]) == 1


def test_a_report_may_come_before_the_cutting_stage_and_waits_beside_its_work(owner, factory):
    order = _order(owner)
    response = _report(factory, order["id"])
    assert response.status_code == 200
    titles = [t["title"] for t in _tasks(owner, order["id"])]
    assert "Confirm the factory's cut" in titles and "Approve the sample" in titles


@pytest.mark.parametrize(
    "sizes, note",
    [
        ({"XS": 5}, None),  # not a size on this order
        ({"Q": 5}, None),  # not a size at all
        ({"S": 0, "M": 0}, None),  # no piece
        ({"S": -1}, None),
        ({"S": 100_001}, None),
        ({"S": 10}, "x" * 501),
    ],
)
def test_a_cut_report_is_refused_in_words(owner, factory, sizes, note):
    oid = _at_cutting(owner)["id"]
    response = _report(factory, oid, sizes, note=note)
    assert response.status_code == 422, response.text
    with SessionLocal() as db:
        assert db.scalar(select(ProdCutReport.id)) is None


def test_a_factory_write_needs_the_csrf_header(owner, factory):
    oid = _at_cutting(owner)["id"]
    bare = TestClient(app)
    bare.cookies.update(factory.cookies)
    assert bare.put(f"/api/factory/orders/{oid}/cut-report", json={"sizes": REPORT}).status_code == 401
    assert bare.post(f"/api/factory/orders/{oid}/delivery-date", json={"date": _day(70), "reason": "x"}).status_code == 401
    wrong = bare.put(
        f"/api/factory/orders/{oid}/cut-report", json={"sizes": REPORT}, headers={"X-CSRF-Token": "not-it"}
    )
    assert wrong.status_code == 401
    with SessionLocal() as db:
        assert db.scalar(select(ProdCutReport.id)) is None
    # Reading needs none.
    assert bare.get(f"/api/factory/orders/{oid}").status_code == 200


# ── The delivery date ─────────────────────────────────────────────────────────


def test_the_factory_moves_its_date_and_the_history_says_the_factory(owner, factory):
    oid = _order(owner)["id"]
    response = factory.post(
        f"/api/factory/orders/{oid}/delivery-date", json={"date": _day(70), "reason": "Waiting in the print queue"}
    )
    assert response.status_code == 200, response.text
    mine = response.json()["order"]
    assert mine["delivery_date"] == _day(70)
    assert mine["moved"] is True and mine["moved_from"] == TARGET.isoformat()
    assert mine["dates"][-1] == {
        "on": TODAY.isoformat(), "date": _day(70), "by": "You", "reason": "Waiting in the print queue",
    }
    assert mine["dates"][0]["by"] == "HBA"
    seen = owner.get(f"/api/prod/orders/{oid}").json()["order"]
    assert seen["date_history"][-1]["set_by"] == "factory"
    with SessionLocal() as db:
        change = db.scalar(select(ProdOrderDateChange).order_by(ProdOrderDateChange.id.desc()))
        account = db.scalar(select(UserAccount).where(UserAccount.email == FACTORY_EMAIL))
        assert change.created_by == account.id
        event = db.scalar(select(AuditEvent).where(AuditEvent.action == "production.order_delivery_date_changed"))
        assert event.actor_id == account.id
    # The same date again, or no reason, is refused in words.
    assert factory.post(f"/api/factory/orders/{oid}/delivery-date", json={"date": _day(70), "reason": "x"}).status_code == 422
    assert factory.post(f"/api/factory/orders/{oid}/delivery-date", json={"date": _day(71), "reason": " "}).status_code == 422
    # A date the server cannot count from, far back or far ahead, is refused.
    for far in ("0001-01-01", "9999-12-31", _day(-31), _day(731)):
        refused = factory.post(f"/api/factory/orders/{oid}/delivery-date", json={"date": far, "reason": "Typing slip"})
        assert refused.status_code == 422, (far, refused.text)


# ── The migration ─────────────────────────────────────────────────────────────


def test_the_downgrade_refuses_while_a_factory_login_exists(owner):
    from alembic import command
    from alembic.config import Config

    assert _invite(owner).status_code == 201
    with pytest.raises(RuntimeError, match="factory"):
        command.downgrade(Config("alembic.ini"), "c9e6a2b40036")
    with engine.connect() as connection:
        assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == HEAD
        assert connection.execute(text("SELECT count(*) FROM prod_factory_access")).scalar_one() == 1


def test_the_database_refuses_a_second_live_login_or_waiting_report(owner, factory):
    from sqlalchemy.exc import IntegrityError

    with pytest.raises(IntegrityError):
        with engine.begin() as connection:
            connection.execute(
                text("INSERT INTO prod_factory_access (supplier_id, email) VALUES ('fac', 'two@example.com')")
            )
    oid = _at_cutting(owner)["id"]
    assert _report(factory, oid).status_code == 200
    with pytest.raises(IntegrityError):
        with engine.begin() as connection:
            connection.execute(
                text("INSERT INTO prod_cut_report (order_id, sizes) VALUES (:o, '{\"S\": 1}')"), {"o": oid}
            )
    with pytest.raises(IntegrityError):
        with engine.begin() as connection:
            connection.execute(
                text("INSERT INTO role_assignment (user_account_id, role) VALUES (1, 'not_a_role')")
            )


def test_a_factory_invitation_is_worded_for_a_factory(owner):
    _invite(owner)
    with SessionLocal() as db:
        row = db.execute(
            text("SELECT payload FROM notification_outbox WHERE recipient_email = :e"), {"e": FACTORY_EMAIL}
        ).scalar_one()
    assert row["role"] == FACTORY_ROLE
    from app.shared.services.notifications import Event, render

    message = render(Event.INVITATION_SENT, row)
    assert "orders with HBA" in message.subject
    assert "affiliate" not in message.body.lower()
