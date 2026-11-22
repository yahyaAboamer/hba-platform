"""Billing (ADR 0089): every purchase from every supplier, and the photos of
its bill. **The owner's alone**: it is money, like Payments.

A bill **is** a purchase (``prod_purchase``), recorded on its supplier's
account as the supplier page records it; nothing here keeps a second record of
money. The day a bill was bought is its purchase line's date on the account.
The photos or PDFs of a bill live in ``prod_purchase_photo``, in the file
bucket under ``production/bills/{purchase_id}/``; a payment's receipts stay in
``prod_supplier_receipt``.

Every write here only stages; the route commits on success and rolls back on a
refusal. The history never carries an amount.
"""

import uuid
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.businesstime import utcnow
from app.modules.inbox.public import file_bucket
from app.modules.production.models import ProductionSupplier
from app.modules.production.orders.models import (
    PURCHASE_PARTS,
    ProdFabric,
    ProdFabricMove,
    ProdOrder,
    ProdPurchase,
    ProdPurchasePhoto,
    ProdSupplierEntry,
)
from app.modules.production.orders.services.files import MAX_BYTES, file_type
from app.modules.production.orders.services.orders import NotFound, Refused, _day, _people
from app.modules.production.orders.services.suppliers import _audit, _subject, _supplier, quantity_text
from app.shared.models.identity import UserAccount

__all__ = ["add_bill_photo", "bill_photo_for_download", "listing", "remove_bill_photo"]


def photo_view(row: ProdPurchasePhoto) -> dict:
    return {"id": row.id, "mime_type": row.mime_type, "url": f"/api/prod/bill-photos/{row.id}"}


# ── The list ──────────────────────────────────────────────────────────────────


def _bought_on():
    """Each purchase's day bought: the date of its own line on the account."""
    return (
        select(
            ProdSupplierEntry.purchase_id.label("purchase_id"),
            func.min(ProdSupplierEntry.happened_on).label("bought_on"),
        )
        .where(
            ProdSupplierEntry.kind == "purchase",
            ProdSupplierEntry.reverses_id.is_(None),
            ProdSupplierEntry.purchase_id.is_not(None),
        )
        .group_by(ProdSupplierEntry.purchase_id)
        .subquery()
    )


def listing(
    db: Session, *, start: date | None = None, end: date | None = None, supplier_id: str | None = None,
    part: str | None = None,
) -> dict:
    """Every bill, newest bought first; ``start``/``end`` inclusive on the day
    bought. Totals count only those not voided, within the filters."""
    if part is not None and part not in PURCHASE_PARTS:
        raise Refused("Choose which part of the cost from the list.")
    bought = _bought_on()
    query = select(ProdPurchase, bought.c.bought_on).outerjoin(bought, bought.c.purchase_id == ProdPurchase.id)
    if start is not None:
        query = query.where(bought.c.bought_on >= start)
    if end is not None:
        query = query.where(bought.c.bought_on <= end)
    if supplier_id:
        query = query.where(ProdPurchase.supplier_id == supplier_id)
    if part:
        query = query.where(ProdPurchase.cost_part == part)
    found = db.execute(
        query.order_by(bought.c.bought_on.desc().nulls_last(), ProdPurchase.id.desc())
    ).all()
    purchases = [p for p, _day_ in found]
    ids = [p.id for p in purchases]

    names = dict(
        db.execute(
            select(ProductionSupplier.id, ProductionSupplier.name).where(
                ProductionSupplier.id.in_({p.supplier_id for p in purchases})
            )
        ).all()
    ) if purchases else {}
    codes = dict(
        db.execute(
            select(ProdOrder.id, ProdOrder.code).where(ProdOrder.id.in_({p.order_id for p in purchases if p.order_id}))
        ).all()
    ) if any(p.order_id for p in purchases) else {}
    fabrics: dict[int, dict] = {}
    photos: dict[int, list[dict]] = {}
    if ids:
        for purchase_id, fabric_id, name in db.execute(
            select(ProdFabricMove.purchase_id, ProdFabric.id, ProdFabric.name)
            .join(ProdFabric, ProdFabric.id == ProdFabricMove.fabric_id)
            .where(ProdFabricMove.purchase_id.in_(ids), ProdFabricMove.kind == "purchase")
        ).all():
            fabrics[purchase_id] = {"id": fabric_id, "name": name}
        for row in db.scalars(
            select(ProdPurchasePhoto)
            .where(ProdPurchasePhoto.purchase_id.in_(ids), ProdPurchasePhoto.deleted_at.is_(None))
            .order_by(ProdPurchasePhoto.created_at.desc(), ProdPurchasePhoto.id.desc())
        ):
            photos.setdefault(row.purchase_id, []).append(photo_view(row))
    people = _people(db, [p.created_by for p in purchases])

    bills = [
        {
            "id": p.id,
            "supplier": {"id": p.supplier_id, "name": names.get(p.supplier_id)},
            "item": p.item,
            "quantity": quantity_text(p.quantity),
            "unit": p.unit,
            "unit_price_piastres": p.unit_price_piastres,
            "total_piastres": p.total_piastres,
            "part": p.cost_part,
            "bought_on": _day(day),
            "expected_on": _day(p.expected_on),
            "received_on": _day(p.received_on),
            "order": None if p.order_id is None else {"id": p.order_id, "code": codes.get(p.order_id)},
            "note": p.note,
            "voided": p.voided_at is not None,
            "void_reason": p.void_reason,
            "fabric": fabrics.get(p.id),
            "photos": photos.get(p.id, []),
            "created_by": people.get(p.created_by),
        }
        for p, day in found
    ]
    live = [p for p in purchases if p.voided_at is None]
    by_part = {key: 0 for key in PURCHASE_PARTS}
    for p in live:
        by_part[p.cost_part] = by_part.get(p.cost_part, 0) + p.total_piastres
    suppliers = [
        {"id": sid, "name": name}
        for sid, name in db.execute(
            select(ProductionSupplier.id, ProductionSupplier.name)
            .where(ProductionSupplier.id.in_(select(ProdPurchase.supplier_id).distinct()))
            .order_by(func.lower(ProductionSupplier.name), ProductionSupplier.id)
        ).all()
    ]
    return {
        "bills": bills,
        "total_piastres": sum(p.total_piastres for p in live),
        "by_part": by_part,
        "suppliers": suppliers,
    }


# ── A bill's photos ───────────────────────────────────────────────────────────


def add_bill_photo(db: Session, purchase_id: int, content: bytes, actor: UserAccount) -> ProdPurchasePhoto:
    """One more photo or PDF of a bill. Every check runs before anything is
    stored; the bucket is written last, once the row is staged."""
    purchase = db.get(ProdPurchase, purchase_id)
    if purchase is None:
        raise NotFound("There is no such bill.")
    supplier = _supplier(db, purchase.supplier_id, for_update=True)
    db.refresh(purchase)
    if purchase.voided_at is not None:
        raise Refused("This bill was voided.")
    if not content:
        raise Refused("Choose a photo to upload.")
    if len(content) > MAX_BYTES:
        raise Refused("Files must be 20 MB or smaller.")
    mime = file_type(content)
    if mime is None:
        raise Refused("Use a JPG, PNG, WebP or GIF photo, or a PDF.")
    key = f"production/bills/{purchase.id}/{uuid.uuid4()}"
    row = ProdPurchasePhoto(
        purchase_id=purchase.id, storage_key=key, mime_type=mime, size_bytes=len(content), uploaded_by=actor.id
    )
    db.add(row)
    db.flush()
    _audit(
        db, _subject(supplier), actor, "bill_photo_added",
        f"Added a photo of the bill for {purchase.item} from {supplier.name}", purchase=purchase.id, photo=row.id,
    )
    file_bucket().put(key, content, mime)
    return row


def bill_photo_for_download(db: Session, photo_id: int) -> ProdPurchasePhoto | None:
    return db.scalar(
        select(ProdPurchasePhoto).where(ProdPurchasePhoto.id == photo_id, ProdPurchasePhoto.deleted_at.is_(None))
    )


def remove_bill_photo(db: Session, photo_id: int, actor: UserAccount) -> int:
    """Take one photo off a bill; the stored copy stays."""
    row = bill_photo_for_download(db, photo_id)
    if row is None:
        raise NotFound("There is no such photo.")
    purchase = db.get(ProdPurchase, row.purchase_id)
    supplier = _supplier(db, purchase.supplier_id, for_update=True)
    # Under the supplier's lock, look again: another removal may have committed.
    db.refresh(row)
    if row.deleted_at is not None:
        raise NotFound("There is no such photo.")
    row.deleted_at = utcnow()
    _audit(
        db, _subject(supplier), actor, "bill_photo_removed",
        f"Removed a photo of the bill for {purchase.item} from {supplier.name}", purchase=purchase.id, photo=row.id,
    )
    return row.id
