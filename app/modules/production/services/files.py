"""Production's photos and documents, in the platform's file bucket.

The old app kept them in Cloudflare R2; nothing had been uploaded by the day
of the export, so nothing moved (ADR 0076). Keys are built here, never from
what a browser sent, and all sit under `production/`.

Photos are checked by their first bytes (JPEG, PNG, GIF, WebP) as before, and
are served only to people who may read Production - the old app served them
to anyone with the link.
"""

import re
import uuid
from datetime import datetime, timezone

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.modules.inbox.public import file_bucket
from app.modules.production.models import (
    ProductionActivity,
    ProductionDocument,
    ProductionOrder,
    ProductionSample,
)
from app.modules.production.services.actions import resolve_order_code
from app.shared.services.audit import record_audit

MAX_BYTES = 20 * 1024 * 1024
IMAGE_TYPES = ("image/jpeg", "image/png", "image/gif", "image/webp")

#: What each kind of photo is filed under, as the old tables named it.
KINDS = {
    "order": {"module": "Production Orders", "type": "Production photo", "prefix": "order-photos",
              "url": "/api/production/order-photos", "fallback": "Production photo"},
    "sample": {"module": "Samples", "type": "Sample photo", "prefix": "sample-photos",
               "url": "/api/production/sample-photos", "fallback": "Sample photo"},
}


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


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def photo_view(row: ProductionDocument, kind: str) -> dict:
    return {
        "id": row.id,
        "name": row.name,
        "mimeType": row.mime_type,
        "size": row.size_bytes,
        "createdAt": _iso(row.created_at),
        "url": f"{KINDS[kind]['url']}/{row.id}",
    }


def find_record(db: Session, kind: str, reference: str):
    """The order (by id, code or legacy code) or sample a photo belongs to."""
    reference = reference[:180]
    if kind == "order":
        code = resolve_order_code(db, reference)
        return db.scalar(
            select(ProductionOrder)
            .where(or_(ProductionOrder.id == reference, ProductionOrder.code == code), ProductionOrder.deleted_at.is_(None))
            .limit(1)
        )
    return db.scalar(
        select(ProductionSample).where(ProductionSample.id == reference, ProductionSample.deleted_at.is_(None))
    )


def list_photos(db: Session, kind: str, record_id: str) -> list[dict]:
    meta = KINDS[kind]
    rows = db.scalars(
        select(ProductionDocument)
        .where(
            ProductionDocument.module == meta["module"],
            ProductionDocument.document_type == meta["type"],
            ProductionDocument.record_id == record_id,
            ProductionDocument.confidential.is_(False),
            ProductionDocument.deleted_at.is_(None),
        )
        .order_by(ProductionDocument.created_at.desc(), ProductionDocument.id.desc())
    )
    return [photo_view(row, kind) for row in rows]


def photo_for_download(db: Session, kind: str, photo_id: str) -> ProductionDocument | None:
    meta = KINDS[kind]
    parent = ProductionOrder if kind == "order" else ProductionSample
    return db.scalar(
        select(ProductionDocument)
        .join(parent, parent.id == ProductionDocument.record_id)
        .where(
            ProductionDocument.id == photo_id,
            ProductionDocument.module == meta["module"],
            ProductionDocument.document_type == meta["type"],
            ProductionDocument.confidential.is_(False),
            ProductionDocument.deleted_at.is_(None),
            ProductionDocument.mime_type.in_(IMAGE_TYPES),
            parent.deleted_at.is_(None),
        )
    )


def save_photo(db: Session, kind: str, record, *, filename: str, content: bytes, mime: str,
               actor_name: str, actor_id: int, actor_email: str) -> dict:
    """Store a checked photo and record it. Staged; the route commits."""
    meta = KINDS[kind]
    photo_id = str(uuid.uuid4())
    name = filename.strip()[:180] or meta["fallback"]
    key = f"production/{meta['prefix']}/{record.id}/{photo_id}"
    file_bucket().put(key, content, mime)
    created = _now()
    row = ProductionDocument(
        id=photo_id, name=name, document_type=meta["type"], storage_key=key, mime_type=mime,
        size_bytes=len(content), module=meta["module"], record_id=record.id, confidential=False,
        uploaded_by_id=actor_id, created_at=created,
    )
    db.add(row)
    record_label = record.code if kind == "order" else record.name
    db.add(
        ProductionActivity(
            id=str(uuid.uuid4()), action="upload_photo", module=meta["module"], record_id=record_label,
            details={"actor": actor_name, "summary": f"Photo added: {name}", "photoId": photo_id},
            actor_id=actor_id, created_at=created,
        )
    )
    record_audit(
        db, action="production.upload_photo", subject=f"production:{record_label}",
        actor_id=actor_id, actor_email=actor_email, after={"photo": photo_id, "name": name},
    )
    return photo_view(row, kind)


def _slug(text: str, limit: int = 80) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", text).strip("-.")[:limit]
    return cleaned or "file"


def list_documents(db: Session, *, include_confidential: bool) -> list[dict]:
    query = select(ProductionDocument).where(ProductionDocument.deleted_at.is_(None))
    if not include_confidential:
        query = query.where(ProductionDocument.confidential.is_(False))
    rows = db.scalars(
        query
        .order_by(ProductionDocument.created_at.desc())
        .limit(100)
    )
    return [
        {
            "id": row.id, "name": row.name, "document_type": row.document_type, "mime_type": row.mime_type,
            "size_bytes": row.size_bytes, "module": row.module, "record_id": row.record_id,
            "confidential": 1 if row.confidential else 0, "created_at": _iso(row.created_at),
        }
        for row in rows
    ]


def save_document(db: Session, *, filename: str, content: bytes, content_type: str, module: str,
                  record_id: str, document_type: str, confidential: bool, actor_id: int, actor_email: str) -> dict:
    document_id = str(uuid.uuid4())
    module = module.strip()[:80] or "Documents"
    record_id = record_id.strip()[:180] or "general"
    document_type = document_type.strip()[:80] or "Other"
    key = (
        f"production/documents/{_slug(module.lower().replace(' ', '-'))}/{_slug(record_id)}/"
        f"{document_id}-{_slug(filename, 120)}"
    )
    mime = (content_type or "application/octet-stream")[:120]
    file_bucket().put(key, content, mime)
    db.add(
        ProductionDocument(
            id=document_id, name=filename[:255], document_type=document_type, storage_key=key, mime_type=mime,
            size_bytes=len(content), module=module, record_id=record_id, confidential=confidential,
            uploaded_by_id=actor_id, created_at=_now(),
        )
    )
    record_audit(
        db, action="production.upload_document", subject=f"production:{record_id}",
        actor_id=actor_id, actor_email=actor_email, after={"document": document_id, "name": filename[:255]},
    )
    return {"document": {"id": document_id, "name": filename, "documentType": document_type,
                         "module": module, "recordId": record_id}}
