"""Production's Incoming (ADR 0084, decision 5; build plan
``docs/plans/2026-11-14-production-incoming-build.md``).

What is still to arrive at Khazenly, nearest first, with the pieces per size,
and every delivery with its two counts (the factory's, and Khazenly's). Read
only: worked out on each read from the orders, sizes and deliveries batch 1
stores. Nothing here is written, so nothing needs a table or a migration.

Every open order is read once, together, with the batched ``_facts_for`` (a
query per kind of row, never a query per order).

**No money anywhere in this response, for anybody**: it holds words, dates
and counts of pieces only.
"""

from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.production.orders.models import SIZES, STAGE_LABELS, ProdDelivery, ProdOrder
from app.modules.production.orders.services.orders import (
    Delivery,
    Facts,
    _day,
    _facts_for,
    _suppliers,
    lateness_days,
    today,
)

#: A closed order's deliveries stay on the screen this long after they were counted.
RECENT_DAYS = 30

MONTHS = (
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
)


# ── Small helpers ─────────────────────────────────────────────────────────────


def _ref(order: ProdOrder) -> dict:
    return {"id": order.id, "code": order.code, "style_name": order.style_name, "colour": order.colour}


def _per_size(values: dict[str, int]) -> dict[str, int]:
    """Every size, in the screens' order, zero where there are none."""
    return {size: values.get(size, 0) for size in SIZES}


def _first_of_next_month(on: date) -> date:
    return date(on.year + 1, 1, 1) if on.month == 12 else date(on.year, on.month + 1, 1)


def _month(first: date, pieces: int) -> dict:
    return {"month": f"{first.year}-{first.month:02d}", "label": MONTHS[first.month - 1], "pieces": pieces}


def _stage(facts: Facts) -> dict | None:
    current = facts.current
    if current is None:
        return None
    return {"key": current.stage, "label": STAGE_LABELS[current.stage], "position": current.position}


# ── Arrivals ──────────────────────────────────────────────────────────────────


def _basis(facts: Facts) -> str:
    """Which count the finished pieces are expected from: the plan until
    cutting is done, then what was cut, then what passed the final inspection."""
    if facts.done("final_inspection"):
        return "passed"
    if facts.done("cutting"):
        return "cut"
    return "planned"


def _status_words(facts: Facts, kind: str) -> str:
    """Where the order is, in a short plain phrase for the order line."""
    if kind == "fix":
        return "repaired pieces"
    current = facts.current
    key = current.stage if current is not None else "warehouse"
    if key == "sample":
        if facts.order.sample_status == "changes":
            return "waiting for the changed sample"
        return "sample not approved yet"
    return {
        "materials": "waiting for fabric",
        "fabric_check": "fabric being checked",
        "pattern_check": "pattern being checked",
        "cutting": "being cut, final numbers after cutting",
        "making": "being made, final numbers after the final inspection",
        "final_inspection": "being inspected, final numbers when it is done",
    }.get(key, "arriving as pieces finish")


def _counts(sizes: dict[str, int], total: int | None = None) -> dict:
    return {"sizes": _per_size(sizes), "total": sum(sizes.values()) if total is None else total}


def _arrival(facts: Facts, kind: str, factory: str | None, on: date) -> dict | None:
    """One arrival row, or ``None`` when no pieces of this kind are still to come."""
    order = facts.order
    if kind == "finished":
        basis: str | None = _basis(facts)
        column = {"planned": "planned", "cut": "cut", "passed": "passed"}[basis]
    else:
        basis, column = None, "to_fix"
    expected = {size: (getattr(row, column) or 0) for size, row in facts.sizes.items()}
    shipped = {size: facts.shipped(kind, size) for size in SIZES}
    to_come = {size: max(0, expected.get(size, 0) - shipped[size]) for size in SIZES}
    expected_total, shipped_total = sum(expected.values()), sum(shipped.values())
    # The total, not the sum of the sizes: a size may have shipped past its own count while the order
    # as a whole is still short, and the server only holds the whole to what passed.
    to_come_total = max(0, expected_total - shipped_total)
    if to_come_total == 0:
        return None

    if kind == "finished":
        # What the order's own form will accept: cutting is done, and something that passed inspection has not shipped.
        can_record = facts.done("cutting") and not facts.done("warehouse") and facts.total("passed") > shipped_total
    else:
        can_record = not facts.done("warehouse")
    return {
        "key": f"order:{order.id}:{kind}",
        "kind": kind,
        "order": _ref(order),
        "factory": factory,
        "basis": basis,
        "expected": _counts(expected, expected_total),
        "shipped": _counts(shipped, shipped_total),
        "to_come": _counts(to_come, to_come_total),
        "due": _day(order.delivery_date),
        "late_days": lateness_days(facts, on),
        "stage": _stage(facts),
        "status_words": _status_words(facts, kind),
        "can_record": can_record,
    }


def _arrivals(facts: dict[int, Facts], open_orders: list[ProdOrder], factories: dict[str, str], on: date) -> list[dict]:
    found: list[dict] = []
    for order in open_orders:
        one = facts[order.id]
        if one.done("warehouse"):  # fully received
            continue
        factory = factories.get(order.factory_id)
        finished = _arrival(one, "finished", factory, on)
        if finished is not None:
            found.append(finished)
        # Fix pieces come back after the final inspection, when some are still at the factory.
        if one.done("final_inspection"):
            fix = _arrival(one, "fix", factory, on)
            if fix is not None:
                found.append(fix)
    # Nearest first, then by order; a fix row after the finished row of the same order.
    found.sort(key=lambda row: (row["due"], row["order"]["code"], row["kind"] == "fix"))
    return found


# ── Deliveries ────────────────────────────────────────────────────────────────


def _delivery(order: ProdOrder, delivery: Delivery) -> dict:
    row = delivery.row
    lines = {size: delivery.sizes[size] for size in SIZES if size in delivery.sizes}
    counted_on = row.counted_on
    shipped = {size: line.shipped for size, line in lines.items()}
    counted = {size: line.counted for size, line in lines.items() if counted_on is not None and line.counted is not None}

    if delivery.waiting_for_count:
        state = "waiting_for_count"
    elif delivery.mismatch:
        state = "explained" if row.mismatch_reason else "mismatch"
    else:
        state = "match"

    differing = [
        {"size": size, "shipped": line.shipped, "counted": line.counted, "difference": line.counted - line.shipped}
        for size, line in lines.items()
        if state in ("mismatch", "explained") and line.counted is not None and line.counted != line.shipped
    ]
    missing = sum(max(0, -line["difference"]) for line in differing)
    extra = sum(max(0, line["difference"]) for line in differing)
    differs = state in ("mismatch", "explained")
    return {
        "id": row.id,
        "order": _ref(order),
        "number": row.number,
        "kind": row.kind,
        "shipped_on": _day(row.shipped_on),
        "counted_on": _day(counted_on),
        "shipped": shipped,
        "shipped_total": sum(shipped.values()),
        "counted": counted,
        "counted_total": sum(counted.values()) if counted_on is not None else None,
        "state": state,
        #: Counted minus shipped, signed; the sizes that differ; the two halves of it. Only when they differ.
        "difference": extra - missing if differs else None,
        "missing": missing,
        "extra": extra,
        "sizes_differ": differing,
        "reason": row.mismatch_reason if state == "explained" else None,
    }


def _waiting_pieces(delivery: Delivery) -> int:
    """Pieces shipped that Khazenly has not counted: all of them before the count date,
    else the sizes added to the shipped numbers after the count was typed."""
    if delivery.row.counted_on is None:
        return delivery.shipped
    return sum(line.shipped for line in delivery.sizes.values() if line.counted is None)


def _deliveries(
    facts: dict[int, Facts], orders: list[ProdOrder], on: date
) -> tuple[list[dict], int]:
    """Every delivery of an open order, and a closed order's counted in the last
    30 days; newest first. Also the pieces waiting for a count."""
    cutoff = on - timedelta(days=RECENT_DAYS)
    found: list[dict] = []
    waiting = 0
    for order in orders:
        for delivery in facts[order.id].deliveries:
            if order.status == "closed" and not (delivery.row.counted_on and delivery.row.counted_on >= cutoff):
                continue
            found.append(_delivery(order, delivery))
            waiting += _waiting_pieces(delivery)
    found.sort(key=lambda row: (row["shipped_on"], row["order"]["code"], row["number"]), reverse=True)
    return found, waiting


# ── The screen ────────────────────────────────────────────────────────────────


def listing(db: Session) -> dict:
    """What is still to arrive, the deliveries, and the four figures at the top.

    An order that is cancelled is never here. An order that is closed has no
    arrivals; its deliveries stay for 30 days after they were counted."""
    on = today()
    open_orders = list(db.scalars(select(ProdOrder).where(ProdOrder.status == "open").order_by(ProdOrder.id)))
    closed_orders = list(
        db.scalars(
            select(ProdOrder)
            .where(
                ProdOrder.status == "closed",
                ProdOrder.id.in_(
                    select(ProdDelivery.order_id).where(ProdDelivery.counted_on >= on - timedelta(days=RECENT_DAYS))
                ),
            )
            .order_by(ProdOrder.id)
        )
    )
    orders = open_orders + closed_orders
    facts = _facts_for(db, orders)
    factories = _suppliers(db, [order.factory_id for order in open_orders])

    arrivals = _arrivals(facts, open_orders, factories, on)
    deliveries, waiting = _deliveries(facts, orders, on)

    this_first = on.replace(day=1)
    next_first = _first_of_next_month(on)
    after_next = _first_of_next_month(next_first)
    # Overdue arrivals (due before this month) are this month's: they are the ones to chase now.
    this_month = sum(row["to_come"]["total"] for row in arrivals if date.fromisoformat(row["due"]) < next_first)
    next_month = sum(
        row["to_come"]["total"] for row in arrivals if next_first <= date.fromisoformat(row["due"]) < after_next
    )
    totals = {
        "to_come_total": sum(row["to_come"]["total"] for row in arrivals),
        "this_month": _month(this_first, this_month),
        "next_month": _month(next_first, next_month),
        "waiting_for_count": waiting,
        "mismatch_pieces": sum(row["missing"] + row["extra"] for row in deliveries if row["state"] == "mismatch"),
    }
    return {"today": on.isoformat(), "totals": totals, "arrivals": arrivals, "deliveries": deliveries}
