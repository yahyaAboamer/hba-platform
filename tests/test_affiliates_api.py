"""The affiliate registry, over HTTP.

Spec section 6.5: a model may never edit anything determining what they are
owed. The `affiliate` role holds no permissions at all, so it must be refused
by every endpoint here - and that is a claim proven per endpoint, not assumed.

`compensation.manage` is checked separately from `affiliates.manage` on the
compensation route. No role in the current bundles grants one without the
other (ADR 0018 - Sara's role deliberately holds both), so there is no
existing role to prove a *wrong*-permission 403 with. What is proven instead:
the affiliate role (which holds neither) is refused, and the admin role
(which holds both) succeeds - which is what every other endpoint's test
proves too, and is the honest version of "enforced server-side" available
today.
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
def anonymous(fresh_database):
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture()
def client(fresh_database):
    """Signed in as the administrator."""
    with TestClient(app) as test_client:
        response = test_client.post("/api/auth/bootstrap", json=BOOTSTRAP)
        assert response.status_code == 201, response.text
        test_client.headers["X-CSRF-Token"] = response.json()["csrf"]
        yield test_client


def _demote_to(role: str) -> None:
    """Change the signed-in account's role without touching its session."""
    with engine.begin() as connection:
        connection.execute(text("UPDATE role_assignment SET role = :r"), {"r": role})


def _make_account(email: str) -> int:
    """A bare user_account, as if created by an accepted invitation."""
    with engine.begin() as connection:
        return connection.execute(
            text(
                "INSERT INTO user_account (email, password_hash, status, display_name) "
                "VALUES (:e, :p, 'active', 'Nour') RETURNING id"
            ),
            {"e": email, "p": hash_password("a-long-enough-password")},
        ).scalar()


@pytest.fixture(autouse=True)
def _shopify(monkeypatch):
    """Registering a code now looks it up in Shopify.

    Autouse and controllable: `_shopify_says` changes what the fake shop
    returns, so tests can cover a code created in March, one Shopify has never
    heard of, and Shopify being unreachable.
    """
    state = {"created_at": None, "exists": True, "error": None}

    def fake_verify(_client, code):
        if state["error"] is not None:
            raise state["error"]
        normalised = str(code).strip().upper()
        if not state["exists"]:
            return {
                "exists": False,
                "code": normalised,
                "status": None,
                "discount_bp": None,
                "usage_count": None,
                "title": None,
                "created_at": None,
            }
        return {
            "exists": True,
            "code": normalised,
            "status": "ACTIVE",
            "discount_bp": 1000,
            "usage_count": 3,
            "title": normalised,
            "created_at": state["created_at"],
        }

    monkeypatch.setattr("app.api.affiliates.verify_discount_code", fake_verify)
    monkeypatch.setattr("app.services.shopify.sync.build_client", lambda: object())
    return state


def _shopify_says(shopify, *, created_at=None, exists=True, error=None):
    shopify.update(created_at=created_at, exists=exists, error=error)


def _add_order(order_id: str, code: str, *, month: str = "2026-08") -> None:
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO order_index (shopify_order_id, order_number, placed_at, "
                "business_month, discount_codes, subtotal_piastres, total_piastres, "
                "shipping_piastres, tax_piastres, currency) "
                "VALUES (:i, :n, now(), :m, ARRAY[:c], 0, 0, 0, 0, 'EGP')"
            ),
            {"i": order_id, "n": f"#{order_id}", "m": month, "c": code},
        )


def _register(client, name="Nour", email="nour@example.com", **overrides) -> dict:
    account_id = _make_account(email)
    body = {"user_account_id": account_id, "name": name, **overrides}
    response = client.post("/api/affiliates", json=body)
    assert response.status_code == 201, response.text
    return response.json()


# ── Nothing here is reachable by an affiliate, or by nobody ────────────────────


ENDPOINTS = [
    ("GET", "/api/affiliates", None),
    ("POST", "/api/affiliates", {"user_account_id": 1, "name": "X"}),
]


@pytest.mark.parametrize(("method", "path", "body"), ENDPOINTS)
def test_endpoints_require_authentication(anonymous, method, path, body):
    response = anonymous.request(method, path, json=body)
    assert response.status_code == 401


def test_reading_an_affiliate_requires_authentication(anonymous):
    assert anonymous.get("/api/affiliates/1").status_code == 401


def test_writing_requires_authentication(anonymous):
    for method, path in [
        ("PATCH", "/api/affiliates/1"),
        ("POST", "/api/affiliates/1/codes"),
        ("POST", "/api/affiliates/1/compensation"),
        ("PUT", "/api/affiliates/1/payout-destination"),
    ]:
        response = anonymous.request(method, path, json={})
        assert response.status_code == 401, path


def test_an_affiliate_cannot_list_or_read(client):
    account_id = _make_account("nour@example.com")
    _demote_to("affiliate")
    assert client.get("/api/affiliates").status_code == 403
    assert client.get(f"/api/affiliates/{account_id}").status_code == 403


def test_an_affiliate_cannot_create_or_change_anything(client):
    """§6.5. A model may never edit anything determining what they are owed."""
    _demote_to("affiliate")
    assert client.post(
        "/api/affiliates", json={"user_account_id": 1, "name": "X"}
    ).status_code == 403
    assert client.patch("/api/affiliates/1", json={"status": "active"}).status_code == 403
    assert client.post(
        "/api/affiliates/1/codes",
        json={"code": "X10"},
    ).status_code == 403
    assert client.post(
        "/api/affiliates/1/compensation",
        json={
            "start_month": "2026-01",
            "compensation_type": "commission",
            "commission_rate_bp": 1000,
        },
    ).status_code == 403
    assert client.put(
        "/api/affiliates/1/payout-destination",
        json={"method": "instapay", "instapay_address_url": "https://ipn.eg/x"},
    ).status_code == 403


# ── Creating and listing ────────────────────────────────────────────────────────


def test_creating_an_affiliate(client):
    body = _register(client)
    assert body["name"] == "Nour"
    assert body["status"] == "pending"
    assert body["account_kind"] == "model"
    assert body["is_payable"] is True


def test_a_house_account_is_created_as_such(client):
    body = _register(client, name="House", email="house@example.com", account_kind="house")
    assert body["account_kind"] == "house"
    assert body["is_payable"] is False


def test_an_unknown_account_kind_is_refused(client):
    account_id = _make_account("nour@example.com")
    response = client.post(
        "/api/affiliates",
        json={"user_account_id": account_id, "name": "Nour", "account_kind": "vip"},
    )
    assert response.status_code == 400


def test_registering_a_nonexistent_account_is_refused(client):
    response = client.post(
        "/api/affiliates", json={"user_account_id": 999999, "name": "Nobody"}
    )
    assert response.status_code == 409


def test_registering_the_same_account_twice_is_refused(client):
    account_id = _make_account("nour@example.com")
    first = client.post(
        "/api/affiliates", json={"user_account_id": account_id, "name": "Nour"}
    )
    assert first.status_code == 201
    second = client.post(
        "/api/affiliates", json={"user_account_id": account_id, "name": "Nour Again"}
    )
    assert second.status_code == 409


def test_listing_shows_created_affiliates(client):
    _register(client, "Nour", "nour@example.com")
    _register(client, "Sara", "sara@example.com")
    body = client.get("/api/affiliates").json()
    assert sorted(a["name"] for a in body["affiliates"]) == ["Nour", "Sara"]


def test_listing_excludes_archived_by_default(client):
    affiliate = _register(client)
    client.patch(f"/api/affiliates/{affiliate['id']}", json={"status": "archived"})

    assert client.get("/api/affiliates").json()["affiliates"] == []
    included = client.get("/api/affiliates?include_archived=true").json()["affiliates"]
    assert len(included) == 1


# ── Reading one ──────────────────────────────────────────────────────────────────


def test_reading_an_unknown_affiliate_is_404(client):
    assert client.get("/api/affiliates/999999").status_code == 404


def test_reading_a_fresh_affiliate_shows_nothing_set_yet(client):
    affiliate = _register(client)
    body = client.get(f"/api/affiliates/{affiliate['id']}").json()
    assert body["codes"] == []
    assert body["compensation"] is None
    assert body["payout_destination"] is None
    assert "current_month" in body


# ── Status ─────────────────────────────────────────────────────────────────────


def _verify_code(client, affiliate_id, code="NOUR10"):
    """Register a code already confirmed against Shopify - the approval gate."""
    response = client.post(
        f"/api/affiliates/{affiliate_id}/codes",
        json={"code": code},
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_updating_status(client):
    affiliate = _register(client)
    _verify_code(client, affiliate["id"])
    response = client.patch(
        f"/api/affiliates/{affiliate['id']}", json={"status": "active"}
    )
    assert response.status_code == 200
    assert response.json()["status"] == "active"


def test_archiving_stamps_archived_at(client):
    affiliate = _register(client)
    response = client.patch(
        f"/api/affiliates/{affiliate['id']}", json={"status": "archived"}
    )
    assert response.json()["archived_at"] is not None


def test_an_unknown_status_is_refused(client):
    affiliate = _register(client)
    response = client.patch(
        f"/api/affiliates/{affiliate['id']}", json={"status": "vip"}
    )
    assert response.status_code == 400


def test_updating_an_unknown_affiliate_is_404(client):
    assert client.patch(
        "/api/affiliates/999999", json={"status": "active"}
    ).status_code == 404


# ── Discount codes ─────────────────────────────────────────────────────────────


def test_registering_a_code(client):
    affiliate = _register(client)
    response = client.post(
        f"/api/affiliates/{affiliate['id']}/codes",
        json={"code": "nour10"},
    )
    assert response.status_code == 201
    body = response.json()
    assert body["code"] == "NOUR10"
    assert body["is_verified"] is True
    assert body["exists_in_shopify"] is True


def test_a_registered_code_shows_up_on_the_affiliate(client):
    """Open-ended from January, so it covers whatever month the suite runs in."""
    affiliate = _register(client)
    client.post(
        f"/api/affiliates/{affiliate['id']}/codes",
        json={"code": "NOUR10"},
    )
    body = client.get(f"/api/affiliates/{affiliate['id']}").json()
    assert body["codes"] == ["NOUR10"]


def test_two_affiliates_cannot_own_the_same_code_at_once(client):
    """The rule the whole task exists to expose over HTTP."""
    nour = _register(client, "Nour", "nour@example.com")
    sara = _register(client, "Sara", "sara@example.com")
    client.post(
        f"/api/affiliates/{nour['id']}/codes",
        json={"code": "SHARED"},
    )
    response = client.post(
        f"/api/affiliates/{sara['id']}/codes",
        json={"code": "SHARED"},
    )
    assert response.status_code == 409


def test_no_month_can_be_supplied_at_all(client):
    """The field is gone, not merely defaulted.

    An extra key is ignored rather than honoured - there is one right start
    month and it is derived, so a caller cannot override it into orphaning
    their own history.
    """
    affiliate = _register(client)
    response = client.post(
        f"/api/affiliates/{affiliate['id']}/codes",
        json={"code": "NOUR10", "start_month": "2026-06"},
    )
    assert response.status_code == 201
    assert response.json()["start_month"] == "2026-01"


def test_registering_a_code_for_an_unknown_affiliate_is_404(client):
    response = client.post(
        "/api/affiliates/999999/codes",
        json={"code": "NOUR10"},
    )
    assert response.status_code == 404


# ── Compensation ───────────────────────────────────────────────────────────────


def test_setting_compensation(client):
    affiliate = _register(client)
    response = client.post(
        f"/api/affiliates/{affiliate['id']}/compensation",
        json={
            "start_month": "2026-01",
            "compensation_type": "commission",
            "commission_rate_bp": 1000,
        },
    )
    assert response.status_code == 201
    body = response.json()
    assert body["compensation_type"] == "commission"
    assert body["commission_rate_bp"] == 1000


def test_a_base_guarantee_requires_a_base_amount(client):
    affiliate = _register(client)
    response = client.post(
        f"/api/affiliates/{affiliate['id']}/compensation",
        json={
            "start_month": "2026-01",
            "compensation_type": "base_guarantee",
            "commission_rate_bp": 1000,
        },
    )
    assert response.status_code == 400


def test_overlapping_compensation_periods_are_refused(client):
    affiliate = _register(client)
    client.post(
        f"/api/affiliates/{affiliate['id']}/compensation",
        json={
            "start_month": "2026-01",
            "end_month": "2026-06",
            "compensation_type": "commission",
            "commission_rate_bp": 800,
        },
    )
    response = client.post(
        f"/api/affiliates/{affiliate['id']}/compensation",
        json={
            "start_month": "2026-04",
            "compensation_type": "commission",
            "commission_rate_bp": 1000,
        },
    )
    assert response.status_code == 409


def test_an_unknown_compensation_type_is_refused(client):
    affiliate = _register(client)
    response = client.post(
        f"/api/affiliates/{affiliate['id']}/compensation",
        json={
            "start_month": "2026-01",
            "compensation_type": "generous",
            "commission_rate_bp": 1000,
        },
    )
    assert response.status_code == 400


def test_current_compensation_shows_up_on_the_affiliate(client):
    affiliate = _register(client)
    client.post(
        f"/api/affiliates/{affiliate['id']}/compensation",
        json={
            "start_month": "2026-01",
            "compensation_type": "commission",
            "commission_rate_bp": 1234,
        },
    )
    body = client.get(f"/api/affiliates/{affiliate['id']}").json()
    assert body["compensation"]["commission_rate_bp"] == 1234


def test_setting_compensation_for_an_unknown_affiliate_is_404(client):
    response = client.post(
        "/api/affiliates/999999/compensation",
        json={
            "start_month": "2026-01",
            "compensation_type": "commission",
            "commission_rate_bp": 1000,
        },
    )
    assert response.status_code == 404


# ── Payout destination ──────────────────────────────────────────────────────────


def test_setting_a_payout_destination_returns_it_masked(client):
    """Even freshly typed by the caller, the raw value is never echoed back."""
    affiliate = _register(client)
    response = client.put(
        f"/api/affiliates/{affiliate['id']}/payout-destination",
        json={
            "method": "instapay",
            "instapay_address_url": "https://ipn.eg/S/nour.mahmoud/instapay/8Xk2Qp",
            "instapay_phone": "01001234567",
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert "nour.mahmoud" not in str(body)
    assert "01001234567" not in str(body)
    assert body["method"] == "instapay"


def test_an_instapay_destination_without_an_address_is_refused(client):
    affiliate = _register(client)
    response = client.put(
        f"/api/affiliates/{affiliate['id']}/payout-destination",
        json={"method": "instapay"},
    )
    assert response.status_code == 400


def test_the_current_destination_shows_up_masked_on_the_affiliate(client):
    affiliate = _register(client)
    client.put(
        f"/api/affiliates/{affiliate['id']}/payout-destination",
        json={
            "method": "instapay",
            "instapay_address_url": "https://ipn.eg/S/nour.mahmoud/instapay/8Xk2Qp",
        },
    )
    body = client.get(f"/api/affiliates/{affiliate['id']}").json()
    assert body["payout_destination"] is not None
    assert body["payout_destination"]["method"] == "instapay"
    assert "nour.mahmoud" not in str(body)


def test_setting_a_destination_for_an_unknown_affiliate_is_404(client):
    response = client.put(
        "/api/affiliates/999999/payout-destination",
        json={"method": "instapay", "instapay_address_url": "https://ipn.eg/x"},
    )
    assert response.status_code == 404


# ── The permitted case actually works ───────────────────────────────────────────


def test_content_manager_can_manage_affiliates_and_compensation(client):
    """Sara's role holds both affiliates.manage and compensation.manage
    (ADR 0018). A uniformly broken endpoint that 403s for everyone must not
    be mistaken for working authorisation.
    """
    account_id = _make_account("nour@example.com")
    _demote_to("content_manager")

    created = client.post(
        "/api/affiliates", json={"user_account_id": account_id, "name": "Nour"}
    )
    assert created.status_code == 201

    response = client.post(
        f"/api/affiliates/{created.json()['id']}/compensation",
        json={
            "start_month": "2026-01",
            "compensation_type": "commission",
            "commission_rate_bp": 1000,
        },
    )
    assert response.status_code == 201


# ── History is captured by default (the flow the business described) ───────────


def test_a_code_older_than_the_platform_starts_at_the_horizon(client, _shopify):
    """Created on Shopify in 2025. There are no orders before 2026 to claim -
    the import does not reach back further.
    """
    from datetime import datetime, timezone

    _shopify_says(_shopify, created_at=datetime(2025, 11, 15, tzinfo=timezone.utc))
    affiliate = _register(client)

    response = client.post(
        f"/api/affiliates/{affiliate['id']}/codes", json={"code": "OLD10"}
    )
    assert response.json()["start_month"] == "2026-01"


def test_a_code_created_after_the_platform_starts_when_it_was_created(client, _shopify):
    """Claiming January would assert ownership of months the code did not
    exist for - and collide with whoever held it before, if anyone did.
    """
    from datetime import datetime, timezone

    _shopify_says(_shopify, created_at=datetime(2026, 3, 4, tzinfo=timezone.utc))
    affiliate = _register(client)

    response = client.post(
        f"/api/affiliates/{affiliate['id']}/codes", json={"code": "NEW10"}
    )
    assert response.json()["start_month"] == "2026-03"


def test_a_code_shopify_has_never_heard_of_is_recorded_unverified(client, _shopify):
    """Some models apply with a code that has not been created yet.

    Refusing to record it would be unhelpful; approving on it would be unsafe.
    So it is stored, marked unverified, and the approval gate stops it becoming
    a paying code until somebody checks.
    """
    _shopify_says(_shopify, exists=False)
    affiliate = _register(client)

    response = client.post(
        f"/api/affiliates/{affiliate['id']}/codes", json={"code": "NOTYET"}
    )
    assert response.status_code == 201
    assert response.json()["is_verified"] is False
    assert response.json()["exists_in_shopify"] is False

    refused = client.patch(
        f"/api/affiliates/{affiliate['id']}", json={"status": "active"}
    )
    assert refused.status_code == 400


def test_registration_fails_loudly_when_shopify_cannot_be_reached(client, _shopify):
    """Registering blind would have to guess the start month, and a wrong
    guess orphans orders silently. Better to fail while somebody is watching.
    """
    from app.services.shopify.client import ShopifyError

    _shopify_says(_shopify, error=ShopifyError("Shopify returned 503"))
    affiliate = _register(client)

    response = client.post(
        f"/api/affiliates/{affiliate['id']}/codes", json={"code": "NOUR10"}
    )
    assert response.status_code == 502


def test_a_default_registration_picks_up_the_orders_already_placed(client):
    """The whole point, end to end: a code already in use stops being reported
    as belonging to nobody the moment it is registered.
    """
    _add_order("1", "NOUR10", month="2026-03")
    _add_order("2", "NOUR10", month="2026-06")

    before = client.get("/api/operations/unregistered-codes").json()["codes"]
    assert {row["code"] for row in before} == {"NOUR10"}

    affiliate = _register(client)
    client.post(f"/api/affiliates/{affiliate['id']}/codes", json={"code": "NOUR10"})

    after = client.get("/api/operations/unregistered-codes").json()["codes"]
    assert after == []


# ── Approval is gated on verification, over HTTP ───────────────────────────────


def test_approving_without_a_verified_code_is_refused(client):
    affiliate = _register(client)
    response = client.patch(
        f"/api/affiliates/{affiliate['id']}", json={"status": "active"}
    )
    assert response.status_code == 400
    assert "Shopify" in response.json()["detail"]


def test_deactivating_never_requires_a_verified_code(client):
    """The gate is on approval, not on every change of status."""
    affiliate = _register(client)
    response = client.patch(
        f"/api/affiliates/{affiliate['id']}", json={"status": "inactive"}
    )
    assert response.status_code == 200
