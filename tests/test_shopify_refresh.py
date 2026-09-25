"""*Refresh now* and *last successful refresh* (Settings → Shopify, item 17).

A refresh is the reconciliation sweep brought forward. These tests drive the
whole action - the request, the worker running the sweep against a simulated
Shopify, and what the card reads afterwards - through success, failure,
a retry and a double click. Nothing here reaches a shop.
"""

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.db import SessionLocal, engine
from app.main import app
from app.services.jobs import JobKind
from app.services.shopify.client import ShopifyClient
from app.worker import run_one

BOOTSTRAP = {"email": "owner@example.com", "display_name": "Owner", "password": "quiet-harbour-lantern"}
URL = "/api/operations/refresh"


@pytest.fixture()
def client(fresh_database, monkeypatch):
    monkeypatch.setattr("app.config.settings.shopify_shop_domain", "hbawear.myshopify.com")
    monkeypatch.setattr("app.config.settings.shopify_access_token", "shpat_test")
    monkeypatch.setattr("app.config.settings.shopify_client_id", "")
    monkeypatch.setattr("app.config.settings.shopify_client_secret", "")
    with TestClient(app) as test_client:
        response = test_client.post("/api/auth/bootstrap", json=BOOTSTRAP)
        assert response.status_code == 201, response.text
        test_client.headers["X-CSRF-Token"] = response.json()["csrf"]
        yield test_client


def _order(order_id: str) -> dict:
    return {
        "id": f"gid://shopify/Order/{order_id}",
        "legacyResourceId": order_id,
        "name": f"#{order_id}",
        "createdAt": "2026-09-24T10:00:00Z",
        "updatedAt": "2026-09-24T10:00:00Z",
        "cancelledAt": None,
        "displayFinancialStatus": "PAID",
        "displayFulfillmentStatus": "FULFILLED",
        "discountCodes": [],
        "currentSubtotalPriceSet": {"shopMoney": {"amount": "100.00", "currencyCode": "EGP"}},
        "currentTotalPriceSet": {"shopMoney": {"amount": "110.00", "currencyCode": "EGP"}},
        "totalShippingPriceSet": {"shopMoney": {"amount": "10.00", "currencyCode": "EGP"}},
        "currentTotalTaxSet": {"shopMoney": {"amount": "0.00", "currencyCode": "EGP"}},
    }


def _shopify(monkeypatch, *, status: int = 200, requests: list | None = None):
    """Stand in for the shop. Records every request so reads can be checked."""

    def handler(request: httpx.Request) -> httpx.Response:
        if requests is not None:
            requests.append(request.read().decode())
        if status != 200:
            return httpx.Response(status, json={"errors": "no"})
        return httpx.Response(200, json={"data": {"orders": {
            "pageInfo": {"hasNextPage": False, "endCursor": None},
            "nodes": [_order("9001"), _order("9002")],
        }}})

    def build():
        shop = ShopifyClient(
            shop_domain="hbawear.myshopify.com",
            access_token="shpat_test",
            transport=httpx.MockTransport(handler),
        )
        shop.retry_base_seconds = 0
        return shop

    monkeypatch.setattr("app.services.shopify.sync.build_client", build)


def _work():
    """What the worker does: take one due job and run it."""
    with SessionLocal() as db:
        return run_one(db, "test-worker")


def _state(client):
    return client.get("/api/operations/sync").json()["refresh"]


def _reconciles():
    with engine.connect() as connection:
        return connection.execute(text(
            "SELECT status FROM background_job WHERE kind = :k ORDER BY id"
        ), {"k": JobKind.RECONCILE}).scalars().all()


def test_nothing_has_refreshed_yet(client):
    assert _state(client) == {
        "state": "never", "last_success_at": None, "failed_at": None, "error_line": None,
    }


def test_accepted_is_not_refreshed_and_finishing_is(client, monkeypatch):
    requests = []
    _shopify(monkeypatch, requests=requests)

    response = client.post(URL)
    assert response.status_code == 200
    body = response.json()
    assert body["accepted"] is True
    # Accepted: queued, and *last successful refresh* has not moved.
    assert body["refresh"]["state"] == "queued"
    assert body["refresh"]["last_success_at"] is None

    assert _work() is True
    after = _state(client)
    assert after["state"] == "succeeded"
    assert after["last_success_at"] is not None
    # It read orders - the query, never a mutation - and indexed them.
    assert requests and all("mutation" not in r for r in requests)
    assert "updated_at:>=" in requests[0]
    with engine.connect() as connection:
        assert connection.execute(text("SELECT count(*) FROM order_index")).scalar() == 2


def test_a_failure_keeps_the_last_success_and_says_so(client, monkeypatch):
    _shopify(monkeypatch)
    client.post(URL)
    _work()
    first_success = _state(client)["last_success_at"]

    _shopify(monkeypatch, status=429)
    client.post(URL)
    _work()

    after = _state(client)
    assert after["state"] == "failed"
    assert after["last_success_at"] == first_success
    assert "429" in after["error_line"]
    assert "Nothing from this attempt was saved" in after["error_line"]
    # No token, domain or raw exception text reaches the page.
    assert "shpat" not in after["error_line"] and "ShopifyError" not in after["error_line"]


def test_try_again_brings_the_retry_forward_and_can_succeed(client, monkeypatch):
    _shopify(monkeypatch, status=401)
    client.post(URL)
    _work()
    failed = _state(client)
    assert failed["state"] == "failed" and failed["last_success_at"] is None
    assert "refused the saved connection" in failed["error_line"]

    # *Try again*: the waiting retry is due now, not a second job.
    retry = client.post(URL).json()
    assert retry["refresh"]["state"] == "queued"
    assert _reconciles() == ["pending"]

    _shopify(monkeypatch)
    _work()
    assert _state(client)["state"] == "succeeded"
    assert _reconciles() == ["succeeded"]


def test_double_clicks_make_one_job(client, monkeypatch):
    _shopify(monkeypatch)
    ids = {client.post(URL).json()["job_id"] for _ in range(3)}

    assert len(ids) == 1
    assert _reconciles() == ["pending"]


def test_a_click_while_one_is_running_joins_it(client, monkeypatch):
    _shopify(monkeypatch)
    first = client.post(URL).json()["job_id"]
    with engine.begin() as connection:
        connection.execute(text(
            "UPDATE background_job SET status = 'running', leased_by = 'w', "
            "leased_until = now() + interval '1 minute' WHERE id = :i"
        ), {"i": first})

    assert _state(client)["state"] == "running"
    again = client.post(URL).json()
    assert again["job_id"] == first and again["joined_running"] is True
    assert _reconciles() == ["running"]


def test_the_scheduled_sweep_is_brought_forward_not_duplicated(client, monkeypatch):
    from app.services.schedule import ensure_scheduled

    _shopify(monkeypatch)
    with SessionLocal() as db:
        ensure_scheduled(db)
        db.commit()
    # Scheduled half an hour out: connected, nothing finished, nothing due.
    assert _state(client)["state"] == "never"

    client.post(URL)
    assert _reconciles() == ["pending"]
    assert _state(client)["state"] == "queued"
    assert _work() is True
    assert _state(client)["state"] == "succeeded"


def test_without_a_connection_nothing_is_queued(client, monkeypatch):
    monkeypatch.setattr("app.config.settings.shopify_shop_domain", "")
    monkeypatch.setattr("app.config.settings.shopify_access_token", "")

    response = client.post(URL)

    assert response.status_code == 409
    assert _reconciles() == []
    assert _state(client)["state"] == "not_connected"


def test_only_staff_who_manage_settings_can_refresh(client, monkeypatch):
    _shopify(monkeypatch)
    with engine.begin() as connection:
        connection.execute(text("UPDATE role_assignment SET role = 'affiliate_manager'"))

    assert client.post(URL).status_code == 403
    assert _reconciles() == []
