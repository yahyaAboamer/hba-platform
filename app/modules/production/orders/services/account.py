"""The supplier's account: the low-level pieces (ADR 0084, decisions 8 and 9;
build plan ``docs/plans/2026-11-14-production-suppliers-build.md``).

**Money is integer piastres** (ADR 0002). ``prod_supplier_entry`` is
append-only: a line is added here and never changed or deleted (a database
trigger refuses both); a mistake is undone by a reversing line, written in
``suppliers``.

This module imports no other service, so ``orders.settle`` can write the work
line from here and ``orders.generated_tasks`` and ``orders.view`` can read the
purchases, without a circle. The rules (what may be bought, paid, reversed)
are in ``suppliers``.

**Locking.** Anything that changes a supplier's account takes the supplier's
row ``FOR UPDATE`` (``lock_supplier``) before it reads a balance. Whenever a
write involves a known order, **the order is locked first and the supplier
second**, always, so two writers cannot wait on each other.
"""

from datetime import date

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.modules.production.models import ProductionSupplier
from app.modules.production.orders.models import (
    ProdOrder,
    ProdPurchase,
    ProdSupplierEntry,
)


def lock_supplier(db: Session, supplier_id: str) -> ProductionSupplier | None:
    """The supplier's row, locked ``FOR UPDATE`` until the transaction ends
    (and read afresh, whatever the session had cached)."""
    return db.get(ProductionSupplier, supplier_id, with_for_update=True, populate_existing=True)


def append(
    db: Session,
    *,
    supplier_id: str,
    kind: str,
    amount: int,
    happened_on: date,
    actor_id: int | None,
    order_id: int | None = None,
    purchase_id: int | None = None,
    method: str | None = None,
    payment_kind: str | None = None,
    note: str | None = None,
    reverses_id: int | None = None,
) -> ProdSupplierEntry:
    """Stage one line of the account. ``amount`` is signed: positive means HBA
    owes more. The caller holds the supplier's lock."""
    if not isinstance(amount, int) or isinstance(amount, bool) or amount == 0:
        raise ValueError("An account line is a whole number of piastres, and never 0.")
    entry = ProdSupplierEntry(
        supplier_id=supplier_id, kind=kind, amount_piastres=amount, happened_on=happened_on,
        order_id=order_id, purchase_id=purchase_id, method=method, payment_kind=payment_kind,
        note=note, reverses_id=reverses_id, created_by=actor_id,
    )
    db.add(entry)
    db.flush()
    return entry


def ledger_sums(db: Session, supplier_ids: list[str]) -> dict[str, int]:
    """What each supplier's lines add up to (HBA owes this much, before any
    order not yet settled)."""
    if not supplier_ids:
        return {}
    found = dict(
        db.execute(
            select(ProdSupplierEntry.supplier_id, func.coalesce(func.sum(ProdSupplierEntry.amount_piastres), 0))
            .where(ProdSupplierEntry.supplier_id.in_(supplier_ids))
            .group_by(ProdSupplierEntry.supplier_id)
        ).all()
    )
    return {sid: int(found.get(sid, 0)) for sid in supplier_ids}


# ── Purchases that are tasks ──────────────────────────────────────────────────


def purchase_tasks(db: Session, on: date) -> list[dict]:
    """The two tasks a live purchase can make (build plan, rule 8): worked out
    on each read, never stored. One expected before ``on`` and not received is
    chased (the supplier is who it waits on); one expected ``on`` or later and
    not received is checked on arrival (the QC manager's). **Titles carry no
    money.**"""
    since = (
        select(func.min(ProdSupplierEntry.happened_on))
        .where(
            ProdSupplierEntry.purchase_id == ProdPurchase.id,
            ProdSupplierEntry.kind == "purchase",
            ProdSupplierEntry.reverses_id.is_(None),
        )
        .scalar_subquery()
    )
    rows = db.execute(
        select(ProdPurchase, ProductionSupplier.name, ProdOrder, since)
        .join(ProductionSupplier, ProductionSupplier.id == ProdPurchase.supplier_id)
        .outerjoin(ProdOrder, ProdOrder.id == ProdPurchase.order_id)
        .where(
            ProdPurchase.voided_at.is_(None),
            ProdPurchase.received_on.is_(None),
            ProdPurchase.expected_on.is_not(None),
            # A purchase for an order that was cancelled is nothing to chase or check.
            or_(ProdOrder.id.is_(None), ProdOrder.status != "cancelled"),
        )
        .order_by(ProdPurchase.expected_on, ProdPurchase.id)
    ).all()
    found: list[dict] = []
    for purchase, supplier_name, order, bought_on in rows:
        late = purchase.expected_on < on
        found.append(
            {
                "key": f"purchase:{purchase.id}:{'chase' if late else 'arrival'}",
                "title": f"Chase the {purchase.item} delivery" if late else f"Check {purchase.item} on arrival",
                "who": "factory" if late else "qc",
                "due": purchase.expected_on.isoformat(),
                "order": None
                if order is None
                else {"id": order.id, "code": order.code, "style_name": order.style_name, "colour": order.colour},
                "stage": None,
                "waiting_on": supplier_name if late else None,
                "since": bought_on.isoformat() if bought_on else None,
                "open": f"purchase:{purchase.id}",
                "supplier": {"id": purchase.supplier_id, "name": supplier_name},
            }
        )
    return found


# ── Cost from purchases (the order's cost card) ───────────────────────────────

#: The order's cost parts a purchase's part can stand for. ``other`` stands for none.
FROM_PURCHASE_PARTS = {
    "fabric": "Fabric",
    "printing": "Printing",
    "accessories": "Accessories",
    "packaging": "Special packaging",
}


def per_piece(total: int, pieces: int) -> int | None:
    """``total`` over ``pieces``, rounded half up to a whole piastre, in whole
    numbers only."""
    if pieces <= 0:
        return None
    return (2 * total + pieces) // (2 * pieces)


def from_purchases(db: Session, order_id: int, pieces: int, basis: str) -> dict:
    """What the live (unvoided) purchases tied to an order say each part costs
    per piece: their total over ``pieces``, which is the pieces cut once
    cutting is done, else the pieces planned (``basis``). It never changes the
    order's own typed costs: the owner chooses to use a figure. **Owner only.**"""
    rows = db.execute(
        select(ProdPurchase, ProductionSupplier.name)
        .join(ProductionSupplier, ProductionSupplier.id == ProdPurchase.supplier_id)
        .where(ProdPurchase.order_id == order_id, ProdPurchase.voided_at.is_(None))
        .order_by(ProdPurchase.id)
    ).all()

    def bought(purchase: ProdPurchase, supplier_name: str) -> dict:
        return {
            "id": purchase.id,
            "item": purchase.item,
            "supplier": {"id": purchase.supplier_id, "name": supplier_name},
            "total_piastres": purchase.total_piastres,
        }

    parts = []
    for part, label in FROM_PURCHASE_PARTS.items():
        behind = [bought(p, name) for p, name in rows if p.cost_part == part]
        total = sum(item["total_piastres"] for item in behind)
        parts.append(
            {
                "part": part,
                "label": label,
                "purchases": behind,
                "total_piastres": total,
                "per_piece_piastres": per_piece(total, pieces) if behind else None,
            }
        )
    other = [bought(p, name) for p, name in rows if p.cost_part == "other"]
    return {
        "pieces": pieces,
        "basis": basis,
        "parts": parts,
        "other": {"purchases": other, "total_piastres": sum(item["total_piastres"] for item in other)},
    }
