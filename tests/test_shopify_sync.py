"""Fetching one order from Shopify and indexing it.

The webhook told us *which* order changed. This is where we ask Shopify what
that order actually is - the webhook body is never trusted as data.
"""

import logging
import subprocess
import sys
from pathlib import Path

import httpx
import pytest

from app.core.signals import Anomaly
from app.models.orders import OrderIndex
from app.services.jobs import PermanentFailure
from app.services.shopify.client import (
    ShopifyClient,
    ShopifyError,
    ShopifyMissingScope,
    ShopifyNotConfigured,
)
from app.services.shopify.sync import build_client, order_gid, sync_one_order

ORDER_NODE = {
    "id": "gid://shopify/Order/5123456789",
    "legacyResourceId": "5123456789",
    "name": "#29115",
    "createdAt": "2026-08-18T16:36:00Z",
    "updatedAt": "2026-08-18T16:36:00Z",
    "cancelledAt": None,
    "displayFinancialStatus": "PAID",
    "displayFulfillmentStatus": "FULFILLED",
    "discountCodes": ["HBA10"],
    "currentSubtotalPriceSet": {
        "shopMoney": {"amount": "1062.00", "currencyCode": "EGP"}
    },
    "currentTotalPriceSet": {"shopMoney": {"amount": "1157.00", "currencyCode": "EGP"}},
    "totalShippingPriceSet": {"shopMoney": {"amount": "95.00", "currencyCode": "EGP"}},
    "currentTotalTaxSet": {"shopMoney": {"amount": "0.00", "currencyCode": "EGP"}},
}


def _client_returning(node, capture: dict | None = None):
    def handler(request: httpx.Request) -> httpx.Response:
        if capture is not None:
            capture["body"] = request.read().decode()
        return httpx.Response(200, json={"data": {"order": node}})

    return ShopifyClient(
        shop_domain="hbawear.myshopify.com",
        access_token="shpat_test",
        api_version="2026-07",
        transport=httpx.MockTransport(handler),
    )


def _client_failing(payload):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload)

    return ShopifyClient(
        shop_domain="s.myshopify.com",
        access_token="t",
        api_version="2026-07",
        transport=httpx.MockTransport(handler),
    )


# ── Fetching and indexing ──────────────────────────────────────────────────────


def test_an_order_is_fetched_and_indexed(db):
    row = sync_one_order(db, "5123456789", client=_client_returning(ORDER_NODE))
    db.flush()

    assert row.shopify_order_id == "5123456789"
    assert row.order_number == "#29115"
    assert row.discount_codes == ["HBA10"]
    assert row.total_piastres == 115_700
    assert row.subtotal_piastres == 106_200
    assert row.shipping_piastres == 9_500


def test_the_business_month_is_derived_not_taken_from_shopify(db):
    """Shopify sends UTC. The month an order belongs to is a Cairo question."""
    row = sync_one_order(db, "5123456789", client=_client_returning(ORDER_NODE))
    db.flush()
    assert row.business_month == "2026-08"


def test_syncing_the_same_order_twice_leaves_one_row(db):
    """A lease can expire and hand the same job to another worker, so running
    twice must be indistinguishable from running once.
    """
    sync_one_order(db, "5123456789", client=_client_returning(ORDER_NODE))
    db.flush()
    sync_one_order(db, "5123456789", client=_client_returning(ORDER_NODE))
    db.flush()
    assert db.query(OrderIndex).count() == 1


def test_a_later_sync_updates_the_row(db):
    """An order that was PAID and is now REFUNDED must not stay PAID."""
    sync_one_order(db, "5123456789", client=_client_returning(ORDER_NODE))
    db.flush()

    changed = dict(ORDER_NODE, displayFinancialStatus="REFUNDED")
    row = sync_one_order(db, "5123456789", client=_client_returning(changed))
    db.flush()

    assert row.financial_status == "refunded"
    assert db.query(OrderIndex).count() == 1


# ── Addressing ─────────────────────────────────────────────────────────────────


def test_a_numeric_id_is_turned_into_a_gid(db):
    """Shopify's GraphQL API addresses orders by global id, not legacy id."""
    capture: dict = {}
    sync_one_order(db, "5123456789", client=_client_returning(ORDER_NODE, capture))
    assert "gid://shopify/Order/5123456789" in capture["body"]


def test_a_gid_is_passed_through_unchanged():
    assert order_gid("gid://shopify/Order/7") == "gid://shopify/Order/7"


def test_a_numeric_id_becomes_a_gid():
    assert order_gid("7") == "gid://shopify/Order/7"


def test_an_integer_id_is_accepted():
    """Shopify's webhook payloads carry ids as numbers, not strings."""
    assert order_gid(5123456789) == "gid://shopify/Order/5123456789"


# ── An order that is not there ─────────────────────────────────────────────────


def test_an_order_that_no_longer_exists_returns_none(db):
    """A deleted order is not an error; it simply has nothing to index.

    Raising would retry forever against an order that will never come back.
    """
    assert sync_one_order(db, "999", client=_client_returning(None)) is None


def test_an_order_that_is_not_there_is_reported(db, caplog):
    """Normal in isolation, and the answer to "why is this order missing from
    the dashboard?" - so it must not vanish into silence.
    """
    with caplog.at_level(logging.WARNING, logger="hba.anomaly"):
        sync_one_order(db, "999", client=_client_returning(None))

    assert Anomaly.ORDER_NOT_FOUND in caplog.text
    assert "999" in caplog.text


def test_an_order_that_is_there_is_not_reported(db, caplog):
    with caplog.at_level(logging.WARNING, logger="hba.anomaly"):
        sync_one_order(db, "5123456789", client=_client_returning(ORDER_NODE))
    assert Anomaly.ORDER_NOT_FOUND not in caplog.text


# ── Failures that should retry, and failures that should not ───────────────────


def test_a_shopify_failure_propagates_so_the_job_retries(db):
    with pytest.raises(ShopifyError):
        sync_one_order(
            db, "1", client=_client_failing({"errors": [{"message": "bad query"}]})
        )


def test_a_missing_credential_fails_permanently_rather_than_retrying(db, monkeypatch):
    """No amount of retrying supplies a credential. Retrying only delays the
    signal by eight minutes and buries it under four identical failures.

    The client refuses to be built without configuration, so this fails inside
    build_client - which is why building has to happen inside the guard.
    """
    monkeypatch.setattr("app.config.settings.shopify_shop_domain", "")

    with pytest.raises(PermanentFailure) as caught:
        sync_one_order(db, "1")
    assert isinstance(caught.value.__cause__, ShopifyNotConfigured)


def test_a_missing_scope_fails_permanently_rather_than_retrying(db):
    """read_discounts is granted by a person, not by waiting."""

    def handler(request: httpx.Request) -> httpx.Response:
        raise ShopifyMissingScope("read_discounts is not granted")

    client = ShopifyClient(
        shop_domain="s.myshopify.com",
        access_token="t",
        transport=httpx.MockTransport(handler),
    )
    with pytest.raises(PermanentFailure):
        sync_one_order(db, "1", client=client)


def test_a_permanent_failure_names_the_order(db, monkeypatch):
    """last_error is what someone reads during an incident."""
    monkeypatch.setattr("app.config.settings.shopify_shop_domain", "")

    with pytest.raises(PermanentFailure, match="5123456789"):
        sync_one_order(db, "5123456789")


# ── The handler the worker runs ────────────────────────────────────────────────


def test_starting_the_application_registers_the_handler():
    """The registration happens as a side effect of importing the module, from
    a line in app.main that looks removable and is not.

    Without it the worker leases every shopify_sync_order job, finds no
    handler, fails it permanently, and no order ever syncs - while the webhook
    endpoint keeps returning 200 as though everything were fine.

    Run in a fresh interpreter on purpose. This test file imports the sync
    module itself, so an in-process assertion would pass whether or not
    app.main does the import - which is exactly the bug being guarded against.
    """
    probe = (
        "import app.main;"
        "from app.api.webhooks import SYNC_ORDER;"
        "from app.worker import HANDLERS;"
        "assert SYNC_ORDER in HANDLERS, SYNC_ORDER;"
        "print('registered')"
    )
    result = subprocess.run(
        [sys.executable, "-c", probe],
        capture_output=True,
        text=True,
        cwd=Path(__file__).resolve().parents[1],
    )
    assert result.returncode == 0, (
        "importing app.main did not register the order sync handler - every "
        f"sync job will fail with no_handler.\n{result.stderr}"
    )
    assert "registered" in result.stdout


def test_the_handler_syncs_the_order_in_its_payload(db, monkeypatch):
    seen = []

    def fake_sync(session, order_id, client=None):
        seen.append(order_id)

    monkeypatch.setattr("app.services.shopify.sync.sync_one_order", fake_sync)

    from app.worker import HANDLERS

    HANDLERS["shopify_sync_order"](db, {"order_id": "5123456789"})
    assert seen == ["5123456789"]


def test_the_handler_refuses_a_payload_with_no_order_permanently(db):
    """A job that cannot name an order will never succeed."""
    from app.worker import HANDLERS

    with pytest.raises(PermanentFailure):
        HANDLERS["shopify_sync_order"](db, {})


# ── Building a client from configuration ───────────────────────────────────────


def test_building_a_client_without_configuration_fails_clearly(monkeypatch):
    monkeypatch.setattr("app.config.settings.shopify_shop_domain", "")
    monkeypatch.setattr("app.config.settings.shopify_access_token", "")
    monkeypatch.setattr("app.config.settings.shopify_client_id", "")
    monkeypatch.setattr("app.config.settings.shopify_client_secret", "")

    with pytest.raises(ShopifyNotConfigured):
        build_client()


def test_building_a_client_passes_the_client_credentials(monkeypatch):
    """The app is a Dev Dashboard app: an id and secret, no permanent token
    (ADR 0015). A build_client forwarding only the token would pass every test
    written against a token and fail against the real shop.

    Asserted through behaviour rather than by reading private attributes: the
    client refuses to be constructed with neither a token nor a credential
    pair, so building at all proves the pair was forwarded.
    """
    monkeypatch.setattr("app.config.settings.shopify_shop_domain", "s.myshopify.com")
    monkeypatch.setattr("app.config.settings.shopify_access_token", "")
    monkeypatch.setattr("app.config.settings.shopify_client_id", "the-id")
    monkeypatch.setattr("app.config.settings.shopify_client_secret", "the-secret")

    assert build_client().shop_domain == "s.myshopify.com"


def test_building_a_client_with_only_half_a_credential_pair_fails(monkeypatch):
    """Guards the test above, which would pass if the token were forwarded and
    the pair silently dropped.
    """
    monkeypatch.setattr("app.config.settings.shopify_shop_domain", "s.myshopify.com")
    monkeypatch.setattr("app.config.settings.shopify_access_token", "")
    monkeypatch.setattr("app.config.settings.shopify_client_id", "the-id")
    monkeypatch.setattr("app.config.settings.shopify_client_secret", "")

    with pytest.raises(ShopifyNotConfigured):
        build_client()


def test_a_built_client_never_exposes_its_secret_in_repr(monkeypatch):
    monkeypatch.setattr("app.config.settings.shopify_shop_domain", "s.myshopify.com")
    monkeypatch.setattr("app.config.settings.shopify_client_id", "the-id")
    monkeypatch.setattr("app.config.settings.shopify_client_secret", "super-secret")

    assert "super-secret" not in repr(build_client())
