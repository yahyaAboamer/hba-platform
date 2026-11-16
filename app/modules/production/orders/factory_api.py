"""The factory's own desk under ``/api/factory`` (ADR 0084, batch 6b; build
plan ``docs/plans/2026-11-16-production-factory-login-build.md``).

**Every route is behind ``current_factory``, on the router itself**, so a route
added here later cannot be added without it - and ``require_permission`` is
never used here: a factory reaches its orders by owning its login, never by a
permission (its role grants none).

Its own orders only. Another supplier's order, a cancelled one, one closed
more than 30 days ago or one that does not exist are all refused **403, in the
same words** - never 404 - and the order is looked up only after the factory
is known. Every answer is built from a whitelist of fields
(``services.factory``): no money, no other supplier, no ratings, no notes
written by HBA, no HBA person's name.

Writes need the CSRF header like every other write (``signed_in``). Validation
refusals are 422, a step that has moved past changing is 409; success commits,
a refusal rolls back. Each write is audited with the factory's account as the
actor.
"""

from datetime import date as Day

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db import get_session
from app.modules.production.models import ProductionSupplier
from app.modules.production.orders.services import factory
from app.modules.production.orders.services.orders import Locked, NotFound, Refused
from app.shared.api.deps import current_factory, current_user
from app.shared.models.identity import UserAccount

router = APIRouter(prefix="/api/factory", tags=["factory"], dependencies=[Depends(current_factory)])


class CutReport(BaseModel):
    sizes: dict[str, int] = Field(max_length=6)
    note: str | None = Field(default=None, max_length=1000)


class DateMove(BaseModel):
    date: Day
    reason: str = Field(max_length=400)


def _refused(exc: Exception) -> HTTPException:
    if isinstance(exc, (factory.NotYours, NotFound)):
        return HTTPException(403, factory.NOT_YOURS)
    return HTTPException(409 if isinstance(exc, Locked) else 422, str(exc))


def _read(act) -> dict:
    try:
        return act()
    except (factory.NotYours, NotFound) as exc:
        raise _refused(exc) from None


def _write(db: Session, supplier: ProductionSupplier, order_id: int, act) -> dict:
    try:
        act()
    except (factory.NotYours, NotFound, Refused) as exc:
        db.rollback()
        raise _refused(exc) from None
    db.commit()
    return {"order": factory.my_order(db, supplier, order_id)}


@router.get("/orders")
def my_orders(supplier: ProductionSupplier = Depends(current_factory), db: Session = Depends(get_session)) -> dict:
    """The factory's open orders, newest delivery date last."""
    return factory.my_orders(db, supplier)


@router.get("/orders/{order_id}")
def my_order(
    order_id: int, supplier: ProductionSupplier = Depends(current_factory), db: Session = Depends(get_session)
) -> dict:
    """One of its orders: open, or closed in the last 30 days."""
    return _read(lambda: {"order": factory.my_order(db, supplier, order_id)})


@router.put("/orders/{order_id}/cut-report")
def report_cut(
    order_id: int,
    body: CutReport,
    supplier: ProductionSupplier = Depends(current_factory),
    actor: UserAccount = Depends(current_user),
    db: Session = Depends(get_session),
) -> dict:
    """What it cut, per size, for HBA's QC manager to confirm. Replaces a
    report not yet confirmed; refused once the cut is recorded."""
    data = body.model_dump()
    return _write(db, supplier, order_id, lambda: factory.report_cut(db, supplier, order_id, data, actor))


@router.post("/orders/{order_id}/delivery-date")
def move_date(
    order_id: int,
    body: DateMove,
    supplier: ProductionSupplier = Depends(current_factory),
    actor: UserAccount = Depends(current_user),
    db: Session = Depends(get_session),
) -> dict:
    """Move its delivery date, with a reason; the history says the factory."""
    return _write(
        db, supplier, order_id, lambda: factory.move_date(db, supplier, order_id, body.date, body.reason, actor)
    )
