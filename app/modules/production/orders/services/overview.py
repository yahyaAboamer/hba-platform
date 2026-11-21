"""Production's Overview (ADR 0084, decision 11; build plan
``docs/plans/2026-11-15-production-overview-build.md``).

One page that reads what the four batches before it already work out: the
open orders and their next actions (``orders``), the tasks (``tasks``), the
arrivals (``incoming``) and what is owed (``suppliers``). **Nothing here is a
rule of its own, nothing is written, and there is no table**: it is worked out
on each read, for "today" in Cairo.

**Money is the owner's alone.** Without it (``with_money=False``) the response
has no ``owed`` and no ``figures.owed_piastres`` (absent, not null), the
``cost_over`` problems are not built at all, and so no key ends ``_piastres``
and no string says "EGP". The money of a ``cost_over`` problem sits in its
title, which is why the whole item is left out for everybody else.
"""

from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.modules.production.models import ProductionSupplier
from app.modules.production.orders.models import (
    STAGE_LABELS,
    ProdOrder,
    ProdOrderDateChange,
    ProdPurchase,
    ProdSupplierEntry,
)
from app.modules.production.orders.services import incoming, orders, suppliers, tasks

#: How many arrivals the page lists: the nearest ones.
ARRIVING = 5


# ── Small helpers ─────────────────────────────────────────────────────────────


def _short(day: date) -> str:
    """A day as the page says it: 20 Nov."""
    return f"{day.day} {day.strftime('%b')}"


def _egp(piastres: int) -> str:
    """Piastres as pounds, in words: EGP 1,200, or EGP 1,200.50 when there are piastres."""
    pounds, rest = divmod(piastres, 100)
    return f"EGP {pounds:,}" if rest == 0 else f"EGP {pounds:,}.{rest:02d}"


def _ref(order: ProdOrder) -> dict:
    return {"id": order.id, "code": order.code, "style_name": order.style_name, "colour": order.colour}


def _decision(task: dict) -> dict:
    return {
        "kind": task["kind"],
        "key": task["key"],
        "id": task.get("id"),
        "title": task["title"],
        "order": task["order"],
        "due": task["due"],
        "since": task["since"],
        "open": task["open"],
        "overdue_days": task["overdue_days"],
    }


def _problem(kind: str, title: str, detail: str, link: dict) -> dict:
    return {"kind": kind, "title": title, "detail": detail, "link": link}


# ── Problems ──────────────────────────────────────────────────────────────────


def _last_date_moves(db: Session, order_ids: list[int]) -> dict[int, ProdOrderDateChange]:
    """The latest move of each order's delivery date (the first line, the target as planned, is no move)."""
    if not order_ids:
        return {}
    found: dict[int, ProdOrderDateChange] = {}
    for change in db.scalars(
        select(ProdOrderDateChange)
        .where(ProdOrderDateChange.order_id.in_(order_ids))
        .order_by(ProdOrderDateChange.created_at, ProdOrderDateChange.id)
    ):
        found[change.order_id] = change
    return {order_id: change for order_id, change in found.items() if change.old_date is not None}


def _late_orders(db: Session, rows: list[dict]) -> list[dict]:
    late = sorted((row for row in rows if row["lateness_days"] > 0), key=lambda row: (-row["lateness_days"], row["code"]))
    moves = _last_date_moves(db, [row["id"] for row in late])
    found = []
    for row in late:
        move = moves.get(row["id"])
        if move is not None:
            who = "Factory" if move.set_by == "factory" else "Owner"
            detail = f"{who} moved {_short(move.old_date)} to {_short(move.new_date)} · {move.reason}"
        else:
            detail = f"At {row['stage']['label']}" if row["stage"] else "In production"
        found.append(
            _problem(
                "late_order",
                f"{row['style_name']} · {row['colour']} is {orders._plural(row['lateness_days'], 'day')} late",
                detail,
                {"to": "order", "id": row["id"]},
            )
        )
    return found


def _late_materials(db: Session, chasing: list[dict], rows: dict[int, dict]) -> list[dict]:
    """Purchases expected before today and not received: the tasks the Tasks list calls "chase"."""
    if not chasing:
        return []
    ids = [int(task["key"].split(":")[1]) for task in chasing]
    items = dict(db.execute(select(ProdPurchase.id, ProdPurchase.item).where(ProdPurchase.id.in_(ids))).all())
    found = []
    for task, purchase_id in zip(chasing, ids):
        item = items.get(purchase_id, "Materials")
        supplier = task["supplier"]["name"]
        days = orders._plural(task["overdue_days"], "day")
        order = task["order"]
        if order is None:
            title, detail = f"{item} from {supplier} are {days} late", supplier
        else:
            title = f"{item} for {order['style_name']} are {days} late"
            stage = (rows.get(order["id"]) or {}).get("stage")
            detail = f"{supplier} · order at {stage['label']}" if stage else supplier
        found.append(_problem("late_material", title, detail, {"to": "tasks"}))
    return found


def _count_mismatches(facts: dict[int, orders.Facts], open_orders: list[ProdOrder]) -> list[dict]:
    """Deliveries whose two counts differ with no reason given yet."""
    found = []
    for order in open_orders:
        for delivery in facts[order.id].deliveries:
            if not delivery.needs_reason:
                continue
            counted = [line for line in delivery.sizes.values() if line.counted is not None]
            short = sum(max(0, line.shipped - line.counted) for line in counted)
            extra = sum(max(0, line.counted - line.shipped) for line in counted)
            title = (
                f"{orders._plural(short, 'piece')} missing between factory and Khazenly"
                if short
                else f"{extra:,} more counted than shipped"
            )
            found.append(
                _problem(
                    "count_mismatch",
                    title,
                    f"{order.style_name} · {order.colour} · no reason given yet",
                    {"to": "order", "id": order.id, "open": f"delivery-reason:{delivery.row.id}"},
                )
            )
    return found


def _costs_over(open_orders: list[ProdOrder]) -> list[dict]:
    """Owner only: open orders whose actual cost per piece is above the target."""
    over = []
    for order in open_orders:
        figures = orders.cost(order)
        actual, target = figures["actual_total_piastres"], figures["target_total_piastres"]
        if actual is None or actual <= target:
            continue
        parts = [
            part["label"]
            for part in figures["parts"]
            if part["actual_piastres"] is not None and part["actual_piastres"] > part["target_piastres"]
        ]
        over.append((actual - target, order, actual, target, parts))
    over.sort(key=lambda item: (-item[0], item[1].code))
    return [
        _problem(
            "cost_over",
            f"{order.style_name} · {order.colour} costs {_egp(by)} more per piece than planned",
            f"{_egp(actual)} actual against {_egp(target)} target · {orders._words(parts)} over target",
            {"to": "order", "id": order.id},
        )
        for by, order, actual, target, parts in over
    ]


# ── What is owed (owner only) ─────────────────────────────────────────────────


def _owed(db: Session) -> list[dict]:
    """Every supplier HBA owes something, largest first. An overpaid supplier is left out here
    and never subtracted from what is owed to the others."""
    suppliers_ = list(
        db.execute(
            select(ProductionSupplier.id, ProductionSupplier.name).where(ProductionSupplier.deleted_at.is_(None))
        ).all()
    )
    ids = [sid for sid, _ in suppliers_]
    standing = suppliers.standings(db, ids)
    names = dict(suppliers_)
    owing = {sid: standing[sid].owed for sid in ids if standing[sid].owed > 0}
    if not owing:
        return []

    wanted = list(owing)
    reversed_ids = select(ProdSupplierEntry.reverses_id).where(ProdSupplierEntry.reverses_id.is_not(None))
    live = (
        ProdSupplierEntry.supplier_id.in_(wanted),
        ProdSupplierEntry.reverses_id.is_(None),
        ProdSupplierEntry.id.not_in(reversed_ids),
    )
    # A payment tied to a purchase is its deposit; a payment tied to none is
    # a lump sum (the weekly payment), which pays the balance, not a purchase.
    deposits: dict[int, int] = {}
    last_paid: dict[str, date] = {}
    last_lump: dict[str, date] = {}
    for supplier_id, purchase_id, amount, latest in db.execute(
        select(
            ProdSupplierEntry.supplier_id,
            ProdSupplierEntry.purchase_id,
            func.sum(-ProdSupplierEntry.amount_piastres),
            func.max(ProdSupplierEntry.happened_on),
        )
        .where(ProdSupplierEntry.kind == "payment", *live)
        .group_by(ProdSupplierEntry.supplier_id, ProdSupplierEntry.purchase_id)
    ):
        if purchase_id is not None:
            deposits[purchase_id] = int(amount)
        elif supplier_id not in last_lump or latest > last_lump[supplier_id]:
            last_lump[supplier_id] = latest
        if supplier_id not in last_paid or latest > last_paid[supplier_id]:
            last_paid[supplier_id] = latest

    # A purchase is named only when it is certainly not paid off: bought after
    # the last lump sum, and its own deposit short of its total. An older one
    # may have been paid by a lump sum, which cannot be told apart.
    open_items: dict[str, list[str]] = {sid: [] for sid in wanted}
    for purchase, bought_on in db.execute(
        select(ProdPurchase, ProdSupplierEntry.happened_on)
        .join(ProdSupplierEntry, ProdSupplierEntry.purchase_id == ProdPurchase.id)
        .where(ProdPurchase.voided_at.is_(None), ProdSupplierEntry.kind == "purchase", *live)
        .order_by(ProdSupplierEntry.happened_on, ProdPurchase.id)
    ):
        lump = last_lump.get(purchase.supplier_id)
        if (lump is None or bought_on > lump) and deposits.get(purchase.id, 0) < purchase.total_piastres:
            open_items[purchase.supplier_id].append(purchase.item)

    def detail(supplier_id: str) -> str | None:
        items = open_items[supplier_id]
        if len(items) == 1:
            return f"Rest of the {items[0]} purchase"
        if len(items) == 2:
            return f"Rest of the {items[0]} and {items[1]} purchases"
        if items:
            return f"Rest of the {items[0]} purchase and {len(items) - 1} more"
        if supplier_id in last_paid:
            return f"Last paid {_short(last_paid[supplier_id])}"
        return None

    return [
        {
            "supplier": {"id": sid, "name": names[sid]},
            "owed_piastres": amount,
            "detail": detail(sid),
        }
        for sid, amount in sorted(owing.items(), key=lambda item: (-item[1], names[item[0]].lower(), item[0]))
    ]


# ── The page ──────────────────────────────────────────────────────────────────


def overview(db: Session, *, with_money: bool) -> dict:
    on = orders.today()
    open_orders = list(
        db.scalars(select(ProdOrder).where(ProdOrder.status == "open").order_by(ProdOrder.delivery_date, ProdOrder.id))
    )
    facts = orders._facts_for(db, open_orders)
    factories, images = orders.row_context(db, open_orders)
    rows = [orders._row(facts[order.id], factories, on, images) for order in open_orders]
    by_order = {row["id"]: row for row in rows}

    listed = tasks.listing(db)["tasks"]
    decisions = [_decision(task) for task in listed if task["who"] == "owner"]
    chasing = [task for task in listed if task["key"].endswith(":chase")]

    problems = (
        _late_orders(db, rows)
        + _late_materials(db, chasing, by_order)
        + _count_mismatches(facts, open_orders)
    )
    if with_money:
        problems += _costs_over(open_orders)

    totals = incoming.listing(db)
    this_month = totals["totals"]["this_month"]
    figures = {
        "decisions": len(decisions),
        "late_orders": sum(1 for row in rows if row["lateness_days"] > 0),
        "open_orders": len(rows),
        "arriving_this_month": {
            "month": this_month["month"],
            "label": this_month["label"],
            "pieces": this_month["pieces"],
        },
    }
    body = {
        "today": on.isoformat(),
        "summary": {"open_orders": len(rows), "planned_pieces": sum(row["planned_total"] for row in rows)},
        "figures": figures,
        "decisions": decisions,
        "problems": problems,
        "orders": rows,
        "arriving": totals["arrivals"][:ARRIVING],
    }
    if with_money:
        owed = _owed(db)
        figures["owed_piastres"] = sum(item["owed_piastres"] for item in owed)
        body["owed"] = owed
    return body
