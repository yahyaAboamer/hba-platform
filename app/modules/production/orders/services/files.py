"""Photos and PDFs on a production order, in the platform's file bucket.

The same bucket, the same first-bytes check and the same size limit as the
old Production (``app.modules.production.services.files``); keys are built
here, never from what a browser sent, under ``production/orders/{order_id}/``.
A file is taken off an order by ``deleted_at``; the stored copy stays.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.businesstime import utcnow
from app.modules.inbox.public import file_bucket
from app.modules.production.orders.models import STAGE_LABELS, STAGES, ProdOrder, ProdOrderFile
from app.modules.production.orders.services.orders import Refused, _audit, _iso, _people
from app.modules.production.services.files import MAX_BYTES, image_type
from app.shared.models.identity import UserAccount

__all__ = ["MAX_BYTES", "add", "for_download", "listing", "remove"]

PDF = "application/pdf"


def file_type(content: bytes) -> str | None:
    """What a file really is, from its first bytes: a photo or a PDF."""
    found = image_type(content[:16])
    if found:
        return found
    if content[:5] == b"%PDF-":
        return PDF
    return None


def view(row: ProdOrderFile, people: dict[int, str]) -> dict:
    return {
        "id": row.id,
        "name": row.name,
        "stage": row.stage,
        "mime_type": row.mime_type,
        "size_bytes": row.size_bytes,
        "created_at": _iso(row.created_at),
        "uploaded_by": people.get(row.uploaded_by),
        "url": f"/api/prod/files/{row.id}",
    }


def listing(db: Session, order_id: int) -> list[dict]:
    if db.get(ProdOrder, order_id) is None:
        raise LookupError("There is no such production order.")
    rows = list(
        db.scalars(
            select(ProdOrderFile)
            .where(ProdOrderFile.order_id == order_id, ProdOrderFile.deleted_at.is_(None))
            .order_by(ProdOrderFile.created_at.desc(), ProdOrderFile.id.desc())
        )
    )
    people = _people(db, [row.uploaded_by for row in rows])
    return [view(row, people) for row in rows]


def add(
    db: Session, order_id: int, *, filename: str, content: bytes, stage: str | None, actor: UserAccount
) -> dict:
    """Store a checked file and record it. Staged; the route commits."""
    order = db.get(ProdOrder, order_id)
    if order is None:
        raise LookupError("There is no such production order.")
    stage = (stage or "").strip() or None
    if stage is not None and stage not in STAGES:
        raise Refused(f"{stage} is not a stage.")
    if not content:
        raise Refused("Choose a file to upload.")
    if len(content) > MAX_BYTES:
        raise Refused("Files must be 20 MB or smaller.")
    mime = file_type(content)
    if mime is None:
        raise Refused("Use a JPG, PNG, WebP or GIF photo, or a PDF.")
    name = " ".join((filename or "").split())[:255] or ("Document" if mime == PDF else "Photo")
    key = f"production/orders/{order.id}/{uuid.uuid4()}"
    file_bucket().put(key, content, mime)
    row = ProdOrderFile(
        order_id=order.id, stage=stage, name=name, storage_key=key, mime_type=mime,
        size_bytes=len(content), uploaded_by=actor.id,
    )
    db.add(row)
    db.flush()
    where = f" to {STAGE_LABELS[stage]}" if stage else ""
    _audit(db, order, actor, "file_added", f"Added {name}{where} on {order.code}", file=row.id)
    return view(row, _people(db, [actor.id]))


def for_download(db: Session, file_id: int) -> ProdOrderFile | None:
    return db.scalar(
        select(ProdOrderFile).where(ProdOrderFile.id == file_id, ProdOrderFile.deleted_at.is_(None))
    )


def remove(db: Session, file_id: int, actor: UserAccount) -> None:
    row = for_download(db, file_id)
    if row is None:
        raise LookupError("There is no such file.")
    row.deleted_at = utcnow()
    order = db.get(ProdOrder, row.order_id)
    _audit(db, order, actor, "file_removed", f"Removed {row.name} from {order.code}", file=row.id)
