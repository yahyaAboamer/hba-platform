"""The Shopify tab (ADR 0057; PRD S1-S7).

The tag combinations are the ones found on the live shop on 3 October 2026.
Shopify itself is never called: a mock transport stands in for it.
"""

import json
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, text

from app.core.businesstime import BUSINESS_TIMEZONE, utcnow
from app.db import engine
from app.main import app
from app.modules.operations.models import OpsShopifyOrder
from app.shared.services.jobs import JobKind
from app.modules.operations.services import shopify
from app.modules.operations.services.freshness import record_failure, record_not_connected, record_success
from app.modules.operations.services.polling import (
    KeyRefused,
    NotConnected,
    PermanentlyUnavailable,
    SourceUnavailable,
)
from app.shared.services.shopify.client import ShopifyClient, ShopifyNotConfigured

# ── Which card an order counts on ─────────────────────────────────────────────


@pytest.mark.parametrize(
    ("tags", "expected"),
    [
        (["Confirmed ✅"], ["confirmed"]),
        (["Confirmed✅"], ["confirmed"]),  # the spelling without the space
        (["Confirmed ✅", "No WhatsApp 📵"], ["confirmed"]),  # not S4
        (["Cancelled ❌", "bosta_sync_failed"], ["cancel_in_shopify"]),  # S7 only
        (
            ["Confirmed ✅", "Edit ✏️", "No answer", "compression"],
            ["confirmed", "compression_not_call_confirmed"],  # S1 and S6, not S2
        ),
        (["Confirmed ✅", "bosta_sync_failed"], ["confirmed", "bosta_sync_failed"]),
        (["No answer"], ["no_answer", "no_answer_no_whatsapp_sent"]),
        (["No answer", "no answer( 2 times )"], ["no_answer_no_whatsapp_sent"]),
        (["No answer", "WA Sent 📤"], ["no_answer"]),
        (["No answer", "No WhatsApp 📵"], ["no_answer", "no_whatsapp"]),
        (["compression", "Call Confirmed📞"], []),
        (["compression"], ["compression_not_call_confirmed"]),
        (["Cancelled ❌"], ["cancel_in_shopify"]),
        ([], []),
    ],
)
def test_the_cards_an_order_counts_on(tags, expected):
    assert shopify.cards_for(tags) == expected


def test_tags_compare_without_case_spaces_or_variation_marks():
    assert shopify.tag_key("Confirmed ✅") == shopify.tag_key("confirmed✅")
    assert shopify.tag_key("Call Confirmed 📞") == shopify.tag_key("Call Confirmed📞")
    assert shopify.tag_key("Edit ✏️") == shopify.tag_key("Edit ✏")
    assert shopify.tag_key("No answer") != shopify.tag_key("no answer( 2 times )")


# ── Reading Shopify ───────────────────────────────────────────────────────────


def _node(number: int, tags: list[str], created: str = "2026-10-03T07:42:00Z", **extra) -> dict:
    return {
        "legacyResourceId": str(6_000_000 + number),
        "name": f"#{number}",
        "createdAt": created,
        "displayFulfillmentStatus": "UNFULFILLED",
        "cancelledAt": None,
        "closed": False,
        "tags": tags,
        **extra,
    }


def _client(pages=None, status: int = 200, errors=None, seen=None) -> ShopifyClient:
    pages = list(pages or [])

    def handler(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(json.loads(request.content))
        if status != 200:
            return httpx.Response(status, json={})
        if errors:
            return httpx.Response(200, json={"errors": errors})
        nodes, has_next = pages.pop(0)
        return httpx.Response(
            200,
            json={
                "data": {
                    "orders": {
                        "pageInfo": {
                            "hasNextPage": has_next,
                            "endCursor": "next" if has_next else None,
                        },
                        "nodes": nodes,
                    }
                }
            },
        )

    client = ShopifyClient(
        "hba-test.myshopify.com", access_token="test-token", transport=httpx.MockTransport(handler)
    )
    client.retry_base_seconds = 0
    return client


def test_every_page_is_read_with_its_own_search():
    seen: list = []
    client = _client([([_node(1, [])], True), ([_node(2, [])], False)], seen=seen)

    orders = shopify.fetch_open_unshipped(client)

    assert [order["name"] for order in orders] == ["#1", "#2"]
    assert seen[0]["variables"] == {"query": shopify.SEARCH, "after": None}
    assert seen[1]["variables"]["after"] == "next"
    # Its own query: nothing from the order sync's shared one.
    assert "OperationsOpenUnshipped" in seen[0]["query"]


def test_a_cancelled_or_closed_order_never_counts_even_if_returned():
    client = _client(
        [
            (
                [
                    _node(1, []),
                    _node(2, [], cancelledAt="2026-10-01T00:00:00Z"),
                    _node(3, [], closed=True),
                ],
                False,
            )
        ]
    )
    assert [order["name"] for order in shopify.fetch_open_unshipped(client)] == ["#1"]


def test_each_read_replaces_the_whole_set(db):
    shopify.read(db, _client([([_node(1, ["Confirmed ✅"]), _node(2, ["No answer"])], False)]))
    # #1 shipped since: the next read no longer has it.
    shopify.read(db, _client([([_node(2, ["No answer"])], False)]))

    numbers = db.scalars(select(OpsShopifyOrder.order_number)).all()
    assert numbers == ["#2"]


def test_a_read_returns_how_many_it_stored(db):
    stored = shopify.read(db, _client([([_node(1, []), _node(2, [])], False)]))
    assert stored == 2
    assert db.scalar(select(func.count()).select_from(OpsShopifyOrder)) == 2


@pytest.mark.parametrize(
    ("client_kwargs", "raised", "reason"),
    [
        ({"status": 401}, KeyRefused, "Shopify refused the platform's connection."),
        (
            {"errors": [{"message": "no", "extensions": {"code": "ACCESS_DENIED"}}]},
            PermanentlyUnavailable,
            "Shopify hasn't given the platform access to orders.",
        ),
        ({"status": 503}, SourceUnavailable, "Shopify didn't answer."),
    ],
)
def test_failures_are_named_in_plain_words(db, client_kwargs, raised, reason):
    with pytest.raises(raised) as caught:
        shopify.read(db, _client(**client_kwargs))
    assert str(caught.value) == reason


def test_a_failed_read_leaves_the_last_set_in_place(db):
    shopify.read(db, _client([([_node(1, ["Confirmed ✅"])], False)]))
    with pytest.raises(SourceUnavailable):
        shopify.read(db, _client(status=503))
    assert db.scalar(select(func.count()).select_from(OpsShopifyOrder)) == 1


def test_no_shopify_connection_is_not_connected(db, monkeypatch):
    from app.shared.services.shopify import connection

    def refuse(_effective):
        raise ShopifyNotConfigured("not configured")

    monkeypatch.setattr(connection, "client_for", refuse)
    with pytest.raises(NotConnected):
        shopify.read(db)


def test_the_read_is_scheduled_every_five_minutes_with_its_handler():
    import app.main  # noqa: F401 - registers the handlers
    from app.shared.services.schedule import SCHEDULE
    from app.worker import HANDLERS

    assert SCHEDULE[JobKind.ORDER_OPS_SHOPIFY][0] == timedelta(minutes=5)
    assert JobKind.ORDER_OPS_SHOPIFY in HANDLERS


# ── The tab ───────────────────────────────────────────────────────────────────


def _cairo(day: int, hour: int) -> datetime:
    return datetime(2026, 10, day, hour, tzinfo=BUSINESS_TIMEZONE)


def _store(db, number: int, tags: list[str], placed: datetime) -> None:
    db.add(
        OpsShopifyOrder(
            shopify_order_id=str(6_000_000 + number),
            order_number=f"#{number}",
            placed_at=placed,
            tags=tags,
            fulfillment_status="UNFULFILLED",
            seen_at=utcnow(),
        )
    )
    db.flush()


def test_waiting_counts_calendar_days_in_cairo():
    now = _cairo(3, 12)
    assert shopify.waiting_days(_cairo(3, 1), now) == 0
    assert shopify.waiting_days(_cairo(1, 21), now) == 2
    # 21:30 UTC on 2 October is already 3 October in Cairo: today.
    late = datetime(2026, 10, 2, 21, 30, tzinfo=timezone.utc)
    assert shopify.waiting_days(late, now) == 0


def test_the_tab_counts_every_card_and_lists_newest_first(db):
    _store(db, 30889, ["Confirmed ✅", "No WhatsApp 📵", "bosta_sync_failed"], _cairo(1, 10))
    _store(db, 30931, ["Confirmed ✅", "bosta_sync_failed"], _cairo(3, 10))
    _store(db, 30900, ["No answer"], _cairo(2, 10))

    body = shopify.tab(db, "hba-test.myshopify.com", now=_cairo(3, 12))

    counts = {card["key"]: card["count"] for card in body["cards"]}
    assert body["total"] == 3
    assert counts == {
        "confirmed": 2,
        "no_answer": 1,
        "no_answer_no_whatsapp_sent": 1,
        "no_whatsapp": 0,
        "bosta_sync_failed": 2,
        "compression_not_call_confirmed": 0,
        "cancel_in_shopify": 0,
    }
    synced = next(card for card in body["cards"] if card["key"] == "bosta_sync_failed")
    first = synced["orders"][0]
    assert [order["order_number"] for order in synced["orders"]] == ["#30931", "#30889"]
    assert first["waiting_days"] == 0
    assert first["admin_url"] == "https://hba-test.myshopify.com/admin/orders/6030931"
    assert first["tags"] == [
        {"text": "Confirmed ✅", "hit": False},
        {"text": "bosta_sync_failed", "hit": True},
    ]


def test_the_tab_carries_no_customer_details(db):
    _store(db, 1, ["Confirmed ✅"], _cairo(3, 10))
    order = shopify.tab(db, "hba-test.myshopify.com")["cards"][0]["orders"][0]
    assert set(order) == {"order_number", "placed_at", "waiting_days", "tags", "admin_url"}


# ── Through the API ───────────────────────────────────────────────────────────

BOOTSTRAP = {
    "email": "owner@example.com",
    "display_name": "Owner",
    "password": "quiet-harbour-lantern",
}


@pytest.fixture()
def client(fresh_database):
    with TestClient(app) as test_client:
        response = test_client.post("/api/auth/bootstrap", json=BOOTSTRAP)
        assert response.status_code == 201, response.text
        test_client.headers["X-CSRF-Token"] = response.json()["csrf"]
        yield test_client


def _committed(write) -> None:
    from app.db import SessionLocal

    with SessionLocal() as session:
        write(session)
        session.commit()


def test_before_the_first_read_there_are_no_numbers_not_zeros(client):
    body = client.get("/api/order-ops/shopify").json()
    assert body["freshness"]["state"] == "never"
    assert body["cards"] is None
    assert body["total"] is None


def test_after_a_read_the_cards_come_with_their_time(client):
    def write(session):
        _store(session, 30931, ["Confirmed ✅"], _cairo(3, 10))
        record_success(session, "shopify", 1)

    _committed(write)
    body = client.get("/api/order-ops/shopify").json()

    assert body["freshness"]["state"] == "fresh"
    assert body["freshness"]["updated_at"] is not None
    assert body["total"] == 1
    assert body["cards"][0]["key"] == "confirmed"
    assert body["cards"][0]["count"] == 1


def test_a_failure_keeps_the_last_numbers_with_the_reason(client):
    def write(session):
        _store(session, 30931, ["Confirmed ✅"], _cairo(3, 10))
        record_success(session, "shopify", 1, at=utcnow() - timedelta(minutes=20))
        record_failure(session, "shopify", "Shopify didn't answer.")

    _committed(write)
    body = client.get("/api/order-ops/shopify").json()

    assert body["freshness"]["state"] == "failed"
    assert body["freshness"]["error"] == "Shopify didn't answer."
    assert body["cards"][0]["count"] == 1


def test_not_connected_shows_no_numbers(client):
    def write(session):
        _store(session, 30931, ["Confirmed ✅"], _cairo(3, 10))
        record_success(session, "shopify", 1, at=utcnow() - timedelta(hours=1))
        record_not_connected(session, "shopify")

    _committed(write)
    assert client.get("/api/order-ops/shopify").json()["cards"] is None


@pytest.mark.parametrize(
    ("role", "expected"),
    [("operations_manager", 200), ("affiliate_manager", 403), ("content_manager", 403)],
)
def test_the_shopify_tab_is_for_operations_only(client, role, expected):
    with engine.begin() as connection:
        connection.execute(text("UPDATE role_assignment SET role = :r"), {"r": role})
    assert client.get("/api/order-ops/shopify").status_code == expected
