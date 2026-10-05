"""The Shopify tab: open orders not shipped yet, counted by their tags (ADR 0057).

**Its own query.** The order sync's shared query (``app.services.shopify.
queries``) runs on every webhook and feeds commission; one field Shopify
refuses there stops orders indexing. So Operations reads with the query
below and shares only the client.

Every 5 minutes the whole set of open, unshipped orders is read and replaces
``ops_shopify_order``; the cards are counted from that table when a page asks.
Which tags put an order on which card is decided once, in ``CARDS``.
"""

import logging
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Callable

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.businesstime import business_date, utcnow
from app.models.order_ops import OpsShopifyOrder
from app.services.jobs import JobKind
from app.services.order_ops.polling import (
    KeyRefused,
    NotConnected,
    PermanentlyUnavailable,
    SourceUnavailable,
    run_poll,
)
from app.services.shopify.client import (
    ShopifyClient,
    ShopifyError,
    ShopifyMissingScope,
    ShopifyNotConfigured,
)
from app.services.stale import admin_url
from app.worker import register_handler

logger = logging.getLogger(__name__)

#: Still open in Shopify (not archived, not cancelled) and not fully shipped.
#: Checked read-only against the live shop on 5 October 2026: Shopify accepts
#: the OR group, and it returned the same 29 orders as the 3 October count.
SEARCH = "status:open -status:cancelled (fulfillment_status:unfulfilled OR fulfillment_status:partial)"

OPEN_UNSHIPPED = """
query OperationsOpenUnshipped($query: String!, $after: String) {
  orders(first: 250, query: $query, after: $after, sortKey: CREATED_AT, reverse: true) {
    pageInfo { hasNextPage endCursor }
    nodes {
      legacyResourceId
      name
      createdAt
      displayFulfillmentStatus
      cancelledAt
      closed
      tags
    }
  }
}
"""

#: 250 a page: far more than a shop's open orders, and a bound on a loop
#: that trusts another system's cursor.
MAX_PAGES = 40


# ── Tags ──────────────────────────────────────────────────────────────────────


def tag_key(tag: str) -> str:
    """A tag as the rules compare it: case, spaces and emoji variation marks
    ignored, so ``Confirmed ✅`` and ``Confirmed✅`` - both written on new
    orders (owner, 3 Oct) - are the same tag."""
    return re.sub(r"\s+", "", tag.replace("️", "")).casefold()


CONFIRMED = tag_key("Confirmed ✅")
NO_ANSWER = tag_key("No answer")
NO_ANSWER_TWICE = tag_key("no answer( 2 times )")
WA_SENT = tag_key("WA Sent 📤")
NO_WHATSAPP = tag_key("No WhatsApp 📵")
BOSTA_SYNC_FAILED = tag_key("bosta_sync_failed")
COMPRESSION = tag_key("compression")
CALL_CONFIRMED = tag_key("Call Confirmed📞")
CANCELLED = tag_key("Cancelled ❌")


@dataclass(frozen=True)
class Card:
    key: str
    #: The tag that puts an order on the card - drawn highlighted in its list.
    hit: str
    counts: Callable[[set[str]], bool]


def _not_cancelled(rule: Callable[[set[str]], bool]) -> Callable[[set[str]], bool]:
    """An order the team tagged cancelled counts only on its own card (PRD)."""
    return lambda keys: CANCELLED not in keys and rule(keys)


#: S1-S7 of the PRD, in the order the tab shows them. An order can sit on
#: more than one card (S1 and S5, say); Confirmed takes an order off S2-S4.
CARDS: tuple[Card, ...] = (
    Card("confirmed", CONFIRMED, _not_cancelled(lambda k: CONFIRMED in k)),
    Card(
        "no_answer",
        NO_ANSWER,
        _not_cancelled(
            lambda k: NO_ANSWER in k and NO_ANSWER_TWICE not in k and CONFIRMED not in k
        ),
    ),
    Card(
        "no_answer_no_whatsapp_sent",
        NO_ANSWER,
        _not_cancelled(
            lambda k: NO_ANSWER in k
            and WA_SENT not in k
            and NO_WHATSAPP not in k
            and CONFIRMED not in k
        ),
    ),
    Card(
        "no_whatsapp",
        NO_WHATSAPP,
        _not_cancelled(lambda k: NO_WHATSAPP in k and CONFIRMED not in k),
    ),
    Card("bosta_sync_failed", BOSTA_SYNC_FAILED, _not_cancelled(lambda k: BOSTA_SYNC_FAILED in k)),
    Card(
        "compression_not_call_confirmed",
        COMPRESSION,
        _not_cancelled(lambda k: COMPRESSION in k and CALL_CONFIRMED not in k),
    ),
    Card("cancel_in_shopify", CANCELLED, lambda k: CANCELLED in k),
)


def cards_for(tags: list[str]) -> list[str]:
    """The keys of the cards an order with these tags counts on."""
    keys = {tag_key(tag) for tag in tags}
    return [card.key for card in CARDS if card.counts(keys)]


# ── Reading Shopify ───────────────────────────────────────────────────────────


def _parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def fetch_open_unshipped(client: ShopifyClient) -> list[dict]:
    """Every open, unshipped order, newest first. Only the fields above."""
    orders: list[dict] = []
    after = None
    for _ in range(MAX_PAGES):
        page = client.execute(OPEN_UNSHIPPED, {"query": SEARCH, "after": after})["orders"]
        for node in page["nodes"]:
            # The search already leaves these out; a second look costs nothing
            # and keeps a cancelled order off every card if it ever did not.
            if node.get("cancelledAt") or node.get("closed"):
                continue
            orders.append(node)
        info = page["pageInfo"]
        if not info["hasNextPage"]:
            return orders
        after = info["endCursor"]
    raise SourceUnavailable("Shopify returned more open orders than Operations reads.")


def _client(db: Session) -> ShopifyClient:
    from app.services.shopify.connection import client_for, effective

    try:
        return client_for(effective(db))
    except ShopifyNotConfigured:
        raise NotConnected from None


def read(db: Session, client: ShopifyClient | None = None) -> int:
    """Replace the snapshot with what Shopify has open now. Returns how many.

    Shopify's own error text is never passed on: each failure is named here
    in plain words (``polling``).
    """
    client = client or _client(db)
    try:
        nodes = fetch_open_unshipped(client)
    except ShopifyMissingScope:
        raise PermanentlyUnavailable(
            "Shopify hasn't given the platform access to orders."
        ) from None
    except ShopifyNotConfigured:
        raise NotConnected from None
    except ShopifyError as exc:
        if "rejected the credentials" in str(exc):
            raise KeyRefused("Shopify refused the platform's connection.") from None
        raise SourceUnavailable("Shopify didn't answer.") from None

    seen = utcnow()
    db.execute(delete(OpsShopifyOrder))
    db.add_all(
        OpsShopifyOrder(
            shopify_order_id=str(node["legacyResourceId"]),
            order_number=node["name"],
            placed_at=_parse_time(node["createdAt"]),
            tags=list(node.get("tags") or []),
            fulfillment_status=node.get("displayFulfillmentStatus"),
            seen_at=seen,
        )
        for node in nodes
    )
    db.flush()
    logger.info("order-ops shopify: %d open, unshipped orders", len(nodes))
    return len(nodes)


@register_handler(JobKind.ORDER_OPS_SHOPIFY)
def _handle_read(db: Session, payload: dict) -> None:
    run_poll(db, "shopify", read)


# ── The tab ───────────────────────────────────────────────────────────────────


def waiting_days(placed_at: datetime, now: datetime) -> int:
    """Calendar days since the order was placed, in Cairo: 0 is today."""
    return max((business_date(now) - business_date(placed_at)).days, 0)


def tab(db: Session, shop_domain: str | None, now: datetime | None = None) -> dict:
    """The cards and their lists, from the last clean read.

    Every card is listed, a zero included, so the tab's shape never changes.
    """
    now = now or utcnow()
    rows = db.scalars(
        select(OpsShopifyOrder).order_by(OpsShopifyOrder.placed_at.desc())
    ).all()

    lists: dict[str, list[dict]] = {card.key: [] for card in CARDS}
    hits = {card.key: card.hit for card in CARDS}
    for row in rows:
        for key in cards_for(row.tags):
            lists[key].append(
                {
                    "order_number": row.order_number,
                    "placed_at": row.placed_at.isoformat(),
                    "waiting_days": waiting_days(row.placed_at, now),
                    "tags": [
                        {"text": tag, "hit": tag_key(tag) == hits[key]} for tag in row.tags
                    ],
                    "admin_url": admin_url(shop_domain, row.shopify_order_id),
                }
            )

    return {
        "total": len(rows),
        "cards": [
            {"key": card.key, "count": len(lists[card.key]), "orders": lists[card.key]}
            for card in CARDS
        ],
    }
