"""Fabric storage (ADR 0089).

A fabric (``prod_fabric``) is a named roll type. **Its stock is never a stored
figure**: it is the sum of its movements (``prod_fabric_move``), kilos to three
decimals, signed: ``purchase`` in (a purchase in kg of the fabric part),
``use`` out (an order took it), ``return`` in (undoing one use, once),
``count`` either way (a correction, with a reason), ``void`` out (undoing a
purchase). Storage never goes below zero: taking more than it holds, counting
below zero and voiding a purchase whose kilos are already used are refused.

Kilos travel as a fixed three-decimal string (``"12.500"``, ``kg_text``);
refusals say them as a person would (``12.5``).

**The price per kg is money**, ``production.owner``'s alone: the average of a
fabric's live purchases (their totals over their kilos), added to a view only
when asked ``with_money=True``. The history never carries a price.

Lock order, as in the rest of Production: an order first, then a supplier,
then the fabric rows (by id). Every write here only stages; the route commits
on success and rolls back on a refusal.
"""

from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.core.businesstime import utcnow
from app.modules.production.models import ProductionSupplier
from app.modules.production.orders.models import ProdFabric, ProdFabricMove, ProdOrder, ProdPurchase
from app.modules.production.orders.services import account
from app.modules.production.orders.services.orders import (
    Locked,
    NotFound,
    Refused,
    _audit as _order_audit,
    _iso,
    _order,
    _people,
    _suppliers,
    _text,
)
from app.shared.models.identity import UserAccount
from app.shared.services.audit import record_audit

__all__ = [
    "add_fabric",
    "choices",
    "count",
    "detail",
    "edit_fabric",
    "give_back",
    "in_stock",
    "kg_text",
    "listing",
    "price_per_kg",
    "take",
]

KG_PLACES = Decimal("0.001")
#: The most kilos one movement may be: a guard against a slipped zero.
MAX_KG = Decimal("1000000")
#: The most fabric lines a New order may take from storage.
MAX_LINES = 10
#: Two saves of fabrics with the same name queue on this, so neither fails on
#: the unique index.
_NAME_LOCK = 840_004
NUMBER = "Give the kilos as a number, like 12.5."


# ── Small helpers ─────────────────────────────────────────────────────────────


def kg_text(kg: Decimal | None) -> str:
    """Kilos as the API carries them: always three decimals, ``"12.500"``."""
    value = Decimal(kg or 0)
    if value == 0:
        value = Decimal(0)
    return f"{value.quantize(KG_PLACES)}"


def said(kg: Decimal) -> str:
    """Kilos as a sentence says them: ``12.5``, never ``12.500``."""
    value = Decimal(kg).quantize(KG_PLACES)
    if value == 0:
        return "0"
    return format(value.normalize(), "f")


def _kg(value, *, zero_ok: bool = False) -> Decimal:
    if value is None or isinstance(value, bool):
        raise Refused(NUMBER)
    try:
        kg = value if isinstance(value, Decimal) else Decimal(str(value).strip())
    except (InvalidOperation, ValueError):
        raise Refused(NUMBER) from None
    if not kg.is_finite():
        raise Refused(NUMBER)
    if kg < 0 or (kg == 0 and not zero_ok):
        raise Refused("The kilos can't be below 0." if zero_ok else "The kilos must be more than 0.")
    if kg > MAX_KG:
        raise Refused("That is too many kilos. Check the number.")
    if kg != kg.quantize(KG_PLACES):
        raise Refused(NUMBER)
    return kg


def _note(value, *, limit: int = 2000) -> str | None:
    if value is None:
        return None
    cleaned = str(value).replace("\r\n", "\n").strip()
    if not cleaned:
        return None
    if len(cleaned) > limit:
        raise Refused(f"Keep the note to {limit:,} characters.")
    return cleaned


def _subject(fabric: ProdFabric) -> str:
    return f"production:fabric:{fabric.id}"


def _audit(db: Session, fabric: ProdFabric, actor: UserAccount, what: str, summary: str, **extra) -> None:
    """One history entry for the fabric. **Never a price.**"""
    record_audit(
        db,
        action=f"production.fabric_{what}",
        subject=_subject(fabric),
        actor_id=actor.id,
        actor_email=actor.email,
        after={"summary": summary[:500], "fabric": fabric.name, **extra},
    )


def _fabric(db: Session, fabric_id: int, *, for_update: bool = False) -> ProdFabric:
    fabric = db.get(ProdFabric, fabric_id, with_for_update=for_update or None, populate_existing=for_update)
    if fabric is None:
        raise NotFound("There is no such fabric.")
    return fabric


def _returned_ids():
    return select(ProdFabricMove.returns_id).where(ProdFabricMove.returns_id.is_not(None))


def _live_uses(db: Session, order_id: int) -> list[ProdFabricMove]:
    """The fabric an order took and has not given back, oldest first."""
    return list(
        db.scalars(
            select(ProdFabricMove)
            .where(
                ProdFabricMove.order_id == order_id,
                ProdFabricMove.kind == "use",
                ProdFabricMove.id.not_in(_returned_ids()),
            )
            .order_by(ProdFabricMove.id)
        )
    )


# ── Reading ───────────────────────────────────────────────────────────────────


def in_stock(db: Session, fabric_ids) -> dict[int, Decimal]:
    """What each fabric holds: the sum of its moves (0 with none)."""
    ids = list({i for i in fabric_ids if i})
    found = {i: Decimal(0) for i in ids}
    if ids:
        for fabric_id, kg in db.execute(
            select(ProdFabricMove.fabric_id, func.sum(ProdFabricMove.kg))
            .where(ProdFabricMove.fabric_id.in_(ids))
            .group_by(ProdFabricMove.fabric_id)
        ).all():
            found[fabric_id] = Decimal(kg or 0)
    return found


def price_per_kg(db: Session, fabric_ids) -> dict[int, int | None]:
    """The average price per kg of each fabric's live purchases: their totals
    over their kilos, rounded half up to a piastre; ``None`` with none. **Money.**"""
    ids = list({i for i in fabric_ids if i})
    found: dict[int, int | None] = {i: None for i in ids}
    if ids:
        for fabric_id, total, kg in db.execute(
            select(ProdFabricMove.fabric_id, func.sum(ProdPurchase.total_piastres), func.sum(ProdFabricMove.kg))
            .join(ProdPurchase, ProdPurchase.id == ProdFabricMove.purchase_id)
            .where(
                ProdFabricMove.fabric_id.in_(ids),
                ProdFabricMove.kind == "purchase",
                ProdPurchase.voided_at.is_(None),
            )
            .group_by(ProdFabricMove.fabric_id)
        ).all():
            if kg and kg > 0:
                found[fabric_id] = int((Decimal(total) / Decimal(kg)).quantize(Decimal(1), rounding=ROUND_HALF_UP))
    return found


def _sums(db: Session, ids: list[int], kinds: tuple[str, ...]) -> dict[int, Decimal]:
    if not ids:
        return {}
    return {
        fabric_id: Decimal(kg or 0)
        for fabric_id, kg in db.execute(
            select(ProdFabricMove.fabric_id, func.sum(ProdFabricMove.kg))
            .where(ProdFabricMove.fabric_id.in_(ids), ProdFabricMove.kind.in_(kinds))
            .group_by(ProdFabricMove.fabric_id)
        ).all()
    }


def _open_orders(db: Session, ids: list[int]) -> dict[int, int]:
    """How many open orders hold a live use of each fabric."""
    if not ids:
        return {}
    return dict(
        db.execute(
            select(ProdFabricMove.fabric_id, func.count(func.distinct(ProdFabricMove.order_id)))
            .join(ProdOrder, ProdOrder.id == ProdFabricMove.order_id)
            .where(
                ProdFabricMove.fabric_id.in_(ids),
                ProdFabricMove.kind == "use",
                ProdFabricMove.id.not_in(_returned_ids()),
                ProdOrder.status == "open",
            )
            .group_by(ProdFabricMove.fabric_id)
        ).all()
    )


def _rows(db: Session, fabrics: list[ProdFabric], *, with_money: bool) -> list[dict]:
    ids = [f.id for f in fabrics]
    stock = in_stock(db, ids)
    bought = _sums(db, ids, ("purchase", "void"))
    used = _sums(db, ids, ("use", "return"))
    orders = _open_orders(db, ids)
    names = _suppliers(db, [f.supplier_id for f in fabrics])
    prices = price_per_kg(db, ids) if with_money else {}
    rows = []
    for f in fabrics:
        row = {
            "id": f.id,
            "name": f.name,
            "fabric_type": f.fabric_type,
            "colour": f.colour,
            "colour_code": f.colour_code,
            "supplier": None if f.supplier_id is None else {"id": f.supplier_id, "name": names.get(f.supplier_id)},
            "active": f.active,
            "in_stock_kg": kg_text(stock.get(f.id)),
            "bought_kg": kg_text(bought.get(f.id)),
            "used_kg": kg_text(-used.get(f.id, Decimal(0))),
            "orders": int(orders.get(f.id, 0)),
        }
        if with_money:
            row["price_per_kg_piastres"] = prices.get(f.id)
        rows.append(row)
    return rows


def listing(db: Session, *, with_money: bool) -> dict:
    """Every fabric, the active ones first, then by name."""
    fabrics = list(
        db.scalars(select(ProdFabric).order_by(ProdFabric.active.desc(), func.lower(ProdFabric.name), ProdFabric.id))
    )
    return {"fabrics": _rows(db, fabrics, with_money=with_money)}


def detail(db: Session, fabric_id: int, *, with_money: bool) -> dict:
    """One fabric and every move of it, newest first."""
    fabric = _fabric(db, fabric_id)
    row = _rows(db, [fabric], with_money=with_money)[0]
    row["note"] = fabric.note
    moves = list(
        db.scalars(
            select(ProdFabricMove)
            .where(ProdFabricMove.fabric_id == fabric.id)
            .order_by(ProdFabricMove.created_at.desc(), ProdFabricMove.id.desc())
        )
    )
    purchases = {
        p.id: p
        for p in db.scalars(select(ProdPurchase).where(ProdPurchase.id.in_({m.purchase_id for m in moves if m.purchase_id})))
    } if any(m.purchase_id for m in moves) else {}
    codes = dict(
        db.execute(select(ProdOrder.id, ProdOrder.code).where(ProdOrder.id.in_({m.order_id for m in moves if m.order_id}))).all()
    ) if any(m.order_id for m in moves) else {}
    names = _suppliers(db, [p.supplier_id for p in purchases.values()])
    returned = {m.returns_id for m in moves if m.returns_id is not None}
    people = _people(db, [m.created_by for m in moves])

    def purchase(move: ProdFabricMove) -> dict | None:
        p = purchases.get(move.purchase_id)
        if p is None:
            return None
        return {"id": p.id, "item": p.item, "supplier": {"id": p.supplier_id, "name": names.get(p.supplier_id)}}

    return {
        "fabric": row,
        "moves": [
            {
                "id": m.id,
                "kind": m.kind,
                "kg": kg_text(m.kg),
                "created_at": _iso(m.created_at),
                "by": people.get(m.created_by),
                "note": m.note,
                "purchase": purchase(m),
                "order": None if m.order_id is None else {"id": m.order_id, "code": codes.get(m.order_id)},
                "returned": m.kind == "use" and m.id in returned,
            }
            for m in moves
        ],
    }


def choices(db: Session) -> list[dict]:
    """The active fabrics for the New order form, with what each holds. No money."""
    fabrics = list(
        db.scalars(select(ProdFabric).where(ProdFabric.active.is_(True)).order_by(func.lower(ProdFabric.name), ProdFabric.id))
    )
    stock = in_stock(db, [f.id for f in fabrics])
    return [{"id": f.id, "name": f.name, "colour": f.colour, "in_stock_kg": kg_text(stock.get(f.id))} for f in fabrics]


# ── Fabrics: adding, editing, counting ────────────────────────────────────────


def _name(db: Session, value, *, keep: int | None = None) -> str:
    name = _text(value, limit=120, what="the fabric's name", required=True)
    db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": _NAME_LOCK})
    query = select(ProdFabric.id).where(func.lower(ProdFabric.name) == name.lower())
    if keep is not None:
        query = query.where(ProdFabric.id != keep)
    if db.scalar(query.limit(1)) is not None:
        raise Refused(f"There is already a fabric called {name}.")
    return name


def _supplier_id(db: Session, value) -> str | None:
    value = (value or "").strip() if isinstance(value, str) else value
    if not value:
        return None
    supplier = db.get(ProductionSupplier, value)
    if supplier is None or supplier.deleted_at is not None:
        raise Refused("Choose the supplier from the list.")
    return supplier.id


#: The words each detail of a fabric is told in, with how long it may be.
_DETAILS = {
    "fabric_type": (400, "fabric type"),
    "colour": (80, "colour"),
    "colour_code": (200, "colour code"),
}
_WORDS = {"name": "name", **{key: words for key, (_l, words) in _DETAILS.items()}, "supplier_id": "supplier", "note": "note"}


def new_fabric(db: Session, data: dict, actor: UserAccount, *, supplier_id: str | None = None) -> ProdFabric:
    """Stage a new fabric (no move). ``supplier_id`` overrides what the data says."""
    fabric = ProdFabric(
        name=_name(db, data.get("name")),
        fabric_type=_text(data.get("fabric_type"), limit=400, what="the fabric type"),
        colour=_text(data.get("colour"), limit=80, what="the colour"),
        colour_code=_text(data.get("colour_code"), limit=200, what="the colour code"),
        supplier_id=supplier_id if supplier_id is not None else _supplier_id(db, data.get("supplier_id")),
        note=_note(data.get("note")),
        active=True,
        created_by=actor.id,
    )
    db.add(fabric)
    db.flush()
    return fabric


def add_fabric(db: Session, data: dict, actor: UserAccount) -> ProdFabric:
    """A new fabric; with ``in_storage_kg`` above 0, what is already in
    storage is recorded as a ``count``."""
    kg = None
    if data.get("in_storage_kg") is not None:
        kg = _kg(data["in_storage_kg"])
    fabric = new_fabric(db, data, actor)
    _audit(db, fabric, actor, "added", f"Added {fabric.name} to fabric storage")
    if kg is not None:
        db.add(
            ProdFabricMove(
                fabric_id=fabric.id, kind="count", kg=kg, note="Already in storage when added", created_by=actor.id
            )
        )
        db.flush()
        _audit(db, fabric, actor, "counted", f"Counted {said(kg)} kg of {fabric.name} already in storage", kg=kg_text(kg))
    return fabric


def edit_fabric(db: Session, fabric_id: int, data: dict, actor: UserAccount) -> ProdFabric:
    fabric = _fabric(db, fabric_id, for_update=True)
    changed: list[str] = []

    def put(column: str, value) -> None:
        if getattr(fabric, column) != value:
            setattr(fabric, column, value)
            changed.append(_WORDS[column])

    if "name" in data:
        name = _text(data["name"], limit=120, what="the fabric's name", required=True)
        if name != fabric.name:
            put("name", _name(db, name, keep=fabric.id))
    for column, (limit, words) in _DETAILS.items():
        if column in data:
            put(column, _text(data[column], limit=limit, what=f"the {words}"))
    if "supplier_id" in data:
        put("supplier_id", _supplier_id(db, data["supplier_id"]))
    if "note" in data:
        put("note", _note(data["note"]))
    retired = None
    if "active" in data and data["active"] is not None and bool(data["active"]) != fabric.active:
        fabric.active = bool(data["active"])
        retired = not fabric.active
    if not changed and retired is None:
        return fabric
    fabric.updated_at = utcnow()
    db.flush()
    if changed:
        _audit(db, fabric, actor, "edited", f"Changed the {_join(changed)} of {fabric.name}", changed=changed)
    if retired is not None:
        _audit(
            db, fabric, actor, "retired" if retired else "restored",
            f"{'Stopped keeping' if retired else 'Started keeping'} {fabric.name} in storage",
        )
    return fabric


def _join(parts: list[str]) -> str:
    return parts[0] if len(parts) == 1 else ", ".join(parts[:-1]) + " and " + parts[-1]


def count(db: Session, fabric_id: int, kg_in_storage, note, actor: UserAccount) -> ProdFabric:
    """Storage counted: one ``count`` move of the difference, with why."""
    fabric = _fabric(db, fabric_id, for_update=True)
    counted = _kg(kg_in_storage, zero_ok=True)
    why = _text(note, limit=500, what="the reason for the count", required=True)
    current = in_stock(db, [fabric.id])[fabric.id]
    difference = counted - current
    if difference == 0:
        raise Refused("Storage already holds that much.")
    db.add(ProdFabricMove(fabric_id=fabric.id, kind="count", kg=difference, note=why, created_by=actor.id))
    db.flush()
    _audit(
        db, fabric, actor, "counted", f"Counted {fabric.name}: {said(counted)} kg in storage",
        kg=kg_text(difference), counted=kg_text(counted),
    )
    return fabric


# ── Orders taking fabric ──────────────────────────────────────────────────────


def _use(db: Session, order: ProdOrder, fabric_id, kg: Decimal, actor: UserAccount) -> ProdFabricMove:
    """One ``use`` move, under the fabric's lock (the order is locked already)."""
    if not isinstance(fabric_id, int) or isinstance(fabric_id, bool):
        raise Refused("Choose the fabric from the list.")
    fabric = db.get(ProdFabric, fabric_id, with_for_update=True, populate_existing=True)
    if fabric is None:
        raise Refused("Choose the fabric from the list.")
    if not fabric.active:
        raise Refused(f"{fabric.name} is no longer kept in storage.")
    stock = in_stock(db, [fabric.id])[fabric.id]
    if kg > stock:
        raise Refused(f"Only {said(max(stock, Decimal(0)))} kg of {fabric.name} is in storage.")
    move = ProdFabricMove(fabric_id=fabric.id, kind="use", kg=-kg, order_id=order.id, created_by=actor.id)
    db.add(move)
    db.flush()
    _order_audit(
        db, order, actor, "fabric_taken", f"Took {said(kg)} kg of {fabric.name} from storage for {order.code}",
        fabric=fabric.id, kg=kg_text(kg),
    )
    return move


def take(db: Session, order_id: int, fabric_id, kg, actor: UserAccount) -> ProdOrder:
    """An open order whose fabric HBA buys takes kilos from storage."""
    order = _order(db, order_id, for_update=True)
    if order.status != "open":
        raise Refused("Pick an order that is still in production.")
    if order.fabric_bought_by != "hba":
        raise Refused("The factory buys this order's fabric.")
    _use(db, order, fabric_id, _kg(kg), actor)
    return order


def take_for_new_order(db: Session, order: ProdOrder, lines, actor: UserAccount) -> None:
    """The fabric a New order takes, in its own transaction (the order row
    exists, staged). A refusal leaves nothing written: the route rolls back."""
    if not lines:
        return
    if order.fabric_bought_by != "hba":
        raise Refused("The factory buys this order's fabric: take none from storage.")
    if len(lines) > MAX_LINES:
        raise Refused(f"Take at most {MAX_LINES} fabrics on one order.")
    wanted: list[tuple[int, Decimal]] = []
    for line in lines:
        fabric_id = line.get("fabric_id") if isinstance(line, dict) else None
        if any(fabric_id == seen for seen, _kg_ in wanted):
            raise Refused("Take each fabric once, with all its kilos.")
        wanted.append((fabric_id, _kg(line.get("kg") if isinstance(line, dict) else None)))
    # Fabric rows are locked in id order, so two orders taking the same two
    # fabrics queue rather than deadlock.
    for fabric_id, kg in sorted(wanted, key=lambda pair: pair[0] if isinstance(pair[0], int) else 0):
        _use(db, order, fabric_id, kg, actor)


def give_back(db: Session, order_id: int, move_id: int, actor: UserAccount) -> ProdOrder:
    """Undo one use: a ``return`` move of its kilos, pointing at it."""
    order = _order(db, order_id, for_update=True)
    move = db.get(ProdFabricMove, move_id)
    if move is None or move.kind != "use" or move.order_id != order.id:
        raise NotFound("This order did not take that fabric.")
    if order.status != "open":
        raise Locked(f"{order.code} is {order.status}: the fabric it took can no longer change.")
    if db.scalar(select(ProdFabricMove.id).where(ProdFabricMove.returns_id == move.id)) is not None:
        raise Refused("That fabric was already given back.")
    fabric = db.get(ProdFabric, move.fabric_id)
    _return(db, move, actor)
    _order_audit(
        db, order, actor, "fabric_returned",
        f"Gave {said(-move.kg)} kg of {fabric.name} back to storage from {order.code}",
        fabric=fabric.id, kg=kg_text(-move.kg),
    )
    return order


def _return(db: Session, move: ProdFabricMove, actor: UserAccount, note: str | None = None) -> ProdFabricMove:
    back = ProdFabricMove(
        fabric_id=move.fabric_id, kind="return", kg=-move.kg, order_id=move.order_id, returns_id=move.id,
        note=note, created_by=actor.id,
    )
    db.add(back)
    db.flush()
    return back


def return_all(db: Session, order: ProdOrder, actor: UserAccount) -> int:
    """Everything a cancelled order took goes back to storage. Call under the
    order's lock. Returns how many uses were given back."""
    uses = _live_uses(db, order.id)
    for move in uses:
        _return(db, move, actor, note="Order cancelled")
    if uses:
        _order_audit(
            db, order, actor, "fabric_returned",
            f"Gave the fabric {order.code} took back to storage when it was cancelled",
            moves=[move.id for move in uses],
        )
    return len(uses)


def holds_fabric(db: Session, order_id: int) -> bool:
    return bool(_live_uses(db, order_id))


def order_fabric(db: Session, order: ProdOrder, pieces: int, basis: str, *, with_money: bool) -> dict:
    """The order view's part: the fabric it holds, for everybody, and, for the
    owner, what that cost (kilos × each fabric's price per kg, rounded half up
    per line), for the order and per piece. ``None`` when it took nothing or a
    fabric has no price yet."""
    uses = _live_uses(db, order.id)
    fabrics = {f.id: f for f in db.scalars(select(ProdFabric).where(ProdFabric.id.in_({m.fabric_id for m in uses})))} if uses else {}
    body: dict = {
        "fabric_uses": [
            {
                "move_id": m.id,
                "fabric": {"id": m.fabric_id, "name": fabrics[m.fabric_id].name, "colour": fabrics[m.fabric_id].colour},
                "kg": kg_text(-m.kg),
            }
            for m in uses
        ]
    }
    if with_money:
        cost = None
        prices = price_per_kg(db, fabrics) if uses else {}
        if uses and all(prices.get(m.fabric_id) is not None for m in uses):
            total = sum(
                int((-m.kg * Decimal(prices[m.fabric_id])).quantize(Decimal(1), rounding=ROUND_HALF_UP)) for m in uses
            )
            cost = {
                "total_piastres": total,
                "per_piece_piastres": account.per_piece(total, pieces),
                "pieces": pieces,
                "basis": basis,
            }
        body["fabric_cost"] = cost
    return body


# ── Purchases filling storage ─────────────────────────────────────────────────


def purchase_target(db: Session, data: dict, *, part: str, unit: str) -> tuple[ProdFabric | None, dict | None]:
    """Where a purchase's kilos go, checked before anything is written: an
    existing active fabric (locked), the fields of a new one, or nowhere."""
    fabric_id = data.get("fabric_id")
    fresh = data.get("new_fabric")
    if fabric_id is None and not fresh:
        return None, None
    if fabric_id is not None and fresh:
        raise Refused("Put the kilos into one fabric: an existing one or a new one.")
    if part != "fabric" or unit != "kg":
        raise Refused("Only fabric bought by the kilo goes into storage.")
    if fresh:
        # The name is checked again, under its lock, when the fabric is made.
        _text(fresh.get("name"), limit=120, what="the fabric's name", required=True)
        return None, dict(fresh)
    fabric = db.get(ProdFabric, fabric_id, with_for_update=True, populate_existing=True)
    if fabric is None:
        raise Refused("Choose the fabric from the list.")
    if not fabric.active:
        raise Refused(f"{fabric.name} is no longer kept in storage.")
    return fabric, None


def fill(
    db: Session, purchase: ProdPurchase, fabric: ProdFabric | None, fresh: dict | None, actor: UserAccount
) -> ProdFabric | None:
    """The ``purchase`` move of a purchase just staged. A new fabric takes the
    purchase's supplier as its own."""
    if fabric is None and fresh is None:
        return None
    if fabric is None:
        fabric = new_fabric(db, fresh, actor, supplier_id=purchase.supplier_id)
        _audit(db, fabric, actor, "added", f"Added {fabric.name} to fabric storage from a purchase")
    db.add(
        ProdFabricMove(
            fabric_id=fabric.id, kind="purchase", kg=purchase.quantity, purchase_id=purchase.id, created_by=actor.id
        )
    )
    db.flush()
    _audit(
        db, fabric, actor, "bought", f"{said(purchase.quantity)} kg of {fabric.name} went into storage from a purchase",
        purchase=purchase.id, kg=kg_text(purchase.quantity),
    )
    return fabric


def filled_by(db: Session, purchase_id: int) -> ProdFabricMove | None:
    """The move by which a purchase filled storage, if it did."""
    return db.scalar(
        select(ProdFabricMove).where(ProdFabricMove.purchase_id == purchase_id, ProdFabricMove.kind == "purchase")
    )


def check_void(db: Session, purchase: ProdPurchase) -> tuple[ProdFabricMove, ProdFabric] | None:
    """Before a purchase is voided (its supplier locked): the kilos it put in
    storage must all still be there. Refused before anything changes."""
    move = filled_by(db, purchase.id)
    if move is None:
        return None
    if db.scalar(
        select(ProdFabricMove.id).where(ProdFabricMove.purchase_id == purchase.id, ProdFabricMove.kind == "void")
    ) is not None:
        return None
    fabric = db.get(ProdFabric, move.fabric_id, with_for_update=True, populate_existing=True)
    stock = in_stock(db, [fabric.id])[fabric.id]
    if stock < move.kg:
        short = move.kg - max(stock, Decimal(0))
        raise Refused(
            f"{said(short)} kg of {fabric.name} from this purchase is already used by orders. "
            "Give it back or count storage first."
        )
    return move, fabric


def void(db: Session, purchase: ProdPurchase, found: tuple[ProdFabricMove, ProdFabric] | None, actor: UserAccount) -> None:
    if found is None:
        return
    move, fabric = found
    db.add(
        ProdFabricMove(
            # Not the void's reason: that is the owner's, kept with the purchase.
            fabric_id=fabric.id, kind="void", kg=-move.kg, purchase_id=purchase.id, note="Purchase voided",
            created_by=actor.id,
        )
    )
    db.flush()
    _audit(
        db, fabric, actor, "voided", f"{said(move.kg)} kg of {fabric.name} left storage with a voided purchase",
        purchase=purchase.id, kg=kg_text(move.kg),
    )
