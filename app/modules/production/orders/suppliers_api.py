"""Production's Suppliers under ``/api/prod`` (ADR 0084, decision 9; build plan
``docs/plans/2026-11-14-production-suppliers-build.md``).

These routes sit on the production orders' router (``api`` includes this one),
so every one of them is behind ``production.view`` already. Writes add:

* ``production.suppliers`` (managers, the owner): a supplier, its sections, and
  the list of sections;
* ``production.edit`` (the QC manager): when a purchase is expected and that it
  arrived;
* ``production.owner``: everything with money (purchases, payments, the balance
  brought forward, adjustments, reversals, voids, receipts).

**Money is filtered here, on the server**: a response carries a price, a total,
an account, an amount owed or held and a receipt only to somebody holding
``production.owner``; without it those keys are absent, not null, on every
route, a write's answer included. A receipt photo is served to the owner alone.

Refusals follow the orders: ``Refused`` -> 422, ``Locked`` -> 409, an unknown
supplier, section, purchase, line or receipt (``NotFound``) -> 404. A refusal
rolls back whatever was staged; success commits.
"""

import logging
from datetime import date
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.permissions import Permission
from app.db import get_session
from app.modules.inbox.public import StorageError, file_bucket
from app.modules.production.api import _too_large
from app.modules.production.orders.guards import EDIT, GUARD, OWNER, SUPPLIERS
from app.modules.production.orders.services import orders as order_service
from app.modules.production.orders.services import suppliers
from app.modules.production.orders.services.orders import NotFound, Refused
from app.shared.api.deps import holds
from app.shared.models.identity import UserAccount

logger = logging.getLogger(__name__)

#: Built with the production orders' own prefix and guard, and its routes are
#: appended to the orders' router (``api``), so they are served from it and
#: found by name on it.
router = APIRouter(prefix="/api/prod", tags=["production-orders"], dependencies=[Depends(GUARD)])

Method = Literal["bank_transfer", "cash", "instapay", "wallet", "cheque"]
Unit = Literal["kg", "m", "piece"]
Part = Literal["fabric", "printing", "accessories", "packaging", "other"]


def _refused(exc: Refused) -> HTTPException:
    return HTTPException(409 if isinstance(exc, order_service.Locked) else 422, str(exc))


def _money(db: Session, actor: UserAccount) -> bool:
    return holds(db, actor, Permission.PRODUCTION_OWNER)


def _write(db: Session, actor: UserAccount, act, extra=lambda result: {}) -> dict:
    """Run one staged change; commit and answer with the supplier's page as
    this person may see it, or roll back and refuse."""
    try:
        supplier, result = act()
    except NotFound as exc:
        db.rollback()
        raise HTTPException(404, str(exc)) from None
    except Refused as exc:
        db.rollback()
        raise _refused(exc) from None
    db.commit()
    return {"supplier": suppliers.page(db, supplier.id, with_money=_money(db, actor)), **extra(result)}


def _same(supplier) -> tuple:
    return supplier, supplier


def _sections_write(db: Session, act) -> dict:
    try:
        act()
    except NotFound as exc:
        db.rollback()
        raise HTTPException(404, str(exc)) from None
    except Refused as exc:
        db.rollback()
        raise _refused(exc) from None
    db.commit()
    return {"sections": suppliers.sections_view(db)}


# ── Bodies ────────────────────────────────────────────────────────────────────


class NewSection(BaseModel):
    name: str = Field(max_length=200)


class NewSupplier(BaseModel):
    name: str = Field(max_length=400)
    contact_person: str | None = Field(default=None, max_length=400)
    phone: str | None = Field(default=None, max_length=400)
    whatsapp: str | None = Field(default=None, max_length=400)
    city: str | None = Field(default=None, max_length=400)
    notes: str | None = Field(default=None, max_length=4000)
    section_ids: list[int] = Field(default_factory=list, max_length=60)


class SupplierEdit(BaseModel):
    """Any of these; what is left out stays as it was. ``section_ids`` replaces
    the supplier's sections as a whole."""

    name: str | None = Field(default=None, max_length=400)
    contact_person: str | None = Field(default=None, max_length=400)
    phone: str | None = Field(default=None, max_length=400)
    whatsapp: str | None = Field(default=None, max_length=400)
    city: str | None = Field(default=None, max_length=400)
    notes: str | None = Field(default=None, max_length=4000)
    active: bool | None = None
    section_ids: list[int] | None = Field(default=None, max_length=60)


class NewPurchase(BaseModel):
    item: str = Field(max_length=400)
    quantity: Decimal = Field(gt=0, le=suppliers.MAX_QUANTITY, allow_inf_nan=False)
    unit: Unit
    unit_price_piastres: int = Field(gt=0, le=suppliers.MAX_UNIT_PIASTRES)
    part: Part
    order_id: int | None = Field(default=None, ge=1, le=2_147_483_647)
    #: The day it was bought; not in the future. Left out: today.
    bought_on: date | None = None
    expected_on: date | None = None
    note: str | None = Field(default=None, max_length=4000)
    #: Paid now, 0 < deposit <= total; its method is then required.
    deposit_piastres: int | None = Field(default=None, ge=0, le=suppliers.MAX_LINE_PIASTRES)
    deposit_method: Method | None = None


class PurchaseEdit(BaseModel):
    """Any of these; what is left out stays as it was. ``null`` clears one."""

    expected_on: date | None = None
    received_on: date | None = None
    note: str | None = Field(default=None, max_length=4000)


class Reason(BaseModel):
    reason: str = Field(max_length=1000)


class NewPayment(BaseModel):
    amount_piastres: int = Field(gt=0, le=suppliers.MAX_LINE_PIASTRES)
    #: Not in the future. Left out: today.
    paid_on: date | None = None
    method: Method
    kind: Literal["weekly", "deposit", "final"]
    note: str | None = Field(default=None, max_length=1000)


class Opening(BaseModel):
    """Positive: HBA owes the supplier. Negative: HBA has overpaid it."""

    amount_piastres: int = Field(ge=-suppliers.MAX_LINE_PIASTRES, le=suppliers.MAX_LINE_PIASTRES)
    happened_on: date | None = None
    note: str | None = Field(default=None, max_length=1000)


class Adjustment(BaseModel):
    """Positive: HBA owes more. Negative: HBA owes less. The note is required."""

    amount_piastres: int = Field(ge=-suppliers.MAX_LINE_PIASTRES, le=suppliers.MAX_LINE_PIASTRES)
    happened_on: date | None = None
    note: str = Field(max_length=1000)


# ── Sections ──────────────────────────────────────────────────────────────────


@router.post("/sections", status_code=201)
def add_section(body: NewSection, actor: UserAccount = Depends(SUPPLIERS), db: Session = Depends(get_session)) -> dict:
    created: dict = {}

    def act():
        created["id"] = suppliers.add_section(db, body.name, actor).id

    answer = _sections_write(db, act)
    return {**answer, "section_id": created["id"]}


@router.patch("/sections/{section_id}")
def rename_section(
    section_id: int, body: NewSection, actor: UserAccount = Depends(SUPPLIERS), db: Session = Depends(get_session)
) -> dict:
    return _sections_write(db, lambda: suppliers.rename_section(db, section_id, body.name, actor))


@router.delete("/sections/{section_id}")
def remove_section(
    section_id: int, actor: UserAccount = Depends(SUPPLIERS), db: Session = Depends(get_session)
) -> dict:
    answer = _sections_write(db, lambda: suppliers.remove_section(db, section_id, actor))
    return {**answer, "deleted": section_id}


# ── Suppliers ─────────────────────────────────────────────────────────────────


@router.get("/suppliers")
def supplier_list(actor: UserAccount = Depends(GUARD), db: Session = Depends(get_session)) -> dict:
    """The sections and every supplier. Without ``production.owner`` no row
    says what is owed or held."""
    return suppliers.listing(db, with_money=_money(db, actor))


@router.post("/suppliers", status_code=201)
def add_supplier(body: NewSupplier, actor: UserAccount = Depends(SUPPLIERS), db: Session = Depends(get_session)) -> dict:
    data = body.model_dump()
    return _write(db, actor, lambda: _same(suppliers.add_supplier(db, data, actor)))


@router.get("/suppliers/{supplier_id}")
def one_supplier(supplier_id: str, actor: UserAccount = Depends(GUARD), db: Session = Depends(get_session)) -> dict:
    try:
        return {"supplier": suppliers.page(db, supplier_id, with_money=_money(db, actor))}
    except NotFound as exc:
        raise HTTPException(404, str(exc)) from None


@router.patch("/suppliers/{supplier_id}")
def edit_supplier(
    supplier_id: str, body: SupplierEdit, actor: UserAccount = Depends(SUPPLIERS), db: Session = Depends(get_session)
) -> dict:
    data = body.model_dump(exclude_unset=True)
    return _write(db, actor, lambda: _same(suppliers.edit_supplier(db, supplier_id, data, actor)))


# ── Purchases ─────────────────────────────────────────────────────────────────


@router.post("/suppliers/{supplier_id}/purchases", status_code=201)
def add_purchase(
    supplier_id: str, body: NewPurchase, actor: UserAccount = Depends(OWNER), db: Session = Depends(get_session)
) -> dict:
    data = body.model_dump()
    return _write(
        db, actor, lambda: suppliers.add_purchase(db, supplier_id, data, actor),
        lambda purchase: {"purchase_id": purchase.id},
    )


@router.patch("/purchases/{purchase_id}")
def edit_purchase(
    purchase_id: int, body: PurchaseEdit, actor: UserAccount = Depends(EDIT), db: Session = Depends(get_session)
) -> dict:
    data = body.model_dump(exclude_unset=True)
    return _write(db, actor, lambda: suppliers.edit_purchase(db, purchase_id, data, actor))


@router.post("/purchases/{purchase_id}/void")
def void_purchase(
    purchase_id: int, body: Reason, actor: UserAccount = Depends(OWNER), db: Session = Depends(get_session)
) -> dict:
    return _write(db, actor, lambda: suppliers.void_purchase(db, purchase_id, body.reason, actor))


# ── The account ───────────────────────────────────────────────────────────────


@router.post("/suppliers/{supplier_id}/payments", status_code=201)
def record_payment(
    supplier_id: str, body: NewPayment, actor: UserAccount = Depends(OWNER), db: Session = Depends(get_session)
) -> dict:
    data = body.model_dump()
    return _write(
        db, actor, lambda: suppliers.record_payment(db, supplier_id, data, actor), lambda entry: {"entry_id": entry.id}
    )


@router.post("/suppliers/{supplier_id}/opening", status_code=201)
def record_opening(
    supplier_id: str, body: Opening, actor: UserAccount = Depends(OWNER), db: Session = Depends(get_session)
) -> dict:
    data = body.model_dump()
    return _write(
        db, actor, lambda: suppliers.record_opening(db, supplier_id, data, actor), lambda entry: {"entry_id": entry.id}
    )


@router.post("/suppliers/{supplier_id}/adjustments", status_code=201)
def record_adjustment(
    supplier_id: str, body: Adjustment, actor: UserAccount = Depends(OWNER), db: Session = Depends(get_session)
) -> dict:
    data = body.model_dump()
    return _write(
        db, actor, lambda: suppliers.record_adjustment(db, supplier_id, data, actor),
        lambda entry: {"entry_id": entry.id},
    )


@router.post("/entries/{entry_id}/reverse")
def reverse_entry(
    entry_id: int, body: Reason, actor: UserAccount = Depends(OWNER), db: Session = Depends(get_session)
) -> dict:
    return _write(
        db, actor, lambda: suppliers.reverse_entry(db, entry_id, body.reason, actor),
        lambda reversal: {"entry_id": reversal.id},
    )


# ── Receipts (the owner's alone, to add and to see) ───────────────────────────


@router.post("/entries/{entry_id}/receipt", status_code=201)
async def add_receipt(
    entry_id: int, request: Request, actor: UserAccount = Depends(OWNER), db: Session = Depends(get_session)
) -> dict:
    """A photo or PDF of a payment, multipart: ``file``. Replaces the one there
    is. Refused before reading when too large or of no stated size."""
    if _too_large(request):
        raise HTTPException(413, "Files must be 20 MB or smaller.")
    form = await request.form()
    upload = form.get("file")
    content = await upload.read() if hasattr(upload, "read") else b""

    def store() -> dict:
        try:
            supplier = suppliers.add_receipt(db, entry_id, content=content, actor=actor)
        except NotFound as exc:
            db.rollback()
            raise HTTPException(404, str(exc)) from None
        except Refused as exc:
            db.rollback()
            raise _refused(exc) from None
        except StorageError:
            db.rollback()
            logger.exception("A supplier payment's receipt could not be stored")
            raise HTTPException(503, "The receipt couldn't be saved. Try again.") from None
        db.commit()
        return {"supplier": suppliers.page(db, supplier.id, with_money=True)}

    return await run_in_threadpool(store)


@router.get("/entries/{entry_id}/receipt")
def one_receipt(entry_id: int, actor: UserAccount = Depends(OWNER), db: Session = Depends(get_session)) -> Response:
    row = suppliers.receipt_for_download(db, entry_id)
    if row is None:
        raise HTTPException(404, "There is no such receipt.")
    try:
        content = file_bucket().get(row.storage_key)
    except StorageError:
        raise HTTPException(404, "There is no such receipt.") from None
    return Response(
        content,
        media_type=row.mime_type,
        headers={"Content-Disposition": "inline", "X-Content-Type-Options": "nosniff"},
    )


@router.delete("/entries/{entry_id}/receipt")
def remove_receipt(entry_id: int, actor: UserAccount = Depends(OWNER), db: Session = Depends(get_session)) -> dict:
    return _write(db, actor, lambda: (suppliers.remove_receipt(db, entry_id, actor), None))
