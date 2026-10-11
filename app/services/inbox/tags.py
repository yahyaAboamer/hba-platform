"""An order's confirmation tag in Shopify (ADR 0059, points 10 and 11).

**The only thing the platform ever writes to Shopify.** One of five tags, on
an order, through the second Shopify app - never the connection that reads
money, which stays read-only (ADR 0015). It never cancels or edits an order:
a customer's Cancel is a tag for somebody to act on.

An order carries **one** of the five at a time, as n8n left it: answering
clears *WA Sent*, and a number with no WhatsApp replaces it.

==================  ================================================
``WA Sent 📤``       the confirmation went out, no answer yet
``No WhatsApp 📵``   the number cannot be reached: call instead
``Confirmed ✅``     she tapped Confirm
``Edit ✏️``          she tapped Edit
``Cancelled ❌``     she tapped Cancel
==================  ================================================

Operations' Shopify cards read these same spellings. Change one here and a
card stops counting.
"""

import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.models.inbox import OrderConfirmation
from app.services.inbox import connection
from app.services.jobs import JobKind, PermanentFailure, enqueue
from app.services.shopify.client import (
    ShopifyClient,
    ShopifyError,
    ShopifyMissingScope,
    ShopifyNotConfigured,
)
from app.worker import register_handler

logger = logging.getLogger(__name__)

SENT = "WA Sent 📤"
NO_WHATSAPP = "No WhatsApp 📵"
ANSWER_TAGS = {"confirmed": "Confirmed ✅", "edit": "Edit ✏️", "cancelled": "Cancelled ❌"}

#: Every tag this module may add or remove. Nothing outside it is touched.
ALL_TAGS = (SENT, NO_WHATSAPP, *ANSWER_TAGS.values())

TAGS_REMOVE = """
mutation ConfirmationTagsRemove($id: ID!, $tags: [String!]!) {
  tagsRemove(id: $id, tags: $tags) { userErrors { message } }
}
"""
TAGS_ADD = """
mutation ConfirmationTagsAdd($id: ID!, $tags: [String!]!) {
  tagsAdd(id: $id, tags: $tags) { userErrors { message } }
}
"""

NOT_CONNECTED = (
    "The Shopify app that writes order tags is not connected (Settings → Shopify)."
)


def wanted_tag(row: OrderConfirmation) -> str | None:
    """The one tag this order should carry, or None if it should carry none.

    Her answer first: once she has answered, that is what the order says.
    """
    if row.answer in ANSWER_TAGS:
        return ANSWER_TAGS[row.answer]
    if row.state == "no_whatsapp":
        return NO_WHATSAPP
    if row.state == "sent":
        return SENT
    return None


def tags_client(db: Session) -> ShopifyClient:
    """A client for the second Shopify app. Never the money connection."""
    app = connection.tags_app(db)
    if app is None:
        raise PermanentFailure(NOT_CONNECTED)
    return ShopifyClient(
        shop_domain=app.shop_domain,
        client_id=app.client_id,
        client_secret=app.client_secret,
        api_version=settings.shopify_api_version,
        timeout_seconds=settings.shopify_timeout_seconds,
    )


def _run(client: ShopifyClient, document: str, field: str, order_id: str, tags: list[str]) -> None:
    data = client.execute(document, {"id": f"gid://shopify/Order/{order_id}", "tags": tags})
    errors = ((data or {}).get(field) or {}).get("userErrors") or []
    if errors:
        # Shopify's own words about the order, not about a customer.
        raise ShopifyError(
            f"Shopify refused the tag change on order {order_id}: "
            + "; ".join(str(error.get("message")) for error in errors)[:200]
        )


def apply_tags(db: Session, order_id: str, client: ShopifyClient | None = None) -> str | None:
    """Make order ``order_id`` carry its one confirmation tag. Returns it.

    Reads what the order should say now, not what it should have said when
    the job was queued - so two answers in quick succession end on the last.
    """
    row = db.scalar(
        select(OrderConfirmation).where(OrderConfirmation.shopify_order_id == order_id)
    )
    if row is None or not order_id.isdigit():
        return None
    wanted = wanted_tag(row)
    if wanted is None:
        return None
    try:
        client = client or tags_client(db)
        _run(client, TAGS_REMOVE, "tagsRemove", order_id, [tag for tag in ALL_TAGS if tag != wanted])
        _run(client, TAGS_ADD, "tagsAdd", order_id, [wanted])
    except (ShopifyNotConfigured, ShopifyMissingScope) as exc:
        raise PermanentFailure(f"Cannot tag order {order_id}: {exc}") from exc
    return wanted


def queue_tags(db: Session, row: OrderConfirmation) -> None:
    """Queue the tag for what this order says now.

    The key carries the tag itself: a second answer while the first tag is
    still being written is a different key, so it is queued and not absorbed.
    """
    wanted = wanted_tag(row)
    if wanted is None:
        return
    enqueue(
        db,
        JobKind.INBOX_TAG_ORDER,
        {"order_id": row.shopify_order_id},
        dedupe_key=f"{JobKind.INBOX_TAG_ORDER}:{row.shopify_order_id}:{wanted}",
    )


@register_handler(JobKind.INBOX_TAG_ORDER)
def _handle_tag_order(db: Session, payload: dict) -> None:
    order_id = str(payload.get("order_id") or "").strip()
    if not order_id:
        raise PermanentFailure(
            f"{JobKind.INBOX_TAG_ORDER} requires an order_id; got payload keys {sorted(payload)!r}"
        )
    tag = apply_tags(db, order_id)
    if tag:
        logger.info("order %s tagged for its confirmation", order_id)
