"""The old chats, brought over from n8n (ADR 0059, point 17; the plan's phase 5).

Run by hand, on the server, with n8n's database read-only::

    N8N_DATABASE_URL='postgresql://…' python -m app.services.inbox.importer --dry-run
    N8N_DATABASE_URL='postgresql://…' python -m app.services.inbox.importer
    N8N_DATABASE_URL='postgresql://…' python -m app.services.inbox.importer --check

It prints counts only - no name, phone or message.

**What n8n kept** (read from its database on 12 October 2026):

- ``inbox_messages``: one row per message, by phone, with ``dir`` ``in`` or
  ``out``, the words, a time in milliseconds, and a file's WhatsApp id and
  kind. **No WhatsApp message id**: a tap is stored as the words "👆 Confirm
  order", not as the button's payload, and no reply says what it answers.
- ``wa_sends``: one row per confirmation sent - WhatsApp's id, the order and
  the phone.
- ``shopify_order_events``: Shopify's order as it arrived, for the order's
  number, first name, total and when it was placed.

**What each becomes:**

- **The sends first.** Each order n8n messaged becomes an ``order_confirmation``
  that says ``sent``, with its phone and WhatsApp's id, so the platform never
  sends it a second message and a tap on it from that phone is believed. An
  order the platform has already recorded while running silently is moved to
  ``sent``; one it has itself sent is left alone. Nothing is tagged: n8n
  tagged them.
- **A tap** is given to the order last sent to that phone before it, as the
  button's own payload would have said. The order's answer is her last tap.
- **"⚠️ Not delivered"** is a note n8n wrote into the chat as if she had said
  it. It is not imported as a message; the order it follows is recorded as
  ``no_whatsapp`` instead.
- **The confirmation itself** is the outgoing message nearest the send, and
  is marked as the template with its three buttons. The three automatic
  replies are marked automatic. Every other reply is ``imported``: n8n never
  recorded who sent it.
- **A file** Meta may still hold (under 30 days old) waits to be copied, as
  one arriving now does; an older one is ``gone``.

**Run it again and nothing doubles.** Every message carries ``n8n:<id>`` in
``source_ref``, which is unique, and an order already recorded as sent is
not touched.
"""

import argparse
import bisect
import json
import os
import re
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Iterable

from sqlalchemy import create_engine, func, select, text
from sqlalchemy.orm import Session

from app.core.businesstime import utcnow
from app.models.inbox import InboxConversation, InboxMedia, InboxMessage, OrderConfirmation
from app.services.inbox.events import ANSWERS, _PREVIEW
from app.services.inbox.media import queue_fetch
from app.services.inbox.outbound import TEMPLATE

#: The confirmation's three buttons, as the chat draws them.
BUTTONS = ["Confirm", "Edit", "Cancel"]

#: Her tap, as n8n wrote it into the chat.
TAPS = {"👆 Confirm order": "confirm", "👆 Edit order": "edit", "👆 Cancel order": "cancel"}

#: n8n's note that the confirmation could not be delivered.
NOT_DELIVERED = "⚠️ Not delivered"
#: n8n's stand-in for something she sent that it could not show.
CANNOT_VIEW = "⚠️ Sent something we cannot view"
#: n8n's stand-in for a reaction, which never said what it was on.
REACTION = "[reaction message]"

#: The automatic replies to a tap, as n8n sent them.
AUTOMATIC = (
    "Your order is confirmed ✅",
    "Your order has been cancelled ❌",
    "What would you like to change?",
)

#: The words n8n put on a file that came with none of its own.
FILE_WORDS = {"📷 Photo", "🎤 Voice note", "🎥 Video", "📹 Video", "🎬 Video", "📄 Document"}
FILE_KINDS = {"image": "image/jpeg", "audio": "audio/ogg", "video": "video/mp4", "document": None}

#: How far from the send its message may be and still be taken for it.
SEND_MATCH = timedelta(minutes=5)
#: How long Meta keeps a file for fetching. Older ones are gone.
MEDIA_KEPT = timedelta(days=30)

SOURCE_ENV = "N8N_DATABASE_URL"


@dataclass(frozen=True)
class OldMessage:
    id: int
    phone: str
    name: str | None
    direction: str
    text: str
    ts: int
    is_read: bool
    media_id: str
    media_type: str


@dataclass(frozen=True)
class OldSend:
    wamid: str
    order_id: str
    phone: str | None
    ts: int


@dataclass(frozen=True)
class OldOrder:
    """The parts of Shopify's order the confirmation needs. Nothing more."""

    order_id: str
    name: str | None
    first_name: str | None
    total: str | None
    placed_at: datetime | None


def phone_of(raw: str | None) -> str:
    """The phone as WhatsApp gives it. n8n kept seven Egyptian numbers with
    the leading 0 left in after the country code (``2001…``)."""
    digits = re.sub(r"\D", "", raw or "")
    if len(digits) == 13 and digits.startswith("200"):
        digits = "20" + digits[3:]
    return digits


def _at(ts: int) -> datetime:
    return datetime.fromtimestamp(ts / 1000, tz=timezone.utc)


def _total(raw: object) -> str | None:
    try:
        return f"{Decimal(str(raw)):.2f}" if raw not in (None, "") else None
    except (InvalidOperation, ValueError):
        return None


def order_from_payload(order_id: str, payload: dict) -> OldOrder:
    """Shopify's order webhook, cut down to what the confirmation said."""
    customer = payload.get("customer") or {}
    try:
        placed = datetime.fromisoformat(str(payload.get("created_at")))
    except ValueError:
        placed = None
    return OldOrder(
        order_id=str(order_id),
        name=(str(payload.get("name") or "")[:40] or None),
        first_name=(str(customer.get("first_name") or "").strip() or "there")[:120],
        total=_total(payload.get("total_price")),
        placed_at=placed.astimezone(timezone.utc) if placed else None,
    )


# ── Reading n8n ───────────────────────────────────────────────────────────────


def source_url(raw: str) -> str:
    """Railway writes ``postgresql://``; SQLAlchemy reads that as psycopg2,
    which this server does not have."""
    for prefix in ("postgresql://", "postgres://"):
        if raw.startswith(prefix):
            return "postgresql+psycopg://" + raw[len(prefix):]
    return raw


def _source(url: str):
    # Read-only on n8n's side too, so no mistake here can change it.
    return create_engine(source_url(url), connect_args={"options": "-c default_transaction_read_only=on"})


def read_source(url: str) -> tuple[list[OldMessage], list[OldSend], dict[str, OldOrder]]:
    """Everything the import needs from n8n, read in one read-only transaction."""
    engine = _source(url)
    try:
        with engine.connect() as source:
            messages = [
                OldMessage(*row)
                for row in source.execute(
                    text(
                        "SELECT id, phone, name, dir, text, ts, is_read, media_id, media_type "
                        "FROM inbox_messages ORDER BY ts, id"
                    )
                )
            ]
            sends = [
                OldSend(*row)
                for row in source.execute(text("SELECT wamid, order_id, phone, ts FROM wa_sends ORDER BY ts"))
            ]
            # The latest event per order: a repeated webhook says the same thing.
            orders = {
                str(order_id): order_from_payload(order_id, payload)
                for order_id, payload in source.execute(
                    text(
                        "SELECT DISTINCT ON (shopify_order_id) shopify_order_id, payload "
                        "FROM shopify_order_events ORDER BY shopify_order_id, received_at DESC"
                    )
                )
            }
    finally:
        engine.dispose()
    return messages, sends, orders


# ── Bringing it over ──────────────────────────────────────────────────────────


def _kind_and_body(message: OldMessage) -> tuple[str, str | None, dict | None]:
    words = message.text.strip()
    if message.direction == "in":
        if words in TAPS:
            return "button", message.text, None
        if words.startswith(CANNOT_VIEW):
            return "unsupported", None, None
        if words == REACTION:
            return "reaction", None, None
    if message.media_id and message.media_type in FILE_KINDS:
        extra = {"voice": True} if message.media_type == "audio" else None
        return message.media_type, (None if words in FILE_WORDS else message.text), extra
    return "text", message.text, None


def import_all(
    db: Session,
    messages: Iterable[OldMessage],
    sends: Iterable[OldSend],
    orders: dict[str, OldOrder],
    *,
    now: datetime | None = None,
) -> dict:
    """Bring n8n's record into this database. Returns what was done, in counts."""
    now = now or utcnow()
    messages = list(messages)
    sends = sorted(sends, key=lambda send: send.ts)
    report: Counter = Counter()
    report["source_messages"] = len(messages)
    report["source_sends"] = len(sends)

    # Each phone's sends in time order, for "the order sent to her before this".
    by_phone: dict[str, list[OldSend]] = defaultdict(list)
    for send in sends:
        by_phone[phone_of(send.phone)].append(send)
    send_times = {phone: [send.ts for send in group] for phone, group in by_phone.items()}

    def sent_before(phone: str, ts: int) -> OldSend | None:
        times = send_times.get(phone)
        if not times:
            return None
        at = bisect.bisect_right(times, ts) - 1
        return by_phone[phone][at] if at >= 0 else None

    # Her answer, and whether it was undeliverable, per order.
    answers: dict[str, tuple[str, int]] = {}
    undelivered: set[str] = set()
    tap_orders: dict[int, str] = {}
    for message in messages:
        if message.direction != "in":
            continue
        words = message.text.strip()
        send = sent_before(phone_of(message.phone), message.ts)
        if words in TAPS and send:
            tap_orders[message.id] = send.order_id
            answers[send.order_id] = (ANSWERS[TAPS[words]], message.ts)
        elif words.startswith(NOT_DELIVERED) and send:
            undelivered.add(send.order_id)

    # The confirmation itself: the outgoing message nearest each send.
    outgoing: dict[str, list[OldMessage]] = defaultdict(list)
    for message in messages:
        if message.direction == "out":
            outgoing[phone_of(message.phone)].append(message)
    template_of: dict[int, OldSend] = {}
    for send in sends:
        candidates = [
            message
            for message in outgoing.get(phone_of(send.phone), [])
            if message.id not in template_of
            and abs(message.ts - send.ts) <= SEND_MATCH.total_seconds() * 1000
            and not message.text.startswith(AUTOMATIC)
        ]
        if candidates:
            nearest = min(candidates, key=lambda message: abs(message.ts - send.ts))
            template_of[nearest.id] = send

    # ── Conversations, by phone ──
    conversations = {c.phone: c for c in db.scalars(select(InboxConversation))}
    names: dict[str, tuple[int, str]] = {}
    for message in messages:
        if message.name and message.name.strip():
            phone = phone_of(message.phone)
            # Her own name as WhatsApp gave it, where she wrote; else any.
            rank = (1 if message.direction == "in" else 0, message.ts)
            if phone not in names or rank > names[phone][0]:
                names[phone] = (rank, message.name.strip()[:120])
    for phone in {phone_of(message.phone) for message in messages} | set(by_phone):
        if not phone:
            continue
        if phone not in conversations:
            conversation = InboxConversation(phone=phone, name=names.get(phone, (None, None))[1])
            db.add(conversation)
            conversations[phone] = conversation
            report["conversations_created"] += 1
        elif not conversations[phone].name and phone in names:
            conversations[phone].name = names[phone][1]
    db.flush()

    # ── The sends, first ──
    held = {row.shopify_order_id: row for row in db.scalars(select(OrderConfirmation))}
    latest_send: dict[str, OldSend] = {}
    for send in sends:
        latest_send[send.order_id] = send
    for order_id, send in latest_send.items():
        phone = phone_of(send.phone)
        old = orders.get(order_id)
        row = held.get(order_id)
        if row is not None and row.state in ("sent", "no_whatsapp") and row.wa_message_id not in (None, send.wamid):
            # The platform sent this one itself.
            report["orders_already_sent_here"] += 1
            continue
        if row is None:
            row = OrderConfirmation(shopify_order_id=order_id, attempts=1)
            db.add(row)
            held[order_id] = row
            report["orders_created"] += 1
        elif row.wa_message_id == send.wamid:
            report["orders_already_imported"] += 1
        else:
            report[f"orders_moved_from_{row.state}"] += 1
        row.state = "no_whatsapp" if order_id in undelivered else "sent"
        row.wa_message_id = send.wamid
        row.phone = phone or row.phone
        row.sent_at = _at(send.ts)
        row.conversation_id = conversations[phone].id if phone in conversations else row.conversation_id
        row.next_attempt_at = None
        row.last_error = None
        if old is not None:
            row.order_name = row.order_name or old.name
            row.customer_name = row.customer_name or old.first_name
            row.total_text = row.total_text or old.total
            row.placed_at = row.placed_at or old.placed_at
        if order_id in answers:
            answer, ts = answers[order_id]
            if row.answered_at is None or row.answered_at < _at(ts):
                row.answer, row.answered_at = answer, _at(ts)
        row.updated_at = now
    db.flush()

    # ── The messages ──
    done = set(
        db.scalars(select(InboxMessage.source_ref).where(InboxMessage.source_ref.like("n8n:%")))
    )
    touched: set[int] = set()
    for message in messages:
        ref = f"n8n:{message.id}"
        if message.direction == "in" and message.text.strip().startswith(NOT_DELIVERED):
            report["notes_kept_as_order_state"] += 1
            continue
        if ref in done:
            report["messages_already_imported"] += 1
            continue
        phone = phone_of(message.phone)
        conversation = conversations[phone]
        kind, body, extra = _kind_and_body(message)
        send = template_of.get(message.id)
        fields: dict = {}
        if message.direction == "in":
            origin, status = "customer", "received"
            if message.id in tap_orders:
                order_id = tap_orders[message.id]
                fields["shopify_order_id"] = order_id
                extra = {"payload": f"{TAPS[message.text.strip()]}_{order_id}"}
        else:
            status = "sent"
            origin = "automatic" if message.text.startswith(AUTOMATIC) else "imported"
            if send is not None:
                kind, origin = "template", "automatic"
                fields.update(
                    shopify_order_id=send.order_id,
                    template_name=TEMPLATE,
                    wa_message_id=send.wamid,
                )
                extra = {"buttons": BUTTONS}
        row = InboxMessage(
            conversation_id=conversation.id,
            direction=message.direction,
            kind=kind,
            body=body,
            status=status,
            origin=origin,
            extra=extra,
            occurred_at=_at(message.ts),
            source_ref=ref,
            **fields,
        )
        db.add(row)
        report[f"messages_{message.direction}_{kind}"] += 1
        touched.add(conversation.id)
        if kind in FILE_KINDS and message.media_id:
            db.flush()
            fresh = now - _at(message.ts) < MEDIA_KEPT
            media = InboxMedia(
                message_id=row.id,
                wa_media_id=message.media_id,
                mime_type=FILE_KINDS[kind],
                state="pending" if fresh else "gone",
            )
            db.add(media)
            db.flush()
            if fresh:
                queue_fetch(db, media.id)
            report["media_to_fetch" if fresh else "media_gone"] += 1
        if message.direction == "in" and not message.is_read and kind != "reaction":
            conversation.unread_count = (conversation.unread_count or 0) + 1
    db.flush()

    # ── What each list row shows, from everything it now holds ──
    for conversation in conversations.values():
        if conversation.id not in touched:
            continue
        rows = db.scalars(
            select(InboxMessage)
            .where(InboxMessage.conversation_id == conversation.id, InboxMessage.kind != "reaction")
            .order_by(InboxMessage.occurred_at.desc(), InboxMessage.id.desc())
        ).all()
        if not rows:
            continue
        last = rows[0]
        conversation.last_message_at = last.occurred_at
        conversation.last_direction = last.direction
        tapped = TAPS.get((last.body or "").strip()) if last.kind == "button" else None
        preview = (
            {"confirm": "Tapped Confirm", "edit": "Tapped Edit", "cancel": "Tapped Cancel"}[tapped]
            if tapped
            else last.body or _PREVIEW.get(last.kind)
        )
        conversation.last_preview = preview[:160] if preview else None
        inbound = [row.occurred_at for row in rows if row.direction == "in"]
        if inbound:
            conversation.last_inbound_at = max(inbound + [conversation.last_inbound_at or inbound[0]])
    db.flush()

    report["conversations"] = len(conversations)
    return dict(sorted(report.items()))


def check(db: Session, messages: Iterable[OldMessage]) -> dict:
    """Each chat's messages here against n8n's, in counts: the phase's test.

    A "Not delivered" note is not a message here (it is the order's state),
    so it is left out of n8n's side.
    """
    theirs: Counter = Counter(
        phone_of(message.phone)
        for message in messages
        if not (message.direction == "in" and message.text.strip().startswith(NOT_DELIVERED))
    )
    ours: Counter = Counter(
        dict(
            db.execute(
                select(InboxConversation.phone, func.count(InboxMessage.id))
                .join(InboxMessage, InboxMessage.conversation_id == InboxConversation.id)
                .where(InboxMessage.source_ref.like("n8n:%"))
                .group_by(InboxConversation.phone)
            ).all()
        )
    )
    differ = [phone for phone in set(theirs) | set(ours) if theirs[phone] != ours[phone]]
    return {
        "n8n_conversations": len(theirs),
        "imported_conversations": len(ours),
        "n8n_messages": sum(theirs.values()),
        "imported_messages": sum(ours.values()),
        "conversations_that_differ": len(differ),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="do everything, report it, and keep none of it")
    mode.add_argument("--check", action="store_true", help="compare each chat's count with n8n's; change nothing")
    arguments = parser.parse_args(argv)
    url = os.environ.get(SOURCE_ENV)
    if not url:
        print(f"Set {SOURCE_ENV} to n8n's database address.", file=sys.stderr)
        return 2

    from app.db import SessionLocal

    messages, sends, orders = read_source(url)
    if arguments.check:
        with SessionLocal() as db:
            result = check(db, messages)
        json.dump(result, sys.stdout, indent=2)
        sys.stdout.write("\n")
        return 1 if result["conversations_that_differ"] else 0
    with SessionLocal() as db:
        report = import_all(db, messages, sends, orders)
        if arguments.dry_run:
            db.rollback()
        else:
            db.commit()
    report["dry_run"] = arguments.dry_run
    json.dump(report, sys.stdout, indent=2, ensure_ascii=False)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
