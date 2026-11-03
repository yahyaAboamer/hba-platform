"""What other departments may use from Inbox (ADR 0065).

The only part of this department another one may import: the import check
(pyproject.toml, `[tool.importlinter]`) refuses its api, models and services.
Empty on the day of the move; the crossings that existed then are listed in
that check, and each one that is untangled comes through here.
"""

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.modules.inbox.models import InboxMedia, InboxMessage
from app.modules.inbox.services import storage
from app.modules.inbox.services.confirmations import latest_for_orders as confirmations_for_orders
from app.modules.inbox.services.connection import describe_whatsapp
from app.modules.inbox.today import look as today_look

__all__ = ["confirmations_for_orders", "file_storage", "today_look", "whatsapp_connection"]


def whatsapp_connection(db: Session) -> dict:
    """The WhatsApp connection as Settings → Integrations shows it (Batch 2.3).

    From what the Inbox already records - nothing here asks Meta. ``saved``:
    a connection was saved; ``readable``: this server can read its keys
    (``problem`` says why not, in words); ``last_message_at``: the latest
    message in or out.
    """
    described = describe_whatsapp(db)
    return {
        "saved": described["phone_number_id"] is not None,
        "readable": described["connected"],
        "problem": described["problem"],
        "last_message_at": db.scalar(select(func.max(InboxMessage.occurred_at))),
    }


def file_storage(db: Session) -> dict:
    """The bucket customers' files are copied into, as Settings →
    Integrations shows it (Batch 2.3).

    From this server's settings and the Inbox's own rows - nothing here asks
    the bucket, so there is no size. ``configured``: there is a bucket to
    copy into; ``latest`` the outcome of the latest file whose copy finished
    (``stored`` or ``failed``) and ``latest_at`` when that file arrived;
    ``last_stored_at`` when the latest file that was kept arrived. A file is
    timed by when it arrived: the row records no other time.
    """
    finished = db.execute(
        select(InboxMedia.state, InboxMedia.created_at)
        .where(InboxMedia.state.in_(("stored", "failed")))
        .order_by(InboxMedia.created_at.desc(), InboxMedia.id.desc())
        .limit(1)
    ).first()
    return {
        "configured": storage.configured(),
        "latest": finished.state if finished else None,
        "latest_at": finished.created_at if finished else None,
        "last_stored_at": db.scalar(
            select(func.max(InboxMedia.created_at)).where(InboxMedia.state == "stored")
        ),
    }
