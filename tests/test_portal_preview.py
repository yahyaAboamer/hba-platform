"""Staff looking at a model's portal, read only. ADR 0064.

Three promises, each asserted rather than assumed:

* **What staff see is what she sees** - the preview's payloads are compared
  with her own `/api/me` answers, value for value.
* **Nobody acts as her** - the preview has no write route, no unmasked payout
  read, and her own routes still refuse staff.
* **Every look is on record**, under the staff member and never as her.
"""

from types import SimpleNamespace

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
PASSWORD = "quiet-harbour-lantern"
SEPTEMBER = "2026-09"


@pytest.fixture(autouse=True)
def _go_live(monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "go_live_month", "2026-01", raising=False)


@pytest.fixture(autouse=True)
def _working_month(monkeypatch):
    monkeypatch.setattr(
        "app.services.portal.working_month", lambda: SEPTEMBER, raising=True
    )


@pytest.fixture()
def admin(fresh_database):
    with TestClient(app) as client:
        response = client.post("/api/auth/bootstrap", json=BOOTSTRAP)
        assert response.status_code == 201, response.text
        client.headers["X-CSRF-Token"] = response.json()["csrf"]
        yield client


def _account(email: str, role: str | None = None) -> int:
    with engine.begin() as connection:
        account_id = connection.execute(
            text(
                "INSERT INTO user_account (email, password_hash, status, "
                "display_name) VALUES (:e, :p, 'active', 'Somebody') RETURNING id"
            ),
            {"e": email, "p": hash_password(PASSWORD)},
        ).scalar_one()
        if role:
            connection.execute(
                text("INSERT INTO role_assignment (user_account_id, role) VALUES (:u, :r)"),
                {"u": account_id, "r": role},
            )
    return account_id


def _model(admin, name="Nour", email="nour@example.com", code="NOUR10") -> dict:
    """An active model with a confirmed code and commission terms."""
    response = admin.post(
        "/api/affiliates", json={"user_account_id": _account(email), "name": name}
    )
    assert response.status_code == 201, response.text
    affiliate = response.json()
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO discount_code_period "
                "(affiliate_id, code, start_month, shopify_verified_at) "
                "VALUES (:a, :c, '2025-01', now())"
            ),
            {"a": affiliate["id"], "c": code},
        )
        connection.execute(
            text("UPDATE affiliate_profile SET status = 'active' WHERE id = :id"),
            {"id": affiliate["id"]},
        )
    terms = admin.put(
        f"/api/affiliates/{affiliate['id']}/pay-history",
        json={
            "periods": [
                {
                    "start_month": "2026-01",
                    "compensation_type": "commission",
                    "commission_rate_bp": 1000,
                }
            ],
            "outcomes": {},
        },
    )
    assert terms.status_code == 200, terms.text
    return affiliate


def _sign_in(email: str) -> TestClient:
    client = TestClient(app)
    response = client.post("/api/auth/login", json={"email": email, "password": PASSWORD})
    assert response.status_code == 200, response.text
    client.headers["X-CSRF-Token"] = response.json()["csrf"]
    return client


#: Every read the portal makes, as the tail both her path and the preview's share.
MIRRORED = [
    "",
    "/notifications",
    "/months",
    f"/earnings/{SEPTEMBER}",
    f"/home/{SEPTEMBER}",
    "/payments",
    "/wardrobe",
    "/best-sellers",
    f"/best-sellers?month={SEPTEMBER}",
    "/targets",
    f"/ranking/{SEPTEMBER}",
]


@pytest.mark.parametrize("path", MIRRORED)
def test_the_preview_shows_exactly_what_she_sees(admin, path):
    nour = _model(admin)
    _model(admin, name="Salma", email="salma@example.com", code="SALMA10")
    hers = _sign_in("nour@example.com")

    own = hers.get(f"/api/me{path}")
    preview = admin.get(f"/api/affiliates/{nour['id']}/portal{path}")

    assert own.status_code == 200, own.text
    assert preview.status_code == 200, preview.text
    assert preview.json() == own.json()


def test_the_preview_says_she_has_applied_as_her_own_screen_does(admin):
    nour = _model(admin)
    own = _sign_in("nour@example.com").get("/api/applications/mine").json()

    preview = admin.get(f"/api/affiliates/{nour['id']}/portal/application").json()

    assert preview == {"applied": own["applied"], "status": own["status"]}


def test_the_ranking_marks_her_row_not_the_viewers(admin):
    nour = _model(admin)
    _model(admin, name="Salma", email="salma@example.com", code="SALMA10")

    rows = admin.get(f"/api/affiliates/{nour['id']}/portal/ranking/{SEPTEMBER}").json()["rows"]

    assert [row["affiliate_id"] for row in rows if row["is_me"]] == [nour["id"]]
    # M02 still holds in the preview: only her own sales leave the server.
    assert all(row["sales"] is None for row in rows if not row["is_me"])


def test_a_look_is_audited_under_the_staff_member_and_never_as_her(admin):
    nour = _model(admin)

    assert admin.get(f"/api/affiliates/{nour['id']}/portal").status_code == 200

    with engine.connect() as connection:
        rows = connection.execute(
            text(
                "SELECT actor_email, subject FROM audit_event "
                "WHERE action = 'portal.previewed'"
            )
        ).all()
    assert rows == [(BOOTSTRAP["email"], f"affiliate:{nour['id']}")]


def test_the_audit_screen_says_it_in_words():
    from app.services.audit_words import _Names, sentence

    names = _Names.__new__(_Names)
    names.affiliates = {6: "Nour Hassan"}
    names.users = {1: "Owner"}
    names.months = {}
    event = SimpleNamespace(
        action="portal.previewed", subject="affiliate:6", before_json=None,
        after_json=None, actor_id=1, actor_email="owner@example.com",
    )

    assert sentence(event, names) == "Looked at Nour Hassan's portal (read only)"


def test_her_payout_details_stay_shortened_in_the_preview(admin):
    nour = _model(admin)

    unmasked = admin.get(f"/api/affiliates/{nour['id']}/portal/payout-destination")

    assert unmasked.status_code == 404


def test_the_preview_router_offers_no_write_at_all():
    from app.api.portal_preview import router

    writable = [
        (sorted(route.methods), route.path)
        for route in router.routes
        if set(route.methods) - {"GET", "HEAD", "OPTIONS"}
    ]
    assert writable == []


def test_every_preview_route_is_behind_the_staff_permission():
    from app.api.portal_preview import GUARD, router

    def calls(dependant):
        for dependency in dependant.dependencies:
            yield dependency.call
            yield from calls(dependency)

    assert router.routes
    for route in router.routes:
        assert GUARD in set(calls(route.dependant)), route.path


def test_a_model_cannot_preview_anybody_herself_included(admin):
    nour = _model(admin)
    salma = _model(admin, name="Salma", email="salma@example.com", code="SALMA10")
    hers = _sign_in("nour@example.com")

    assert hers.get(f"/api/affiliates/{salma['id']}/portal").status_code == 403
    assert hers.get(f"/api/affiliates/{nour['id']}/portal").status_code == 403


def test_staff_without_access_to_models_are_refused(admin):
    nour = _model(admin)
    _account("inbox@example.com", role="customer_service")
    inbox = _sign_in("inbox@example.com")

    assert inbox.get(f"/api/affiliates/{nour['id']}/portal").status_code == 403


def test_signed_out_is_refused(admin):
    nour = _model(admin)

    assert TestClient(app).get(f"/api/affiliates/{nour['id']}/portal").status_code == 401


def test_a_model_who_does_not_exist_is_not_found(admin):
    assert admin.get("/api/affiliates/999999/portal").status_code == 404


def test_only_the_preview_frame_may_be_framed_and_only_by_our_own_pages():
    """`X-Frame-Options: DENY` everywhere else, as before: clickjacking."""
    client = TestClient(app)

    frame = client.get("/affiliates/3/portal/frame")
    assert frame.headers["x-frame-options"] == "SAMEORIGIN"
    assert frame.headers["content-security-policy"] == "frame-ancestors 'self'"

    for elsewhere in ("/affiliates/3/portal", "/affiliates/3", "/api/affiliates/3/portal",
                      "/affiliates/3/portal/frame/extra", "/sign-in"):
        assert client.get(elsewhere).headers["x-frame-options"] == "DENY", elsewhere


def test_her_own_routes_still_refuse_staff(admin):
    """ADR 0006 is unchanged: the preview is a second gate, not a merged one."""
    _model(admin)

    assert admin.get("/api/me").status_code == 403
    assert admin.put("/api/me/measurements", json={}).status_code == 403
