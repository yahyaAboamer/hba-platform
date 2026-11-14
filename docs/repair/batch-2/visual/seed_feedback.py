"""Fill a throwaway database with post-delivery feedback (ADR 0083), so the
Feedback sheet, the chat list's follow-up views and an open chat's Feedback
block can be looked at with every case on screen.

Run it AFTER `seed_inbox.py` (it needs that script's users and its WhatsApp
connection, and adds its own chats beside the mockup's). Everything here is
made up. It clears only `feedback_survey`, `feedback_settings` and the chats
whose phone starts 2019990, so running it twice gives the same picture.

    DATABASE_URL='postgresql+psycopg://hba:hba@127.0.0.1:5433/hba_browser_feedback' \
    APP_ENV=development GO_LIVE_MONTH=2026-06 \
    .venv/Scripts/python.exe docs/repair/batch-2/visual/seed_feedback.py

Start the server with INBOX_FEEDBACK_ENABLED=true. Nothing in this script, and
nothing it makes, can reach WhatsApp or Shopify.
"""

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from sqlalchemy import select, text  # noqa: E402

from app.db import SessionLocal, engine  # noqa: E402
from app.modules.inbox.models import (  # noqa: E402
    FeedbackSettings,
    FeedbackSurvey,
    InboxConversation,
    InboxMessage,
)
from app.shared.models.identity import UserAccount  # noqa: E402
from seed_inbox import refuse_anything_but_a_scratch_database  # noqa: E402

NOW = datetime.now(timezone.utc)

LONG_COMMENT = (
    "The shirt itself is lovely and the fabric feels better than I expected, but the sleeves "
    "were a good three centimetres longer than the size chart said, and the second button came "
    "loose after the very first wash. I called twice and nobody picked up. I wanted to say this "
    "properly because I do like the brand and I would like to keep buying from you, so please "
    "look at how the sizes are measured."
)
ARABIC_COMMENT = "القماش جميل جدا والتغليف كان ممتازا، لكن التوصيل تأخر يومين عن الموعد المتفق عليه."
ARABIC_LONG = (
    "طلبت المقاس الكبير لكن وصلني مقاس صغير، وعندما اتصلت بخدمة العملاء قالوا إن المقاسات "
    "نفدت. أحتاج استبدال الطلب أو استرجاع المبلغ في أقرب وقت ممكن لأن المناسبة بعد أسبوع "
    "وليس لدي وقت للانتظار أكثر من ذلك، وشكرا لكم على تعاونكم."
)


def ago(**delta) -> datetime:
    return NOW - timedelta(**delta)


def main() -> None:
    refuse_anything_but_a_scratch_database()
    db = SessionLocal()
    mariam = db.scalar(select(UserAccount.id).where(UserAccount.email == "mariam@example.com"))
    owner = db.scalar(select(UserAccount.id).where(UserAccount.email == "owner@example.com"))
    if mariam is None or owner is None:
        raise SystemExit("Run seed_inbox.py first: it makes the users.")

    db.execute(text("DELETE FROM feedback_survey"))
    db.execute(text("DELETE FROM feedback_settings"))
    db.execute(text("DELETE FROM inbox_conversation WHERE phone LIKE '2019990%'"))
    db.add(FeedbackSettings(id=1, started_at=ago(days=60), reply_hours=24))
    db.flush()

    counter = {"n": 0}

    def make(days, *, name="Nour", courier="Bosta", products=("Linen Shirt",), state="sent",
             rating=None, reason=None, comment=None, reorder=None, step="rating", hours=0,
             chat=True, last="", **fields):
        """One survey asked ``days`` days (and ``hours``) ago, with its chat."""
        counter["n"] += 1
        n = counter["n"]
        asked = ago(days=days, hours=hours)
        phone = f"2019990{n:04d}"
        conversation_id = None
        if chat:
            row = InboxConversation(
                phone=phone, name=name, last_message_at=asked + timedelta(minutes=30),
                last_preview=last or "Thank you for your feedback, it really helps us.",
                last_direction="out", unread_count=0, last_inbound_at=asked + timedelta(minutes=20),
            )
            db.add(row)
            db.flush()
            conversation_id = row.id
            db.add(InboxMessage(
                conversation_id=row.id, direction="out", kind="text",
                body="How was your order? Tap one answer.", status="read", origin="automatic",
                occurred_at=asked,
            ))
            if rating:
                db.add(InboxMessage(
                    conversation_id=row.id, direction="in", kind="text",
                    body={"loved": "Loved it", "okay": "It was okay", "unhappy": "Not happy"}[rating],
                    status="received", origin="customer", occurred_at=asked + timedelta(minutes=5),
                ))
        sent = asked if state in ("sent",) else None
        values = dict(
            shopify_order_id=f"88{n:05d}", order_name=f"#{31000 + n}",
            delivered_at=asked - timedelta(days=2), courier=courier, products=list(products),
            conversation_id=conversation_id, phone=phone, customer_name=name, state=state,
            sent_at=sent, rating=rating, reason=reason, comment=comment, reorder=reorder, step=step,
            created_at=asked, updated_at=asked,
            rated_at=asked + timedelta(minutes=5) if rating else None,
            reason_at=asked + timedelta(minutes=6) if reason else None,
            comment_at=asked + timedelta(minutes=8) if comment else None,
        )
        values.update(fields)
        db.add(FeedbackSurvey(**values))
        db.flush()

    # Loved
    make(0, hours=3, rating="loved", reason="quality", step="done", comment="Great quality, thank you!",
         reorder="very_likely", code="FB-K3M7QX", code_sent_at=ago(hours=3), code_expires_at=ago(hours=3) - timedelta(days=-30))
    make(2, rating="loved", reason="design", step="done", comment=LONG_COMMENT, reorder="very_likely",
         courier="Aramex", products=("Linen Shirt", "Wide Trousers"),
         code="FB-R9T2HC", code_sent_at=ago(days=2), code_expires_at=ago(days=-28),
         code_used_at=ago(days=1), code_order_name="#31102")
    make(3, name="نور الهدى", rating="loved", reason="delivery", step="done", comment=ARABIC_COMMENT,
         courier="Mylerz", products=("قميص كتان", "Wide Trousers", "Cotton Tee"),
         reorder="maybe", code="FB-W4N8PD", code_sent_at=ago(days=3), code_expires_at=ago(days=-27))
    make(4, name="Salma", rating="loved", reason="fit", step="done", courier="Bosta",
         products=("Wrap Dress",), code="FB-Y6B3ZA", code_sent_at=ago(days=4), code_expires_at=ago(days=-26))
    make(6, name="Dina", rating="loved", reason="other", step="done", courier="Aramex",
         products=("Silk Scarf", "Linen Shirt", "Wide Trousers", "Cotton Tee"))
    # Okay
    make(1, hours=2, name="Hana", rating="okay", reason="size_fit", step="done", comment="Runs a bit small.",
         courier="Aramex", products=("Cotton Tee",), last="Thank you for your feedback, it really helps us.")
    make(2, hours=5, name="Farida", rating="okay", reason="packaging", step="comment", courier="Mylerz",
         products=("Wrap Dress", "Silk Scarf"))
    make(5, name="Reem", rating="okay", reason="price", step="done", comment=None, courier="Bosta")
    make(8, name="Layla", rating="okay", reason="delivery", step="done", comment=ARABIC_COMMENT, courier="Aramex",
         code="FB-D7G2JE", code_sent_at=ago(days=8), code_expires_at=ago(days=-22))
    make(12, name="Mona", rating="okay", reason="quality", step="done", courier="Mylerz")
    # Unhappy, waiting for a person
    make(1, name="Yara", rating="unhappy", reason="size_fit", step="support", comment="The size chart is wrong.",
         courier="Bosta", products=("Linen Shirt",), last="Our team will reply within 24 hours.")
    make(2, hours=4, name="Mariam K.", rating="unhappy", reason="wrong_item", step="support", comment=LONG_COMMENT,
         courier="Aramex", products=("Wide Trousers", "Cotton Tee"), last="Our team will reply within 24 hours.")
    make(9, name="هبة محمود", rating="unhappy", reason="delivery", step="support", comment=ARABIC_LONG,
         courier="Mylerz", products=("قميص كتان",), last="Our team will reply within 24 hours.")
    # Reopened: she said No, and the later question could not be sent
    make(7, name="Aya", rating="unhappy", reason="quality", step="support", comment="Stitching came apart.",
         courier="Bosta", products=("Wrap Dress",), reopened_count=1, solved=False, solved_at=ago(days=1),
         resolved_at=None, last_error='The question "Was your issue solved?" could not be sent: '
         'WhatsApp is not connected on this server.', last="Our team will reply within 24 hours.")
    # Resolved, waiting for her answer
    make(4, name="Nada", rating="unhappy", reason="quality", step="solved", comment="Button fell off.",
         courier="Aramex", products=("Linen Shirt",), resolved_at=ago(days=3), resolved_by=mariam,
         last="Our team will reply within 24 hours.")
    # Solved yes, reorder answered, code used
    make(14, name="Sara", rating="unhappy", reason="delivery", step="done", comment="Late by a week.",
         courier="Mylerz", products=("Silk Scarf",), resolved_at=ago(days=12), resolved_by=owner,
         solved=True, solved_at=ago(days=10), solved_asked_at=ago(days=11), reorder="maybe",
         code="FB-M5X9VS", code_sent_at=ago(days=10), code_expires_at=ago(days=-20),
         code_used_at=ago(days=5), code_order_name="#31140")
    # Solved no, resolved twice, closed
    make(20, name="Rana", rating="unhappy", reason="wrong_item", step="done", comment="Still not fixed.",
         courier="Bosta", products=("Cotton Tee", "Wide Trousers"), resolved_at=ago(days=15), resolved_by=mariam,
         solved=False, solved_at=ago(days=14), reopened_count=2)
    # Unhappy, has not picked her reason yet
    make(0, hours=1, name="Heba", rating="unhappy", reason=None, step="reason", courier="Aramex")
    # Not answered
    make(0, hours=3, name="Lina", step="rating", courier="Bosta")
    make(10, name="Omar", step="rating", courier="Aramex", products=("Linen Shirt", "Cotton Tee"))
    make(21, name="Karim", step="rating", courier="Mylerz")
    # Never reached
    make(1, name="Tarek", state="no_whatsapp", courier="Bosta", chat=False,
         last_error="The number is not on WhatsApp.")
    make(2, name="Mazen", state="failed", courier="Aramex", chat=False,
         last_error="Meta refused the message (131026): the number cannot be messaged right now.")
    make(5, name="Youssef", state="would_send", courier="Mylerz", chat=False)
    # Older, an expired unused code, a long title
    make(30, name="Jana", rating="loved", reason="quality", step="done", courier="Mylerz",
         products=("The Extra Long Named Oversized Brushed Cotton Winter Jacket With Detachable Hood",),
         code="FB-C8U4TN", code_sent_at=ago(days=30), code_expires_at=ago(days=-0.1),
         comment="Warm and soft.")
    make(44, name="Malak", rating="okay", reason="price", step="done", courier="Aramex")

    # Filler, so a second page exists: the sheet shows 50 at a time.
    cycle = [
        ("loved", "quality"), ("loved", "fit"), ("okay", "size_fit"), ("unhappy", "other"),
        (None, None), ("loved", "design"), ("okay", "other"), (None, None),
    ]
    couriers = ("Bosta", "Aramex", "Mylerz")
    for k in range(36):
        rating, reason = cycle[k % len(cycle)]
        unhappy = rating == "unhappy"
        make(
            11 + k, hours=k % 7, name=f"Customer {k + 1}", courier=couriers[k % 3],
            products=("Cotton Tee",) if k % 2 else ("Linen Shirt", "Silk Scarf"),
            rating=rating, reason=reason,
            step=("done" if rating and not unhappy else "support" if unhappy else "rating"),
            resolved_at=ago(days=11 + k - 1) if unhappy and k % 2 else None,
            resolved_by=mariam if unhappy and k % 2 else None,
            chat=False,
        )
        # one resolved filler must not be waiting for follow-up
    db.execute(text(
        "UPDATE feedback_survey SET step = 'done' WHERE rating = 'unhappy' AND resolved_at IS NOT NULL "
        "AND customer_name LIKE 'Customer %'"
    ))
    db.commit()
    total = db.scalar(text("SELECT count(*) FROM feedback_survey"))
    print(f"{total} surveys. Sign in as owner@example.com or mariam@example.com.")


if __name__ == "__main__":
    main()
