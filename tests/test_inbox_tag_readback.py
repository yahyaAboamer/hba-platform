"""An answer tagged in Shopify counts, and the cards count open orders (ADR 0063).

Shopify is never called: a mock transport answers and records what was
asked. Every order, name and number here is made up.
"""

import json
from datetime import timedelta

import httpx
import pytest
from sqlalchemy import text

from app.core.businesstime import utcnow
from app.modules.inbox.models import OrderConfirmation
from app.shared.models.orders import OrderIndex
from app.modules.inbox.services import chats, tags
from app.modules.inbox.services.confirmations import queue_if_new
from app.shared.services.jobs import INBOX_WORK, JobKind, enqueue
from app.shared.services.shopify.client import ShopifyClient

CONFIRMED = tags.ANSWER_TAGS["confirmed"]
EDIT = tags.ANSWER_TAGS["edit"]
CANCELLED = tags.ANSWER_TAGS["cancelled"]


@pytest.fixture(autouse=True)
def switched_on(monkeypatch):
    monkeypatch.setattr("app.config.settings.inbox_confirmations_enabled", True)


def _row(db, order_id="5001", *, state="sent", answer=None, placed=None, **changes) -> OrderConfirmation:
    row = OrderConfirmation(
        shopify_order_id=order_id, order_name=f"#{order_id}", state=state, answer=answer,
        phone="201005550188", customer_name="Nour",
        placed_at=placed or utcnow() - timedelta(hours=5), sent_at=utcnow() - timedelta(hours=5),
        **changes,
    )
    db.add(row)
    db.flush()
    return row


def _indexed(db, order_id="5001", **changes) -> OrderIndex:
    placed = changes.pop("placed", utcnow() - timedelta(hours=5))
    row = OrderIndex(
        shopify_order_id=order_id, order_number=f"#{order_id}", placed_at=placed,
        business_month=placed.strftime("%Y-%m"), **changes,
    )
    db.add(row)
    db.flush()
    return row


def _shopify(order_tags: list[str] | None, asked: list | None = None) -> ShopifyClient:
    def handler(request: httpx.Request) -> httpx.Response:
        if asked is not None:
            asked.append(json.loads(request.read()))
        node = None if order_tags is None else {"tags": order_tags}
        return httpx.Response(200, json={"data": {"order": node}})

    return ShopifyClient(
        shop_domain="hba-test.myshopify.com", access_token="shpat_test",
        api_version="2026-07", transport=httpx.MockTransport(handler),
    )


def _jobs(db) -> list[str]:
    db.flush()
    return [kind for (kind,) in db.execute(text("SELECT kind FROM background_job ORDER BY id"))]


# ── Taking the answer from the tag ────────────────────────────────────────────


def test_an_order_tagged_confirmed_in_shopify_is_confirmed(db):
    """#31441, 18 October: WA Sent here, Confirmed in Shopify, no tap."""
    row = _row(db)
    assert tags.adopt(row, ["bosta_synced", CONFIRMED]) is True
    assert (row.answer, row.answered_in) == ("confirmed", "shopify")
    assert row.answered_at is not None
    # Only the platform's own tags are kept, never the shop's others.
    assert row.shopify_tags == CONFIRMED
    assert tags.wanted_tag(row) == CONFIRMED


def test_the_teams_later_answer_replaces_hers(db):
    row = _row(db, answer="edit", answered_in="whatsapp")
    assert tags.adopt(row, [CANCELLED]) is True
    assert (row.answer, row.answered_in) == ("cancelled", "shopify")


def test_two_answer_tags_at_once_are_left_alone(db):
    row = _row(db, answer="edit")
    assert tags.adopt(row, [CONFIRMED, CANCELLED]) is False
    assert row.answer == "edit"
    assert row.shopify_tags == f"{CONFIRMED} + {CANCELLED}"


def test_a_removed_tag_takes_no_answer_away(db):
    row = _row(db, answer="confirmed", answered_in="whatsapp")
    assert tags.adopt(row, []) is False
    assert (row.answer, row.answered_in) == ("confirmed", "whatsapp")
    assert row.shopify_tags is None and row.tags_read_at is not None


def test_the_same_answer_is_not_recorded_again(db):
    row = _row(db, answer="confirmed", answered_in="whatsapp")
    assert tags.adopt(row, [CONFIRMED]) is False
    assert row.answered_in == "whatsapp"


def test_a_payment_request_takes_no_answer_from_a_tag(db):
    row = _row(db, kind="payment")
    assert tags.adopt(row, [CONFIRMED]) is False
    assert row.answer is None


def test_reading_asks_shopify_and_writes_nothing_back(db):
    row = _row(db)
    asked: list = []
    tags.read_tags(db, "5001", client=_shopify([CONFIRMED], asked))
    assert len(asked) == 1 and "tags" in asked[0]["query"]
    assert asked[0]["variables"] == {"id": "gid://shopify/Order/5001"}
    assert row.answer == "confirmed"
    # No tag write is queued in answer to a read.
    assert JobKind.INBOX_TAG_ORDER not in _jobs(db)


def test_no_read_while_our_own_tag_is_being_written(db):
    """Her tap is on its way to Shopify; the old tag must not undo it."""
    row = _row(db, answer="confirmed", answered_in="whatsapp")
    enqueue(db, JobKind.INBOX_TAG_ORDER, {"order_id": "5001"}, dedupe_key="tag:5001")
    asked: list = []
    tags.read_tags(db, "5001", client=_shopify([EDIT], asked))
    assert asked == []
    assert (row.answer, row.tags_read_at) == ("confirmed", None)


def test_an_unchanged_tag_read_again_does_not_undo_a_newer_tap(db):
    """Staff tagged Confirmed (taken); later she tapped Cancel and our write
    failed. Shopify still says Confirmed - an old answer, not a new one."""
    row = _row(db)
    tags.adopt(row, [CONFIRMED])
    row.answer, row.answered_in = "cancelled", "whatsapp"
    assert tags.adopt(row, [CONFIRMED]) is False
    assert (row.answer, row.answered_in) == ("cancelled", "whatsapp")


def test_a_tap_while_shopify_was_being_asked_wins(db):
    row = _row(db)

    class Slow:
        """Shopify answers - and meanwhile she taps Cancel."""

        def execute(self, document, variables):
            db.execute(
                text("UPDATE order_confirmation SET answer = 'cancelled', "
                     "answered_at = now(), answered_in = 'whatsapp' WHERE shopify_order_id = '5001'")
            )
            return {"order": {"tags": [CONFIRMED]}}

    tags.read_tags(db, "5001", client=Slow())
    assert (row.answer, row.answered_in) == ("cancelled", "whatsapp")
    # The tags are still kept, for the panel.
    assert row.shopify_tags == CONFIRMED


def test_the_read_is_dated_by_when_shopify_was_asked(db):
    """A change made while the read was running is newer than the read, so
    the sweep reads the order again."""
    row = _row(db)
    asked_at = utcnow() - timedelta(seconds=30)
    tags.adopt(row, [], asked_at=asked_at)
    assert row.tags_read_at == asked_at


def test_an_answer_from_a_tag_is_dated_by_the_orders_change_in_shopify(db):
    row = _row(db)
    tagged_at = utcnow() - timedelta(minutes=10)
    tags.adopt(row, [CONFIRMED], tagged_at=tagged_at)
    assert row.answered_at == tagged_at


def test_the_read_runs_in_the_inbox_lane():
    assert JobKind.INBOX_READ_TAGS in INBOX_WORK


# ── When it is read ───────────────────────────────────────────────────────────


def test_a_change_to_a_recent_order_queues_a_read(db):
    _row(db)
    queue_if_new(db, _indexed(db))
    assert _jobs(db).count(JobKind.INBOX_READ_TAGS) == 1


def test_a_settled_old_order_is_not_read(db):
    _row(db, placed=utcnow() - timedelta(days=20))
    queue_if_new(db, _indexed(db, placed=utcnow() - timedelta(days=20)))
    assert JobKind.INBOX_READ_TAGS not in _jobs(db)


def test_the_sweep_reads_what_was_never_read_or_changed_since(db):
    now = utcnow()
    _row(db, "1")
    _indexed(db, "1")
    _row(db, "2", tags_read_at=now - timedelta(hours=2))
    _indexed(db, "2", updated_at_shopify=now - timedelta(hours=1))
    _row(db, "3", tags_read_at=now - timedelta(minutes=5))
    _indexed(db, "3", updated_at_shopify=now - timedelta(hours=1))
    assert sorted(tags.stale_reads(db)) == ["1", "2"]


# ── The cards ─────────────────────────────────────────────────────────────────


def test_the_action_cards_count_only_orders_still_open_in_shopify(db):
    """18 October: 15 asked to cancel, 14 of them already cancelled."""
    _row(db, "1", answer="cancelled")
    _indexed(db, "1", cancelled_at=utcnow())
    _row(db, "2", answer="cancelled")
    _indexed(db, "2")
    _row(db, "3")  # waiting, shipped
    _indexed(db, "3", delivery_state="in_flight")
    _row(db, "4")  # waiting, open
    _indexed(db, "4", fulfillment_status="unfulfilled")
    _row(db, "5", answer="confirmed")  # an outcome: counted however it stands
    _indexed(db, "5", delivery_state="delivered", fulfillment_status="fulfilled")

    body = chats.confirmations(db)
    assert body["tiles"]["cancelled"] == 1 and body["done"]["cancelled"] == 1
    assert body["tiles"]["waiting"] == 1 and body["done"]["waiting"] == 1
    assert body["tiles"]["confirmed"] == 1
    assert "confirmed" not in body["done"]

    listed = chats.confirmations(db, tile="waiting")["orders"]
    assert [order["order_id"] for order in listed] == ["4"]


def test_an_unpaid_international_order_that_shipped_stays_on_its_card(db):
    """Paid before it ships (ADR 0062): shipped unpaid is somebody's job."""
    _row(db, "7", kind="payment")
    _indexed(db, "7", delivery_state="in_flight")
    _row(db, "8", kind="payment")
    _indexed(db, "8", cancelled_at=utcnow())
    body = chats.confirmations(db)
    assert body["tiles"]["awaiting_payment"] == 1
    assert body["done"]["awaiting_payment"] == 1


def test_an_order_not_yet_indexed_counts_as_open(db):
    _row(db, "9")
    assert chats.confirmations(db)["tiles"]["waiting"] == 1


def test_the_panel_says_what_shopify_has_and_where_the_answer_came_from(db):
    row = _row(db)
    tags.adopt(row, [CONFIRMED])
    described = chats.describe_order(row)
    assert described["shopify_tags"] == CONFIRMED
    assert described["answered_in"] == "shopify"
    assert described["tags_read_at"] is not None


def test_a_mark_in_the_inbox_says_so(db):
    _row(db)
    described = chats.set_answer(db, "5001", "edit", actor_id=None, actor_email=None)
    assert described["answered_in"] == "inbox"
