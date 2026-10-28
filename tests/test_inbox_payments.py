"""An unpaid international order's payment request (ADR 0062).

Shopify and Meta are never called: mock transports answer and record what
was asked. Every order, name, number and link here is made up.
"""

import json
from datetime import timedelta

import httpx
import pytest
from cryptography.fernet import Fernet
from sqlalchemy import select, text

from app.core.businesstime import utcnow
from app.modules.inbox.models import InboxMessage, OrderConfirmation
from app.shared.models.orders import OrderIndex
from app.modules.inbox.services import chats, connection, payments, tags
from app.modules.inbox.services.confirmations import (
    BAD_FOREIGN_PHONE,
    PAID,
    confirm_order,
    decide,
    queue_if_new,
)
from app.modules.inbox.services.meta import MetaClient, NumberInfo
from app.modules.inbox.services.outbound import send_confirmation
from app.modules.inbox.services.sending import international_mobile
from app.shared.services.jobs import INBOX_WORK, JobKind
from app.shared.services.shopify.client import ShopifyClient

BASE = "https://hbawear.store/72695906535/order_payment/"
SECRET_PART = "9100200300400?secret=made0up0secret0000000000000000a1"
LINK = BASE + SECRET_PART
HER = "966501234567"
TOKEN = "EAAG-made-up-access-key-0000a1b2"
NUMBER_ID = "100200300400500"


@pytest.fixture(autouse=True)
def switched_on(monkeypatch):
    monkeypatch.setattr("app.config.settings.inbox_confirmations_enabled", True)
    monkeypatch.setattr("app.config.settings.inbox_payment_requests_enabled", True)
    monkeypatch.setattr("app.config.settings.inbox_payment_link_base", BASE)


@pytest.fixture()
def may_send(db, monkeypatch):
    """The one configuration in which a customer is messaged."""
    monkeypatch.setattr(
        "app.config.settings.settings_encryption_key", Fernet.generate_key().decode()
    )
    monkeypatch.setattr("app.config.settings.inbox_test_numbers", "")
    connection.save_whatsapp(
        db,
        phone_number_id=NUMBER_ID,
        business_account_id="777888999000111",
        access_token=TOKEN,
        app_secret="made-up-app-secret-000000009f3c",
        verify_token="made-up-check-word-0001",
        actor_id=None,
        actor_email=None,
        checker=lambda *args: NumberInfo("+20 100 555 0100", "HBA Wear", "GREEN"),
    )
    connection.set_sending(db, True, actor_id=None, actor_email=None)
    monkeypatch.setattr("app.config.settings.inbox_send_to_customers", True)


def _iso(moment) -> str:
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def _order(**changes) -> dict:
    node = {
        "legacyResourceId": "9100",
        "name": "#31510",
        "createdAt": _iso(utcnow() - timedelta(minutes=2)),
        "cancelledAt": None,
        "test": False,
        "displayFinancialStatus": "PENDING",
        "paymentGatewayNames": ["Cash on Delivery (COD)"],
        "totalPriceSet": {"shopMoney": {"amount": "5850.0"}},
        "totalOutstandingSet": {"shopMoney": {"amount": "5850.0", "currencyCode": "EGP"}},
        "phone": None,
        "customer": {"firstName": "Sara", "phone": None},
        "shippingAddress": {"phone": "0501234567", "countryCodeV2": "SA"},
    }
    node.update(changes)
    return node


def _owed(amount="5850.0", link=LINK, cancelled=None) -> dict:
    return {
        "cancelledAt": cancelled,
        "totalOutstandingSet": {"shopMoney": {"amount": amount, "currencyCode": "EGP"}},
        "paymentCollectionDetails": {"additionalPaymentCollectionUrl": link},
    }


def _shopify(node, asked: list | None = None, *, data: dict | None = None) -> ShopifyClient:
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.read())
        if asked is not None:
            asked.append(body)
        return httpx.Response(200, json={"data": data if data is not None else {"order": node}})

    return ShopifyClient(
        shop_domain="hba-test.myshopify.com",
        access_token="shpat_test",
        api_version="2026-07",
        transport=httpx.MockTransport(handler),
    )


def _meta(asked: list) -> MetaClient:
    def handler(request: httpx.Request) -> httpx.Response:
        asked.append(json.loads(request.read()))
        return httpx.Response(200, json={"messages": [{"id": f"wamid.PAY{len(asked)}"}]})

    return MetaClient(TOKEN, NUMBER_ID, api_version="v23.0", transport=httpx.MockTransport(handler))


def _yes(order_id: str) -> bool:
    return True


def _request(db, *, state="pending", order_id="9100", **changes) -> OrderConfirmation:
    row = OrderConfirmation(
        shopify_order_id=order_id, order_name="#31510", state=state, kind="payment",
        country="SA", phone=HER, customer_name="Sara", total_text="EGP 5,850.00",
        placed_at=utcnow() - timedelta(minutes=2), **changes,
    )
    db.add(row)
    db.flush()
    return row


def _indexed(db, order_id="9100", **changes) -> OrderIndex:
    placed = utcnow() - timedelta(days=1)
    row = OrderIndex(
        shopify_order_id=order_id, order_number=f"#{order_id}", placed_at=placed,
        business_month=placed.strftime("%Y-%m"), **changes,
    )
    db.add(row)
    db.flush()
    return row


def _jobs(db) -> list[str]:
    db.flush()
    return [kind for (kind,) in db.execute(text("SELECT kind FROM background_job ORDER BY id"))]


# ── A foreign number ──────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("raw", "country", "read"),
    [
        ("+966 50 123 4567", "SA", "966501234567"),
        ("0501234567", "SA", "966501234567"),
        ("501234567", "SA", "966501234567"),
        ("966501234567", "SA", "966501234567"),
        ("00966501234567", "SA", "966501234567"),
        ("07701234567", "IQ", "9647701234567"),
        ("+44 7700 900123", "GB", "447700900123"),
        ("(212) 555-0142", "US", "12125550142"),
        # An Egyptian number on an order abroad: as written with +20, fine.
        ("+20 100 555 0188", "SA", "201005550188"),
    ],
)
def test_a_foreign_number_is_read_with_the_country_it_ships_to(raw, country, read):
    assert international_mobile(raw, country) == read


@pytest.mark.parametrize(
    ("raw", "country"),
    [
        # "010…" could be Egyptian or local. It is neither guessed.
        ("01005550188", "SA"),
        # A country the platform has no code for, written locally.
        ("0712345678", "ZZ"),
        ("12345", "SA"),
        ("", "SA"),
        # +20 must still be an Egyptian mobile.
        ("+20 2 2345 6789", "SA"),
        # An Italian mobile written locally that starts with Italy's code:
        # local, or already international? Ten digits could be either.
        ("3931234567", "IT"),
    ],
)
def test_a_number_that_could_reach_a_stranger_is_refused(raw, country):
    assert international_mobile(raw, country) is None


# ── The decision ──────────────────────────────────────────────────────────────


def test_an_unpaid_international_order_becomes_a_payment_request():
    decision = decide(_order(), payments=True)
    assert (decision.state, decision.kind, decision.country) == ("would_send", "payment", "SA")
    assert decision.phone == HER
    assert decision.customer_name == "Sara"
    assert decision.total_text == "EGP 5,850.00"


def test_an_international_order_that_owes_nothing_gets_no_message():
    paid = _order(
        displayFinancialStatus="PAID",
        paymentGatewayNames=["Paymob - Native Checkout for Debit/Credit Cards"],
        totalOutstandingSet={"shopMoney": {"amount": "0.0", "currencyCode": "EGP"}},
    )
    decision = decide(paid, payments=True)
    assert (decision.state, decision.reason) == ("not_needed", PAID)


def test_an_unreadable_foreign_number_is_recorded_as_such():
    decision = decide(
        _order(shippingAddress={"phone": "01005550188", "countryCodeV2": "SA"}), payments=True
    )
    assert (decision.state, decision.kind, decision.reason) == (
        "bad_phone", "payment", BAD_FOREIGN_PHONE,
    )


def test_an_egyptian_order_is_decided_as_before():
    egyptian = _order(shippingAddress={"phone": "01005550188", "countryCodeV2": "EG"})
    decision = decide(egyptian, payments=True)
    assert (decision.state, decision.kind) == ("would_send", "confirmation")
    assert decision.total_text == "5850.00"


def test_switched_off_an_international_order_is_decided_as_before():
    """Before 18 October it reached nobody: the number is not Egyptian."""
    decision = decide(_order(), payments=False)
    assert (decision.state, decision.kind) == ("bad_phone", "confirmation")


def test_the_decision_is_recorded_as_a_payment_request(db, may_send):
    row = confirm_order(db, "9100", client=_shopify(_order()))
    assert (row.state, row.kind, row.country, row.phone) == ("pending", "payment", "SA", HER)
    kinds = _jobs(db)
    assert JobKind.INBOX_SEND_CONFIRMATION in kinds
    # The invoice email is asked for too.
    assert JobKind.INBOX_SEND_INVOICE in kinds


def test_no_invoice_email_from_a_server_that_may_not_message_customers(db):
    row = confirm_order(db, "9100", client=_shopify(_order()))
    assert row.state == "would_send"
    assert JobKind.INBOX_SEND_INVOICE not in _jobs(db)


def test_the_new_work_runs_in_the_inbox_lane():
    assert JobKind.INBOX_PAYMENT_REMINDER in INBOX_WORK
    assert JobKind.INBOX_SEND_INVOICE in INBOX_WORK


# ── The link ──────────────────────────────────────────────────────────────────


def test_only_what_follows_the_approved_part_is_sent():
    assert payments.link_suffix(LINK) == SECRET_PART
    assert payments.link_suffix("https://another.store/1/order_payment/9100?secret=x") is None
    assert payments.link_suffix(BASE) is None
    assert payments.link_suffix(None) is None


def test_the_message_carries_her_name_the_order_the_amount_and_the_link(db):
    row = _request(db)
    built = payments.components(row, SECRET_PART)
    assert [p["text"] for p in built[0]["parameters"]] == ["Sara", "#31510", "EGP 5,850.00"]
    assert built[1] == {
        "type": "button", "sub_type": "url", "index": "0",
        "parameters": [{"type": "text", "text": SECRET_PART}],
    }


def test_the_request_goes_out_with_its_link(db, may_send, monkeypatch):
    monkeypatch.setattr(payments, "build_client", lambda: _shopify(_owed()))
    asked: list = []
    row = _request(db)
    send_confirmation(db, "9100", client=_meta(asked), claim=_yes)

    template = asked[0]["template"]
    assert asked[0]["to"] == HER
    assert (template["name"], template["language"]["code"]) == ("international_payment", "en")
    assert template["components"][1]["parameters"][0]["text"] == SECRET_PART
    assert (row.state, row.wa_message_id) == ("sent", "wamid.PAY1")
    message = db.scalar(select(InboxMessage).where(InboxMessage.wa_message_id == "wamid.PAY1"))
    assert message.body == "Payment request · #31510"
    assert message.extra == {"buttons": ["Pay now"]}
    # The link is never kept.
    assert SECRET_PART not in str(message.body) + str(message.extra) + str(row.last_error)
    assert tags.wanted_tag(row) == tags.AWAITING_PAYMENT


def test_a_link_that_does_not_match_the_approved_one_is_not_sent(db, may_send, monkeypatch):
    other = "https://new.store/1/order_payment/9100?secret=x"
    monkeypatch.setattr(payments, "build_client", lambda: _shopify(_owed(link=other)))
    asked: list = []
    row = _request(db)
    send_confirmation(db, "9100", client=_meta(asked), claim=_yes)
    assert asked == []
    assert (row.state, row.last_error) == ("failed", payments.LINK_MISMATCH)


def test_an_order_paid_before_its_link_went_out_gets_none(db, may_send, monkeypatch):
    monkeypatch.setattr(payments, "build_client", lambda: _shopify(_owed(amount="0.0")))
    asked: list = []
    row = _request(db)
    send_confirmation(db, "9100", client=_meta(asked), claim=_yes)
    assert asked == []
    assert (row.state, row.last_error) == ("not_needed", payments.PAID)


def test_shopify_not_answering_puts_the_request_back_to_be_tried_again(db, may_send, monkeypatch):
    """The real claim commits ``sending`` in a session of its own; this one
    must not go on believing the row is still ``pending``."""

    def down(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503)

    unreachable = ShopifyClient(
        shop_domain="hba-test.myshopify.com", access_token="shpat_test",
        api_version="2026-07", transport=httpx.MockTransport(down),
    )
    unreachable.retry_base_seconds = 0
    monkeypatch.setattr(payments, "build_client", lambda: unreachable)
    row = _request(db)

    def claimed_elsewhere(order_id: str) -> bool:
        # Plain SQL, as another session's commit looks to this one.
        db.execute(
            text("UPDATE order_confirmation SET state = 'sending' WHERE shopify_order_id = :id"),
            {"id": order_id},
        )
        return True

    asked: list = []
    send_confirmation(db, "9100", client=_meta(asked), claim=claimed_elsewhere)
    db.flush()
    stored = db.execute(
        text("SELECT state, attempts FROM order_confirmation WHERE shopify_order_id = '9100'")
    ).one()
    assert asked == []
    assert tuple(stored) == ("pending", 1)
    assert row.next_attempt_at is not None


def test_a_staff_answer_is_refused_on_a_payment_request(db):
    _request(db, state="sent")
    with pytest.raises(chats.Refused):
        chats.set_answer(db, "9100", "confirmed", actor_id=None, actor_email=None)


# ── Paid ──────────────────────────────────────────────────────────────────────


def test_paid_is_noticed_when_the_order_syncs(db):
    row = _request(db, state="sent", sent_at=utcnow() - timedelta(hours=2))
    order = _indexed(db, financial_status="pending")
    assert queue_if_new(db, order) is False
    assert row.paid_at is None

    order.financial_status = "paid"
    queue_if_new(db, order)
    assert row.paid_at is not None
    assert tags.wanted_tag(row) == tags.PAID
    assert JobKind.INBOX_TAG_ORDER in _jobs(db)


@pytest.mark.parametrize("state", ["would_send", "bad_phone", "no_phone"])
def test_a_request_never_sent_leaves_shopify_alone_when_paid(db, state):
    """A server that may not message customers writes nothing to the store."""
    row = _request(db, state=state)
    queue_if_new(db, _indexed(db, financial_status="paid"))
    assert row.paid_at is not None
    assert tags.wanted_tag(row) is None
    assert JobKind.INBOX_TAG_ORDER not in _jobs(db)


# ── The reminder ──────────────────────────────────────────────────────────────


def test_one_reminder_after_24_hours(db, may_send):
    row = _request(db, state="sent", sent_at=utcnow() - timedelta(hours=25))
    _indexed(db)
    assert payments.due_reminders(db) == ["9100"]

    asked: list = []
    payments.send_reminder(db, "9100", client=_meta(asked), reader=_shopify(_owed()), claim=_yes)
    assert len(asked) == 1 and asked[0]["template"]["name"] == "international_payment"
    assert row.reminded_at is not None
    message = db.scalar(select(InboxMessage).where(InboxMessage.body.like("Payment reminder%")))
    assert message.status == "sent"

    # Never a second.
    payments.send_reminder(db, "9100", client=_meta(asked), reader=_shopify(_owed()), claim=_yes)
    assert len(asked) == 1
    assert payments.due_reminders(db) == []


@pytest.mark.parametrize("hours", [23, 73])
def test_no_reminder_before_24_hours_or_after_72(db, hours):
    _request(db, state="sent", sent_at=utcnow() - timedelta(hours=hours))
    _indexed(db)
    assert payments.due_reminders(db) == []


def test_no_reminder_for_a_cancelled_or_paid_order(db, may_send):
    row = _request(db, state="sent", sent_at=utcnow() - timedelta(hours=25))
    _indexed(db, cancelled_at=utcnow())
    assert payments.due_reminders(db) == []

    asked: list = []
    payments.send_reminder(
        db, "9100", client=_meta(asked), reader=_shopify(_owed(amount="0")), claim=_yes
    )
    assert asked == []
    assert row.paid_at is not None


def test_three_days_unpaid_needs_a_person(db):
    row = _request(db, state="sent", sent_at=utcnow() - timedelta(hours=73))
    assert payments.needs_a_person(row) is True
    row.paid_at = utcnow()
    assert payments.needs_a_person(row) is False


# ── The invoice email ─────────────────────────────────────────────────────────


def test_shopify_is_asked_once_to_email_the_invoice(db, may_send):
    row = _request(db, state="sent")
    asked: list = []
    writer = _shopify(None, asked, data={"orderInvoiceSend": {"userErrors": []}})
    payments.send_invoice(db, "9100", client=writer, reader=_shopify(_owed()), claim=_yes)
    assert len(asked) == 1 and "orderInvoiceSend" in asked[0]["query"]
    assert asked[0]["variables"] == {"id": "gid://shopify/Order/9100"}
    assert row.invoice_at is not None and row.invoice_error is None

    payments.send_invoice(db, "9100", client=writer, reader=_shopify(_owed()), claim=_yes)
    assert len(asked) == 1


def test_shopify_refusing_the_invoice_is_shown(db, may_send):
    row = _request(db, state="bad_phone")
    refused = {"orderInvoiceSend": {"userErrors": [{"message": "Email is required"}]}}
    payments.send_invoice(
        db, "9100", client=_shopify(None, data=refused), reader=_shopify(_owed()), claim=_yes
    )
    assert row.invoice_error == "Shopify refused the invoice email: Email is required"


def test_an_invoice_email_that_timed_out_is_never_asked_for_again(db, may_send):
    """Shopify may have sent it before the answer was lost: one email only."""
    calls: list = []

    def slow(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        raise httpx.ReadTimeout("no answer")

    writer = ShopifyClient(
        shop_domain="hba-test.myshopify.com", access_token="shpat_test",
        api_version="2026-07", transport=httpx.MockTransport(slow),
    )
    writer.retry_base_seconds = 0
    row = _request(db, state="sent")
    payments.send_invoice(db, "9100", client=writer, reader=_shopify(_owed()), claim=_yes)
    assert len(calls) == 1
    assert row.invoice_error == payments.INVOICE_UNANSWERED


def test_no_invoice_for_an_order_that_no_longer_owes(db, may_send):
    row = _request(db, state="sent")
    asked: list = []
    writer = _shopify(None, asked, data={"orderInvoiceSend": {"userErrors": []}})
    payments.send_invoice(db, "9100", client=writer, reader=_shopify(_owed(amount="0")), claim=_yes)
    assert asked == [] and row.invoice_at is None


# ── The Confirmations screen ──────────────────────────────────────────────────


def test_payment_requests_have_their_own_cards(db):
    _request(db, state="sent", order_id="9100", sent_at=utcnow())
    _request(db, state="sent", order_id="9101", sent_at=utcnow(), paid_at=utcnow())
    db.add(
        OrderConfirmation(
            shopify_order_id="5001", order_name="#31044", state="sent",
            phone="201005550188", placed_at=utcnow(), sent_at=utcnow(),
        )
    )
    db.flush()
    body = chats.confirmations(db)
    assert body["tiles"]["awaiting_payment"] == 1
    assert body["tiles"]["paid"] == 1
    # A payment request has nothing to tap: it is never waiting for an answer.
    assert body["tiles"]["waiting"] == 1

    listed = chats.confirmations(db, tile="awaiting_payment")["orders"]
    assert [order["order_id"] for order in listed] == ["9100"]
    assert listed[0]["kind"] == "payment" and listed[0]["needs_a_person"] is False
