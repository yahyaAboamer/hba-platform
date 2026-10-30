"""What the Inbox says is waiting, for Today (Phase 2, batch 2.2).

Only for somebody holding ``inbox.use``. The counts are Chats' own
(``chats.counts``: its *Unread* and *Wants a change* views), and WhatsApp's
state is the Inbox heading's (``health.pulse``).
"""

from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app.core.businesstime import at_words, clock_words
from app.core.permissions import Permission
from app.modules.inbox.services import chats, health
from app.shared.services.today import ELAPSED, SINCE, Item, Look

DEPARTMENT = "inbox"

#: A customer waiting longer than this for a reply is late.
REPLY_LATE_AFTER = timedelta(minutes=60)
#: A change asked for and not dealt with in a day is late.
CHANGE_LATE_AFTER = timedelta(hours=24)


def look(db: Session, permissions: frozenset[str], now: datetime) -> Look:
    """The Inbox's items, and the sidebar's unread count."""
    found = Look()
    if Permission.INBOX_USE not in permissions:
        return found

    counted = chats.counts(db)
    unread = counted["unread"]
    found.counts["chats_unread"] = unread
    if unread:
        oldest = chats.oldest_unread_at(db)
        found.items.append(
            Item(
                key="inbox.waiting_for_reply",
                department=DEPARTMENT,
                what=(
                    "1 customer is waiting for a reply"
                    if unread == 1
                    else f"{unread} customers are waiting for a reply"
                ),
                detail=f"The oldest wrote {at_words(oldest, now)}" if oldest else "",
                go_label="Open Chats",
                go_to="/inbox/chats",
                late=oldest is not None and now - oldest > REPLY_LATE_AFTER,
                since=oldest,
                when=ELAPSED if oldest else None,
            )
        )

    edit = counted["edit"]
    if edit:
        oldest = chats.oldest_edit_answer_at(db)
        found.items.append(
            Item(
                key="inbox.wants_a_change",
                department=DEPARTMENT,
                what=(
                    "1 customer asked to change their order"
                    if edit == 1
                    else f"{edit} customers asked to change their order"
                ),
                detail="They answered Change on the confirmation message",
                go_label="Open",
                # Chats chooses its view by a click, not by its address, so
                # this opens Chats (no new screen behaviour in 2.2).
                go_to="/inbox/chats",
                late=oldest is not None and now - oldest > CHANGE_LATE_AFTER,
                since=oldest,
                when=SINCE if oldest else None,
            )
        )

    pulse = health.pulse(db)
    # Operations has the WhatsApp screen; someone without it goes to Chats,
    # and the button says where it goes.
    whatsapp_label, whatsapp_to = (
        ("Open WhatsApp", "/operations/whatsapp")
        if Permission.ORDER_OPS_VIEW in permissions
        else ("Open Chats", "/inbox/chats")
    )
    if not pulse["connected"]:
        found.items.append(
            Item(
                key="inbox.whatsapp_not_connected",
                department=DEPARTMENT,
                what="WhatsApp is not connected",
                detail="Customers' messages and confirmation answers are not arriving",
                go_label=whatsapp_label,
                go_to=whatsapp_to,
                broken=True,
            )
        )
    elif pulse["quiet_since"]:
        quiet = datetime.fromisoformat(pulse["quiet_since"])
        found.items.append(
            Item(
                key="inbox.whatsapp_quiet",
                department=DEPARTMENT,
                what=f"WhatsApp has been quiet since {clock_words(quiet, now)}",
                detail="Messages went out and nothing has come back",
                go_label=whatsapp_label,
                go_to=whatsapp_to,
                broken=True,
                late=True,
                since=quiet,
                when=ELAPSED,
            )
        )
    return found
