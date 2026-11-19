"""Photos and PDFs on a production order, in the platform's file bucket.

A file may be one of the product's own (build plan 2026-11-19): its ``pattern``
(a photo, a PDF or any other file, such as DXF, PLT, AI or ZIP: anything that is
not a photo or PDF is kept as ``application/octet-stream`` and only ever
downloaded) or its ``size_chart`` (a photo or PDF).

The platform's file bucket, a first-bytes check and a size limit; keys are
built here, never from what a browser sent, under ``production/orders/{order_id}/``.
A file is taken off an order by ``deleted_at``; the stored copy stays.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.businesstime import utcnow
from app.modules.inbox.public import file_bucket
from app.modules.production.orders.models import FILE_KINDS, STAGE_LABELS, STAGES, ProdOrder, ProdOrderFile
from app.modules.production.orders.services.orders import Locked, NotFound, Refused, _audit, _iso, _order, _people
from app.shared.models.identity import UserAccount

__all__ = ["MAX_BYTES", "add", "for_download", "listing", "remove"]

PDF = "application/pdf"
#: What a pattern file that is not a photo or PDF is stored and served as.
OTHER = "application/octet-stream"
KIND_WORDS = {"pattern": "pattern file", "size_chart": "size chart"}
MAX_BYTES = 20 * 1024 * 1024


def image_type(head: bytes) -> str | None:
    """The image a file really is, from its first bytes."""
    if head[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if head[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if head[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "image/webp"
    return None


def _must_be_open(order: ProdOrder) -> None:
    """A closed or cancelled order keeps the files it closed with."""
    if order.status != "open":
        raise Locked(f"{order.code} is {order.status}: its files can no longer be changed.")


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
        "kind": row.kind,
        "mime_type": row.mime_type,
        "size_bytes": row.size_bytes,
        "created_at": _iso(row.created_at),
        "uploaded_by": people.get(row.uploaded_by),
        "url": f"/api/prod/files/{row.id}",
    }


def listing(db: Session, order_id: int) -> list[dict]:
    if db.get(ProdOrder, order_id) is None:
        raise NotFound("There is no such production order.")
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
    db: Session, order_id: int, *, filename: str, content: bytes, stage: str | None, actor: UserAccount,
    kind: str | None = None,
) -> dict:
    """Check a file, record it and store it. Staged; the route commits.

    The order is read ``FOR UPDATE``, as every other write does, so an upload
    cannot slip past a settle or a cancel that is committing at the same
    time. The bucket is written last, once every check has passed and the row
    is staged, so a refusal never leaves a stored file behind.
    """
    order = _order(db, order_id, for_update=True)
    _must_be_open(order)
    stage = (stage or "").strip() or None
    if stage is not None and stage not in STAGES:
        raise Refused(f"{stage} is not a stage.")
    # Anything but the two kinds is an ordinary file.
    kind = kind if kind in FILE_KINDS else None
    if not content:
        raise Refused("Choose a file to upload.")
    if len(content) > MAX_BYTES:
        raise Refused("Files must be 20 MB or smaller.")
    mime = file_type(content)
    if mime is None:
        if kind != "pattern":
            raise Refused("Use a JPG, PNG, WebP or GIF photo, or a PDF.")
        mime = OTHER
    name = " ".join((filename or "").split())[:255] or (
        "Pattern" if mime == OTHER else "Document" if mime == PDF else "Photo"
    )
    key = f"production/orders/{order.id}/{uuid.uuid4()}"
    row = ProdOrderFile(
        order_id=order.id, stage=stage, kind=kind, name=name, storage_key=key, mime_type=mime,
        size_bytes=len(content), uploaded_by=actor.id,
    )
    db.add(row)
    db.flush()
    where = f" to {STAGE_LABELS[stage]}" if stage else ""
    what = f" as the {KIND_WORDS[kind]}" if kind else ""
    _audit(db, order, actor, "file_added", f"Added {name}{what}{where} on {order.code}", file=row.id)
    file_bucket().put(key, content, mime)
    return view(row, _people(db, [actor.id]))


def for_download(db: Session, file_id: int) -> ProdOrderFile | None:
    return db.scalar(
        select(ProdOrderFile).where(ProdOrderFile.id == file_id, ProdOrderFile.deleted_at.is_(None))
    )


def remove(db: Session, file_id: int, actor: UserAccount) -> None:
    row = for_download(db, file_id)
    if row is None:
        raise NotFound("There is no such file.")
    # Lock the order first, then look at the file again: a settle, a cancel or
    # another removal may have committed while this one waited.
    order = _order(db, row.order_id, for_update=True)
    db.refresh(row)
    if row.deleted_at is not None:
        raise NotFound("There is no such file.")
    _must_be_open(order)
    row.deleted_at = utcnow()
    _audit(db, order, actor, "file_removed", f"Removed {row.name} from {order.code}", file=row.id)
