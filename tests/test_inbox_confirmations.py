"""Whether an order gets a WhatsApp confirmation (ADR 0059; the plan's phase 2).

The engine runs silently for now: it decides what n8n decides and records it
as ``would_send``. Shopify is never called - a mock transport answers - and
every order, name and number here is made up.
"""

from datetime import timedelta

import httpx
import pytest
from sqlalchemy import select, text

from app.core.businesstime import utcnow
from app.models.inbox import OrderConfirmation
from app.models.orders import OrderIndex
from app.services.inbox import confirmations
from app.services.inbox.confirmations import (
    BAD_PHONE,
    CANCELLED,
    NO_PHONE,
    PAID,
    TEST_ORDER,
    confirm_order,
    decide,
    is_cash_on_delivery,
    queue_if_new,
    unconfirmed_recent,
)
from app.services.jobs import INBOX_WORK, JobKind, PermanentFailure
from app.services.shopify.client import ShopifyClient, ShopifyNotConfigured

COD = ["Cash on Delivery (COD)"]
CARD = ["Paymob - Native Checkout for Debit/Credit Cards"]


@pytest.fixture(autouse=True)
def switched_on(monkeypatch):
    """The engine is off unless a server is told otherwise; these tests are
    about what it does when on. The last section turns it off again."""
    monkeypatch.setattr("app.config.settings.inbox_confirmations_enabled", True)


def _iso(moment) -> str:
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def _order(**changes) -> dict:
    node = {
        "legacyResourceId": "5001",
        "name": "#31044",
        "createdAt": _iso(utcnow() - timedelta(minutes=2)),
        "cancelledAt": None,
        "test": False,
        "displayFinancialStatus": "PENDING",
        "paymentGatewayNames": COD,
        "totalPriceSet": {"shopMoney": {"amount": "1450.0"}},
        "phone": None,
        "customer": {"firstName": "Nour", "phone": "+201005550188"},
        "shippingAddress": {"phone": "01005550188"},
    }
    node.update(changes)
    return node


def _shopify(node, asked: list | None = None) -> ShopifyClient:
    def handler(request: httpx.Request) -> httpx.Response:
        if asked is not None:
            asked.append(request.read().decode())
        return httpx.Response(200, json={"data": {"order": node}})

    return ShopifyClient(
        shop_domain="hba-test.myshopify.com",
        access_token="shpat_test",
        api_version="2026-07",
        transport=httpx.MockTransport(handler),
    )


def _indexed(db, order_id="5001", placed=None) -> OrderIndex:
    placed = placed or utcnow() - timedelta(minutes=2)
    row = OrderIndex(
        shopify_order_id=order_id,
        order_number=f"#{order_id}",
        placed_at=placed,
        business_month=placed.strftime("%Y-%m"),
    )
    db.add(row)
    db.flush()
    return row


def _jobs(db) -> list[tuple]:
    db.flush()
    return db.execute(
        text("SELECT kind, payload->>'order_id', dedupe_key FROM background_job ORDER BY id")
    ).all()


# ── The decision ──────────────────────────────────────────────────────────────


def test_a_cash_on_delivery_order_would_get_the_message():
    decision = decide(_order())
    assert decision.state == "would_send"
    assert decision.phone == "201005550188"
    assert decision.customer_name == "Nour"
    assert decision.total_text == "1450.00"
    assert decision.reason is None


@pytest.mark.parametrize(
    ("gateways", "status", "cod"),
    [
        (COD, "PENDING", True),
        (COD, "PAID", True),            # named for cash, whatever the status
        (CARD, "PENDING", True),        # not paid yet, whatever the gateway
        (["CASH ON DELIVERY"], "PAID", True),
        (CARD, "PAID", False),
        ([], "PAID", False),
        (None, None, False),
        (CARD, "AUTHORIZED", False),
    ],
)
def test_cash_on_delivery_is_n8ns_own_test(gateways, status, cod):
    assert is_cash_on_delivery(gateways, status) is cod


def test_a_paid_order_is_finished_not_failed():
    """n8n dropped these unmarked, retried five times and called them failed."""
    decision = decide(_order(paymentGatewayNames=CARD, displayFinancialStatus="PAID"))
    assert (decision.state, decision.reason) == ("not_needed", PAID)
    assert decision.phone is None


def test_a_cancelled_or_test_order_gets_no_message():
    cancelled = decide(_order(cancelledAt="2026-10-11T10:00:00Z"))
    assert (cancelled.state, cancelled.reason) == ("not_needed", CANCELLED)
    test_order = decide(_order(test=True))
    assert (test_order.state, test_order.reason) == ("not_needed", TEST_ORDER)


def test_the_phone_is_the_orders_then_the_customers_then_the_shipping_addresss():
    assert decide(_order(phone="01105550111")).phone == "201105550111"
    assert decide(_order(customer={"firstName": "Nour", "phone": None})).phone == "201005550188"
    customer_only = _order(shippingAddress=None)
    assert decide(customer_only).phone == "201005550188"


def test_a_number_that_cannot_be_read_does_not_hide_one_that_can():
    """n8n took the first number whatever it was. A landline on the order
    with a mobile on the address is still a customer who can be reached."""
    decision = decide(_order(phone="0225550188"))
    assert decision.state == "would_send"
    assert decision.phone == "201005550188"


def test_an_order_with_no_phone_or_no_usable_one_says_which():
    nothing = decide(_order(phone=None, customer={"firstName": "Nour"}, shippingAddress={}))
    assert (nothing.state, nothing.reason) == ("no_phone", NO_PHONE)
    unusable = decide(
        _order(phone="+44 7700 900123", customer=None, shippingAddress={"phone": "0225550188"})
    )
    assert (unusable.state, unusable.reason) == ("bad_phone", BAD_PHONE)
    assert unusable.phone is None


def test_an_order_with_no_first_name_is_greeted_as_the_old_message_did():
    assert decide(_order(customer={"firstName": None, "phone": "01005550188"})).customer_name == "there"
    assert decide(_order(customer={"firstName": "  ", "phone": "01005550188"})).customer_name == "there"


@pytest.mark.parametrize(
    ("amount", "text_"),
    [("1450.0", "1450.00"), ("489.1", "489.10"), ("635", "635.00"), (None, None), ("abc", None)],
)
def test_the_total_is_written_as_the_old_message_wrote_it(amount, text_):
    node = _order(totalPriceSet={"shopMoney": {"amount": amount}})
    assert decide(node).total_text == text_


# ── Recording it ──────────────────────────────────────────────────────────────


def test_the_decision_is_recorded_once_and_sends_nothing(db):
    row = confirm_order(db, "5001", client=_shopify(_order()))
    assert row.state == "would_send"
    assert (row.order_name, row.phone, row.customer_name, row.total_text) == (
        "#31044", "201005550188", "Nour", "1450.00",
    )
    assert row.wa_message_id is None and row.sent_at is None
    assert row.placed_at is not None
    assert db.query(OrderConfirmation).count() == 1


def test_an_order_already_decided_is_not_asked_about_again(db):
    asked: list = []
    first = confirm_order(db, "5001", client=_shopify(_order(), asked))
    # Paid since - but it was decided, and a decision is not remade.
    again = confirm_order(
        db, "5001", client=_shopify(_order(displayFinancialStatus="PAID", paymentGatewayNames=CARD), asked)
    )
    assert again.id == first.id
    assert again.state == "would_send"
    assert len(asked) == 1


def test_why_there_is_no_message_is_kept_with_the_order(db):
    row = confirm_order(
        db, "5002", client=_shopify(_order(paymentGatewayNames=CARD, displayFinancialStatus="PAID"))
    )
    assert (row.state, row.last_error) == ("not_needed", PAID)


def test_an_old_order_is_never_considered(db):
    """A re-sync of last month's orders must not produce a confirmation."""
    old = _order(createdAt=_iso(utcnow() - timedelta(hours=49)))
    assert confirm_order(db, "5003", client=_shopify(old)) is None
    assert db.query(OrderConfirmation).count() == 0


def test_an_order_shopify_no_longer_has_records_nothing(db):
    assert confirm_order(db, "5004", client=_shopify(None)) is None
    assert db.query(OrderConfirmation).count() == 0


def test_it_reads_the_order_with_its_own_query_and_asks_for_nothing_it_does_not_use(db):
    asked: list = []
    confirm_order(db, "5001", client=_shopify(_order(), asked))
    assert "ConfirmationOrder" in asked[0]
    assert "gid://shopify/Order/5001" in asked[0]
    for unused in ("email", "address1", "lineItems", "note", "lastName"):
        assert unused not in asked[0]


def test_a_missing_shopify_connection_fails_at_once_rather_than_retrying(db, monkeypatch):
    def unconfigured():
        raise ShopifyNotConfigured("Shopify is not configured")

    monkeypatch.setattr(confirmations, "build_client", unconfigured)
    with pytest.raises(PermanentFailure, match="Cannot read order 5001"):
        confirm_order(db, "5001")


def test_the_handler_needs_an_order_id(db):
    with pytest.raises(PermanentFailure, match="requires an order_id"):
        confirmations._handle_confirm_order(db, {})


# ── Queueing ──────────────────────────────────────────────────────────────────


def test_a_fresh_order_is_queued_when_it_is_indexed_and_only_once(db):
    order = _indexed(db)
    assert queue_if_new(db, order) is True
    assert queue_if_new(db, order) is True  # absorbed by the first: one job
    assert _jobs(db) == [("inbox_confirm_order", "5001", "inbox_confirm_order:5001")]


def test_an_order_already_decided_is_not_queued_again(db):
    order = _indexed(db)
    confirm_order(db, "5001", client=_shopify(_order()))
    assert queue_if_new(db, order) is False
    assert _jobs(db) == []


def test_an_old_order_being_resynced_queues_nothing(db):
    order = _indexed(db, placed=utcnow() - timedelta(days=30))
    assert queue_if_new(db, order) is False
    assert _jobs(db) == []


def test_syncing_an_order_queues_its_confirmation(db, monkeypatch):
    """The live path: a webhook's order is indexed, then considered."""
    from app.services.shopify import sync

    order = _indexed(db)
    monkeypatch.setattr(sync, "sync_one_order", lambda db_, order_id: order)
    sync._handle_sync_order(db, {"order_id": "5001"})
    assert ("inbox_confirm_order", "5001", "inbox_confirm_order:5001") in _jobs(db)


def test_the_sweep_finds_recent_orders_with_nothing_on_record(db):
    """An order whose webhook was missed reaches the index only by the sweep."""
    _indexed(db, "5001")
    _indexed(db, "5002")
    _indexed(db, "5003", placed=utcnow() - timedelta(days=3))
    confirm_order(db, "5002", client=_shopify(_order()))

    assert unconfirmed_recent(db) == ["5001"]
    confirmations._handle_confirm_sweep(db, {})
    assert _jobs(db) == [("inbox_confirm_order", "5001", "inbox_confirm_order:5001")]


def test_the_reconciliation_sweep_queues_the_confirmation_sweep(db):
    from app.services.reconcile import _queue_confirmations

    _queue_confirmations(db)
    _queue_confirmations(db)
    assert _jobs(db) == [("inbox_confirm_sweep", None, "inbox_confirm_sweep:sweep")]


def test_both_kinds_have_a_handler_and_run_in_the_inbox_lane():
    from app.worker import HANDLERS

    assert {JobKind.INBOX_CONFIRM_ORDER, JobKind.INBOX_CONFIRM_SWEEP} <= INBOX_WORK
    # Every kind the inbox lane takes has something to run it.
    import app.main  # noqa: F401 - registers the handlers

    assert INBOX_WORK <= set(HANDLERS)


# ── Switched off ──────────────────────────────────────────────────────────────


@pytest.fixture()
def switched_off(monkeypatch):
    monkeypatch.setattr("app.config.settings.inbox_confirmations_enabled", False)


def test_the_engine_is_off_unless_a_server_is_told_otherwise():
    """Staging reads the real store. Off by default is what keeps a customer's
    phone out of its database."""
    from app.config import Settings

    assert Settings.model_fields["inbox_confirmations_enabled"].default is False


def test_switched_off_an_indexed_order_queues_nothing(db, switched_off):
    assert queue_if_new(db, _indexed(db)) is False
    assert _jobs(db) == []


def test_switched_off_the_sweeps_queue_nothing(db, switched_off):
    from app.services.reconcile import _queue_confirmations

    _indexed(db)
    _queue_confirmations(db)
    confirmations._handle_confirm_sweep(db, {})
    assert _jobs(db) == []


def test_switched_off_a_job_already_queued_reads_nothing_and_keeps_nothing(
    db, switched_off, monkeypatch
):
    """Turned off between the queueing and the run."""

    def never():
        raise AssertionError("Shopify must not be asked while the engine is off")

    monkeypatch.setattr(confirmations, "build_client", never)
    confirmations._handle_confirm_order(db, {"order_id": "5001"})
    assert db.query(OrderConfirmation).count() == 0


def test_the_engine_decides_and_never_reaches_whatsapp_itself(db):
    """Sending is other code's (``outbound``), behind the one rule on who may
    be messaged. The engine has no way to reach WhatsApp."""
    import inspect

    source = inspect.getsource(confirmations)
    for sender in ("MetaClient", "send_template", "send_text", "inbox.meta"):
        assert sender not in source


def test_on_a_server_that_may_not_message_her_the_order_only_records(db):
    """The silent run: no WhatsApp connection, so nothing waits to be sent."""
    row = confirm_order(db, "5001", client=_shopify(_order()))
    assert row.state == "would_send"
    assert not any(kind == "inbox_send_confirmation" for kind, _, _ in _jobs(db))


@pytest.fixture()
def may_message_customers(db, monkeypatch):
    """WhatsApp connected, sending on, and the server told it may."""
    from cryptography.fernet import Fernet

    from app.services.inbox import connection
    from app.services.inbox.meta import NumberInfo

    monkeypatch.setattr(
        "app.config.settings.settings_encryption_key", Fernet.generate_key().decode()
    )
    connection.save_whatsapp(
        db,
        phone_number_id="100200300400500",
        business_account_id="777888999000111",
        access_token="EAAG-made-up-access-key-0000a1b2",
        app_secret="made-up-app-secret-000000009f3c",
        verify_token="made-up-check-word-0001",
        actor_id=None,
        actor_email=None,
        checker=lambda *args: NumberInfo("+20 100 555 0100", "HBA Wear", "GREEN"),
    )
    connection.set_sending(db, True, actor_id=None, actor_email=None)
    monkeypatch.setattr("app.config.settings.inbox_send_to_customers", True)


def test_on_a_server_that_may_message_her_the_order_waits_to_be_sent(db, may_message_customers):
    row = confirm_order(db, "5001", client=_shopify(_order()))
    assert row.state == "pending"
    assert ("inbox_send_confirmation", "5001", "inbox_send_confirmation:5001:0") in _jobs(db)


def test_an_order_that_gets_no_message_queues_no_sending(db, may_message_customers):
    paid = _order(paymentGatewayNames=CARD, displayFinancialStatus="PAID")
    assert confirm_order(db, "5002", client=_shopify(paid)).state == "not_needed"
    assert _jobs(db) == []


def test_an_order_recorded_as_would_send_is_never_sent_later(db, monkeypatch):
    """Turning sending on changes orders decided from then on, and none before."""
    confirm_order(db, "5001", client=_shopify(_order()))
    assert db.query(OrderConfirmation).one().state == "would_send"

    from app.services.inbox.outbound import send_confirmation

    def never(*args, **kwargs):
        raise AssertionError("an order that was only recorded must not be sent")

    monkeypatch.setattr("app.services.inbox.outbound._client", never)
    send_confirmation(db, "5001", claim=never)
    assert db.query(OrderConfirmation).one().state == "would_send"
