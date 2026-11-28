"""Production orders under ``/api/prod`` (ADR 0084; build plan 2026-11-14).

Every route is behind ``production.view``, on the router itself, so a route
added later cannot be added without it. The QC manager's writes add
``production.edit``; the owner's add ``production.owner``.

**Money is filtered here, on the server**: a response carries ``cost`` and
``settlement`` only to somebody holding ``production.owner``. Without it they
are absent, not null. The history carries no money for anybody.

Tasks (``/tasks``): the list is every open order's generated tasks plus the
ones typed in by hand, for anybody who reads Production; the hand-added ones
are written with ``production.edit``. No task carries money.

Incoming (``/incoming``): what is still to arrive at Khazenly and every delivery
with its two counts, read from the orders for anybody who reads Production.
No money, for anybody.

Overview (``/overview``): the first tab, read from what the other four screens
already work out. Read only. Without ``production.owner`` it has no ``owed``,
no cost problem and no key ending ``_piastres``.

Library (``/library``, ADR 0087): every Shopify product with what HBA types
about it. Anybody who reads Production reads it; the details and the COGS are
changed with ``production.owner``, files added and removed with
``production.edit``. The COGS is money: a product carries ``cogs`` only for
``production.owner``, and the list carries no amount for anybody.

Refusals follow Operations: ``Refused`` -> 422, ``Locked`` -> 409, an
unknown order, stage, delivery or file (``NotFound``, and only that) -> 404.
A refusal rolls back whatever was staged; success commits.
"""

import logging
import re
from datetime import date
from decimal import Decimal
from typing import Literal
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.core.permissions import Permission
from app.db import get_session
from app.modules.inbox.public import StorageError, file_bucket
from app.modules.production.orders.guards import EDIT, GUARD, OWNER, SUPPLIERS, too_large  # noqa: F401
from app.modules.production.orders.services import files, incoming, library, orders, overview, ratings, tasks
from app.shared.api.deps import holds
from app.shared.models.identity import UserAccount

logger = logging.getLogger(__name__)

# The guards (kept by name so a test can find them) live in ``guards``, which
# the suppliers' routes share.
router = APIRouter(prefix="/api/prod", tags=["production-orders"], dependencies=[Depends(GUARD)])

Size = Literal["XS", "S", "M", "L", "XL", "XXL"]
Stage = Literal[
    "plan", "sample", "materials", "fabric_check", "pattern_check", "cutting", "making",
    "final_inspection", "warehouse", "settle",
]

def _refused(exc: orders.Refused) -> HTTPException:
    return HTTPException(409 if isinstance(exc, orders.Locked) else 422, str(exc))


def _money(db: Session, actor: UserAccount) -> bool:
    return holds(db, actor, Permission.PRODUCTION_OWNER)


def _write(db: Session, actor: UserAccount, act) -> dict:
    """Run one staged change; commit and answer with the order as this person
    may see it, or roll back and refuse."""
    try:
        order = act()
    except orders.NotFound as exc:
        db.rollback()
        raise HTTPException(404, str(exc)) from None
    except orders.Refused as exc:
        db.rollback()
        raise _refused(exc) from None
    db.commit()
    return {"order": orders.view(db, order.id, with_money=_money(db, actor))}


# ── Bodies ────────────────────────────────────────────────────────────────────


class FabricLine(BaseModel):
    """Kilos of one fabric a New order takes from storage (ADR 0089)."""

    model_config = ConfigDict(extra="forbid")

    fabric_id: int = Field(ge=1, le=2_147_483_647)
    kg: Decimal = Field(allow_inf_nan=False, max_digits=20)


class NewOrder(BaseModel):
    style_name: str = Field(max_length=400)
    colour: str = Field(max_length=200)
    shopify_product_id: str | None = Field(default=None, max_length=32)
    factory_id: str = Field(max_length=80)
    fabric_bought_by: Literal["hba", "factory"]
    printing: Literal["factory", "outside", "none"]
    print_supplier_id: str | None = Field(default=None, max_length=80)
    repeat_run: bool = False
    target_date: date
    planned: dict[Size, int] = Field(default_factory=dict)
    target_fabric_piastres: int = Field(default=0, ge=0, le=orders.MAX_PART_PIASTRES)
    target_manufacturing_piastres: int = Field(default=0, ge=0, le=orders.MAX_PART_PIASTRES)
    target_printing_piastres: int = Field(default=0, ge=0, le=orders.MAX_PART_PIASTRES)
    target_accessories_piastres: int = Field(default=0, ge=0, le=orders.MAX_PART_PIASTRES)
    target_packaging_piastres: int = Field(default=0, ge=0, le=orders.MAX_PART_PIASTRES)
    #: Overrides of the dates filled in backwards from the target date.
    expected_dates: dict[Stage, date] | None = None
    notes: str | None = Field(default=None, max_length=4000)
    #: The product's details (build plan 2026-11-19); blank is none.
    colour_code: str | None = Field(default=None, max_length=200)
    fabric_type: str | None = Field(default=None, max_length=400)
    decoration_type: str | None = Field(default=None, max_length=400)
    decoration_width_cm: Decimal | None = Field(default=None, allow_inf_nan=False, max_digits=12)
    #: The fabric it takes from storage (ADR 0089): at most ten lines, each
    #: fabric once. Only when HBA buys the fabric.
    fabric: list[FabricLine] | None = Field(default=None, max_length=10)


class OrderEdit(BaseModel):
    style_name: str | None = Field(default=None, max_length=400)
    colour: str | None = Field(default=None, max_length=200)
    shopify_product_id: str | None = Field(default=None, max_length=32)
    factory_id: str | None = Field(default=None, max_length=80)
    fabric_bought_by: Literal["hba", "factory"] | None = None
    printing: Literal["factory", "outside", "none"] | None = None
    print_supplier_id: str | None = Field(default=None, max_length=80)
    target_date: date | None = None
    notes: str | None = Field(default=None, max_length=4000)
    planned: dict[Size, int] | None = None
    target_fabric_piastres: int | None = Field(default=None, ge=0, le=orders.MAX_PART_PIASTRES)
    target_manufacturing_piastres: int | None = Field(default=None, ge=0, le=orders.MAX_PART_PIASTRES)
    target_printing_piastres: int | None = Field(default=None, ge=0, le=orders.MAX_PART_PIASTRES)
    target_accessories_piastres: int | None = Field(default=None, ge=0, le=orders.MAX_PART_PIASTRES)
    target_packaging_piastres: int | None = Field(default=None, ge=0, le=orders.MAX_PART_PIASTRES)
    #: ``null`` clears a typed actual.
    actual_fabric_piastres: int | None = Field(default=None, ge=0, le=orders.MAX_PART_PIASTRES)
    actual_manufacturing_piastres: int | None = Field(default=None, ge=0, le=orders.MAX_PART_PIASTRES)
    actual_printing_piastres: int | None = Field(default=None, ge=0, le=orders.MAX_PART_PIASTRES)
    actual_accessories_piastres: int | None = Field(default=None, ge=0, le=orders.MAX_PART_PIASTRES)
    actual_packaging_piastres: int | None = Field(default=None, ge=0, le=orders.MAX_PART_PIASTRES)
    #: The product's details; ``null`` or blank clears one. Only while the order is open.
    colour_code: str | None = Field(default=None, max_length=200)
    fabric_type: str | None = Field(default=None, max_length=400)
    decoration_type: str | None = Field(default=None, max_length=400)
    decoration_width_cm: Decimal | None = Field(default=None, allow_inf_nan=False, max_digits=12)


class StageEdit(BaseModel):
    expected_date: date | None = None
    note: str | None = Field(default=None, max_length=4000)


class StageDone(BaseModel):
    done_on: date | None = None
    note: str | None = Field(default=None, max_length=4000)
    #: Fabric check only.
    result: Literal["passed", "failed"] | None = None


class WithReason(BaseModel):
    reason: str = Field(default="", max_length=1000)


class Reason(BaseModel):
    reason: str = Field(max_length=400)
    quantity: int = Field(gt=0, le=orders.MAX_PIECES * 6)


class Cut(BaseModel):
    sizes: dict[Size, int]
    reasons: list[Reason] = Field(default_factory=list, max_length=50)
    promised_date: date
    done_on: date | None = None


class Inspected(BaseModel):
    """One size's counts. All three are required: a size sent in part would
    silently zero the others."""

    passed: int = Field(ge=0, le=orders.MAX_PIECES)
    to_fix: int = Field(ge=0, le=orders.MAX_PIECES)
    rejected: int = Field(ge=0, le=orders.MAX_PIECES)


class InspectionReason(Reason):
    kind: Literal["rejected", "to_fix"]


class Inspection(BaseModel):
    sizes: dict[Size, Inspected] = Field(default_factory=dict)
    #: Left out: the reasons stay as they were. Given: they replace them.
    reasons: list[InspectionReason] | None = Field(default=None, max_length=100)
    complete: bool = False
    done_on: date | None = None


class WriteOff(BaseModel):
    sizes: dict[Size, int]
    reason: str = Field(default="", max_length=1000)


class Sample(BaseModel):
    decision: Literal["approved", "changes"]
    note: str | None = Field(default=None, max_length=4000)


class DeliveryDate(BaseModel):
    new_date: date
    set_by: Literal["owner", "factory"]
    reason: str = Field(default="", max_length=1000)


class NewDelivery(BaseModel):
    kind: Literal["finished", "fix"]
    shipped_on: date
    shipped: dict[Size, int]
    counted_on: date | None = None
    counted: dict[Size, int] | None = None
    mismatch_reason: str | None = Field(default=None, max_length=2000)


class DeliveryEdit(BaseModel):
    shipped_on: date | None = None
    shipped: dict[Size, int] | None = None
    counted_on: date | None = None
    counted: dict[Size, int] | None = None
    mismatch_reason: str | None = Field(default=None, max_length=2000)


class StageDays(BaseModel):
    days: dict[str, int]


class NewTask(BaseModel):
    title: str = Field(max_length=400)
    due_on: date | None = None
    order_id: int | None = Field(default=None, ge=1, le=2_147_483_647)
    note: str | None = Field(default=None, max_length=4000)
    for_owner: bool = False
    next_action: str | None = Field(default=None, max_length=1000)


class TaskEdit(BaseModel):
    """Any of these; what is left out stays as it was. ``null`` clears the
    date, the order or the note."""

    title: str | None = Field(default=None, max_length=400)
    due_on: date | None = None
    order_id: int | None = Field(default=None, ge=1, le=2_147_483_647)
    note: str | None = Field(default=None, max_length=4000)
    for_owner: bool | None = None
    done: bool | None = None
    #: ``null`` or blank clears it.
    next_action: str | None = Field(default=None, max_length=1000)


class TaskUpdate(BaseModel):
    """A follow-up line. ``next_action`` sent (even ``null``) also replaces the
    task's next action; left out, it stays."""

    text: str = Field(max_length=4000)
    next_action: str | None = Field(default=None, max_length=1000)


# ── Orders ────────────────────────────────────────────────────────────────────


@router.get("/orders")
def order_list(
    status: Literal["open", "closed"] = Query("open"),
    db: Session = Depends(get_session),
) -> dict:
    """The order list. ``closed`` is settled and cancelled orders together.
    No money in a row, for anybody."""
    return {"orders": orders.rows(db, status)}


@router.post("/orders", status_code=201)
def create_order(body: NewOrder, actor: UserAccount = Depends(OWNER), db: Session = Depends(get_session)) -> dict:
    data = body.model_dump()
    return _write(db, actor, lambda: orders.create(db, data, actor))


@router.get("/orders/{order_id}")
def one_order(order_id: int, actor: UserAccount = Depends(GUARD), db: Session = Depends(get_session)) -> dict:
    try:
        return {"order": orders.view(db, order_id, with_money=_money(db, actor))}
    except orders.NotFound as exc:
        raise HTTPException(404, str(exc)) from None


@router.patch("/orders/{order_id}")
def edit_order(
    order_id: int, body: OrderEdit, actor: UserAccount = Depends(OWNER), db: Session = Depends(get_session)
) -> dict:
    data = body.model_dump(exclude_unset=True)
    return _write(db, actor, lambda: orders.edit(db, order_id, data, actor))


@router.patch("/orders/{order_id}/stages/{stage}")
def edit_stage(
    order_id: int, stage: str, body: StageEdit,
    actor: UserAccount = Depends(EDIT), db: Session = Depends(get_session),
) -> dict:
    data = body.model_dump(exclude_unset=True)
    return _write(db, actor, lambda: orders.edit_stage(db, order_id, stage, data, actor))


@router.post("/orders/{order_id}/stages/{stage}/complete")
def complete_stage(
    order_id: int, stage: str, body: StageDone,
    actor: UserAccount = Depends(EDIT), db: Session = Depends(get_session),
) -> dict:
    data = body.model_dump()
    return _write(db, actor, lambda: orders.complete_stage(db, order_id, stage, data, actor))


@router.post("/orders/{order_id}/stages/{stage}/reopen")
def reopen_stage(
    order_id: int, stage: str, body: WithReason,
    actor: UserAccount = Depends(OWNER), db: Session = Depends(get_session),
) -> dict:
    return _write(db, actor, lambda: orders.reopen_stage(db, order_id, stage, body.reason, actor))


@router.put("/orders/{order_id}/cut")
def record_cut(
    order_id: int, body: Cut, actor: UserAccount = Depends(EDIT), db: Session = Depends(get_session)
) -> dict:
    data = body.model_dump()
    return _write(db, actor, lambda: orders.record_cut(db, order_id, data, actor))


class CutEdit(BaseModel):
    sizes: dict[Size, int]
    reasons: list[Reason] = Field(default_factory=list, max_length=50)
    reason: str = Field(default="", max_length=1000)


@router.patch("/orders/{order_id}/cut")
def edit_cut(
    order_id: int, body: CutEdit, actor: UserAccount = Depends(OWNER), db: Session = Depends(get_session)
) -> dict:
    """The owner corrects the cut counts after cutting is recorded."""
    data = body.model_dump()
    return _write(db, actor, lambda: orders.edit_cut(db, order_id, data, actor))


@router.put("/orders/{order_id}/inspection")
def save_inspection(
    order_id: int, body: Inspection, actor: UserAccount = Depends(EDIT), db: Session = Depends(get_session)
) -> dict:
    data = body.model_dump(exclude_unset=True)
    data.setdefault("sizes", {})
    return _write(db, actor, lambda: orders.save_inspection(db, order_id, data, actor))


@router.post("/orders/{order_id}/write-off")
def write_off(
    order_id: int, body: WriteOff, actor: UserAccount = Depends(OWNER), db: Session = Depends(get_session)
) -> dict:
    return _write(db, actor, lambda: orders.write_off(db, order_id, dict(body.sizes), body.reason, actor))


@router.post("/orders/{order_id}/sample")
def decide_sample(
    order_id: int, body: Sample, actor: UserAccount = Depends(OWNER), db: Session = Depends(get_session)
) -> dict:
    return _write(db, actor, lambda: orders.decide_sample(db, order_id, body.decision, body.note, actor))


@router.post("/orders/{order_id}/delivery-date")
def change_delivery_date(
    order_id: int, body: DeliveryDate, actor: UserAccount = Depends(EDIT), db: Session = Depends(get_session)
) -> dict:
    return _write(
        db, actor,
        lambda: orders.change_delivery_date(db, order_id, body.new_date, body.set_by, body.reason, actor),
    )


@router.post("/orders/{order_id}/deliveries", status_code=201)
def add_delivery(
    order_id: int, body: NewDelivery, actor: UserAccount = Depends(EDIT), db: Session = Depends(get_session)
) -> dict:
    data = body.model_dump()
    created: dict = {}

    def act():
        order, delivery = orders.add_delivery(db, order_id, data, actor)
        created["id"] = delivery.id
        return order

    answer = _write(db, actor, act)
    return {**answer, "delivery_id": created["id"]}


@router.patch("/deliveries/{delivery_id}")
def edit_delivery(
    delivery_id: int, body: DeliveryEdit, actor: UserAccount = Depends(EDIT), db: Session = Depends(get_session)
) -> dict:
    data = body.model_dump(exclude_unset=True)
    return _write(db, actor, lambda: orders.edit_delivery(db, delivery_id, data, actor))


@router.post("/orders/{order_id}/settle")
def settle(order_id: int, actor: UserAccount = Depends(OWNER), db: Session = Depends(get_session)) -> dict:
    return _write(db, actor, lambda: orders.settle(db, order_id, actor))


@router.post("/orders/{order_id}/cancel")
def cancel(
    order_id: int, body: WithReason, actor: UserAccount = Depends(OWNER), db: Session = Depends(get_session)
) -> dict:
    return _write(db, actor, lambda: orders.cancel(db, order_id, body.reason, actor))


class RatingBody(BaseModel):
    quality: int = Field(strict=True, ge=1, le=5)
    timing: int = Field(strict=True, ge=1, le=5)
    dealing: int = Field(strict=True, ge=1, le=5)
    note: str | None = Field(default=None, max_length=1000)


@router.get("/orders/{order_id}/ratings")
def order_ratings(order_id: int, db: Session = Depends(get_session)) -> dict:
    """Who is rated on a settled order, the suggested timing stars and what
    was saved. For anybody who reads Production; no money."""
    try:
        return ratings.sheet(db, order_id)
    except orders.NotFound as exc:
        raise HTTPException(404, str(exc)) from None


@router.put("/orders/{order_id}/ratings/{supplier_id}")
def rate_supplier(
    order_id: int,
    supplier_id: str,
    body: RatingBody,
    actor: UserAccount = Depends(OWNER),
    db: Session = Depends(get_session),
) -> dict:
    """The owner's rating of one supplier on a settled order, saved or changed
    in place. Answers with the order's ratings as ``GET`` gives them."""
    data = body.model_dump()
    try:
        ratings.save(db, order_id, supplier_id, data, actor)
    except orders.NotFound as exc:
        db.rollback()
        raise HTTPException(404, str(exc)) from None
    except orders.Refused as exc:
        db.rollback()
        raise _refused(exc) from None
    db.commit()
    return ratings.sheet(db, order_id)


@router.get("/orders/{order_id}/history")
def order_history(order_id: int, db: Session = Depends(get_session)) -> dict:
    """The order's history, newest first. No entry carries money."""
    try:
        return orders.history(db, order_id)
    except orders.NotFound as exc:
        raise HTTPException(404, str(exc)) from None


# ── Tasks ─────────────────────────────────────────────────────────────────────


def _task_write(db: Session, act) -> dict:
    """Run one staged change to a hand-added task; commit and answer with it
    as the list shows it, or roll back and refuse."""
    try:
        task = act()
    except orders.NotFound as exc:
        db.rollback()
        raise HTTPException(404, str(exc)) from None
    except orders.Refused as exc:
        db.rollback()
        raise _refused(exc) from None
    db.commit()
    return {"task": tasks.view(db, task)}


@router.get("/tasks")
def task_list(
    done: bool = Query(False),
    view: Literal["open", "done"] = Query("open"),
    from_: date | None = Query(None, alias="from"),
    to: date | None = Query(None),
    db: Session = Depends(get_session),
) -> dict:
    """Every open task, grouped by when it is due, and the counts the filters
    show. ``done=1`` adds the hand-added tasks done in the last 14 days.
    ``view=done`` is every hand-added task marked done, newest first.
    ``from``/``to`` (inclusive) keep the open tasks whose deadline is inside,
    or the done ones marked done inside (Cairo's date). No money, for anybody."""
    if from_ is not None and to is not None and from_ > to:
        raise HTTPException(422, "The From date is after the To date. Swap them or clear one.")
    return tasks.listing(db, show_done=done, view=view, start=from_, end=to)


@router.get("/incoming")
def incoming_list(db: Session = Depends(get_session)) -> dict:
    """The arrivals (finished and fix pieces still to leave the factory, nearest
    first), the deliveries with their counts and state, and the four figures at
    the top. Read only; no money, for anybody."""
    return incoming.listing(db)


@router.get("/overview")
def overview_page(actor: UserAccount = Depends(GUARD), db: Session = Depends(get_session)) -> dict:
    """What waits for the owner, what is wrong now, every open order and its next
    action, the nearest arrivals and (owner only) what is owed. Read only."""
    return overview.overview(db, with_money=_money(db, actor))


@router.post("/tasks", status_code=201)
def add_task(body: NewTask, actor: UserAccount = Depends(EDIT), db: Session = Depends(get_session)) -> dict:
    data = body.model_dump()
    return _task_write(db, lambda: tasks.create(db, data, actor))


@router.patch("/tasks/{task_id}")
def edit_task(
    task_id: int, body: TaskEdit, actor: UserAccount = Depends(EDIT), db: Session = Depends(get_session)
) -> dict:
    data = body.model_dump(exclude_unset=True)
    return _task_write(db, lambda: tasks.edit(db, task_id, data, actor))


@router.post("/tasks/{task_id}/updates", status_code=201)
def add_task_update(
    task_id: int, body: TaskUpdate, actor: UserAccount = Depends(EDIT), db: Session = Depends(get_session)
) -> dict:
    """What happened on a task, and (when sent) its next action. A done task
    may take one too; a deleted one is 404."""
    data = body.model_dump(exclude_unset=True)
    return _task_write(db, lambda: tasks.add_update(db, task_id, data, actor))


@router.delete("/tasks/{task_id}")
def delete_task(task_id: int, actor: UserAccount = Depends(EDIT), db: Session = Depends(get_session)) -> dict:
    try:
        tasks.delete(db, task_id, actor)
    except orders.NotFound as exc:
        db.rollback()
        raise HTTPException(404, str(exc)) from None
    db.commit()
    return {"deleted": task_id}


# ── Files ─────────────────────────────────────────────────────────────────────


@router.get("/orders/{order_id}/files")
def order_files(order_id: int, db: Session = Depends(get_session)) -> dict:
    try:
        return {"files": files.listing(db, order_id)}
    except orders.NotFound as exc:
        raise HTTPException(404, str(exc)) from None


@router.post("/orders/{order_id}/files", status_code=201)
async def add_file(
    order_id: int, request: Request, actor: UserAccount = Depends(EDIT), db: Session = Depends(get_session)
) -> dict:
    """A photo or PDF, multipart: ``file``, an optional ``stage`` and an
    optional ``kind`` (``pattern``, which may be any file, or ``size_chart``).
    Refused before reading when too large or of no stated size."""
    if too_large(request):
        raise HTTPException(413, "Files must be 20 MB or smaller.")
    form = await request.form()
    upload = form.get("file")
    content = await upload.read() if hasattr(upload, "read") else b""
    filename = getattr(upload, "filename", None) or ""
    stage = form.get("stage")
    stage = stage if isinstance(stage, str) else None
    kind = form.get("kind")
    kind = kind.strip() if isinstance(kind, str) else None

    def store() -> dict:
        try:
            saved = files.add(
                db, order_id, filename=filename, content=content, stage=stage, actor=actor, kind=kind
            )
        except orders.NotFound as exc:
            db.rollback()
            raise HTTPException(404, str(exc)) from None
        except orders.Refused as exc:
            db.rollback()
            raise _refused(exc) from None
        except StorageError:
            db.rollback()
            logger.exception("A production order's file could not be stored")
            raise HTTPException(503, "The file couldn't be saved. Try again.") from None
        db.commit()
        return {"file": saved}

    return await run_in_threadpool(store)


def _attachment(name: str) -> str:
    """``attachment`` with the file's name, safely quoted: an ASCII fallback
    (no quote, backslash or control character) and the name itself, percent-encoded
    (RFC 5987/6266)."""
    fallback = re.sub(r'[^A-Za-z0-9 ._()\-]', "_", name).strip() or "file"
    return f"attachment; filename=\"{fallback}\"; filename*=UTF-8''{quote(name, safe='')}"


@router.get("/files/{file_id}")
def one_file(file_id: int, db: Session = Depends(get_session)) -> Response:
    row = files.for_download(db, file_id)
    if row is None:
        raise HTTPException(404, "There is no such file.")
    try:
        content = file_bucket().get(row.storage_key)
    except StorageError:
        raise HTTPException(404, "There is no such file.") from None
    return Response(
        content,
        media_type=row.mime_type,
        headers={
            # A photo or PDF opens in the browser; any other pattern file is
            # only ever downloaded, never shown.
            "Content-Disposition": "inline" if row.mime_type != files.OTHER else _attachment(row.name),
            "X-Content-Type-Options": "nosniff",
            # No Cache-Control here: the app marks every API response
            # no-store (app/main.py), which is right for a production file too.
        },
    )


@router.delete("/files/{file_id}")
def remove_file(file_id: int, actor: UserAccount = Depends(EDIT), db: Session = Depends(get_session)) -> dict:
    try:
        files.remove(db, file_id, actor)
    except orders.NotFound as exc:
        raise HTTPException(404, str(exc)) from None
    except orders.Refused as exc:
        db.rollback()
        raise _refused(exc) from None
    db.commit()
    return {"deleted": file_id}


# ── Library (ADR 0087) ────────────────────────────────────────────────────────


class LibraryEdit(BaseModel):
    """Only the fields sent are changed; ``null`` or blank clears one."""

    model_config = ConfigDict(extra="forbid")

    colour_code: str | None = Field(default=None, max_length=200)
    fabric_type: str | None = Field(default=None, max_length=400)
    decoration_type: str | None = Field(default=None, max_length=400)
    decoration_width_cm: Decimal | None = Field(default=None, allow_inf_nan=False, max_digits=12)
    notes: str | None = Field(default=None, max_length=8000)
    cogs_fabric_piastres: int | None = None
    cogs_manufacturing_piastres: int | None = None
    cogs_printing_piastres: int | None = None
    cogs_accessories_piastres: int | None = None
    cogs_packaging_piastres: int | None = None


@router.get("/library")
def library_list(db: Session = Depends(get_session)) -> dict:
    """Every product, active, draft and archived. No money, for anybody."""
    return {"products": library.listing(db)}


@router.get("/library/{pid}")
def library_product(pid: str, actor: UserAccount = Depends(GUARD), db: Session = Depends(get_session)) -> dict:
    try:
        return {"product": library.detail(db, pid, with_money=_money(db, actor))}
    except orders.NotFound as exc:
        raise HTTPException(404, str(exc)) from None


@router.patch("/library/{pid}")
def edit_library_product(
    pid: str, body: LibraryEdit, actor: UserAccount = Depends(OWNER), db: Session = Depends(get_session)
) -> dict:
    data = body.model_dump(exclude_unset=True)
    try:
        library.update(db, pid, data, actor)
    except orders.NotFound as exc:
        db.rollback()
        raise HTTPException(404, str(exc)) from None
    except orders.Refused as exc:
        db.rollback()
        raise _refused(exc) from None
    db.commit()
    return {"product": library.detail(db, pid, with_money=_money(db, actor))}


@router.post("/library/{pid}/files", status_code=201)
async def add_library_file(
    pid: str, request: Request, actor: UserAccount = Depends(EDIT), db: Session = Depends(get_session)
) -> dict:
    """Multipart: ``file`` and ``kind`` (``design`` or ``pattern``, any file;
    ``size_chart``, a photo or PDF). Refused before reading when too large or
    of no stated size."""
    if too_large(request):
        raise HTTPException(413, "Files must be 20 MB or smaller.")
    form = await request.form()
    upload = form.get("file")
    content = await upload.read() if hasattr(upload, "read") else b""
    filename = getattr(upload, "filename", None) or ""
    kind = form.get("kind")
    kind = kind.strip() if isinstance(kind, str) else None

    def store() -> dict:
        try:
            saved = library.add(db, pid, filename=filename, content=content, kind=kind, actor=actor)
        except orders.NotFound as exc:
            db.rollback()
            raise HTTPException(404, str(exc)) from None
        except orders.Refused as exc:
            db.rollback()
            raise _refused(exc) from None
        except StorageError:
            db.rollback()
            logger.exception("A Library file could not be stored")
            raise HTTPException(503, "The file couldn't be saved. Try again.") from None
        db.commit()
        return {"file": saved}

    return await run_in_threadpool(store)


@router.get("/library-files/{file_id}")
def one_library_file(file_id: int, db: Session = Depends(get_session)) -> Response:
    row = library.for_download(db, file_id)
    if row is None:
        raise HTTPException(404, "There is no such file.")
    try:
        content = file_bucket().get(row.storage_key)
    except StorageError:
        raise HTTPException(404, "There is no such file.") from None
    return Response(
        content,
        media_type=row.mime_type,
        headers={
            # A photo or PDF opens in the browser; any other file is only ever
            # downloaded, never shown.
            "Content-Disposition": "inline" if row.mime_type != files.OTHER else _attachment(row.name),
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.delete("/library-files/{file_id}")
def remove_library_file(
    file_id: int, actor: UserAccount = Depends(EDIT), db: Session = Depends(get_session)
) -> dict:
    try:
        library.remove(db, file_id, actor)
    except orders.NotFound as exc:
        db.rollback()
        raise HTTPException(404, str(exc)) from None
    db.commit()
    return {"deleted": file_id}


# ── Settings and choices ──────────────────────────────────────────────────────


@router.get("/settings/stage-days")
def stage_days(db: Session = Depends(get_session)) -> dict:
    return orders.settings_view(db)


@router.put("/settings/stage-days")
def save_stage_days(
    body: StageDays, actor: UserAccount = Depends(OWNER), db: Session = Depends(get_session)
) -> dict:
    try:
        orders.save_stage_days(db, body.days, actor)
    except orders.Refused as exc:
        db.rollback()
        raise _refused(exc) from None
    db.commit()
    return orders.settings_view(db)


@router.get("/choices")
def choices(db: Session = Depends(get_session)) -> dict:
    """What the New order form needs: active suppliers, the active and draft
    Shopify products (with status and picture), the sizes, the typical days
    per stage and the active fabrics in storage with their kilos (no price)."""
    return orders.choices(db)


# ── Suppliers (batch 4) ───────────────────────────────────────────────────────
# Their routes are in ``suppliers_api`` (built with this router's prefix and
# guard) and are appended to this router's own routes.

from app.modules.production.orders import suppliers_api  # noqa: E402

router.routes.extend(suppliers_api.router.routes)

# ── Billing and fabric storage (ADR 0089) ─────────────────────────────────────
# Their routes are in ``fabric_api``, built and appended the same way.

from app.modules.production.orders import fabric_api  # noqa: E402

router.routes.extend(fabric_api.router.routes)
