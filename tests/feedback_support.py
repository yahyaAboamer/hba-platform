"""What the post-delivery feedback tests (ADR 0083) share.

Real ``MetaClient`` and ``ShopifyClient`` over ``httpx.MockTransport``: nothing
leaves the machine and every number, name and order here is made up. The
fixtures are imported into the test modules that use them.
"""

import json
from datetime import timedelta

import httpx
import pytest
from cryptography.fernet import Fernet
from sqlalchemy import text

from app.core.businesstime import utcnow
from app.modules.inbox.models import FeedbackSurvey, InboxConversation
from app.modules.inbox.services import connection
from app.modules.inbox.services.meta import MetaClient, NumberInfo
from app.shared.models.orders import OrderIndex
from app.shared.services.shopify.client import ShopifyClient

HER = "201005550188"
TOKEN = "EAAG-made-up-access-key-0000a1b2"
NUMBER_ID = "100200300400500"


@pytest.fixture()
def connected(db, monkeypatch):
    """WhatsApp connected, sending still off, server not told it may send."""
    monkeypatch.setattr(
        "app.config.settings.settings_encryption_key", Fernet.generate_key().decode()
    )
    monkeypatch.setattr("app.config.settings.inbox_send_to_customers", False)
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


@pytest.fixture()
def may_send(db, connected, monkeypatch):
    """The one configuration in which a customer is messaged."""
    connection.set_sending(db, True, actor_id=None, actor_email=None)
    monkeypatch.setattr("app.config.settings.inbox_send_to_customers", True)


@pytest.fixture()
def feature_on(monkeypatch):
    monkeypatch.setattr("app.config.settings.inbox_feedback_enabled", True)


def meta(asked: list, *, refuse: tuple[int, int] | None = None) -> MetaClient:
    """A MetaClient that records every body it is asked to send."""

    def handler(request: httpx.Request) -> httpx.Response:
        asked.append(json.loads(request.read()))
        if refuse:
            status, code = refuse
            return httpx.Response(status, json={"error": {"code": code, "message": f"to {HER}"}})
        return httpx.Response(200, json={"messages": [{"id": f"wamid.SENT{len(asked)}"}]})

    return MetaClient(TOKEN, NUMBER_ID, api_version="v23.0", transport=httpx.MockTransport(handler))


def node(**changes) -> dict:
    """An order as the feedback query returns it."""
    found = {
        "legacyResourceId": "7001",
        "name": "#7001",
        "cancelledAt": None,
        "test": False,
        "phone": None,
        "customer": {"firstName": "Nour", "phone": "+201005550188"},
        "shippingAddress": {"phone": "01005550188"},
        "lineItems": {"nodes": [{"title": "Linen Shirt"}, {"title": "Wide Trousers"}]},
    }
    found.update(changes)
    return found


def shopify(nodes: dict[str, dict | None], asked: list | None = None) -> ShopifyClient:
    """A ShopifyClient answering the feedback query from ``nodes``, by order id."""

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.read())
        if asked is not None:
            asked.append(body)
        order_id = body["variables"]["id"].rsplit("/", 1)[-1]
        return httpx.Response(200, json={"data": {"order": nodes.get(order_id)}})

    return ShopifyClient(
        shop_domain="hba-test.myshopify.com",
        access_token="shpat_test",
        api_version="2026-07",
        transport=httpx.MockTransport(handler),
    )


def order(db, order_id="7001", *, delivered_ago=timedelta(days=3), **changes) -> OrderIndex:
    """A delivered order in the index, delivered ``delivered_ago`` ago."""
    delivered = utcnow() - delivered_ago
    values = {
        "shopify_order_id": order_id,
        "order_number": f"#{order_id}",
        "placed_at": delivered - timedelta(days=6),
        "business_month": delivered.strftime("%Y-%m"),
        "delivery_state": "delivered",
        "delivered_at": delivered,
        "fulfilments": [{"company": "Bosta", "status": "SUCCESS"}],
        "financial_status": "PENDING",
    }
    values.update(changes)
    row = OrderIndex(**values)
    db.add(row)
    db.flush()
    return row


def started(db, *, days_ago: int = 30):
    """The feature was first switched on ``days_ago`` days ago."""
    from app.modules.inbox.services import feedback

    cfg = feedback.get_settings(db)
    cfg.started_at = utcnow() - timedelta(days=days_ago)
    db.flush()
    return cfg


def conversation(db, *, wrote_ago: timedelta | None = timedelta(minutes=5), unread=0) -> InboxConversation:
    row = InboxConversation(
        phone=HER,
        last_inbound_at=utcnow() - wrote_ago if wrote_ago is not None else None,
        unread_count=unread,
    )
    db.add(row)
    db.flush()
    return row


def survey(db, order_id="7001", **changes) -> FeedbackSurvey:
    """A survey whose first question went out and has not been answered."""
    values = {
        "shopify_order_id": order_id,
        "order_name": f"#{order_id}",
        "delivered_at": utcnow() - timedelta(days=3),
        "courier": "Bosta",
        "products": ["Linen Shirt"],
        "phone": HER,
        "customer_name": "Nour",
        "state": "sent",
        "step": "rating",
        "sent_at": utcnow() - timedelta(hours=1),
        "wa_message_id": f"wamid.FIRST{order_id}",
    }
    values.update(changes)
    row = FeedbackSurvey(**values)
    db.add(row)
    db.flush()
    return row


def jobs(db, kind: str | None = None) -> list[tuple]:
    db.flush()
    query = "SELECT kind, dedupe_key, payload FROM background_job"
    if kind:
        return db.execute(text(query + " WHERE kind = :k ORDER BY id"), {"k": kind}).all()
    return db.execute(text(query + " ORDER BY id")).all()
