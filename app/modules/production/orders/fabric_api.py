"""Billing and fabric storage under ``/api/prod`` (ADR 0089).

These routes sit on the production orders' router (``api`` appends them), so
every one of them is behind ``production.view`` already. On top of it:

* **Billing** (``/billing``, ``/purchases/{id}/photos``, ``/bill-photos/{id}``)
  is ``production.owner``'s alone: it is money, like Payments. A bill is a
  purchase; it is added on the supplier's page.
* **Fabric storage** (``/fabrics``) is read by everybody in Production; fabrics
  are added, edited and counted, and an order takes fabric and gives it back,
  with ``production.edit``. The price per kg is in a response only for
  ``production.owner``; without it the key is absent, not null.

Refusals follow the orders: ``Refused`` -> 422, ``Locked`` -> 409, an unknown
fabric, order, move, bill or photo (``NotFound``) -> 404. A refusal rolls back
whatever was staged; success commits.
"""

import logging
from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.core.permissions import Permission
from app.db import get_session
from app.modules.inbox.public import StorageError, file_bucket
from app.modules.production.orders.guards import EDIT, GUARD, OWNER, too_large
from app.modules.production.orders.services import billing, fabric
from app.modules.production.orders.services import orders as order_service
from app.modules.production.orders.services.orders import NotFound, Refused
from app.shared.api.deps import holds
from app.shared.models.identity import UserAccount

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/prod", tags=["production-orders"], dependencies=[Depends(GUARD)])


def _refused(exc: Refused) -> HTTPException:
    return HTTPException(409 if isinstance(exc, order_service.Locked) else 422, str(exc))


def _money(db: Session, actor: UserAccount) -> bool:
    return holds(db, actor, Permission.PRODUCTION_OWNER)


def _staged(db: Session, act):
    """Run one staged change; commit, or roll back and refuse."""
    try:
        result = act()
    except NotFound as exc:
        db.rollback()
        raise HTTPException(404, str(exc)) from None
    except Refused as exc:
        db.rollback()
        raise _refused(exc) from None
    db.commit()
    return result


# ── Bodies ────────────────────────────────────────────────────────────────────


class NewFabric(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(max_length=400)
    fabric_type: str | None = Field(default=None, max_length=800)
    colour: str | None = Field(default=None, max_length=200)
    colour_code: str | None = Field(default=None, max_length=400)
    supplier_id: str | None = Field(default=None, max_length=80)
    note: str | None = Field(default=None, max_length=4000)
    #: What is in storage already, recorded as a count; above 0, or left out.
    in_storage_kg: Decimal | None = Field(default=None, allow_inf_nan=False, max_digits=20)


class FabricEdit(BaseModel):
    """Any of these; what is left out stays as it was. ``null`` clears a detail."""

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, max_length=400)
    fabric_type: str | None = Field(default=None, max_length=800)
    colour: str | None = Field(default=None, max_length=200)
    colour_code: str | None = Field(default=None, max_length=400)
    supplier_id: str | None = Field(default=None, max_length=80)
    note: str | None = Field(default=None, max_length=4000)
    active: bool | None = None


class Count(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kg_in_storage: Decimal = Field(allow_inf_nan=False, max_digits=20)
    note: str = Field(max_length=1000)


class Take(BaseModel):
    model_config = ConfigDict(extra="forbid")

    fabric_id: int = Field(ge=1, le=2_147_483_647)
    kg: Decimal = Field(allow_inf_nan=False, max_digits=20)


# ── Billing (the owner's) ─────────────────────────────────────────────────────


@router.get("/billing")
def bill_list(
    from_: date | None = Query(None, alias="from"),
    to: date | None = Query(None),
    supplier: str | None = Query(None, max_length=80),
    part: str | None = Query(None, max_length=20),
    actor: UserAccount = Depends(OWNER),
    db: Session = Depends(get_session),
) -> dict:
    """Every purchase from every supplier, newest bought first, with its bill
    photos, the total of those not voided and that total per part;
    ``from``/``to`` inclusive on the day bought."""
    if from_ is not None and to is not None and from_ > to:
        raise HTTPException(422, "The From date is after the To date. Swap them or clear one.")
    try:
        return billing.listing(
            db, start=from_, end=to, supplier_id=(supplier or "").strip() or None, part=(part or "").strip() or None
        )
    except Refused as exc:
        raise _refused(exc) from None


@router.post("/purchases/{purchase_id}/photos", status_code=201)
async def add_bill_photo(
    purchase_id: int, request: Request, actor: UserAccount = Depends(OWNER), db: Session = Depends(get_session)
) -> dict:
    """One more photo or PDF of a bill, multipart: ``file``. Refused before
    reading when too large or of no stated size."""
    if too_large(request):
        raise HTTPException(413, "Files must be 20 MB or smaller.")
    form = await request.form()
    upload = form.get("file")
    content = await upload.read() if hasattr(upload, "read") else b""

    def store() -> dict:
        try:
            row = _staged(db, lambda: billing.add_bill_photo(db, purchase_id, content, actor))
        except StorageError:
            db.rollback()
            logger.exception("A bill's photo could not be stored")
            raise HTTPException(503, "The photo couldn't be saved. Try again.") from None
        return {"photo": billing.photo_view(row)}

    return await run_in_threadpool(store)


@router.get("/bill-photos/{photo_id}")
def one_bill_photo(photo_id: int, actor: UserAccount = Depends(OWNER), db: Session = Depends(get_session)) -> Response:
    row = billing.bill_photo_for_download(db, photo_id)
    if row is None:
        raise HTTPException(404, "There is no such photo.")
    try:
        content = file_bucket().get(row.storage_key)
    except StorageError:
        raise HTTPException(404, "There is no such photo.") from None
    return Response(
        content,
        media_type=row.mime_type,
        headers={"Content-Disposition": "inline", "X-Content-Type-Options": "nosniff"},
    )


@router.delete("/bill-photos/{photo_id}")
def remove_bill_photo(photo_id: int, actor: UserAccount = Depends(OWNER), db: Session = Depends(get_session)) -> dict:
    return {"deleted": _staged(db, lambda: billing.remove_bill_photo(db, photo_id, actor))}


# ── Fabric storage ────────────────────────────────────────────────────────────


@router.get("/fabrics")
def fabric_list(actor: UserAccount = Depends(GUARD), db: Session = Depends(get_session)) -> dict:
    """Every fabric, active first, with what it holds. The price per kg only
    for ``production.owner``."""
    return fabric.listing(db, with_money=_money(db, actor))


@router.post("/fabrics", status_code=201)
def add_fabric(body: NewFabric, actor: UserAccount = Depends(EDIT), db: Session = Depends(get_session)) -> dict:
    data = body.model_dump()
    made = _staged(db, lambda: fabric.add_fabric(db, data, actor))
    return {"fabric": fabric.detail(db, made.id, with_money=_money(db, actor))["fabric"]}


@router.get("/fabrics/{fabric_id}")
def one_fabric(fabric_id: int, actor: UserAccount = Depends(GUARD), db: Session = Depends(get_session)) -> dict:
    try:
        return fabric.detail(db, fabric_id, with_money=_money(db, actor))
    except NotFound as exc:
        raise HTTPException(404, str(exc)) from None


@router.patch("/fabrics/{fabric_id}")
def edit_fabric(
    fabric_id: int, body: FabricEdit, actor: UserAccount = Depends(EDIT), db: Session = Depends(get_session)
) -> dict:
    data = body.model_dump(exclude_unset=True)
    _staged(db, lambda: fabric.edit_fabric(db, fabric_id, data, actor))
    return fabric.detail(db, fabric_id, with_money=_money(db, actor))


@router.post("/fabrics/{fabric_id}/count")
def count_fabric(
    fabric_id: int, body: Count, actor: UserAccount = Depends(EDIT), db: Session = Depends(get_session)
) -> dict:
    _staged(db, lambda: fabric.count(db, fabric_id, body.kg_in_storage, body.note, actor))
    return fabric.detail(db, fabric_id, with_money=_money(db, actor))


# ── An order's fabric ─────────────────────────────────────────────────────────


@router.post("/orders/{order_id}/fabric")
def take_fabric(
    order_id: int, body: Take, actor: UserAccount = Depends(EDIT), db: Session = Depends(get_session)
) -> dict:
    """An open order whose fabric HBA buys takes kilos from storage."""
    order = _staged(db, lambda: fabric.take(db, order_id, body.fabric_id, body.kg, actor))
    return {"order": order_service.view(db, order.id, with_money=_money(db, actor))}


@router.delete("/orders/{order_id}/fabric/{move_id}")
def give_back_fabric(
    order_id: int, move_id: int, actor: UserAccount = Depends(EDIT), db: Session = Depends(get_session)
) -> dict:
    """Give what one take took back to storage."""
    order = _staged(db, lambda: fabric.give_back(db, order_id, move_id, actor))
    return {"order": order_service.view(db, order.id, with_money=_money(db, actor))}
