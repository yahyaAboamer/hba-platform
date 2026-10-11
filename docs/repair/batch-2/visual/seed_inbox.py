"""Fill a throwaway database with the Inbox mockup's own cast, so the built
screens can be put beside `docs/design/whatsapp-inbox-2026-10-11.html` and the
difference is the design, not the data.

Every name, phone number, order and message here is made up, as in the mockup.

It adds to the database rather than emptying it: run it after
`seed_browser.py`, or on its own on a migrated database. Only the inbox's own
tables are cleared.

## What cannot match

- **Photos and voice notes.** A kept file is read from the media bucket, and
  a throwaway database has none. Nour's photo is seeded as still being
  fetched and her voice note as gone; a stored one is covered by the tests.
- **Replies.** WhatsApp is not connected to anything real. A reply typed here
  is refused with the reason, which is the server's rule on who may be
  messaged doing its job.

## Refuses anything but a scratch database

    DATABASE_URL='postgresql+psycopg://hba:hba@127.0.0.1:5433/hba_browser' \
    APP_ENV=development GO_LIVE_MONTH=2026-06 \
    .venv/Scripts/python.exe docs/repair/batch-2/visual/seed_inbox.py

Sign in as mariam@example.com (customer service), amr@example.com (operations
manager) or owner@example.com (admin), all with `PASSWORD` below.
"""

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

from sqlalchemy import select, text  # noqa: E402

from app.config import settings  # noqa: E402
from app.core.passwords import hash_password  # noqa: E402
from app.db import SessionLocal, engine  # noqa: E402
from app.models.identity import UserAccount  # noqa: E402
from app.models.inbox import (  # noqa: E402
    InboxConnection,
    InboxConversation,
    InboxMedia,
    InboxMessage,
    MetaWebhookEvent,
    OrderConfirmation,
)

PASSWORD = "a-long-enough-password"
NOW = datetime.now(timezone.utc)

INBOX_TABLES = (
    "inbox_media", "inbox_message", "order_confirmation", "inbox_conversation",
    "meta_webhook_event", "inbox_connection",
)


def refuse_anything_but_a_scratch_database() -> None:
    name = engine.url.database or ""
    if not name.startswith("hba_browser"):
        raise SystemExit(
            f"Refusing to run against {name!r}. This script clears the inbox's "
            "tables. Point DATABASE_URL at a database named hba_browser*."
        )
    if settings.app_env != "development":
        raise SystemExit(f"Refusing to run: APP_ENV is {settings.app_env!r}.")


def ago(**delta) -> datetime:
    return NOW - timedelta(**delta)


def staff(db, name: str, email: str, role: str) -> int:
    """The account, made if it is not there, holding exactly this role."""
    row = db.scalar(select(UserAccount).where(UserAccount.email == email))
    if row is None:
        row = UserAccount(
            email=email, password_hash=hash_password(PASSWORD), status="active", display_name=name
        )
        db.add(row)
        db.flush()
    db.execute(text("DELETE FROM role_assignment WHERE user_account_id = :u"), {"u": row.id})
    db.execute(
        text("INSERT INTO role_assignment (user_account_id, role) VALUES (:u, :r)"),
        {"u": row.id, "r": role},
    )
    return row.id


def chat(db, phone, name, *, at, preview, direction="in", unread=0, heard=None) -> InboxConversation:
    row = InboxConversation(
        phone=phone, name=name, last_message_at=at, last_preview=preview,
        last_direction=direction, unread_count=unread,
        last_inbound_at=heard if heard is not None else (at if direction == "in" else None),
    )
    db.add(row)
    db.flush()
    return row


def say(db, conversation, body, *, at, out=False, kind="text", status=None, origin=None, **fields):
    row = InboxMessage(
        conversation_id=conversation.id, direction="out" if out else "in", kind=kind, body=body,
        status=status or ("read" if out else "received"),
        origin=origin or ("automatic" if out else "customer"),
        occurred_at=at, **fields,
    )
    db.add(row)
    db.flush()
    return row


def order(db, number, conversation, *, state="sent", answer=None, placed, name, **fields):
    phone = fields.pop("phone", conversation.phone if conversation else None)
    row = OrderConfirmation(
        shopify_order_id=f"59{number}", order_name=f"#{number}", state=state, answer=answer,
        conversation_id=conversation.id if conversation else None,
        phone=phone, customer_name=name, total_text=fields.pop("total", "1450.00"),
        placed_at=placed,
        sent_at=fields.pop("sent_at", placed + timedelta(minutes=1) if state == "sent" else None),
        answered_at=fields.pop("answered_at", placed + timedelta(minutes=4) if answer else None),
        **fields,
    )
    db.add(row)
    db.flush()
    return row


def main() -> None:
    refuse_anything_but_a_scratch_database()
    with engine.begin() as connection:
        connection.execute(
            text("TRUNCATE " + ", ".join(INBOX_TABLES) + " RESTART IDENTITY CASCADE")
        )
    db = SessionLocal()

    staff(db, "Yahya", "owner@example.com", "admin")
    mariam = staff(db, "Mariam", "mariam@example.com", "customer_service")
    staff(db, "Amr", "amr@example.com", "operations_manager")

    # Connected and switched on, with keys nothing can read: this server may
    # still message nobody, which is what a reply typed here is told.
    db.add(InboxConnection(
        id=1, phone_number_id="100000000000001", business_account_id="200000000000002",
        display_number="+20 100 555 0100", verified_name="HBA Wear",
        access_token_encrypted="not-a-key", app_secret_encrypted="not-a-key",
        verify_token_encrypted="not-a-key", access_token_hint="4f2a", app_secret_hint="91c0",
        verified_at=NOW, sending_enabled=True,
    ))
    db.add(MetaWebhookEvent(digest="a" * 64, payload={}, received_at=ago(minutes=1), processed_at=NOW))

    # ── Frame 1: Nour, who tapped Edit and is waiting on an answer ────────
    nour = chat(db, "201005550188", "Nour Adel", at=ago(minutes=1), preview="Voice note", unread=2)
    order(db, "28104", nour, answer="confirmed", placed=ago(days=89), name="Nour")
    order(db, "29871", nour, answer="confirmed", placed=ago(days=39), name="Nour")
    order(db, "31044", nour, answer="edit", placed=ago(minutes=80), name="Nour")
    confirmation = say(
        db, nour,
        "Hi Nour, thank you for your order #31044. Your total is EGP 1,450, cash on delivery. "
        "Please confirm it below.",
        at=ago(minutes=79), out=True, kind="template", template_name="order_confirmation",
        shopify_order_id="5931044", wa_message_id="wamid.N1",
        extra={"buttons": ["Confirm", "Edit", "Cancel"]},
    )
    say(db, nour, "Edit", at=ago(minutes=76), kind="button", shopify_order_id="5931044",
        wa_message_id="wamid.N2", reply_to_wa_id=confirmation.wa_message_id,
        extra={"payload": "edit_5931044"})
    say(db, nour, "What would you like to change? ✏️ Type it here and our team will help you.",
        at=ago(minutes=76), out=True, wa_message_id="wamid.N3")
    say(db, nour, "Hi, I ordered the black set but I want it in beige please",
        at=ago(minutes=75), wa_message_id="wamid.N4")
    photo = say(db, nour, "This one", at=ago(minutes=75), kind="image", wa_message_id="wamid.N5")
    db.add(InboxMedia(message_id=photo.id, wa_media_id="m1", mime_type="image/jpeg", state="pending"))
    say(db, nour, "Of course. Beige in the same size, M?", at=ago(minutes=70), out=True,
        origin="staff", sent_by=mariam, wa_message_id="wamid.N6", reply_to_wa_id="wamid.N5")
    say(db, nour, "Yes M", at=ago(minutes=2), wa_message_id="wamid.N7")
    voice = say(db, nour, None, at=ago(minutes=1), kind="audio", wa_message_id="wamid.N8",
                extra={"voice": True})
    db.add(InboxMedia(message_id=voice.id, wa_media_id="m2", mime_type="audio/ogg", state="gone"))

    # ── The rest of the list ──────────────────────────────────────────────
    salma = chat(db, "201005550121", "Salma Hany", at=ago(minutes=13),
                 preview="Can I change the size to M?", unread=1)
    say(db, salma, "Can I change the size to M?", at=ago(minutes=13), wa_message_id="wamid.S1")
    order(db, "31043", salma, placed=ago(minutes=50), name="Salma")

    unnamed = chat(db, "201005550143", None, at=ago(minutes=30), preview="Photo", unread=1)
    fetching = say(db, unnamed, None, at=ago(minutes=30), kind="image", wa_message_id="wamid.U1")
    db.add(InboxMedia(message_id=fetching.id, wa_media_id="m3", mime_type="image/jpeg", state="pending"))

    habiba = chat(db, "201005550155", "Habiba Tarek", at=ago(minutes=42),
                  preview="Done, it will ship tomorrow.", direction="out", heard=ago(minutes=50))
    say(db, habiba, "Is my order on its way?", at=ago(minutes=50), wa_message_id="wamid.H1")
    say(db, habiba, "Done, it will ship tomorrow.", at=ago(minutes=42), out=True, origin="staff",
        sent_by=mariam, status="delivered", wa_message_id="wamid.H2")
    order(db, "31041", habiba, answer="confirmed", placed=ago(hours=3), name="Habiba")

    rana = chat(db, "201005550166", "Rana Sherif", at=ago(minutes=84), preview="Tapped Confirm")
    order(db, "31042", rana, answer="confirmed", placed=ago(minutes=90), name="Rana")
    say(db, rana, "Confirm", at=ago(minutes=84), kind="button", shopify_order_id="5931042",
        wa_message_id="wamid.R1", extra={"payload": "confirm_5931042"})

    mai = chat(db, "201005550177", "Mai Ashraf", at=ago(minutes=111), preview="Tapped Cancel")
    order(db, "31039", mai, answer="cancelled", placed=ago(hours=2), name="Mai")
    say(db, mai, "Cancel", at=ago(minutes=111), kind="button", shopify_order_id="5931039",
        wa_message_id="wamid.M1", extra={"payload": "cancel_5931039"})

    yara = chat(db, "201005550199", "Yara Magdy", at=ago(minutes=155),
                preview="Order confirmation · #31036", direction="out")
    order(db, "31036", yara, placed=ago(minutes=156), name="Yara")
    say(db, yara, "Hi Yara, thank you for your order #31036.", at=ago(minutes=155), out=True,
        kind="template", status="sent", shopify_order_id="5931036", wa_message_id="wamid.Y1",
        extra={"buttons": ["Confirm", "Edit", "Cancel"]})

    # ── Frame 2: silent for more than 24 hours; refused; brought over ─────
    laila = chat(db, "201005550111", "Laila Emad", at=ago(days=3, minutes=10),
                 preview="Within three working days.", direction="out", heard=ago(days=3, minutes=22))
    say(db, laila, "When will it arrive?", at=ago(days=3, minutes=22), wa_message_id="wamid.L1")
    say(db, laila, "Within three working days.", at=ago(days=3, minutes=10), out=True,
        origin="staff", sent_by=mariam, wa_message_id="wamid.L2")

    reem = chat(db, "201005550122", "Reem Khaled", at=ago(hours=3), preview="Is the beige available?")
    say(db, reem, "Is the beige available?", at=ago(hours=3, minutes=2), wa_message_id="wamid.K1")
    say(db, reem, "Yes, it is. Shall I change your order?", at=ago(hours=3), out=True, origin="staff",
        sent_by=mariam, status="failed", error="WhatsApp could not reach this number.")

    farida = chat(db, "201005550133", "Farida Samir", at=ago(days=53), preview="receipt.pdf",
                  heard=ago(days=53))
    old = say(db, farida, None, at=ago(days=53, minutes=25), kind="image", origin="imported",
              source_ref="n8n:1")
    db.add(InboxMedia(message_id=old.id, mime_type="image/jpeg", state="gone"))
    say(db, farida, "It arrived like this", at=ago(days=53, minutes=25), origin="imported",
        source_ref="n8n:2")
    say(db, farida, "Sorry about that. We will send a replacement.", at=ago(days=53, minutes=9),
        out=True, origin="imported", source_ref="n8n:3")
    receipt = say(db, farida, None, at=ago(days=53), kind="document", origin="imported",
                  source_ref="n8n:4")
    db.add(InboxMedia(message_id=receipt.id, mime_type="application/pdf", filename="receipt.pdf",
                      state="gone"))

    # ── Frames 3 and 4: orders that went wrong, with no chat of their own ─
    order(db, "31040", None, state="failed", placed=ago(minutes=100), name="Dina", phone="201005550201",
          last_error="WhatsApp was not answering · tried 5 times", attempts=5)
    order(db, "31033", None, state="failed", placed=ago(hours=4), name="Jana", phone="201005550202",
          last_error="WhatsApp was not answering · tried 5 times", attempts=5)
    order(db, "31007", None, state="bad_phone", placed=ago(hours=19), name="Malak",
          last_error="The phone number on the order is not a valid Egyptian number")
    order(db, "30988", None, state="no_phone", placed=ago(hours=30), name="Reem",
          last_error="The order has no phone number")
    order(db, "31012", None, state="no_whatsapp", placed=ago(hours=9), name="Hana", phone="201005550203")
    for index in range(9):
        order(db, f"3090{index}", None, placed=ago(hours=30 + index), name="Customer",
              phone=f"20100555030{index}")

    db.commit()
    print(f"Inbox seeded. Sign in as mariam@example.com / {PASSWORD}")


if __name__ == "__main__":
    main()
