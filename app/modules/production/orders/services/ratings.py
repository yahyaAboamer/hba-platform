"""Ratings and the performance record (ADR 0084, decision 10; build plan
``docs/plans/2026-11-15-production-ratings-build.md``, batch 6a).

Once an order is **closed** (settled) the owner rates each supplier that worked
on it: quality, timing and dealing, 1 to 5 stars and an optional note. The
timing stars are *suggested* from the real lateness and the owner may change
them. A cancelled order is never rated.

What a supplier's record says (usual lateness, average stars) is **calculated
on each read, never typed**. Lateness per job is the order's own lateness
(``orders.lateness_days``, once its warehouse receipt is done) for the factory,
and for any supplier with purchases the days a received purchase came after its
expected date.

**No money anywhere in here**: ratings and the record are read by everybody who
reads Production (the QC manager sees them), so nothing here may carry a price,
a total or an amount. Writes only stage; the route commits on success and rolls
back on a refusal (``Refused`` -> 422, ``Locked`` -> 409, ``NotFound`` -> 404).
"""

import statistics
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.businesstime import utcnow
from app.modules.production.models import ProductionSupplier
from app.modules.production.orders.models import (
    ProdOrder,
    ProdOrderStage,
    ProdPurchase,
    ProdRating,
)
from app.modules.production.orders.services import orders as order_service
from app.modules.production.orders.services.orders import (
    Facts,
    Locked,
    NotFound,
    Refused,
    _iso,
    _text,
)
from app.shared.models.identity import UserAccount
from app.shared.services.audit import record_audit

#: How many of a supplier's latest known lateness figures its "usual" is the median of.
USUAL_JOBS = 10
NOTE_LIMIT = 1000

#: (most days late, stars): the timing suggestion. Later than the last is 1 star.
_BANDS = ((0, 5), (2, 4), (5, 3), (9, 2))


def stars_for_days(days: int) -> int:
    """The suggested timing stars for a lateness in days: on time 5, 1-2 days
    late 4, 3-5 days 3, 6-9 days 2, 10 or more 1."""
    for limit, stars in _BANDS:
        if days <= limit:
            return stars
    return 1


def _round(value, places: str) -> float:
    return float(Decimal(str(value)).quantize(Decimal(places), rounding=ROUND_HALF_UP))


# ── Who worked on an order, and how late each was ─────────────────────────────


def _live_purchases(order_ids=None, supplier_id: str | None = None):
    query = select(ProdPurchase).where(ProdPurchase.voided_at.is_(None))
    if order_ids is not None:
        query = query.where(ProdPurchase.order_id.in_(order_ids))
    if supplier_id is not None:
        query = query.where(ProdPurchase.supplier_id == supplier_id)
    return query


def crew(db: Session, orders: list[ProdOrder]) -> dict[int, list[tuple[str, str]]]:
    """Each order's suppliers as ``(supplier_id, role)``: the factory, the
    outside print house, then every supplier with a live purchase for the
    order (role ``materials``). A supplier appears once, in the first role it
    holds. One query for all the orders."""
    found: dict[int, list[tuple[str, str]]] = {}
    for order in orders:
        members = [(order.factory_id, "factory")]
        if order.print_supplier_id and order.print_supplier_id != order.factory_id:
            members.append((order.print_supplier_id, "print"))
        found[order.id] = members
    if orders:
        rows = db.execute(
            select(ProdPurchase.order_id, ProdPurchase.supplier_id)
            .where(ProdPurchase.order_id.in_(list(found)), ProdPurchase.voided_at.is_(None))
            .distinct()
            .order_by(ProdPurchase.order_id, ProdPurchase.supplier_id)
        ).all()
        for order_id, supplier_id in rows:
            if all(supplier_id != existing for existing, _ in found[order_id]):
                found[order_id].append((supplier_id, "materials"))
    return found


def _finished_lateness(order: ProdOrder, warehouse: ProdOrderStage | None) -> int | None:
    """The order's lateness, once its warehouse receipt is done (and it was not
    cancelled); otherwise not known. It is batch 1's ``lateness_days`` itself,
    which only looks at the order and its warehouse stage."""
    if order.status == "cancelled" or warehouse is None or warehouse.status != "done":
        return None
    return order_service.lateness_days(Facts(order, {}, {"warehouse": warehouse}, [], []), order_service.today())


def _purchase_days(purchase: ProdPurchase) -> int | None:
    if purchase.received_on is None or purchase.expected_on is None:
        return None
    return max(0, (purchase.received_on - purchase.expected_on).days)


def lateness_map(db: Session, orders: list[ProdOrder], supplier_id: str | None = None) -> dict[tuple[int, str], int]:
    """How late each supplier was on each order, where it is known:
    ``{(order_id, supplier_id): days}``. The factory's is the order's own
    lateness once its warehouse receipt is done; anybody else's is the largest
    lateness of its received purchases for the order (so a print house with no
    purchases has none). ``supplier_id`` narrows it to one supplier. Two
    queries however many orders."""
    if not orders:
        return {}
    ids = [o.id for o in orders]
    found: dict[tuple[int, str], int] = {}
    for purchase in db.scalars(_live_purchases(ids, supplier_id)):
        days = _purchase_days(purchase)
        if days is not None:
            key = (purchase.order_id, purchase.supplier_id)
            found[key] = max(found.get(key, 0), days)
    warehouses = {
        stage.order_id: stage
        for stage in db.scalars(
            select(ProdOrderStage).where(ProdOrderStage.order_id.in_(ids), ProdOrderStage.stage == "warehouse")
        )
    }
    for order in orders:
        # The factory's lateness is the order's, never its purchases'.
        found.pop((order.id, order.factory_id), None)
        days = _finished_lateness(order, warehouses.get(order.id))
        if days is not None and supplier_id in (None, order.factory_id):
            found[(order.id, order.factory_id)] = days
    return found


# ── One order's ratings (the sheet) ───────────────────────────────────────────


def rating_view(row: ProdRating | None) -> dict | None:
    if row is None:
        return None
    return {
        "quality": row.quality,
        "timing": row.timing,
        "dealing": row.dealing,
        "note": row.note,
        "updated_at": _iso(row.updated_at),
    }


def sheet(db: Session, order_id: int) -> dict:
    """Who is rated on one order, with the suggested timing and what was saved.
    ``ratable`` is true only for a closed order; for any other the list is empty."""
    order = order_service._order(db, order_id)
    if order.status != "closed":
        return {"ratable": False, "suppliers": []}
    members = crew(db, [order])[order.id]
    names = order_service._suppliers(db, [sid for sid, _ in members])
    lateness = lateness_map(db, [order])
    saved = {
        row.supplier_id: row for row in db.scalars(select(ProdRating).where(ProdRating.order_id == order.id))
    }
    rows = []
    for supplier_id, role in members:
        days = lateness.get((order.id, supplier_id))
        rows.append(
            {
                "supplier": {"id": supplier_id, "name": names.get(supplier_id)},
                "role": role,
                "lateness_days": days,
                "suggested_timing": None if days is None else stars_for_days(days),
                "rating": rating_view(saved.get(supplier_id)),
            }
        )
    # The factory, then the print house, then the materials suppliers by name.
    first = [r for r in rows if r["role"] != "materials"]
    rest = sorted((r for r in rows if r["role"] == "materials"), key=lambda r: (r["supplier"]["name"] or "").lower())
    return {"ratable": True, "suppliers": first + rest}


def _stars(value, what: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 5:
        raise Refused(f"Give {what} from 1 to 5 stars.")
    return value


def save(db: Session, order_id: int, supplier_id: str, data: dict, actor: UserAccount) -> ProdOrder:
    """Save (or change, in place) one supplier's ratings on a closed order."""
    quality = _stars(data.get("quality"), "the quality")
    timing = _stars(data.get("timing"), "the timing")
    dealing = _stars(data.get("dealing"), "the dealing")
    note = _text(data.get("note"), limit=NOTE_LIMIT, what="the note")
    order = order_service._order(db, order_id, for_update=True)
    if order.status == "cancelled":
        raise Locked(f"{order.code} was cancelled. A cancelled order is not rated.")
    if order.status != "closed":
        raise Locked(f"{order.code} is not settled yet. Rate the suppliers once it is settled.")
    if supplier_id not in {sid for sid, _ in crew(db, [order])[order.id]}:
        raise NotFound(f"That supplier did not work on {order.code}.")
    row = db.scalar(select(ProdRating).where(ProdRating.order_id == order.id, ProdRating.supplier_id == supplier_id))
    if row is None:
        row = ProdRating(order_id=order.id, supplier_id=supplier_id, created_by=actor.id)
        db.add(row)
    row.quality, row.timing, row.dealing, row.note = quality, timing, dealing, note
    row.updated_by = actor.id
    row.updated_at = utcnow()
    name = db.scalar(select(ProductionSupplier.name).where(ProductionSupplier.id == supplier_id))
    # The sentence names the stars, never the note.
    record_audit(
        db,
        action="production.rating_saved",
        subject=f"production:order:{order.id}",
        actor_id=actor.id,
        actor_email=actor.email,
        after={
            "summary": f"Rated {name} on {order.code}: quality {quality}, timing {timing}, dealing {dealing}"[:500],
            "order": order.code,
        },
    )
    db.flush()
    return order


# ── A supplier's record (calculated, never typed) ─────────────────────────────


@dataclass
class Record:
    #: ``{quality, timing, dealing, count}`` averaged to one decimal, or ``None`` when never rated.
    ratings: dict | None
    #: The median of the last ``USUAL_JOBS`` known lateness figures, whole days, or ``None``.
    usual_lateness_days: int | None


def _usual(jobs: list[tuple[date, int]]) -> int | None:
    if not jobs:
        return None
    latest = [days for _, days in sorted(jobs, key=lambda job: job[0], reverse=True)[:USUAL_JOBS]]
    middle = statistics.median(latest)
    return int(Decimal(str(middle)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def records(db: Session, supplier_ids: list[str]) -> dict[str, Record]:
    """Each supplier's record, in three queries however many suppliers."""
    wanted = list(supplier_ids)
    jobs: dict[str, list[tuple[date, int]]] = {i: [] for i in wanted}
    averages: dict[str, dict] = {}
    if wanted:
        # As the factory: every order of its that has reached the warehouse.
        finished = db.execute(
            select(ProdOrder, ProdOrderStage)
            .join(ProdOrderStage, ProdOrderStage.order_id == ProdOrder.id)
            .where(
                ProdOrder.factory_id.in_(wanted),
                ProdOrder.status != "cancelled",
                ProdOrderStage.stage == "warehouse",
                ProdOrderStage.status == "done",
            )
        ).all()
        for order, warehouse in finished:
            days = _finished_lateness(order, warehouse)
            if days is not None:
                jobs[order.factory_id].append((warehouse.done_on, days))
        # As a supplier of anything bought: each received purchase with an expected date.
        for purchase in db.scalars(
            _live_purchases().where(
                ProdPurchase.supplier_id.in_(wanted),
                ProdPurchase.received_on.is_not(None),
                ProdPurchase.expected_on.is_not(None),
            )
        ):
            jobs[purchase.supplier_id].append((purchase.received_on, _purchase_days(purchase)))
        for supplier_id, quality, timing, dealing, count in db.execute(
            select(
                ProdRating.supplier_id,
                func.avg(ProdRating.quality),
                func.avg(ProdRating.timing),
                func.avg(ProdRating.dealing),
                func.count(),
            )
            .where(ProdRating.supplier_id.in_(wanted))
            .group_by(ProdRating.supplier_id)
        ):
            averages[supplier_id] = {
                "quality": _round(quality, "0.1"),
                "timing": _round(timing, "0.1"),
                "dealing": _round(dealing, "0.1"),
                "count": count,
            }
    return {i: Record(averages.get(i), _usual(jobs[i])) for i in wanted}


def rating_map(db: Session, supplier_id: str) -> dict[int, ProdRating]:
    """One supplier's ratings by order id."""
    return {row.order_id: row for row in db.scalars(select(ProdRating).where(ProdRating.supplier_id == supplier_id))}


def reject_rate(facts: Facts) -> float | None:
    """Rejected over cut, in per cent to one decimal; ``None`` when nothing was cut."""
    cut = facts.total("cut")
    if not cut:
        return None
    return _round(Decimal(facts.total("rejected")) * 100 / Decimal(cut), "0.1")
