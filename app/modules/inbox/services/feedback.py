"""A delivered order is asked how it went, on WhatsApp (ADR 0083): who is
asked, the first question, and the sheet's reads.

**This decides and sends the first question; the rest of the conversation is
``feedback_replies``.** Everything a customer is sent in this feature is
worded in the constants below, so it is edited in one place.

The flow, in the inbox lane:

1. ``INBOX_FEEDBACK_SWEEP`` (every 30 minutes) finds delivered orders that
   are due - two days after Shopify's delivered date, no later than seven,
   and not before the feature was first switched on - reads each one's phone,
   first name and products from Shopify with a query of its own, applies the
   skips (``decide``) and records a row for it: ``pending`` to be asked, or
   ``skipped`` with the reason. **Every decided order has a row, so it is
   never looked at twice.** A skipped row keeps no customer details.
2. ``INBOX_FEEDBACK_SEND`` sends the first question, an approved template
   with three buttons. It is claimed in a transaction of its own before
   WhatsApp is asked, so it is sent at most once; on a server that may not
   message that customer it is recorded as ``would_send`` and nothing is sent.

**Off unless the server is told to** (``INBOX_FEEDBACK_ENABLED``): switched
off, the sweep returns at once and nothing is read or kept.
"""

import logging
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import Text, exists, func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import set_committed_value

from app.config import settings
from app.core.businesstime import utcnow
from app.modules.inbox.models import (
    FeedbackSettings,
    FeedbackSurvey,
    InboxConversation,
)
from app.modules.inbox.services import outbound, sending
from app.modules.inbox.services.events import _conversation
from app.modules.inbox.services.meta import MetaClient, MetaError
from app.modules.inbox.services.sending import egyptian_mobile
from app.shared.models.identity import UserAccount
from app.shared.models.orders import OrderIndex
from app.shared.services.jobs import JobKind, PermanentFailure, enqueue
from app.shared.services.shopify.client import ShopifyClient, ShopifyError
from app.shared.services.shopify.sync import PERMANENT, build_client, order_gid
from app.worker import register_handler

logger = logging.getLogger(__name__)

# ── What customers are sent ───────────────────────────────────────────────────
# Button titles are at most 20 characters, list rows 24, a list's own button
# 20 (WhatsApp's limits; ``MetaClient`` refuses anything longer).

#: The first question: an approved message, by the name and language Meta
#: holds it under. Its two details are her first name and the order's name;
#: its three buttons carry ``fb_<answer>_<order id>``.
TEMPLATE = "order_feedback"
LANGUAGE = "en"
#: The answers, in the order of the template's three buttons.
RATINGS = ("loved", "okay", "unhappy")
RATING_TITLES = {"loved": "Loved it", "okay": "It was okay", "unhappy": "Not happy"}

#: What the chat shows for the first question, which is a template.
FIRST_QUESTION_CHAT = "Order feedback · {order}"

#: The second approved message: *Was your issue solved?* for a customer whose
#: 24 hours have closed. One detail (the order's name), two buttons.
SOLVED_TEMPLATE = "feedback_resolved"
SOLVED_LANGUAGE = "en"
SOLVED_QUESTION = "Was your issue solved?"
SOLVED_CHAT = "Was your issue solved? · {order}"
SOLVED_BUTTONS = (("yes", "Yes"), ("no", "No"))

#: The one question after a rating, as a list: ``(id, title)`` rows.
LIST_LABEL = "Choose one"
REASON_QUESTIONS = {
    "loved": "What did you like most?",
    "okay": "What would have made it better?",
    "unhappy": "We're sorry. What went wrong?",
}
REASONS = {
    "loved": (
        ("quality", "Quality"), ("fit", "Fit"), ("design", "Design"),
        ("delivery", "Delivery"), ("other", "Something else"),
    ),
    "okay": (
        ("size_fit", "Size / fit"), ("quality", "Quality"), ("delivery", "Delivery"),
        ("packaging", "Packaging"), ("price", "Price"), ("other", "Something else"),
    ),
    "unhappy": (
        ("size_fit", "Size / fit"), ("quality", "Quality"), ("wrong_item", "Wrong item"),
        ("delivery", "Delivery"), ("other", "Something else"),
    ),
}

#: After a happy or middling customer's reason (code and link: the codes batch).
CLOSING = (
    "Thank you for your feedback, it really helps us. "
    "If there is anything we could do better, just reply here."
)
CODE_LINE = "Here is your code for 20% off your next order: {code}"
#: After an unhappy customer's reason. ``{hours}`` is the promised time.
SUPPORT = (
    "Thank you for telling us. A member of our team will message you here "
    "within {hours} hours."
)

#: After she says her issue was solved.
REORDER_QUESTION = "How likely are you to order from us again?"
REORDERS = (("very_likely", "Very likely"), ("maybe", "Maybe"), ("unlikely", "Unlikely"))

# ── When ──────────────────────────────────────────────────────────────────────

#: An order is asked this long after Shopify's delivered date...
ASK_AFTER = timedelta(days=2)
#: ...and not at all once it was delivered this long ago.
ASK_BEFORE = timedelta(days=7)
#: The same customer is not asked again within this long.
SAME_PHONE_FOR = timedelta(days=60)
#: Orders decided per sweep. A day's deliveries are a fraction of this.
SWEEP_BATCH = 50

# ── Why an order was not asked (``skip_reason``) ──────────────────────────────

SKIP_NOT_FOUND = "order_not_found"
SKIP_CANCELLED = "cancelled"
SKIP_TEST = "test_order"
SKIP_RETURN = "return_or_refund"
SKIP_NO_PHONE = "no_phone"
SKIP_BAD_PHONE = "bad_phone"
SKIP_ASKED_RECENTLY = "asked_recently"
SKIP_UNREAD = "unread_chat"
SKIP_UNHAPPY_OPEN = "unhappy_open"

#: What the feedback question needs from the order, and nothing else. Its own
#: query, like the confirmation's: a customer field Shopify refused here fails
#: only this job, never an order's indexing.
FEEDBACK_ORDER = """
query FeedbackOrder($id: ID!) {
  order(id: $id) {
    legacyResourceId
    name
    cancelledAt
    test
    phone
    customer { firstName phone }
    shippingAddress { phone }
    lineItems(first: 20) { nodes { title } }
  }
}
"""


def enabled() -> bool:
    """Whether this server asks about delivered orders at all."""
    return bool(settings.inbox_feedback_enabled)


def get_settings(db: Session) -> FeedbackSettings:
    """The feature's one settings row, made the first time it is asked for."""
    db.execute(
        insert(FeedbackSettings).values(id=1).on_conflict_do_nothing(index_elements=["id"])
    )
    return db.get(FeedbackSettings, 1)


# ── Who is due ────────────────────────────────────────────────────────────────


def due_orders(
    db: Session, now: datetime | None = None, *, limit: int = SWEEP_BATCH
) -> list[OrderIndex]:
    """Delivered orders whose feedback question is due and not yet decided.

    Delivered two to seven days ago and since the feature was first switched
    on; not cancelled, refunded or voided; no return in Shopify at all; no
    survey row yet. Oldest delivery first. Nothing before ``started_at`` is
    ever due, and with no ``started_at`` yet nothing is.
    """
    now = now or utcnow()
    started_at = get_settings(db).started_at
    if started_at is None:
        return []
    refunded = func.lower(func.coalesce(OrderIndex.financial_status, "")).in_(
        ("refunded", "voided")
    )
    return list(
        db.scalars(
            select(OrderIndex)
            .where(
                OrderIndex.delivery_state == "delivered",
                OrderIndex.delivered_at.is_not(None),
                OrderIndex.delivered_at <= now - ASK_AFTER,
                OrderIndex.delivered_at >= now - ASK_BEFORE,
                OrderIndex.delivered_at >= started_at,
                OrderIndex.cancelled_at.is_(None),
                ~refunded,
                OrderIndex.return_open.is_(False),
                OrderIndex.return_activity.is_(False),
                ~exists().where(FeedbackSurvey.shopify_order_id == OrderIndex.shopify_order_id),
            )
            .order_by(OrderIndex.delivered_at, OrderIndex.shopify_order_id)
            .limit(limit)
        )
    )


def _courier(fulfilments: list[dict] | None) -> str | None:
    """The courier that delivered it: the last fulfilment that names one."""
    names = [
        str(row.get("company")).strip()
        for row in fulfilments or []
        if isinstance(row, dict) and row.get("company")
    ]
    return names[-1][:80] if names else None


def _titles(node: dict) -> list[str]:
    nodes = ((node.get("lineItems") or {}).get("nodes")) or []
    return [str(item.get("title")).strip()[:200] for item in nodes if item.get("title")][:20]


def _asked_recently(db: Session, phone: str, now: datetime) -> bool:
    asked_at = func.coalesce(FeedbackSurvey.sent_at, FeedbackSurvey.created_at)
    return bool(
        db.scalar(
            select(FeedbackSurvey.id)
            .where(
                FeedbackSurvey.phone == phone,
                FeedbackSurvey.state.in_(("pending", "sending", "would_send", "sent")),
                asked_at >= now - SAME_PHONE_FOR,
            )
            .limit(1)
        )
    )


def _why_not(
    db: Session, order: OrderIndex, node: dict | None, now: datetime
) -> tuple[str | None, str | None]:
    """``(skip reason, phone)``: the first reason this order is not asked, or
    None and her number if it is."""
    if not node:
        return SKIP_NOT_FOUND, None
    if node.get("test"):
        return SKIP_TEST, None
    if node.get("cancelledAt"):
        return SKIP_CANCELLED, None

    # Operations' side of "a return" (ADR 0083, point 1): a return waiting for
    # review on E-stebdal, or a refund still owed. Through its public surface.
    from app.modules.operations.public import order_numbers_with_return_work

    if order_numbers_with_return_work(db, [order.order_number]):
        return SKIP_RETURN, None

    customer = node.get("customer") or {}
    given = [
        str(raw).strip()
        for raw in (node.get("phone"), customer.get("phone"), (node.get("shippingAddress") or {}).get("phone"))
        if raw and str(raw).strip()
    ]
    if not given:
        return SKIP_NO_PHONE, None
    phone = next((read for read in map(egyptian_mobile, given) if read), None)
    if phone is None:
        return SKIP_BAD_PHONE, None

    if _asked_recently(db, phone, now):
        return SKIP_ASKED_RECENTLY, None
    conversation = db.scalar(select(InboxConversation).where(InboxConversation.phone == phone))
    if conversation is not None and conversation.unread_count > 0:
        # She has written and nobody has answered: not the time to ask.
        return SKIP_UNREAD, None
    if db.scalar(
        select(FeedbackSurvey.id)
        .where(
            FeedbackSurvey.phone == phone,
            FeedbackSurvey.rating == "unhappy",
            FeedbackSurvey.step == "support",
        )
        .limit(1)
    ):
        # An unhappy answer still waiting for a person.
        return SKIP_UNHAPPY_OPEN, None
    return None, phone


def decide(
    db: Session, order: OrderIndex, shopify_order: dict | None, now: datetime | None = None
) -> FeedbackSurvey:
    """Decide one due order and record it. Returns the row.

    ``pending`` if she is to be asked, otherwise ``skipped`` with a short
    ``skip_reason``. A skipped row keeps no customer detail: no phone, no
    name, no products. An order already decided is returned as it stands.
    """
    now = now or utcnow()
    existing = db.scalar(
        select(FeedbackSurvey).where(FeedbackSurvey.shopify_order_id == order.shopify_order_id)
    )
    if existing is not None:
        return existing

    reason, phone = _why_not(db, order, shopify_order, now)
    node = shopify_order or {}
    values: dict[str, Any] = {
        "shopify_order_id": order.shopify_order_id,
        "order_name": (str(node.get("name") or "").strip() or order.order_number)[:40] or None,
        "delivered_at": order.delivered_at,
        "courier": _courier(order.fulfilments),
    }
    if reason is not None:
        values.update(state="skipped", skip_reason=reason, step="done")
    else:
        first_name = str((node.get("customer") or {}).get("firstName") or "").strip()
        values.update(
            state="pending",
            step="rating",
            phone=phone,
            # The confirmation's own fallback, for an order with no first name.
            customer_name=(first_name or "there")[:120],
            products=_titles(node),
        )
    db.execute(
        insert(FeedbackSurvey)
        .values(**values)
        .on_conflict_do_nothing(index_elements=["shopify_order_id"])
    )
    db.flush()
    return db.scalar(
        select(FeedbackSurvey).where(FeedbackSurvey.shopify_order_id == order.shopify_order_id)
    )


def sweep(
    db: Session, *, now: datetime | None = None, client: ShopifyClient | None = None
) -> int:
    """One pass: decide what is due and queue the sending. Returns how many
    orders were decided."""
    now = now or utcnow()
    interrupted = recover_interrupted(db)
    if interrupted:
        logger.warning("%s feedback questions were interrupted while sending", interrupted)

    cfg = get_settings(db)
    if cfg.started_at is None:
        # Nothing delivered before this moment is ever asked.
        cfg.started_at = now
        cfg.updated_at = now
        db.flush()

    due = due_orders(db, now)
    if not due:
        return 0
    try:
        client = client or build_client()
    except PERMANENT as exc:
        raise PermanentFailure(f"Cannot read orders for their feedback question: {exc}") from exc

    decided = 0
    for order in due:
        try:
            data = client.execute(FEEDBACK_ORDER, {"id": order_gid(order.shopify_order_id)})
        except PERMANENT as exc:
            raise PermanentFailure(
                f"Cannot read order {order.shopify_order_id} for its feedback question: {exc}"
            ) from exc
        except ShopifyError as exc:
            # Shopify is not answering. What is decided stands; the rest wait.
            logger.warning("feedback sweep stopped early: %s", exc)
            break
        row = decide(db, order, data.get("order"), now)
        decided += 1
        if row.state == "pending":
            queue_send(db, row.id)
    if decided:
        logger.info("feedback sweep decided %s orders", decided)
    return decided


# ── The first question ────────────────────────────────────────────────────────


def components(row: FeedbackSurvey) -> list[dict[str, Any]]:
    """The approved message's two details and three buttons: her first name
    and the order's name; then loved, okay, unhappy."""
    details = (row.customer_name or "there", row.order_name or "")
    built: list[dict[str, Any]] = [
        {"type": "body", "parameters": [{"type": "text", "text": detail} for detail in details]}
    ]
    for index, rating in enumerate(RATINGS):
        built.append(
            {
                "type": "button",
                "sub_type": "quick_reply",
                "index": str(index),
                "parameters": [
                    {"type": "payload", "payload": f"fb_{rating}_{row.shopify_order_id}"}
                ],
            }
        )
    return built


def queue_send(
    db: Session, survey_id: int, *, attempt: int | str = 0, run_after: datetime | None = None
) -> None:
    enqueue(
        db,
        JobKind.INBOX_FEEDBACK_SEND,
        {"survey_id": survey_id},
        run_after=run_after,
        # The attempt is in the key: a retry is queued while the attempt that
        # failed is still the running job under the old key.
        dedupe_key=f"{JobKind.INBOX_FEEDBACK_SEND}:{survey_id}:{attempt}",
    )


def _claim(survey_id: int) -> bool:
    """Take the survey for sending, in a transaction of its own.

    Committed before WhatsApp is asked: whatever happens next - a crash, a
    lost lease, a second worker - it is no longer ``pending``, and nobody
    else will send it.
    """
    from app.db import SessionLocal

    with SessionLocal() as own:
        claimed = own.execute(
            update(FeedbackSurvey)
            .where(FeedbackSurvey.id == survey_id, FeedbackSurvey.state == "pending")
            .values(state="sending", updated_at=utcnow())
        ).rowcount
        own.commit()
    return claimed == 1


def _not_taken(db: Session, row: FeedbackSurvey, exc: MetaError) -> None:
    """WhatsApp did not take the question. Say why, and what happens next."""
    row.attempts += 1
    row.last_error = str(exc)[:300]
    row.updated_at = utcnow()
    if exc.kind == "undeliverable":
        # The number has no WhatsApp. Trying again will not give it one.
        row.state = "no_whatsapp"
    elif exc.retryable and row.attempts < outbound.MAX_ATTEMPTS:
        row.state = "pending"
        wait = outbound.RETRY_AFTER[min(row.attempts, len(outbound.RETRY_AFTER)) - 1]
        row.next_attempt_at = utcnow() + wait
        queue_send(db, row.id, attempt=row.attempts, run_after=row.next_attempt_at)
    else:
        row.state = "failed"


def send_first_question(
    db: Session,
    survey_id: int,
    *,
    client: MetaClient | None = None,
    claim: Callable[[int], bool] = _claim,
) -> FeedbackSurvey | None:
    """Send one order's first question, if it is still waiting to be sent."""
    row = db.get(FeedbackSurvey, survey_id)
    if row is None or row.state != "pending" or not row.phone:
        return row
    if sending.refusal(db, row.phone):
        # This server may not message her: what would have been sent.
        row.state = "would_send"
        row.updated_at = utcnow()
        return row

    owned = client is None
    client = client or outbound._client(db)
    try:
        if not claim(survey_id):
            return row
        # The claim was committed in a session of its own, so this one still
        # holds the row as ``pending``; tell it what the database now says,
        # or putting it back to ``pending`` for a retry would be no change.
        set_committed_value(row, "state", "sending")
        try:
            wa_message_id = client.send_template(row.phone, TEMPLATE, LANGUAGE, components(row))
        except MetaError as exc:
            _not_taken(db, row, exc)
            return row
    finally:
        if owned:
            client.close()

    now = utcnow()
    name = row.customer_name if row.customer_name and row.customer_name != "there" else None
    conversation = _conversation(db, row.phone, name)
    row.state = "sent"
    row.wa_message_id = wa_message_id
    row.sent_at = now
    row.attempts += 1
    row.last_error = None
    row.next_attempt_at = None
    row.conversation_id = conversation.id
    row.updated_at = now
    outbound.record_outbound(
        db,
        conversation,
        kind="template",
        body=FIRST_QUESTION_CHAT.format(order=row.order_name or row.shopify_order_id),
        origin="automatic",
        status="sent",
        wa_message_id=wa_message_id,
        template_name=TEMPLATE,
        extra={"buttons": [RATING_TITLES[rating] for rating in RATINGS]},
        order_id=row.shopify_order_id,
    )
    return row


def recover_interrupted(db: Session) -> int:
    """Questions left ``sending`` by a crash become failed, never re-sent.

    Whether the message went out is not something the platform can know, so
    it says so and leaves the decision to a person.
    """
    recovered = db.execute(
        update(FeedbackSurvey)
        .where(
            FeedbackSurvey.state == "sending",
            FeedbackSurvey.updated_at < utcnow() - outbound.INTERRUPTED_AFTER,
        )
        .values(state="failed", last_error=outbound.INTERRUPTED, updated_at=utcnow())
    ).rowcount
    return recovered or 0


@register_handler(JobKind.INBOX_FEEDBACK_SWEEP)
def _handle_sweep(db: Session, payload: dict) -> None:
    if not enabled():
        return
    sweep(db)


@register_handler(JobKind.INBOX_FEEDBACK_SEND)
def _handle_send(db: Session, payload: dict) -> None:
    survey_id = payload.get("survey_id")
    if not isinstance(survey_id, int):
        raise PermanentFailure(
            f"{JobKind.INBOX_FEEDBACK_SEND} requires a survey_id; got payload keys "
            f"{sorted(payload)!r}"
        )
    # Queued while it was on, run after it was turned off: send nothing.
    if not enabled():
        return
    try:
        send_first_question(db, survey_id)
    except outbound.NotSent as exc:
        # The keys cannot be read. Retrying will not read them.
        raise PermanentFailure(f"Cannot send feedback question {survey_id}: {exc}") from exc


# ── What the Feedback sheet and Needs follow-up read ──────────────────────────


def _iso(at: datetime | None) -> str | None:
    return at.isoformat() if at else None


def describe(row: FeedbackSurvey, resolved_by: str | None = None) -> dict:
    """One survey as a plain dict, for the sheet and the follow-up list."""
    return {
        "id": row.id,
        "order_id": row.shopify_order_id,
        "order_name": row.order_name,
        "delivered_at": _iso(row.delivered_at),
        "sent_at": _iso(row.sent_at),
        "customer_name": row.customer_name,
        "phone": row.phone,
        "products": list(row.products or []),
        "courier": row.courier,
        "state": row.state,
        "skip_reason": row.skip_reason,
        "step": row.step,
        "rating": row.rating,
        "rated_at": _iso(row.rated_at),
        "reason": row.reason,
        "comment": row.comment,
        "comment_at": _iso(row.comment_at),
        "reorder": row.reorder,
        "needs_follow_up": row.rating == "unhappy" and row.step == "support",
        "resolved_at": _iso(row.resolved_at),
        "resolved_by": row.resolved_by,
        "resolved_by_name": resolved_by,
        "solved": row.solved,
        "solved_at": _iso(row.solved_at),
        "reopened_count": row.reopened_count,
        "code": row.code,
        "code_sent_at": _iso(row.code_sent_at),
        "code_expires_at": _iso(row.code_expires_at),
        "code_used_at": _iso(row.code_used_at),
        "code_order_name": row.code_order_name,
    }


def _like(text: str) -> str:
    """``%`` and ``_`` typed into a filter are letters, not wildcards."""
    escaped = text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def _names(db: Session, rows: list[FeedbackSurvey]) -> dict[int, str]:
    ids = {row.resolved_by for row in rows if row.resolved_by}
    if not ids:
        return {}
    return {
        user_id: name or email
        for user_id, name, email in db.execute(
            select(UserAccount.id, UserAccount.display_name, UserAccount.email).where(
                UserAccount.id.in_(ids)
            )
        )
    }


def needs_follow_up(db: Session) -> list[dict]:
    """Unhappy answers waiting for a person, longest waiting first."""
    rows = list(
        db.scalars(
            select(FeedbackSurvey)
            .where(FeedbackSurvey.rating == "unhappy", FeedbackSurvey.step == "support")
            .order_by(FeedbackSurvey.rated_at, FeedbackSurvey.id)
        )
    )
    return [describe(row) for row in rows]


def rows(
    db: Session,
    *,
    since: datetime | None = None,
    until: datetime | None = None,
    rating: str | None = None,
    reason: str | None = None,
    product: str | None = None,
    courier: str | None = None,
    include_skipped: bool = False,
    limit: int = 200,
    offset: int = 0,
) -> list[dict]:
    """The Feedback sheet: one dict per asked order, newest delivery first.

    ``since`` and ``until`` bound the delivered date. Skipped orders are not
    asked and are left out unless ``include_skipped``.
    """
    query = select(FeedbackSurvey)
    if not include_skipped:
        query = query.where(FeedbackSurvey.state != "skipped")
    if since is not None:
        query = query.where(FeedbackSurvey.delivered_at >= since)
    if until is not None:
        query = query.where(FeedbackSurvey.delivered_at < until)
    if rating:
        query = query.where(FeedbackSurvey.rating == rating)
    if reason:
        query = query.where(FeedbackSurvey.reason == reason)
    if courier:
        query = query.where(FeedbackSurvey.courier == courier)
    if product:
        query = query.where(FeedbackSurvey.products.cast(Text).ilike(_like(product), escape="\\"))
    found = list(
        db.scalars(
            query.order_by(
                FeedbackSurvey.delivered_at.desc().nulls_last(), FeedbackSurvey.id.desc()
            )
            .limit(max(1, min(limit, 1000)))
            .offset(max(0, offset))
        )
    )
    names = _names(db, found)
    return [describe(row, names.get(row.resolved_by)) for row in found]
