"""An order's confirmation tag in Shopify (ADR 0059, points 10 and 11).

The only thing the platform writes to Shopify. Shopify is never called: a
mock transport answers, and records what was asked. Every order is made up.
"""

import json

import httpx
import pytest
from cryptography.fernet import Fernet
from sqlalchemy import text

from app.models.inbox import OrderConfirmation
from app.services.inbox import connection, tags
from app.services.inbox.tags import ALL_TAGS, apply_tags, queue_tags, wanted_tag
from app.services.jobs import PermanentFailure
from app.services.shopify.client import ShopifyClient, ShopifyError


def _row(db, order_id="5001", state="sent", answer=None) -> OrderConfirmation:
    row = OrderConfirmation(shopify_order_id=order_id, state=state, answer=answer)
    db.add(row)
    db.flush()
    return row


def _shopify(asked: list, errors: dict | None = None) -> ShopifyClient:
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.read())
        asked.append(body)
        field = "tagsRemove" if "tagsRemove" in body["query"] else "tagsAdd"
        user_errors = (errors or {}).get(field, [])
        return httpx.Response(200, json={"data": {field: {"userErrors": user_errors}}})

    return ShopifyClient(
        shop_domain="hba-test.myshopify.com",
        access_token="shpat_test",
        api_version="2026-07",
        transport=httpx.MockTransport(handler),
    )


# ── Which tag ─────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("state", "answer", "tag"),
    [
        ("sent", None, "WA Sent 📤"),
        ("no_whatsapp", None, "No WhatsApp 📵"),
        ("sent", "confirmed", "Confirmed ✅"),
        ("sent", "edit", "Edit ✏️"),
        ("sent", "cancelled", "Cancelled ❌"),
        # Her answer is what the order says, whatever came before.
        ("no_whatsapp", "confirmed", "Confirmed ✅"),
        ("would_send", None, None),
        ("pending", None, None),
        ("failed", None, None),
        ("not_needed", None, None),
    ],
)
def test_an_order_carries_one_tag_for_where_its_confirmation_stands(db, state, answer, tag):
    assert wanted_tag(_row(db, state=state, answer=answer)) == tag


def test_the_tags_are_spelled_as_operations_reads_them():
    """Operations' Shopify cards count these exact strings. The last two are
    a payment request's (ADR 0062)."""
    assert set(ALL_TAGS) == {
        "WA Sent 📤", "No WhatsApp 📵", "Confirmed ✅", "Edit ✏️", "Cancelled ❌",
        "Awaiting payment 💳", "Paid 💳",
    }


# ── Writing it ────────────────────────────────────────────────────────────────


def test_the_other_four_are_cleared_and_the_one_is_added(db):
    asked: list = []
    _row(db, answer="confirmed")
    assert apply_tags(db, "5001", client=_shopify(asked)) == "Confirmed ✅"

    remove, add = asked
    assert "tagsRemove" in remove["query"] and "tagsAdd" in add["query"]
    assert remove["variables"]["id"] == add["variables"]["id"] == "gid://shopify/Order/5001"
    assert set(remove["variables"]["tags"]) == set(ALL_TAGS) - {"Confirmed ✅"}
    assert add["variables"]["tags"] == ["Confirmed ✅"]


def test_it_only_ever_adds_and_removes_tags(db):
    """ADR 0059, point 10: it never cancels or edits an order."""
    asked: list = []
    _row(db, answer="cancelled")
    apply_tags(db, "5001", client=_shopify(asked))
    for request in asked:
        assert request["query"].count("mutation") == 1
        for forbidden in ("orderCancel", "orderUpdate", "orderEdit", "orderClose", "refund"):
            assert forbidden not in request["query"]
        assert set(request["variables"]["tags"]) <= set(ALL_TAGS)

    import inspect

    source = inspect.getsource(tags)
    for forbidden in ("orderCancel", "orderUpdate", "orderEdit", "orderClose"):
        assert forbidden not in source


def test_it_writes_what_the_order_says_now_not_when_it_was_queued(db):
    """Two taps in quick succession end on the last."""
    asked: list = []
    row = _row(db, answer="confirmed")
    row.answer = "cancelled"
    db.flush()
    assert apply_tags(db, "5001", client=_shopify(asked)) == "Cancelled ❌"


def test_an_order_with_nothing_to_say_is_not_touched(db):
    asked: list = []
    _row(db, state="would_send")
    assert apply_tags(db, "5001", client=_shopify(asked)) is None
    assert apply_tags(db, "9999", client=_shopify(asked)) is None
    assert asked == []


def test_an_order_id_that_is_not_a_number_never_reaches_shopify(db):
    asked: list = []
    _row(db, order_id="5001/../x")
    assert apply_tags(db, "5001/../x", client=_shopify(asked)) is None
    assert asked == []


def test_a_refusal_from_shopify_fails_the_job_so_it_is_tried_again(db):
    _row(db)
    refusing = _shopify([], errors={"tagsAdd": [{"message": "Order does not exist"}]})
    with pytest.raises(ShopifyError, match="refused the tag change on order 5001"):
        apply_tags(db, "5001", client=refusing)


# ── Through the second app only ───────────────────────────────────────────────


def test_without_the_second_app_the_job_fails_at_once_and_says_why(db):
    _row(db)
    with pytest.raises(PermanentFailure, match="not connected"):
        apply_tags(db, "5001")


def test_the_client_is_the_second_apps_never_the_money_connections(db, monkeypatch):
    monkeypatch.setattr(
        "app.config.settings.settings_encryption_key", Fernet.generate_key().decode()
    )
    monkeypatch.setattr("app.config.settings.shopify_shop_domain", "hba-test.myshopify.com")
    monkeypatch.setattr("app.config.settings.shopify_client_id", "main-app-client-id-0000aaaa")
    monkeypatch.setattr("app.config.settings.shopify_client_secret", "main-app-secret")
    connection.save_tags(
        db,
        client_id="tags-app-client-id-0000bbbb",
        client_secret="made-up-tags-secret-0000c7d8",
        actor_id=None,
        actor_email=None,
        checker=lambda *args: {"write_orders"},
    )
    client = tags.tags_client(db)
    assert client._client_id == "tags-app-client-id-0000bbbb"
    assert client._client_secret == "made-up-tags-secret-0000c7d8"
    assert client.shop_domain == "hba-test.myshopify.com"


# ── Queueing ──────────────────────────────────────────────────────────────────


def _jobs(db) -> list[tuple]:
    db.flush()
    return db.execute(
        text("SELECT kind, payload->>'order_id', dedupe_key FROM background_job ORDER BY id")
    ).all()


def test_a_second_answer_is_queued_while_the_first_is_still_being_written(db):
    row = _row(db, answer="confirmed")
    queue_tags(db, row)
    queue_tags(db, row)  # the same answer: one job
    row.answer = "cancelled"
    queue_tags(db, row)  # a different one: not absorbed
    assert _jobs(db) == [
        ("inbox_tag_order", "5001", "inbox_tag_order:5001:Confirmed ✅"),
        ("inbox_tag_order", "5001", "inbox_tag_order:5001:Cancelled ❌"),
    ]


def test_an_order_with_nothing_to_say_queues_nothing(db):
    queue_tags(db, _row(db, state="would_send"))
    assert _jobs(db) == []


def test_the_handler_needs_an_order_id(db):
    with pytest.raises(PermanentFailure, match="requires an order_id"):
        tags._handle_tag_order(db, {})
