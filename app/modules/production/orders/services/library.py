"""Production's Library: every Shopify product with what HBA types about it
(ADR 0087).

What Shopify knows (title, status, photo, sizes and SKUs) is read from
``product`` and ``product_variant`` and never copied. What HBA types lives in
``prod_library_item`` (one row per product, made on its first save) and its
files in ``prod_library_file``.

**The COGS is money**: :func:`detail` adds a ``cogs`` block only when asked
``with_money=True``, the listing carries no amount, and the history (which
everybody in Production reads) never carries a figure of money: a COGS change
is recorded by which parts changed, not by their amounts.

Every write here only stages; the route commits on success and rolls back on a
refusal, as the orders do.
"""

import uuid

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.core.businesstime import utcnow
from app.modules.inbox.public import file_bucket
from app.modules.production.orders.models import (
    COST_PARTS,
    LIBRARY_FILE_KINDS,
    ProdLibraryFile,
    ProdLibraryItem,
    ProdOrder,
    ProdOrderSize,
)
from app.modules.production.orders.services.files import MAX_BYTES, OTHER, PDF, file_type
from app.modules.production.orders.services.orders import (
    _DETAILS,
    MAX_PART_PIASTRES,
    PART_LABELS,
    NotFound,
    Refused,
    _day,
    _iso,
    _people,
    _text,
    _width,
    _width_text,
)
from app.shared.models.catalogue import Product, ProductVariant
from app.shared.models.identity import UserAccount
from app.shared.services.audit import record_audit

__all__ = ["add", "detail", "for_download", "listing", "remove", "update"]

#: The most a Library product's notes may be.
MAX_NOTES = 4000

DETAIL_KEYS = ("colour_code", "fabric_type", "decoration_type", "decoration_width_cm")
COGS_KEYS = tuple(f"cogs_{part}_piastres" for part in COST_PARTS)
KIND_WORDS = {"design": "design file", "size_chart": "size chart", "pattern": "pattern file"}
_WORDS = {
    **{key: words for key, (_limit, words) in _DETAILS.items()},
    "decoration_width_cm": "print / embroidery width",
    "notes": "notes",
}


def _subject(pid: str) -> str:
    return f"production:library:{pid}"


def _audit(db: Session, product: Product, actor: UserAccount, what: str, summary: str, **after) -> None:
    """One history entry for the product. **Never a figure of money.**"""
    record_audit(
        db,
        action=f"production.library_{what}",
        subject=_subject(product.shopify_product_id),
        actor_id=actor.id,
        actor_email=actor.email,
        before=after.pop("before", None),
        after={"summary": summary[:500], "product": product.title, **after},
    )


def _product(db: Session, pid: str) -> Product:
    product = db.get(Product, pid)
    if product is None:
        raise NotFound("There is no such product.")
    return product


def _words(parts: list[str]) -> str:
    if len(parts) == 1:
        return parts[0]
    return ", ".join(parts[:-1]) + " and " + parts[-1]


# ── The list ──────────────────────────────────────────────────────────────────


def listing(db: Session) -> list[dict]:
    """Every product, active, draft and archived, by title. No money."""
    products = list(db.scalars(select(Product).order_by(Product.title, Product.shopify_product_id)))
    sizes: dict[str, list[str]] = {}
    skus: dict[str, list[str]] = {}
    for pid, title, sku in db.execute(
        select(ProductVariant.shopify_product_id, ProductVariant.title, ProductVariant.sku).order_by(
            ProductVariant.shopify_product_id,
            ProductVariant.position.asc().nulls_last(),
            ProductVariant.title,
            ProductVariant.shopify_variant_id,
        )
    ).all():
        sizes.setdefault(pid, []).append(title)
        if sku and sku.strip():
            skus.setdefault(pid, []).append(sku)
    items = {item.shopify_product_id: item for item in db.scalars(select(ProdLibraryItem))}
    kinds: dict[str, set[str]] = {}
    for pid, kind in db.execute(
        select(ProdLibraryFile.shopify_product_id, ProdLibraryFile.kind)
        .where(ProdLibraryFile.deleted_at.is_(None))
        .distinct()
    ).all():
        kinds.setdefault(pid, set()).add(kind)
    counts = dict(
        db.execute(
            select(ProdOrder.shopify_product_id, func.count())
            .where(ProdOrder.shopify_product_id.is_not(None))
            .group_by(ProdOrder.shopify_product_id)
        ).all()
    )

    rows = []
    for product in products:
        pid = product.shopify_product_id
        item = items.get(pid)
        found = kinds.get(pid, set())
        rows.append(
            {
                "id": pid,
                "title": product.title,
                "status": product.status,
                "image_url": product.image_url,
                "sizes": sizes.get(pid, []),
                "skus": skus.get(pid, []),
                "colour_code": item.colour_code if item else None,
                "fabric_type": item.fabric_type if item else None,
                "filled": {
                    "details": bool(item) and any(getattr(item, key) is not None for key in DETAIL_KEYS),
                    "cogs": bool(item) and any(getattr(item, key) is not None for key in COGS_KEYS),
                    "design": "design" in found,
                    "size_chart": "size_chart" in found,
                },
                "orders": counts.get(pid, 0),
            }
        )
    return rows


# ── One product ───────────────────────────────────────────────────────────────


def file_view(row: ProdLibraryFile, people: dict[int, str]) -> dict:
    return {
        "id": row.id,
        "name": row.name,
        "mime_type": row.mime_type,
        "size_bytes": row.size_bytes,
        "created_at": _iso(row.created_at),
        "uploaded_by": people.get(row.uploaded_by),
        "url": f"/api/prod/library-files/{row.id}",
    }


def _cogs(item: ProdLibraryItem | None) -> dict:
    parts = {part: (getattr(item, f"cogs_{part}_piastres") if item else None) for part in COST_PARTS}
    found = [value for value in parts.values() if value is not None]
    return {
        **{f"{part}_piastres": value for part, value in parts.items()},
        "total_piastres": sum(found) if found else None,
    }


def _orders(db: Session, pid: str) -> list[dict]:
    rows = list(
        db.scalars(
            select(ProdOrder)
            .where(ProdOrder.shopify_product_id == pid)
            .order_by(ProdOrder.created_at.desc(), ProdOrder.id.desc())
        )
    )
    planned = dict(
        db.execute(
            select(ProdOrderSize.order_id, func.sum(ProdOrderSize.planned))
            .where(ProdOrderSize.order_id.in_([row.id for row in rows]))
            .group_by(ProdOrderSize.order_id)
        ).all()
    ) if rows else {}
    return [
        {
            "id": row.id,
            "code": row.code,
            "colour": row.colour,
            "status": row.status,
            "planned_total": int(planned.get(row.id) or 0),
            "target_date": _day(row.target_date),
        }
        for row in rows
    ]


def detail(db: Session, pid: str, *, with_money: bool) -> dict:
    product = _product(db, pid)
    item = db.get(ProdLibraryItem, pid)
    variants = list(
        db.scalars(
            select(ProductVariant)
            .where(ProductVariant.shopify_product_id == pid)
            .order_by(
                ProductVariant.position.asc().nulls_last(), ProductVariant.title, ProductVariant.shopify_variant_id
            )
        )
    )
    files = list(
        db.scalars(
            select(ProdLibraryFile)
            .where(ProdLibraryFile.shopify_product_id == pid, ProdLibraryFile.deleted_at.is_(None))
            .order_by(ProdLibraryFile.created_at.desc(), ProdLibraryFile.id.desc())
        )
    )
    people = _people(db, [row.uploaded_by for row in files] + [item.updated_by if item else None])

    view = {
        "id": product.shopify_product_id,
        "title": product.title,
        "handle": product.handle,
        "status": product.status,
        "image_url": product.image_url,
        "synced_at": _iso(product.synced_at),
        "variants": [{"id": v.shopify_variant_id, "title": v.title, "sku": v.sku} for v in variants],
        "details": {
            "colour_code": item.colour_code if item else None,
            "fabric_type": item.fabric_type if item else None,
            "decoration_type": item.decoration_type if item else None,
            "decoration_width_cm": _width_text(item.decoration_width_cm) if item else None,
            "notes": item.notes if item else None,
        },
    }
    if with_money:
        view["cogs"] = _cogs(item)
    view["files"] = {
        kind: [file_view(row, people) for row in files if row.kind == kind] for kind in LIBRARY_FILE_KINDS
    }
    view["orders"] = _orders(db, pid)
    view["updated_at"] = _iso(item.updated_at) if item else None
    view["updated_by"] = people.get(item.updated_by) if item else None
    return view


# ── Changing it (the owner's) ─────────────────────────────────────────────────


def _notes(value) -> str | None:
    if value is None:
        return None
    cleaned = str(value).replace("\r\n", "\n").strip()
    if not cleaned:
        return None
    if len(cleaned) > MAX_NOTES:
        raise Refused(f"Keep the notes to {MAX_NOTES:,} characters.")
    return cleaned


def _cogs_part(value, part: str) -> int | None:
    what = f"The {PART_LABELS[part].lower()} COGS"
    if value is None:
        return None
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise Refused(f"{what} must be a whole number of piastres, 0 or more.")
    if value > MAX_PART_PIASTRES:
        raise Refused(f"{what} is too large. Check the number.")
    return value


def _clean(data: dict) -> dict:
    """Each field sent, checked and in the form it is stored; blank is none."""
    found: dict = {}
    for key, value in data.items():
        if key in _DETAILS:
            limit, words = _DETAILS[key]
            found[key] = _text(value, limit=limit, what=f"the {words}")
        elif key == "decoration_width_cm":
            found[key] = _width(value)
        elif key == "notes":
            found[key] = _notes(value)
        elif key in COGS_KEYS:
            found[key] = _cogs_part(value, key[len("cogs_"):-len("_piastres")])
        else:
            raise Refused(f"{key} is not something the Library holds.")
    return found


def _locked(db: Session, pid: str) -> ProdLibraryItem | None:
    return db.scalar(
        select(ProdLibraryItem).where(ProdLibraryItem.shopify_product_id == pid).with_for_update()
    )


def _shown(key: str, value) -> object:
    """A detail as the history keeps it (a width as its text). Never money."""
    return _width_text(value) if key == "decoration_width_cm" else value


def update(db: Session, pid: str, data: dict, actor: UserAccount) -> None:
    """Apply the fields sent. The Library record is made on the first save
    that sets anything; the row is locked so two saves queue."""
    product = _product(db, pid)
    wanted = _clean(data)
    item = _locked(db, pid)
    if item is None:
        if all(value is None for value in wanted.values()):
            return  # Nothing to keep, and nothing kept yet.
        db.execute(insert(ProdLibraryItem).values(shopify_product_id=pid).on_conflict_do_nothing())
        item = _locked(db, pid)

    changed = [key for key, value in wanted.items() if getattr(item, key) != value]
    if not changed:
        return
    before = {key: _shown(key, getattr(item, key)) for key in changed if key not in COGS_KEYS}
    for key in changed:
        setattr(item, key, wanted[key])
    item.updated_by = actor.id
    item.updated_at = utcnow()
    db.flush()

    details = [key for key in changed if key not in COGS_KEYS]
    parts = [key[len("cogs_"):-len("_piastres")] for key in changed if key in COGS_KEYS]
    said = [_WORDS[key] for key in details]
    if parts:
        said.append(f"COGS ({_words([PART_LABELS[part].lower() for part in parts])})")
    _audit(
        db, product, actor, "updated", f"Changed the {_words(said)} of {product.title} in the Library",
        before=before or None,
        changed=details,
        cogs_parts=parts,
        **{key: _shown(key, getattr(item, key)) for key in details},
    )


# ── Files ─────────────────────────────────────────────────────────────────────


def add(db: Session, pid: str, *, filename: str, content: bytes, kind: str | None, actor: UserAccount) -> dict:
    """Check a file, record it and store it. Staged; the route commits. The
    bucket is written last, once every check has passed, so a refusal never
    leaves a stored file behind."""
    product = _product(db, pid)
    kind = (kind or "").strip()
    if kind not in LIBRARY_FILE_KINDS:
        raise Refused("Say what the file is: a design, a size chart or a pattern.")
    if not content:
        raise Refused("Choose a file to upload.")
    if len(content) > MAX_BYTES:
        raise Refused("Files must be 20 MB or smaller.")
    mime = file_type(content)
    if mime is None:
        if kind == "size_chart":
            raise Refused("Use a JPG, PNG, WebP or GIF photo, or a PDF.")
        mime = OTHER
    name = " ".join((filename or "").split())[:255] or (
        "Document" if mime == PDF else KIND_WORDS[kind].capitalize() if mime == OTHER else "Photo"
    )
    key = f"production/library/{pid}/{uuid.uuid4()}"
    row = ProdLibraryFile(
        shopify_product_id=pid, kind=kind, name=name, storage_key=key, mime_type=mime,
        size_bytes=len(content), uploaded_by=actor.id,
    )
    db.add(row)
    db.flush()
    _audit(
        db, product, actor, "file_added", f"Added {name} as the {KIND_WORDS[kind]} of {product.title}",
        file=row.id, kind=kind,
    )
    file_bucket().put(key, content, mime)
    return file_view(row, _people(db, [actor.id]))


def for_download(db: Session, file_id: int) -> ProdLibraryFile | None:
    return db.scalar(
        select(ProdLibraryFile).where(ProdLibraryFile.id == file_id, ProdLibraryFile.deleted_at.is_(None))
    )


def remove(db: Session, file_id: int, actor: UserAccount) -> None:
    row = db.scalar(
        select(ProdLibraryFile)
        .where(ProdLibraryFile.id == file_id, ProdLibraryFile.deleted_at.is_(None))
        .with_for_update()
    )
    if row is None:
        raise NotFound("There is no such file.")
    row.deleted_at = utcnow()
    product = _product(db, row.shopify_product_id)
    _audit(
        db, product, actor, "file_removed", f"Removed {row.name} from {product.title}",
        file=row.id, kind=row.kind,
    )
