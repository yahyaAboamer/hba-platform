"""An order's confirmation tag in Shopify (ADR 0059, points 10 and 11).

**One of the two things the platform writes to Shopify**, beside an unpaid
international order's invoice email (ADR 0062). One of seven tags, on an
order, through the second Shopify app - never the connection that reads
money, which stays read-only (ADR 0015). It never cancels or edits an order:
a customer's Cancel is a tag for somebody to act on.

An order carries **one** of the seven at a time, as n8n left it: answering
clears *WA Sent*, and a number with no WhatsApp replaces it.

======================  ================================================
``WA Sent 📤``           the confirmation went out, no answer yet
``No WhatsApp 📵``       the number cannot be reached: call instead
``Confirmed ✅``         she tapped Confirm
``Edit ✏️``              she tapped Edit
``Cancelled ❌``         she tapped Cancel
``Awaiting payment 💳``  an international order's payment link went out
``Paid 💳``              it has been paid since
======================  ================================================

Operations' Shopify cards read these same spellings. Change one here and a
card stops counting.
"""

import logging
from datetime import timedelta

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.config import settings
from app.core.businesstime import utcnow
from app.modules.inbox.models import OrderConfirmation
from app.modules.inbox.services import connection
from app.shared.services.jobs import JobKind, PermanentFailure, enqueue
from app.shared.services.shopify.client import (
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
#: A payment request's two (ADR 0062, point 7).
AWAITING_PAYMENT = "Awaiting payment 💳"
PAID = "Paid 💳"

#: Every tag this module may add or remove. Nothing outside it is touched.
ALL_TAGS = (SENT, NO_WHATSAPP, *ANSWER_TAGS.values(), AWAITING_PAYMENT, PAID)

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

    Her answer first: once she has answered, that is what the order says. A
    payment request has no answer: it is paid, awaiting payment, or cannot
    be reached (ADR 0062).
    """
    if row.kind == "payment":
        # Only a request a message went out for is tagged at all: one that
        # was never sent - recorded on a server that may not message
        # customers, or with no usable number - leaves Shopify alone.
        if row.state not in ("sent", "no_whatsapp"):
            return None
        if row.paid_at is not None:
            return PAID
        return NO_WHATSAPP if row.state == "no_whatsapp" else AWAITING_PAYMENT
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


# ── Reading them back (ADR 0063) ──────────────────────────────────────────────

#: Which answer each answer tag means.
ANSWER_FROM_TAG = {tag: answer for answer, tag in ANSWER_TAGS.items()}

#: Orders whose confirmation was decided this recently have their tags read
#: when Shopify says they changed. Older ones are settled.
READ_FOR = timedelta(days=14)

#: How many orders one sweep queues for a read.
READ_BATCH = 500

ORDER_TAGS = """
query ConfirmationTagsRead($id: ID!) {
  order(id: $id) { tags }
}
"""


def _answer_tags(joined: str | None) -> set[str]:
    return {tag for tag in (joined or "").split(" + ") if tag in ANSWER_FROM_TAG}


def adopt(
    row: OrderConfirmation,
    shopify_tags: list[str],
    *,
    asked_at=None,
    tagged_at=None,
    may_answer: bool = True,
) -> bool:
    """Keep what Shopify says, and take an answer tagged there. Pure.

    Exactly one answer tag becomes the answer, given in Shopify - but only
    when the answer tags **changed since the last read** (or were never
    read). An unchanged tag is one the platform already knows, and taking it
    again would undo a newer tap or mark. Two answer tags at once are left
    alone; a removed tag takes nothing away. Returns whether the answer
    changed.

    ``asked_at`` is when Shopify was asked, so a change made while the read
    was running is still newer than the read. ``tagged_at`` is the closest
    the platform knows to when the tag was set (the order's last change in
    Shopify), so a tap made after it still wins.
    """
    asked_at = asked_at or utcnow()
    ours = [tag for tag in ALL_TAGS if tag in shopify_tags]
    first_read = row.tags_read_at is None
    changed = first_read or _answer_tags(row.shopify_tags) != set(ours) & set(ANSWER_FROM_TAG)
    row.shopify_tags = " + ".join(ours)[:160] or None
    row.tags_read_at = asked_at
    answers = [ANSWER_FROM_TAG[tag] for tag in ours if tag in ANSWER_FROM_TAG]
    # A payment request is answered by paying, which Shopify reports itself.
    if (
        not may_answer
        or not changed
        or row.kind == "payment"
        or len(answers) != 1
        or answers[0] == row.answer
    ):
        return False
    at = min(tagged_at or asked_at, asked_at)
    row.answer = answers[0]
    # A tag that changed since the last read is newer than the answer before it.
    row.answered_at = max(at, row.answered_at) if row.answered_at else at
    row.answered_in = "shopify"
    row.updated_at = utcnow()
    return True


def read_tags(
    db: Session, order_id: str, client: ShopifyClient | None = None
) -> OrderConfirmation | None:
    """Read the order's tags from Shopify and keep them. Writes nothing there.

    Through the connection that reads money, which stays read-only.
    """
    from app.shared.services.shopify.sync import build_client, order_gid

    row = db.scalar(
        select(OrderConfirmation).where(OrderConfirmation.shopify_order_id == order_id)
    )
    if row is None:
        return None
    if _writing(db, order_id):
        # Our own tag is on its way: what Shopify has now is about to be
        # replaced, and taking it as the answer would undo hers. The write
        # changes the order, which queues another read once it lands.
        return row
    answered_before = row.answered_at
    asked_at = utcnow()
    try:
        data = (client or build_client()).execute(ORDER_TAGS, {"id": order_gid(order_id)})
    except (ShopifyNotConfigured, ShopifyMissingScope) as exc:
        raise PermanentFailure(f"Cannot read order {order_id}'s tags: {exc}") from exc
    node = (data or {}).get("order")
    if node is None:
        return row
    # Shopify took a moment to answer. If she tapped, or staff marked it, in
    # that moment, theirs is newer than the tag just read: keep the tags, take
    # no answer from them.
    db.refresh(row)
    may_answer = row.answered_at == answered_before and not _writing(db, order_id)
    if adopt(
        row,
        [str(tag) for tag in node.get("tags") or []],
        asked_at=asked_at,
        tagged_at=_changed_in_shopify(db, order_id),
        may_answer=may_answer,
    ):
        logger.info("order %s: answer taken from its tag in Shopify", order_id)
    return row


def _changed_in_shopify(db: Session, order_id: str):
    """When Shopify last changed the order, as the index has it."""
    from app.shared.models.orders import OrderIndex

    return db.scalar(
        select(OrderIndex.updated_at_shopify).where(OrderIndex.shopify_order_id == order_id)
    )


def _writing(db: Session, order_id: str) -> bool:
    """Whether a tag write for this order is waiting or running."""
    from app.shared.models.integration import BackgroundJob
    from app.shared.services.jobs import JobStatus

    return bool(
        db.scalar(
            select(BackgroundJob.id)
            .where(
                BackgroundJob.kind == JobKind.INBOX_TAG_ORDER,
                BackgroundJob.payload["order_id"].astext == order_id,
                BackgroundJob.status.in_((JobStatus.PENDING, JobStatus.RUNNING)),
            )
            .limit(1)
        )
    )


def queue_read(db: Session, order_id: str) -> None:
    enqueue(
        db,
        JobKind.INBOX_READ_TAGS,
        {"order_id": order_id},
        dedupe_key=f"{JobKind.INBOX_READ_TAGS}:{order_id}",
    )


def stale_reads(db: Session, *, limit: int = READ_BATCH) -> list[str]:
    """Recent orders whose tags were never read, or changed in Shopify since.

    The catch-up for a change that arrived while a read was already running,
    and the first read of every recent order once this ships.
    """
    from app.shared.models.orders import OrderIndex

    return list(
        db.scalars(
            select(OrderConfirmation.shopify_order_id)
            .join(OrderIndex, OrderIndex.shopify_order_id == OrderConfirmation.shopify_order_id)
            .where(
                OrderConfirmation.placed_at >= utcnow() - READ_FOR,
                or_(
                    OrderConfirmation.tags_read_at.is_(None),
                    OrderIndex.updated_at_shopify > OrderConfirmation.tags_read_at,
                ),
            )
            .order_by(OrderConfirmation.placed_at.desc())
            .limit(limit)
        )
    )


@register_handler(JobKind.INBOX_READ_TAGS)
def _handle_read_tags(db: Session, payload: dict) -> None:
    order_id = str(payload.get("order_id") or "").strip()
    if not order_id:
        raise PermanentFailure(
            f"{JobKind.INBOX_READ_TAGS} requires an order_id; got payload keys {sorted(payload)!r}"
        )
    # Queued while confirmations were on, run after they were turned off.
    if not settings.inbox_confirmations_enabled:
        return
    read_tags(db, order_id)


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
