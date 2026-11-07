"""What other departments may use from Inbox (ADR 0065).

The only part of this department another one may import: the import check
(pyproject.toml, `[tool.importlinter]`) refuses its api, models and services.
Empty on the day of the move; the crossings that existed then are listed in
that check, and each one that is untangled comes through here.
"""

from datetime import datetime

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from app.modules.inbox.models import InboxMedia, InboxMessage
from app.modules.inbox.services import storage
from app.modules.inbox.services.confirmations import latest_for_orders as confirmations_for_orders
from app.modules.inbox.services.connection import describe_whatsapp
from app.modules.inbox.services.media import BUCKET_REFUSED
from app.modules.inbox.today import look as today_look

__all__ = [
    "StorageError",
    "confirmations_for_orders",
    "file_bucket",
    "file_bucket_configured",
    "file_storage",
    "today_look",
    "whatsapp_connection",
]

#: The platform's one file bucket (ADR 0065: "the file bucket" is shared
#: plumbing). It was built for the Inbox and still lives here; Production
#: keeps its photos and documents in it under `production/` (ADR 0076).
file_bucket = storage.bucket
file_bucket_configured = storage.configured
StorageError = storage.StorageError


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
    the bucket, so there is no size. ``configured``: there is a bucket to copy
    into. ``refused_at``: when the bucket refused the latest file whose copy
    into it finished, or None when that file was kept. ``last_stored_at``:
    when the latest file that was kept arrived (the row records no other
    time).

    **Only the bucket's own refusals count** (``media.BUCKET_REFUSED``): a file
    too large to keep, or one WhatsApp would not hand over, is ``failed`` too
    and says nothing about storage, so it is passed over.
    """
    refused_at = InboxMessage.extra[BUCKET_REFUSED].astext
    finished = db.execute(
        select(InboxMedia.state, refused_at.label("refused_at"))
        .join(InboxMessage, InboxMessage.id == InboxMedia.message_id)
        .where(
            or_(
                InboxMedia.state == "stored",
                and_(InboxMedia.state == "failed", refused_at.is_not(None)),
            )
        )
        .order_by(InboxMedia.created_at.desc(), InboxMedia.id.desc())
        .limit(1)
    ).first()
    refused = finished.refused_at if finished and finished.state == "failed" else None
    return {
        "configured": storage.configured(),
        "refused_at": datetime.fromisoformat(refused) if refused else None,
        "last_stored_at": db.scalar(
            select(func.max(InboxMedia.created_at)).where(InboxMedia.state == "stored")
        ),
    }
