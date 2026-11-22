"""The production order: its stages, counts, deliveries, dates and money
(ADR 0084; build plan ``docs/plans/2026-11-14-production-orders-build.md``).

Every write here only stages; the route commits on success and rolls back
on a refusal (the Operations pattern). A refusal is ``Refused`` (422) or,
when the order or the step has moved past changing, ``Locked`` (409).

**Money is the owner's.** ``view`` and ``row`` add a ``cost`` and a
``settlement`` block only when asked ``with_money=True``; nothing else here
returns a cost, a rate or a payable. The history (``audit_event``) never
carries a figure of money at all, so it can be read by anybody who reads
Production, here and in the activity log.

Lateness is calculated, never stored. "Today" is Cairo's date.
"""

import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.core.businesstime import business_date, utcnow
from app.modules.production.models import ProductionSupplier, ProductionSupplierCategory
from app.modules.production.orders.services import account
from app.modules.production.orders.models import (
    COST_PARTS,
    ProdCutReport,
    DEFAULT_STAGE_DAYS,
    SIZES,
    STAGE_LABELS,
    STAGES,
    ProdDelivery,
    ProdDeliverySize,
    ProdLibraryItem,
    ProdOrder,
    ProdOrderDateChange,
    ProdOrderFile,
    ProdOrderReason,
    ProdOrderSize,
    ProdOrderStage,
    ProdPurchase,
    ProdStageDays,
)
from app.shared.models.audit import AuditEvent
from app.shared.models.catalogue import Product, ProductStatus
from app.shared.models.identity import UserAccount
from app.shared.services.audit import record_audit

#: The most pieces one size may hold, as a guard against a slipped zero.
MAX_PIECES = 100_000
#: The most one part of a piece's cost may be: EGP 100,000.
MAX_PART_PIASTRES = 10_000_000

PART_LABELS = {
    "fabric": "Fabric",
    "manufacturing": "Manufacturing",
    "printing": "Printing",
    "accessories": "Accessories",
    "packaging": "Special packaging",
}

#: The note on the work line an order cancelled after cutting writes on its factory's account.
CANCELLED_AFTER_CUTTING = "Cancelled after cutting"

#: Stages the QC manager marks done from ``complete``: a date and a note.
SIMPLE_STAGES = ("materials", "pattern_check", "making")

#: Where each other stage is completed instead, in words for the refusal.
COMPLETED_ELSEWHERE = {
    "plan": "The plan is done when the order is made.",
    "sample": "The owner decides the sample with Approve or Ask for changes.",
    "cutting": "Cutting is done by recording the cut quantities.",
    "final_inspection": "The final inspection is done from its counts, with Complete inspection.",
    "warehouse": "The warehouse receipt completes by itself once every delivery is counted.",
    "settle": "The order is settled with Settle.",
}


class Refused(ValueError):
    """A change refused, in words a person can act on."""


class Locked(Refused):
    """The order, or this part of it, has moved past changing."""


class NotFound(LookupError):
    """There is no such order, stage, delivery or file (404).

    A class of its own, so the API turns exactly this into a 404 and a stray
    ``KeyError`` (also a ``LookupError``) inside a service stays the bug it is.
    """


# ── Small helpers ─────────────────────────────────────────────────────────────


def today() -> date:
    """Cairo's date."""
    return business_date(utcnow())


def _iso(moment: datetime | None) -> str | None:
    if moment is None:
        return None
    return moment.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _said(value: date) -> str:
    """A day as a person reads it in a sentence: 20 Dec 2026."""
    return f"{value.day} {value.strftime('%b %Y')}"


def _day(value: date | None) -> str | None:
    return value.isoformat() if value is not None else None


def _text(value: str | None, *, limit: int, what: str, required: bool = False) -> str | None:
    cleaned = re.sub(r"\s+", " ", value or "").strip()
    if not cleaned:
        if required:
            raise Refused(f"Give {what}.")
        return None
    if len(cleaned) > limit:
        raise Refused(f"Keep {what} to {limit} characters.")
    return cleaned


def _not_future(day: date | None, what: str = "The date") -> date:
    day = day or today()
    if day > today():
        raise Refused(f"{what} can't be in the future.")
    return day


def _pieces(value) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise Refused("Each count must be a whole number, 0 or more.")
    if value > MAX_PIECES:
        raise Refused(f"{value:,} pieces is too many for one size. Check the number.")
    return value


def _size_map(raw: dict | None, *, what: str = "pieces") -> dict[str, int]:
    found: dict[str, int] = {}
    for size, count in (raw or {}).items():
        if size not in SIZES:
            raise Refused(f"{size} is not a size. Use XS, S, M, L, XL or XXL.")
        found[size] = _pieces(count)
    return found


def _plural(count: int, word: str) -> str:
    return f"{count:,} {word}" if count == 1 else f"{count:,} {word}s"


def _money(value, what: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise Refused(f"{what} must be a whole number of piastres, 0 or more.")
    if value > MAX_PART_PIASTRES:
        raise Refused(f"{what} is too large. Check the number.")
    return value


def _audit(db: Session, order: ProdOrder, actor: UserAccount, what: str, summary: str, **extra) -> None:
    """One history entry for the order. **Never a figure of money**: the
    history and the activity log are read by everybody in Production."""
    record_audit(
        db,
        action=f"production.order_{what}",
        subject=f"production:order:{order.id}",
        actor_id=actor.id,
        actor_email=actor.email,
        after={"summary": summary[:500], "order": order.code, **extra},
    )


def _touch(order: ProdOrder) -> None:
    order.updated_at = utcnow()


# ── Reading an order whole ────────────────────────────────────────────────────


@dataclass
class Delivery:
    row: ProdDelivery
    sizes: dict[str, ProdDeliverySize] = field(default_factory=dict)

    @property
    def shipped(self) -> int:
        return sum(r.shipped for r in self.sizes.values())

    @property
    def counted(self) -> int | None:
        if self.row.counted_on is None:
            return None
        return sum(r.counted or 0 for r in self.sizes.values())

    @property
    def waiting_for_count(self) -> bool:
        """No count date yet, or a size (added to the shipped numbers after
        the count was typed) that Khazenly has not counted."""
        return self.row.counted_on is None or any(r.counted is None for r in self.sizes.values())

    @property
    def mismatch(self) -> bool:
        return self.row.counted_on is not None and any(
            r.counted is not None and r.counted != r.shipped for r in self.sizes.values()
        )

    @property
    def needs_reason(self) -> bool:
        return self.mismatch and not self.row.mismatch_reason

    @property
    def explained(self) -> int:
        """Pieces short on this delivery that a reason accounts for."""
        if not (self.mismatch and self.row.mismatch_reason):
            return 0
        return sum(max(0, r.shipped - (r.counted or 0)) for r in self.sizes.values() if r.counted is not None)


@dataclass
class Facts:
    order: ProdOrder
    sizes: dict[str, ProdOrderSize]
    stages: dict[str, ProdOrderStage]
    deliveries: list[Delivery]
    reasons: list[ProdOrderReason]

    def total(self, column: str) -> int:
        return sum(getattr(row, column) or 0 for row in self.sizes.values())

    def recorded(self, column: str) -> bool:
        return any(getattr(row, column) is not None for row in self.sizes.values())

    @property
    def current(self) -> ProdOrderStage | None:
        for key in STAGES:
            if self.stages[key].status == "todo":
                return self.stages[key]
        return None

    def done(self, key: str) -> bool:
        return self.stages[key].status == "done"

    def of_kind(self, kind: str) -> list[Delivery]:
        return [d for d in self.deliveries if d.row.kind == kind]

    def shipped(self, kind: str, size: str | None = None) -> int:
        return sum(
            (d.sizes[size].shipped if size in d.sizes else 0) if size else d.shipped for d in self.of_kind(kind)
        )

    def counted(self, kind: str) -> int:
        return sum(d.counted or 0 for d in self.of_kind(kind))

    def explained(self, kind: str) -> int:
        return sum(d.explained for d in self.of_kind(kind))

    @property
    def fix_not_returned(self) -> int:
        return max(0, self.total("to_fix") - self.shipped("fix"))


def _facts_for(db: Session, orders: list[ProdOrder]) -> dict[int, Facts]:
    ids = [order.id for order in orders]
    if not ids:
        return {}
    sizes: dict[int, dict] = {i: {} for i in ids}
    for row in db.scalars(select(ProdOrderSize).where(ProdOrderSize.order_id.in_(ids))):
        sizes[row.order_id][row.size] = row
    stages: dict[int, dict] = {i: {} for i in ids}
    for row in db.scalars(select(ProdOrderStage).where(ProdOrderStage.order_id.in_(ids))):
        stages[row.order_id][row.stage] = row
    deliveries: dict[int, list[Delivery]] = {i: [] for i in ids}
    by_id: dict[int, Delivery] = {}
    for row in db.scalars(
        select(ProdDelivery).where(ProdDelivery.order_id.in_(ids)).order_by(ProdDelivery.number)
    ):
        by_id[row.id] = Delivery(row)
        deliveries[row.order_id].append(by_id[row.id])
    if by_id:
        for row in db.scalars(select(ProdDeliverySize).where(ProdDeliverySize.delivery_id.in_(list(by_id)))):
            by_id[row.delivery_id].sizes[row.size] = row
    reasons: dict[int, list] = {i: [] for i in ids}
    for row in db.scalars(
        select(ProdOrderReason).where(ProdOrderReason.order_id.in_(ids)).order_by(ProdOrderReason.id)
    ):
        reasons[row.order_id].append(row)
    return {
        order.id: Facts(order, sizes[order.id], stages[order.id], deliveries[order.id], reasons[order.id])
        for order in orders
    }


def _facts(db: Session, order: ProdOrder) -> Facts:
    db.flush()
    return _facts_for(db, [order])[order.id]


def _order(db: Session, order_id: int, *, for_update: bool = False) -> ProdOrder:
    order = db.get(ProdOrder, order_id, with_for_update=for_update or None)
    if order is None:
        raise NotFound("There is no such production order.")
    return order


def _open(db: Session, order_id: int) -> ProdOrder:
    order = _order(db, order_id, for_update=True)
    if order.status == "closed":
        raise Locked(f"{order.code} is settled and closed. Nothing on it can change now.")
    if order.status == "cancelled":
        raise Locked(f"{order.code} was cancelled. Nothing on it can change now.")
    return order


def _earlier_done(facts: Facts, key: str) -> None:
    for earlier in STAGES[: STAGES.index(key)]:
        if facts.stages[earlier].status == "todo":
            raise Refused(f"Finish {STAGE_LABELS[earlier]} first.")


def _still_todo(facts: Facts, key: str) -> ProdOrderStage:
    stage = facts.stages[key]
    if stage.status == "done":
        raise Locked(f"{STAGE_LABELS[key]} is done. Reopen it to change it.")
    if stage.status == "skipped":
        raise Refused(f"{STAGE_LABELS[key]} is skipped on this order.")
    return stage


def _mark_done(stage: ProdOrderStage, actor: UserAccount, on: date, note: str | None = None) -> None:
    stage.status = "done"
    stage.done_on = on
    stage.done_by = actor.id
    if note is not None:
        stage.note = note


# ── Settings: the typical days per stage ──────────────────────────────────────


def stage_days(db: Session) -> dict[str, int]:
    """The typical days per stage: the stored figures over the seeded ones."""
    days = dict(DEFAULT_STAGE_DAYS)
    for row in db.scalars(select(ProdStageDays)):
        days[row.stage] = row.days
    return days


def settings_view(db: Session) -> dict:
    rows = {row.stage: row for row in db.scalars(select(ProdStageDays))}
    names = _people(db, [row.updated_by for row in rows.values()])
    days = stage_days(db)
    return {
        "stages": [
            {
                "stage": key,
                "label": STAGE_LABELS[key],
                "days": days[key],
                "updated_at": _iso(rows[key].updated_at) if key in rows else None,
                "updated_by": names.get(rows[key].updated_by) if key in rows else None,
            }
            for key in STAGES[1:]
        ]
    }


def save_stage_days(db: Session, changes: dict[str, int], actor: UserAccount) -> None:
    if not changes:
        raise Refused("Change at least one stage.")
    rows = {row.stage: row for row in db.scalars(select(ProdStageDays).with_for_update())}
    current = stage_days(db)
    changed = []
    for key, days in changes.items():
        if key not in STAGES[1:]:
            raise Refused(f"{key} is not a stage with typical days.")
        if not isinstance(days, int) or isinstance(days, bool) or not 0 <= days <= 365:
            raise Refused(f"{STAGE_LABELS[key]}: give a number of days from 0 to 365.")
        if current[key] == days:
            continue
        row = rows.get(key)
        if row is None:
            row = ProdStageDays(stage=key, days=days)
            db.add(row)
        row.days = days
        row.updated_at = utcnow()
        row.updated_by = actor.id
        changed.append(f"{STAGE_LABELS[key]} {current[key]} to {days}")
    if changed:
        record_audit(
            db,
            action="production.stage_days_changed",
            subject="production:settings",
            actor_id=actor.id,
            actor_email=actor.email,
            after={"summary": ("Changed the typical days: " + ", ".join(changed))[:500]},
        )


def fill_dates(
    target: date, days: dict[str, int], skipped: frozenset[str] = frozenset(), not_before: date | None = None
) -> dict[str, date | None]:
    """Each stage's expected date, backwards from the target date.

    ``warehouse`` is the target date; each earlier stage is the next stage's
    expected date minus the next stage's days; ``settle`` is the target date
    plus its days. A skipped stage has no date and takes no days.

    With ``not_before`` (the day the order is made) no stage is expected
    before that day: a target date too near for the usual days would
    otherwise make an order that is weeks overdue the moment it is saved.
    """
    dates: dict[str, date | None] = {
        "warehouse": target,
        "settle": target + timedelta(days=days["settle"]),
    }
    following = "warehouse"
    for key in reversed(STAGES[: STAGES.index("warehouse")]):
        if key in skipped:
            dates[key] = None
            continue
        dates[key] = dates[following] - timedelta(days=days[following])
        following = key
    if not_before is not None:
        for key, day in dates.items():
            if day is not None and day < not_before:
                dates[key] = not_before
    return dates


# ── Choices for the New order form ───────────────────────────────────────────


def choices(db: Session) -> dict:
    suppliers = db.execute(
        select(ProductionSupplier.id, ProductionSupplier.name, ProductionSupplierCategory.name)
        .outerjoin(ProductionSupplierCategory, ProductionSupplierCategory.id == ProductionSupplier.category_id)
        .where(ProductionSupplier.active.is_(True), ProductionSupplier.deleted_at.is_(None))
        .order_by(ProductionSupplier.name)
    ).all()
    # A style may be made before it is on sale, so draft products are offered
    # too (the owner, 19 November 2026); archived ones are not.
    products = db.execute(
        select(Product.shopify_product_id, Product.title, Product.status, Product.image_url)
        .where(Product.status.in_((ProductStatus.ACTIVE, ProductStatus.DRAFT)))
        .order_by(Product.title, Product.shopify_product_id)
    ).all()
    return {
        "suppliers": [{"id": sid, "name": name, "category": category} for sid, name, category in suppliers],
        "products": [
            {"id": pid, "title": title, "status": status, "image_url": image_url}
            for pid, title, status, image_url in products
        ],
        "sizes": list(SIZES),
        "stage_days": stage_days(db),
        # The fabric in storage a New order may take (ADR 0089). No money.
        "fabrics": _storage().choices(db),
    }


def _storage():
    """Fabric storage (ADR 0089), which imports this module."""
    from app.modules.production.orders.services import fabric

    return fabric


def _supplier(db: Session, supplier_id: str | None, what: str, keep: str | None = None) -> ProductionSupplier:
    """A supplier to put on an order. ``keep`` is the supplier the order
    already has: it may stay even after it was deactivated, so one stale
    supplier does not make every other edit fail. Only a *changed* supplier
    must be active."""
    supplier = db.get(ProductionSupplier, supplier_id) if supplier_id else None
    staying = supplier is not None and supplier.id == keep
    if supplier is None or (supplier.deleted_at is not None and not staying):
        raise Refused(f"Choose {what} from the list.")
    if not supplier.active and not staying:
        raise Refused(f"{supplier.name} is not an active supplier.")
    return supplier


#: The most a print or embroidery may be wide, in cm.
MAX_DECORATION_WIDTH = Decimal("999.9")


def _width(value) -> Decimal | None:
    """A print or embroidery width in cm, to one decimal; blank is none."""
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    if isinstance(value, bool):
        raise Refused("Give the print / embroidery width in cm, like 12.5.")
    try:
        width = Decimal(str(value).strip()).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
    except (InvalidOperation, ValueError):
        raise Refused("Give the print / embroidery width in cm, like 12.5.") from None
    if not width.is_finite() or width <= 0:
        raise Refused("The print / embroidery width must be more than 0 cm.")
    if width > MAX_DECORATION_WIDTH:
        raise Refused("The print / embroidery width can be at most 999.9 cm.")
    return width


def _width_text(width: Decimal | None) -> str | None:
    return None if width is None else f"{width.quantize(Decimal('0.1'))}"


#: The product's text details an order holds, each with how long it may be and
#: the words its history uses (build plan 2026-11-19). No money.
_DETAILS = {
    "colour_code": (40, "colour code"),
    "fabric_type": (120, "fabric type"),
    "decoration_type": (120, "print / embroidery type"),
}


def _product(db: Session, product_id: str | None) -> str | None:
    product_id = (product_id or "").strip() or None
    if product_id is not None and db.get(Product, product_id) is None:
        raise Refused("That product is not in the product list.")
    return product_id


# ── Create and edit (the owner's) ────────────────────────────────────────────


#: The lock two simultaneous "New order" saves queue on, so they cannot both
#: take the same ``PO-YYMM-NN`` and have one of them fail on the unique code.
_CODE_LOCK = 840_001


def _next_code(db: Session) -> str:
    db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": _CODE_LOCK})
    day = today()
    prefix = f"PO-{day:%y%m}-"
    codes = db.scalars(select(ProdOrder.code).where(ProdOrder.code.startswith(prefix)))
    numbers = [int(code[len(prefix):]) for code in codes if code[len(prefix):].isdigit()]
    return f"{prefix}{max(numbers, default=0) + 1:02d}"


def _printing(db: Session, printing: str, print_supplier_id: str | None, keep: str | None = None) -> str | None:
    if printing == "outside":
        return _supplier(db, print_supplier_id, "the print house", keep).id
    return None


#: The details a new order takes from its product's Library record when the
#: request leaves them out (ADR 0087). Never the COGS: the New order form fills
#: the target cost from it, where the owner sees it.
_FROM_LIBRARY = ("colour_code", "fabric_type", "decoration_type", "decoration_width_cm")


def _from_library(db: Session, product_id: str | None, data: dict) -> dict:
    """The request with each detail it left out (absent, null or blank) taken
    from the product's Library record. What the request gives wins."""
    if product_id is None:
        return data
    item = db.get(ProdLibraryItem, product_id)
    if item is None:
        return data
    filled = dict(data)
    for key in _FROM_LIBRARY:
        given = data.get(key)
        if given is None or (isinstance(given, str) and not given.strip()):
            filled[key] = getattr(item, key)
    return filled


def create(db: Session, data: dict, actor: UserAccount) -> ProdOrder:
    style = _text(data.get("style_name"), limit=180, what="the style", required=True)
    colour = _text(data.get("colour"), limit=80, what="the colour", required=True)
    factory = _supplier(db, data.get("factory_id"), "the factory")
    print_supplier = _printing(db, data["printing"], data.get("print_supplier_id"))
    planned = _size_map(data.get("planned"))
    total = sum(planned.values())
    if total <= 0:
        raise Refused("Plan at least one piece.")
    target = data["target_date"]
    if target < today():
        raise Refused("The target date can't be in the past.")
    repeat = bool(data.get("repeat_run"))
    product_id = _product(db, data.get("shopify_product_id"))
    data = _from_library(db, product_id, data)

    order = ProdOrder(
        code=_next_code(db),
        style_name=style,
        colour=colour,
        shopify_product_id=product_id,
        factory_id=factory.id,
        fabric_bought_by=data["fabric_bought_by"],
        printing=data["printing"],
        print_supplier_id=print_supplier,
        repeat_run=repeat,
        target_date=target,
        delivery_date=target,
        sample_status="none" if repeat else "pending",
        status="open",
        notes=_text(data.get("notes"), limit=2000, what="the notes"),
        colour_code=_text(data.get("colour_code"), limit=40, what="the colour code"),
        fabric_type=_text(data.get("fabric_type"), limit=120, what="the fabric type"),
        decoration_type=_text(data.get("decoration_type"), limit=120, what="the print / embroidery type"),
        decoration_width_cm=_width(data.get("decoration_width_cm")),
        created_by=actor.id,
    )
    for part in COST_PARTS:
        setattr(order, f"target_{part}_piastres", _money(data.get(f"target_{part}_piastres", 0), PART_LABELS[part]))
    db.add(order)
    db.flush()

    for size in SIZES:
        if planned.get(size):
            db.add(ProdOrderSize(order_id=order.id, size=size, planned=planned[size]))

    skipped = frozenset({"sample"}) if repeat else frozenset()
    dates = fill_dates(target, stage_days(db), skipped, not_before=today())
    overrides = data.get("expected_dates") or {}
    for key, day in overrides.items():
        if key not in STAGES:
            raise Refused(f"{key} is not a stage.")
        if key in skipped:
            raise Refused("The sample is skipped on a repeat run, so it has no date.")
        dates[key] = day
    made_on = today()
    for position, key in enumerate(STAGES, start=1):
        stage = ProdOrderStage(
            order_id=order.id, stage=key, position=position, status="todo", expected_date=dates[key]
        )
        if key == "plan":
            _mark_done(stage, actor, made_on)
        elif key in skipped:
            stage.status = "skipped"
            stage.note = "Repeat run, nothing changed"
        db.add(stage)
    db.add(
        ProdOrderDateChange(
            order_id=order.id, old_date=None, new_date=target, set_by="owner",
            reason="Target when planned", created_by=actor.id,
        )
    )
    _audit(
        db, order, actor, "created",
        f"Created {order.code}: {style} · {colour}, {_plural(total, 'piece')}, target {_said(target)}",
    )
    # The fabric it takes from storage, in this same transaction (ADR 0089).
    _storage().take_for_new_order(db, order, data.get("fabric") or [], actor)
    return order


#: What an edit may change, in the words its history entry uses.
_BASICS = {
    "style_name": "style",
    "colour": "colour",
    "shopify_product_id": "Shopify product",
    "factory_id": "factory",
    "fabric_bought_by": "who buys the fabric",
    "printing": "printing",
    "print_supplier_id": "print house",
    "target_date": "target date",
    "notes": "notes",
    "colour_code": "colour code",
    "fabric_type": "fabric type",
    "decoration_type": "print / embroidery type",
    "decoration_width_cm": "print / embroidery width",
}


#: The words a change of who buys the fabric, or of printing, is told in.
_FABRIC_WORDS = {"hba": "HBA", "factory": "the factory"}
_PRINTING_WORDS = {"factory": "at the factory", "outside": "at an outside print house", "none": "no printing"}


def edit(db: Session, order_id: int, data: dict, actor: UserAccount) -> ProdOrder:
    order = _open(db, order_id)
    facts = _facts(db, order)
    changed: list[str] = []
    #: After cutting, the factory's deduction rests on who bought the fabric
    #: and on who prints, and what it is owed is for one factory, so those
    #: three stay as they were (the same value sent again is no change).
    cut = facts.done("cutting")

    def put(column: str, value, told=None) -> None:
        before = getattr(order, column)
        if before != value:
            setattr(order, column, value)
            changed.append(f"{_BASICS[column]} ({told(before, value)})" if told else _BASICS[column])

    if "style_name" in data:
        put("style_name", _text(data["style_name"], limit=180, what="the style", required=True))
    if "colour" in data:
        put("colour", _text(data["colour"], limit=80, what="the colour", required=True))
    if "shopify_product_id" in data:
        put("shopify_product_id", _product(db, data["shopify_product_id"]))
    if "factory_id" in data:
        if cut and data["factory_id"] != order.factory_id:
            raise Locked("The factory cannot change after cutting. Reopen cutting first.")
        put("factory_id", _supplier(db, data["factory_id"], "the factory", keep=order.factory_id).id)
    if "fabric_bought_by" in data and data["fabric_bought_by"] is not None:
        if cut and data["fabric_bought_by"] != order.fabric_bought_by:
            raise Locked("Who buys the fabric cannot change after cutting. Reopen cutting first.")
        if data["fabric_bought_by"] == "factory" and _storage().holds_fabric(db, order.id):
            raise Refused(
                f"{order.code} took fabric from storage. Give it back before saying the factory buys the fabric."
            )
        put(
            "fabric_bought_by", data["fabric_bought_by"],
            lambda old, new: f"from {_FABRIC_WORDS[old]} to {_FABRIC_WORDS[new]}",
        )
    if "printing" in data or "print_supplier_id" in data:
        printing = data.get("printing") or order.printing
        wanted = data.get("print_supplier_id", order.print_supplier_id) if printing == "outside" else None
        if cut and (printing != order.printing or wanted != order.print_supplier_id):
            raise Locked("Printing cannot change after cutting. Reopen cutting first.")
        supplier = _printing(db, printing, wanted, keep=order.print_supplier_id)
        names = _suppliers(db, [order.print_supplier_id, supplier])
        put("printing", printing, lambda old, new: f"from {_PRINTING_WORDS[old]} to {_PRINTING_WORDS[new]}")
        put(
            "print_supplier_id", supplier,
            lambda old, new: f"from {names.get(old, 'none') if old else 'none'} to {names.get(new, 'none') if new else 'none'}",
        )
    if "target_date" in data and data["target_date"] is not None:
        put("target_date", data["target_date"])
    if "notes" in data:
        put("notes", _text(data["notes"], limit=2000, what="the notes"))
    for column, (limit, words) in _DETAILS.items():
        if column in data:
            put(column, _text(data[column], limit=limit, what=f"the {words}"))
    if "decoration_width_cm" in data:
        put("decoration_width_cm", _width(data["decoration_width_cm"]))

    if data.get("planned") is not None:
        if facts.done("cutting"):
            raise Locked("Cutting is done, so the plan is kept as it was. The cut counts say what was made.")
        planned = _size_map(data["planned"])
        if sum(planned.values()) <= 0:
            raise Refused("Plan at least one piece.")
        before = {size: row.planned for size, row in facts.sizes.items() if row.planned}
        for size, count in planned.items():
            row = facts.sizes.get(size)
            if row is None:
                if count:
                    db.add(ProdOrderSize(order_id=order.id, size=size, planned=count))
            else:
                row.planned = count
        for size, row in facts.sizes.items():
            if size not in planned:
                row.planned = 0
        if before != {size: count for size, count in planned.items() if count}:
            changed.append("planned sizes")

    costs = False
    for part in COST_PARTS:
        for kind in ("target", "actual"):
            key = f"{kind}_{part}_piastres"
            if key not in data:
                continue
            value = data[key]
            if value is None:
                if kind == "target":
                    raise Refused(f"Give a target for {PART_LABELS[part].lower()}, 0 or more.")
            else:
                value = _money(value, f"{PART_LABELS[part]} ({kind})")
            if getattr(order, key) != value:
                setattr(order, key, value)
                costs = True
    if costs:
        changed.append("cost per piece")

    if not changed:
        return order
    _touch(order)
    _audit(db, order, actor, "edited", f"Changed {order.code}'s " + _words(changed))
    return order


def _words(parts: list[str]) -> str:
    parts = list(dict.fromkeys(parts))
    return parts[0] if len(parts) == 1 else ", ".join(parts[:-1]) + " and " + parts[-1]


# ── Stages ────────────────────────────────────────────────────────────────────


def _stage_key(key: str) -> str:
    if key not in STAGES:
        raise NotFound("There is no such stage.")
    return key


def edit_stage(db: Session, order_id: int, key: str, data: dict, actor: UserAccount) -> ProdOrder:
    """An expected date or a note on one stage; the owner or the QC manager."""
    key = _stage_key(key)
    order = _open(db, order_id)
    stage = _facts(db, order).stages[key]
    changed = []
    if "expected_date" in data:
        if stage.status == "skipped" and data["expected_date"] is not None:
            raise Refused(f"{STAGE_LABELS[key]} is skipped on this order, so it has no date.")
        if stage.expected_date != data["expected_date"]:
            before = stage.expected_date
            stage.expected_date = data["expected_date"]
            changed.append(
                f"moved {STAGE_LABELS[key]}'s expected date from {_day(before) or 'none'} "
                f"to {_day(stage.expected_date) or 'none'}"
            )
    if "note" in data:
        note = _text(data["note"], limit=2000, what="the note")
        if stage.note != note:
            stage.note = note
            changed.append(f"changed the note on {STAGE_LABELS[key]}")
    if changed:
        _touch(order)
        summary = _words(changed)
        _audit(db, order, actor, "stage_changed", summary[0].upper() + summary[1:], stage=key)
    return order


def complete_stage(db: Session, order_id: int, key: str, data: dict, actor: UserAccount) -> ProdOrder:
    """Materials, fabric check, pattern check and making: the QC manager's."""
    key = _stage_key(key)
    if key in COMPLETED_ELSEWHERE:
        raise Refused(COMPLETED_ELSEWHERE[key])
    order = _open(db, order_id)
    facts = _facts(db, order)
    stage = _still_todo(facts, key)
    _earlier_done(facts, key)
    on = _not_future(data.get("done_on"))
    note = _text(data.get("note"), limit=2000, what="the note")
    if key == "fabric_check":
        result = data.get("result")
        if result not in ("passed", "failed"):
            raise Refused("Say whether the fabric passed or failed.")
        if result == "failed":
            if note is None:
                raise Refused("Say what was wrong with the fabric.")
            stage.note = note
            _touch(order)
            _audit(db, order, actor, "fabric_failed", f"Fabric check failed on {order.code}: {note}", stage=key)
            return order
    _mark_done(stage, actor, on, note)
    _touch(order)
    _audit(
        db, order, actor, "stage_done",
        f"{STAGE_LABELS[key]} done on {order.code}" + (f": {note}" if note else ""), stage=key,
    )
    return order


def reopen_stage(db: Session, order_id: int, key: str, reason: str, actor: UserAccount) -> ProdOrder:
    """The owner reopens the latest done stage, with a reason."""
    key = _stage_key(key)
    reason = _text(reason, limit=500, what="the reason", required=True)
    order = _open(db, order_id)
    facts = _facts(db, order)
    done = [k for k in STAGES if facts.stages[k].status == "done"]
    latest = done[-1] if done else None
    if key == "plan":
        raise Refused("The plan can't be reopened. Edit the order instead.")
    if key != latest:
        raise Refused(
            "Only the latest finished stage can be reopened"
            + (f": {STAGE_LABELS[latest]}." if latest and latest != "plan" else ".")
        )
    stage = facts.stages[key]
    stage.status = "todo"
    stage.done_on = None
    stage.done_by = None
    if key == "sample":
        order.sample_status = "pending"
        order.sample_decided_by = None
        order.sample_decided_at = None
    _touch(order)
    _audit(db, order, actor, "stage_reopened", f"Reopened {STAGE_LABELS[key]} on {order.code}: {reason}", stage=key)
    return order


def decide_sample(db: Session, order_id: int, decision: str, note: str | None, actor: UserAccount) -> ProdOrder:
    order = _open(db, order_id)
    facts = _facts(db, order)
    stage = _still_todo(facts, "sample")
    _earlier_done(facts, "sample")
    note = _text(note, limit=2000, what="the note")
    order.sample_decided_by = actor.id
    order.sample_decided_at = utcnow()
    order.sample_note = note
    if decision == "changes":
        if note is None:
            raise Refused("Say what the factory should change.")
        order.sample_status = "changes"
        stage.note = note
        _touch(order)
        _audit(db, order, actor, "sample_changes", f"Asked for changes to {order.code}'s sample: {note}")
        return order
    order.sample_status = "approved"
    _mark_done(stage, actor, today(), note)
    _touch(order)
    _audit(
        db, order, actor, "sample_approved",
        f"Approved {order.code}'s sample" + (f": {note}" if note else ""),
    )
    return order


def _reasons_total(reasons: list[dict], kind: str, what: str) -> list[tuple[str, int]]:
    rows = []
    for item in reasons:
        if item.get("kind", kind) != kind:
            continue
        reason = _text(item.get("reason"), limit=200, what=f"a reason for {what}", required=True)
        quantity = item.get("quantity")
        if not isinstance(quantity, int) or isinstance(quantity, bool) or quantity <= 0:
            raise Refused("Each reason needs a number of pieces, more than 0.")
        rows.append((reason, quantity))
    return rows


def _replace_reasons(db: Session, facts: Facts, kind: str, rows: list[tuple[str, int]], actor: UserAccount) -> None:
    for old in facts.reasons:
        if old.kind == kind:
            db.delete(old)
    for reason, quantity in rows:
        db.add(
            ProdOrderReason(
                order_id=facts.order.id, kind=kind, reason=reason, quantity=quantity, created_by=actor.id
            )
        )


def _move_delivery_date(
    db: Session, order: ProdOrder, new: date, set_by: str, reason: str, actor: UserAccount
) -> None:
    db.add(
        ProdOrderDateChange(
            order_id=order.id, old_date=order.delivery_date, new_date=new, set_by=set_by,
            reason=reason, created_by=actor.id,
        )
    )
    order.delivery_date = new


def record_cut(db: Session, order_id: int, data: dict, actor: UserAccount) -> ProdOrder:
    """Cut quantities per size and the factory's promised date: completes
    cutting. A shortfall against the plan needs reasons adding up to it."""
    order = _open(db, order_id)
    facts = _facts(db, order)
    stage = _still_todo(facts, "cutting")
    _earlier_done(facts, "cutting")
    cut = _size_map(data.get("sizes"))
    if sum(cut.values()) <= 0:
        raise Refused("Give the number cut for at least one size.")
    for size, row in facts.sizes.items():
        inspected = (row.passed or 0) + (row.to_fix or 0) + (row.rejected or 0)
        if inspected > cut.get(size, 0):
            raise Refused(f"Size {size}: {inspected} pieces are already inspected, more than {cut.get(size, 0)} cut.")
    on = _not_future(data.get("done_on"))
    promised = data.get("promised_date")
    if promised is None:
        raise Refused("Give the date the factory promised.")

    planned_total = facts.total("planned")
    cut_total = sum(cut.values())
    shortfall = planned_total - cut_total
    reasons = _reasons_total(data.get("reasons") or [], "cut_short", "cutting fewer")
    if shortfall > 0:
        given = sum(q for _, q in reasons)
        if given != shortfall:
            raise Refused(
                f"{_plural(shortfall, 'piece')} fewer were cut than planned; "
                f"the reasons account for {given:,}. Make them add up to {shortfall:,}."
            )
    else:
        reasons = []
    _replace_reasons(db, facts, "cut_short", reasons, actor)

    for size in SIZES:
        row = facts.sizes.get(size)
        if size in cut:
            if row is None:
                row = ProdOrderSize(order_id=order.id, size=size, planned=0)
                db.add(row)
            row.cut = cut[size]
        elif row is not None:
            row.cut = 0
    _mark_done(stage, actor, on)
    moved = ""
    if promised != order.delivery_date:
        _move_delivery_date(db, order, promised, "factory", "Promised at cutting", actor)
        moved = f"; the factory promised {_said(promised)}"
    # The factory's own report, if one waits, is confirmed by this: the
    # confirmed figures are what was saved here, whatever it said (batch 6b).
    waiting = waiting_cut_reports(db, [order.id], lock=True).get(order.id)
    if waiting is not None:
        waiting.confirmed_at = utcnow()
        moved += "; confirmed the factory's report"
    _touch(order)
    _audit(
        db, order, actor, "cut_recorded",
        f"Recorded {_plural(cut_total, 'piece')} cut on {order.code}"
        + (f", {shortfall:,} fewer than planned" if shortfall > 0 else "") + moved,
    )
    return order


# ── The factory's cut report (batch 6b) ──────────────────────────────────────


def waiting_cut_reports(db: Session, order_ids: list[int], *, lock: bool = False) -> dict[int, ProdCutReport]:
    """The report each order's factory sent that the QC manager has not yet
    confirmed (at most one per order), by order."""
    if not order_ids:
        return {}
    query = select(ProdCutReport).where(
        ProdCutReport.order_id.in_(order_ids),
        ProdCutReport.confirmed_at.is_(None),
        ProdCutReport.replaced_at.is_(None),
    )
    if lock:
        query = query.with_for_update()
    return {row.order_id: row for row in db.scalars(query)}


def cut_report_view(report: ProdCutReport | None) -> dict | None:
    """A waiting report as the order page and the cut form read it: the cut
    form opens filled with these sizes and says when it was reported."""
    if report is None:
        return None
    sizes = {size: int(report.sizes[size]) for size in SIZES if size in (report.sizes or {})}
    return {
        "sizes": sizes,
        "total": sum(sizes.values()),
        "note": report.note,
        "reported_on": _day(business_date(report.reported_at)),
        "reported_at": _iso(report.reported_at),
    }


def save_inspection(db: Session, order_id: int, data: dict, actor: UserAccount) -> ProdOrder:
    """Passed / to fix / rejected per size, saved in batches after cutting;
    ``complete`` finishes the final inspection once every size adds up."""
    order = _open(db, order_id)
    facts = _facts(db, order)
    if not facts.done("cutting"):
        raise Refused("Record the cut quantities first.")
    stage = _still_todo(facts, "final_inspection")

    for size, counts in (data.get("sizes") or {}).items():
        if size not in SIZES:
            raise Refused(f"{size} is not a size. Use XS, S, M, L, XL or XXL.")
        row = facts.sizes.get(size)
        cut = (row.cut or 0) if row is not None else 0
        absent = [column for column in ("passed", "to_fix", "rejected") if column not in counts]
        if absent:
            # A size sent in part would silently zero the rest.
            raise Refused(f"Size {size}: give passed, to fix and rejected together, 0 where there are none.")
        values = {column: _pieces(counts[column]) for column in ("passed", "to_fix", "rejected")}
        if sum(values.values()) > cut:
            raise Refused(f"Size {size}: {sum(values.values()):,} inspected, more than the {cut:,} cut.")
        if row is None:
            if not any(values.values()):
                continue
            row = ProdOrderSize(order_id=order.id, size=size, planned=0, cut=0)
            db.add(row)
        for column, value in values.items():
            setattr(row, column, value)
    db.flush()
    facts = _facts(db, order)

    if facts.total("passed") < facts.shipped("finished"):
        raise Refused(
            f"{facts.shipped('finished'):,} finished pieces have already left the factory, "
            f"more than the {facts.total('passed'):,} passed."
        )
    if facts.total("to_fix") < facts.shipped("fix"):
        raise Refused(
            f"{facts.shipped('fix'):,} fixed pieces have already come back, more than the "
            f"{facts.total('to_fix'):,} sent to fix."
        )

    reasons_in = data.get("reasons")
    if reasons_in is not None:
        for kind, what in (("rejected", "rejecting"), ("to_fix", "sending to fix")):
            rows = _reasons_total(reasons_in, kind, what)
            if sum(q for _, q in rows) > facts.total(kind):
                raise Refused(
                    f"The reasons for {what} add up to more than the {facts.total(kind):,} pieces counted."
                )
            _replace_reasons(db, facts, kind, rows, actor)
        db.flush()
        facts = _facts(db, order)

    if not data.get("complete"):
        _touch(order)
        _audit(
            db, order, actor, "inspection_saved",
            f"Saved inspection counts on {order.code}: {facts.total('passed'):,} passed, "
            f"{facts.total('to_fix'):,} to fix, {facts.total('rejected'):,} rejected",
        )
        _warehouse_check(db, order, actor)
        return order

    _earlier_done(facts, "final_inspection")
    for size, row in facts.sizes.items():
        inspected = (row.passed or 0) + (row.to_fix or 0) + (row.rejected or 0)
        if inspected != (row.cut or 0):
            raise Refused(
                f"Size {size}: {inspected:,} inspected of {row.cut or 0:,} cut. "
                "Passed, to fix and rejected must add up to the cut for every size."
            )
    for kind, what in (("rejected", "rejected"), ("to_fix", "to fix")):
        given = sum(r.quantity for r in facts.reasons if r.kind == kind)
        if given != facts.total(kind):
            raise Refused(
                f"{facts.total(kind):,} {what}, and the reasons account for {given:,}. Make them add up."
            )
    on = _not_future(data.get("done_on"))
    _mark_done(stage, actor, on)
    _touch(order)
    _audit(
        db, order, actor, "inspection_done",
        f"Final inspection done on {order.code}: {facts.total('passed'):,} passed, "
        f"{facts.total('to_fix'):,} to fix, {facts.total('rejected'):,} rejected",
    )
    _warehouse_check(db, order, actor)
    return order


def write_off(db: Session, order_id: int, sizes: dict, reason: str, actor: UserAccount) -> ProdOrder:
    """Fix pieces that will not come back move from to-fix to rejected."""
    order = _open(db, order_id)
    facts = _facts(db, order)
    reason = _text(reason, limit=200, what="the reason", required=True)
    if not facts.done("final_inspection"):
        raise Refused("Finish the final inspection first.")
    if facts.done("warehouse"):
        raise Locked("The warehouse receipt is done. Reopen it to write pieces off.")
    amounts = {size: count for size, count in _size_map(sizes).items() if count}
    if not amounts:
        raise Refused("Give the number of pieces to write off.")
    for size, count in amounts.items():
        row = facts.sizes.get(size)
        outstanding = max(0, (row.to_fix or 0) - facts.shipped("fix", size)) if row else 0
        if count > outstanding:
            raise Refused(f"Size {size}: only {outstanding:,} fix pieces are still at the factory.")
    total = 0
    for size, count in amounts.items():
        row = facts.sizes[size]
        row.to_fix = (row.to_fix or 0) - count
        row.rejected = (row.rejected or 0) + count
        total += count
    db.add(
        ProdOrderReason(
            order_id=order.id, kind="rejected", reason=f"Written off: {reason}"[:200], quantity=total,
            created_by=actor.id,
        )
    )
    # The pieces left "to fix", so the reasons for fixing must shrink with
    # them: the order page then adds up, and a reopened inspection can be
    # completed again without retyping. Largest reason first; a reason that
    # reaches zero goes.
    left = total
    for old in sorted((r for r in facts.reasons if r.kind == "to_fix"), key=lambda r: (-r.quantity, r.id)):
        if left <= 0:
            break
        taken = min(old.quantity, left)
        left -= taken
        if taken == old.quantity:
            db.delete(old)
        else:
            old.quantity -= taken
    _touch(order)
    _audit(db, order, actor, "written_off", f"Wrote off {_plural(total, 'fix piece')} on {order.code}: {reason}")
    _warehouse_check(db, order, actor)
    return order


def change_delivery_date(
    db: Session, order_id: int, new: date, set_by: str, reason: str, actor: UserAccount
) -> ProdOrder:
    order = _open(db, order_id)
    reason = _text(reason, limit=200, what="the reason", required=True)
    if new == order.delivery_date:
        raise Refused(f"The delivery date is already {_said(new)}.")
    old = order.delivery_date
    _move_delivery_date(db, order, new, set_by, reason, actor)
    _touch(order)
    who = "the factory" if set_by == "factory" else "the owner"
    _audit(
        db, order, actor, "delivery_date_changed",
        f"Delivery date of {order.code} moved from {_said(old)} to {_said(new)} by {who}: {reason}",
    )
    return order


# ── Deliveries ────────────────────────────────────────────────────────────────


def _check_shipped(facts: Facts, kind: str, shipped: dict[str, int], excluding: int | None = None) -> None:
    others = sum(d.shipped for d in facts.of_kind(kind) if d.row.id != excluding)
    total = others + sum(shipped.values())
    if kind == "finished":
        limit = facts.total("passed")
        if total > limit:
            raise Refused(
                f"That makes {total:,} finished pieces shipped, more than the {limit:,} that passed inspection."
            )
    else:
        limit = facts.total("to_fix")
        if total > limit:
            raise Refused(f"That makes {total:,} fixed pieces back, more than the {limit:,} sent to fix.")


def _apply_counts(delivery: ProdDelivery, rows: dict[str, ProdDeliverySize], db: Session,
                  counted_on: date | None, counted: dict[str, int] | None) -> None:
    if counted is None and counted_on is None:
        return
    if counted is None:
        raise Refused("Give Khazenly's count for each size.")
    if counted_on is None:
        raise Refused("Give the date Khazenly counted it.")
    counted_on = _not_future(counted_on, "Khazenly's count date")
    if counted_on < delivery.shipped_on:
        raise Refused("Khazenly can't have counted it before it left the factory.")
    delivery.counted_on = counted_on
    for size, count in counted.items():
        if size not in rows:
            rows[size] = ProdDeliverySize(delivery_id=delivery.id, size=size, shipped=0)
            db.add(rows[size])
        rows[size].counted = count
    for size, row in rows.items():
        if size not in counted:
            row.counted = 0


def add_delivery(db: Session, order_id: int, data: dict, actor: UserAccount) -> tuple[ProdOrder, ProdDelivery]:
    order = _open(db, order_id)
    facts = _facts(db, order)
    if not facts.done("cutting"):
        raise Refused("Deliveries can be recorded once cutting is done.")
    if facts.done("warehouse"):
        raise Locked("The warehouse receipt is done. Reopen it to record another delivery.")
    kind = data["kind"]
    shipped = {size: count for size, count in _size_map(data.get("shipped")).items() if count}
    if not shipped:
        raise Refused("Give the number shipped for at least one size.")
    _check_shipped(facts, kind, shipped)
    shipped_on = _not_future(data.get("shipped_on"), "The shipping date")
    number = (max((d.row.number for d in facts.deliveries), default=0)) + 1
    delivery = ProdDelivery(order_id=order.id, number=number, kind=kind, shipped_on=shipped_on, created_by=actor.id)
    db.add(delivery)
    db.flush()
    rows = {}
    for size in SIZES:
        if size in shipped:
            rows[size] = ProdDeliverySize(delivery_id=delivery.id, size=size, shipped=shipped[size])
            db.add(rows[size])
    counted = _size_map(data["counted"]) if data.get("counted") is not None else None
    _apply_counts(delivery, rows, db, data.get("counted_on"), counted)
    delivery.mismatch_reason = _text(data.get("mismatch_reason"), limit=1000, what="the reason")
    total = sum(shipped.values())
    words = "fixed pieces" if kind == "fix" else "pieces"
    summary = f"Delivery {number} of {order.code}: {total:,} {words} left the factory on {_said(shipped_on)}"
    if delivery.counted_on is not None:
        summary += f"; Khazenly counted {sum(counted.values()):,}"
    _touch(order)
    _audit(db, order, actor, "delivery_added", summary, delivery=number)
    _warehouse_check(db, order, actor)
    return order, delivery


def edit_delivery(db: Session, delivery_id: int, data: dict, actor: UserAccount) -> ProdOrder:
    # Lock the order before reading the delivery, as every other write does,
    # so two edits (or an edit and a settle) cannot both act on stale rows.
    order_id = db.scalar(select(ProdDelivery.order_id).where(ProdDelivery.id == delivery_id))
    if order_id is None:
        raise NotFound("There is no such delivery.")
    order = _open(db, order_id)
    delivery = db.get(ProdDelivery, delivery_id, populate_existing=True)
    if delivery is None:
        raise NotFound("There is no such delivery.")
    facts = _facts(db, order)
    if facts.done("warehouse"):
        raise Locked("The warehouse receipt is done. Reopen it to change a delivery.")
    current = next(d for d in facts.deliveries if d.row.id == delivery.id)
    rows = current.sizes
    changed = []

    if "shipped_on" in data and data["shipped_on"] is not None:
        delivery.shipped_on = _not_future(data["shipped_on"], "The shipping date")
        changed.append("the shipping date")
    if data.get("shipped") is not None:
        shipped = _size_map(data["shipped"])
        if not any(shipped.values()):
            raise Refused("Give the number shipped for at least one size.")
        _check_shipped(facts, delivery.kind, shipped, excluding=delivery.id)
        for size, count in shipped.items():
            if size not in rows:
                rows[size] = ProdDeliverySize(delivery_id=delivery.id, size=size, shipped=0)
                db.add(rows[size])
            rows[size].shipped = count
        for size, row in rows.items():
            if size not in shipped:
                row.shipped = 0
        changed.append("the shipped numbers")
    if "counted" in data or "counted_on" in data:
        counted = _size_map(data["counted"]) if data.get("counted") is not None else None
        counted_on = data.get("counted_on", delivery.counted_on)
        if counted is None and data.get("counted_on") is not None and delivery.counted_on is not None:
            counted = {size: row.counted or 0 for size, row in rows.items()}
        _apply_counts(delivery, rows, db, counted_on, counted)
        changed.append("Khazenly's count")
    if delivery.counted_on is not None and delivery.counted_on < delivery.shipped_on:
        raise Refused("Khazenly can't have counted it before it left the factory.")
    if "mismatch_reason" in data:
        delivery.mismatch_reason = _text(data["mismatch_reason"], limit=1000, what="the reason")
        changed.append("the reason the counts differ")
    if not changed:
        # Nothing to save, but a warehouse receipt the owner reopened has no
        # other way to be completed again than a save from here.
        _warehouse_check(db, order, actor)
        return order
    delivery.updated_at = utcnow()
    _touch(order)
    db.flush()
    _audit(
        db, order, actor, "delivery_changed",
        f"Changed {_words(changed)} on delivery {delivery.number} of {order.code}", delivery=delivery.number,
    )
    _warehouse_check(db, order, actor)
    return order


def _warehouse_ready(facts: Facts) -> bool:
    if facts.stages["warehouse"].status != "todo":
        return False
    if any(facts.stages[k].status == "todo" for k in STAGES[: STAGES.index("warehouse")]):
        return False
    for delivery in facts.deliveries:
        if delivery.waiting_for_count or delivery.needs_reason:
            return False
    # Everything has to have *left the factory* as well as been counted: a fix
    # delivery that shipped 8 of 10 and was counted as 10 leaves 2 pieces at
    # the factory that no count can account for.
    if facts.shipped("finished") < facts.total("passed") or facts.fix_not_returned > 0:
        return False
    if facts.counted("finished") + facts.explained("finished") < facts.total("passed"):
        return False
    if facts.counted("fix") + facts.explained("fix") < facts.total("to_fix"):
        return False
    return True


def _warehouse_check(db: Session, order: ProdOrder, actor: UserAccount) -> None:
    """The warehouse receipt completes by itself once everything is counted."""
    facts = _facts(db, order)
    if not _warehouse_ready(facts):
        return
    counted = [d.row.counted_on for d in facts.deliveries if d.row.counted_on is not None]
    _mark_done(facts.stages["warehouse"], actor, max(counted) if counted else today())
    _audit(
        db, order, actor, "warehouse_received",
        f"Everything for {order.code} is counted at Khazenly: the warehouse receipt is done",
    )


# ── Settle and cancel (the owner's) ──────────────────────────────────────────


def settle(db: Session, order_id: int, actor: UserAccount) -> ProdOrder:
    order = _open(db, order_id)
    facts = _facts(db, order)
    stage = _still_todo(facts, "settle")
    _earlier_done(facts, "settle")
    if any(d.needs_reason for d in facts.deliveries):
        raise Refused("A delivery's counts do not match and have no reason yet.")
    # The order is locked (by ``_open``); now the factory, always in that order.
    account.lock_supplier(db, order.factory_id)
    figures = settlement(facts)
    order.settled_payable_piastres = figures["payable_piastres"]
    order.settled_at = utcnow()
    order.settled_by = actor.id
    order.status = "closed"
    _mark_done(stage, actor, today())
    # What the factory is owed becomes a line of its account, in this same
    # transaction: dated today, tied to the order, and negative when the
    # rejects came to more than the work. A payable of nothing writes none.
    if figures["payable_piastres"] != 0:
        account.append(
            db, supplier_id=order.factory_id, kind="work", amount=figures["payable_piastres"],
            happened_on=today(), order_id=order.id, actor_id=actor.id,
        )
    _touch(order)
    _audit(db, order, actor, "settled", f"Settled {order.code} with the factory and closed it")
    return order


def cancel(db: Session, order_id: int, reason: str, actor: UserAccount) -> ProdOrder:
    """Cancel an open order. One cancelled **before cutting is done** writes
    nothing to any account. One cancelled **after cutting** keeps what the
    factory has earned (built as recommended on 15 November 2026, awaiting the
    owner's confirmation): in this same transaction, one ``work`` line on the
    factory's account for the payable so far (batch 1's ``settlement``), dated
    today, tied to the order, noted "Cancelled after cutting"; none at zero, a
    negative line when the rejects came to more than the work. The figure is
    frozen on the order as ``settle`` freezes it, so the order page still says
    what was owed, while the status stays ``cancelled`` (never ``closed``).
    The order is locked by ``_open``; the factory after it, always in that order."""
    reason = _text(reason, limit=500, what="the reason", required=True)
    order = _open(db, order_id)
    facts = _facts(db, order)
    if facts.done("cutting"):
        account.lock_supplier(db, order.factory_id)
        payable = settlement(facts)["payable_piastres"]
        order.settled_payable_piastres = payable
        order.settled_at = utcnow()
        order.settled_by = actor.id
        if payable != 0:
            account.append(
                db, supplier_id=order.factory_id, kind="work", amount=payable, happened_on=today(),
                order_id=order.id, note=CANCELLED_AFTER_CUTTING, actor_id=actor.id,
            )
    order.status = "cancelled"
    order.notes = (f"{order.notes}\n" if order.notes else "") + f"Cancelled: {reason}"
    _touch(order)
    _audit(db, order, actor, "cancelled", f"Cancelled {order.code}: {reason}")
    # Everything it took from fabric storage goes back (ADR 0089).
    _storage().return_all(db, order, actor)
    return order


# ── Money (the owner's alone) ─────────────────────────────────────────────────


def _part(order: ProdOrder, part: str) -> int:
    actual = getattr(order, f"actual_{part}_piastres")
    return actual if actual is not None else getattr(order, f"target_{part}_piastres")


def making_rate(order: ProdOrder) -> int:
    """Manufacturing, plus printing when the factory prints; actual where
    typed, else target."""
    rate = _part(order, "manufacturing")
    if order.printing == "factory":
        rate += _part(order, "printing")
    return rate


def piece_cost(order: ProdOrder) -> int:
    return sum(_part(order, part) for part in COST_PARTS)


def cost(order: ProdOrder) -> dict:
    typed = any(getattr(order, f"actual_{part}_piastres") is not None for part in COST_PARTS)
    return {
        "parts": [
            {
                "part": part,
                "label": PART_LABELS[part],
                "target_piastres": getattr(order, f"target_{part}_piastres"),
                "actual_piastres": getattr(order, f"actual_{part}_piastres"),
            }
            for part in COST_PARTS
        ],
        "target_total_piastres": sum(getattr(order, f"target_{part}_piastres") for part in COST_PARTS),
        #: Null until an actual is typed; then each part's actual, or its
        #: target where none is typed yet.
        "actual_total_piastres": piece_cost(order) if typed else None,
        "piece_cost_piastres": piece_cost(order),
    }


def cogs(facts: Facts) -> dict:
    """What the product costs to make: the piece cost (actual where typed,
    else target) over the pieces passed once the final inspection is done,
    else those cut once cutting is done, else those planned. **The owner's.**"""
    if facts.done("final_inspection"):
        basis = "passed"
    elif facts.done("cutting"):
        basis = "cut"
    else:
        basis = "planned"
    pieces = facts.total(basis)
    per_piece = piece_cost(facts.order)
    return {
        "per_piece_piastres": per_piece,
        "pieces": pieces,
        "pieces_basis": basis,
        "total_piastres": per_piece * pieces,
    }


def settlement(facts: Facts) -> dict:
    """What the factory is owed for this order (ADR 0084, decision 8)."""
    order = facts.order
    rate = making_rate(order)
    cut = facts.total("cut")
    rejected = facts.total("rejected")
    # A rejected piece is not paid for: the making, and the fabric too when
    # the factory bought it (the owner, 14 November 2026). Accessories and
    # packaging are HBA's own and never come off the factory.
    rejected_rate = rate if order.fabric_bought_by == "hba" else rate + _part(order, "fabric")
    held_pieces = facts.fix_not_returned
    work = cut * rate
    deduction = rejected * rejected_rate
    held = held_pieces * rate
    payable = work - deduction - held
    settled = order.settled_at is not None
    return {
        "making_rate_piastres": rate,
        "rate_includes_printing": order.printing == "factory",
        "pieces_cut": cut,
        "work_value_piastres": work,
        "rejected_pieces": rejected,
        "rejected_basis": "making" if order.fabric_bought_by == "hba" else "fabric_and_making",
        "rejected_rate_piastres": rejected_rate,
        "rejected_deduction_piastres": deduction,
        "held_pieces": held_pieces,
        "held_piastres": held,
        "payable_piastres": order.settled_payable_piastres if settled else payable,
        "settled": settled,
        "settled_at": _iso(order.settled_at),
    }


# ── What happens next, and how late ──────────────────────────────────────────


def lateness_days(facts: Facts, on: date) -> int:
    order = facts.order
    if order.status == "cancelled":
        return 0
    warehouse = facts.stages["warehouse"]
    if warehouse.status == "done":
        end = warehouse.done_on
    else:
        end = max(order.delivery_date, on)
    return max(0, (end - order.target_date).days)


def next_action(facts: Facts, on: date | None = None) -> dict | None:
    """What happens next on an open order, who does it (``owner`` | ``qc`` |
    ``factory``) and by when. The list, the order and the Tasks batch read
    this one function."""
    order = facts.order
    stage = facts.current
    if order.status != "open" or stage is None:
        return None
    key = stage.stage
    by = stage.expected_date
    done = [facts.stages[k].done_on for k in STAGES if facts.stages[k].done_on is not None]
    since = max(done) if done else None

    if key == "sample":
        if order.sample_status == "changes":
            what, who = "Factory to send the changed sample", "factory"
        else:
            what, who = "Approve the sample", "owner"
    elif key == "materials":
        what, who = "Record the materials arriving", "qc"
    elif key == "fabric_check":
        what, who = "Check the fabric", "qc"
    elif key == "pattern_check":
        what, who = "Check the pattern", "qc"
    elif key == "cutting":
        what, who = "Record cut quantities", "qc"
    elif key == "making":
        what, who, by = "Final inspection", "qc", order.delivery_date
    elif key == "final_inspection":
        what, who = "Finish the final inspection", "qc"
    elif key == "warehouse":
        to_come = max(0, facts.total("passed") - facts.shipped("finished"))
        if any(d.needs_reason for d in facts.deliveries):
            what, who = "Give a reason for the count that does not match", "qc"
        elif any(d.waiting_for_count for d in facts.deliveries):
            what, who = "Enter Khazenly's count", "qc"
        elif to_come:
            what, who, by = f"Receive {_plural(to_come, 'piece')}", "factory", order.delivery_date
        elif facts.fix_not_returned:
            what, who, by = f"Receive {_plural(facts.fix_not_returned, 'fix piece')}", "factory", order.delivery_date
        else:
            # Everything is shipped and counted, so this is a receipt the
            # owner reopened: saving a delivery completes it again.
            what, who = "Check the delivery counts", "qc"
    else:  # settle
        what, who = "Settle with the factory", "owner"
    return {"stage": key, "what": what, "who": who, "by": _day(by), "since": _day(since)}


def flags(facts: Facts, on: date) -> dict:
    order = facts.order
    open_ = order.status == "open"
    current = facts.current
    return {
        "late": lateness_days(facts, on) > 0,
        "waiting_for_owner": open_ and current is not None and (
            (current.stage == "sample" and order.sample_status == "pending") or current.stage == "settle"
        ),
        "count_mismatch": any(d.needs_reason for d in facts.deliveries),
        "fix_pieces_due": open_ and facts.done("final_inspection") and facts.fix_not_returned > 0,
    }


# ── Tasks, generated and never stored (batch 2) ──────────────────────────────

#: Which form of the order page each stage's work is done in (``open``, below).
_STAGE_FORM = {
    "materials": "stage:materials",
    "fabric_check": "stage:fabric_check",
    "pattern_check": "stage:pattern_check",
    "making": "stage:making",
    "cutting": "cut",
    "final_inspection": "inspection",
    "settle": "settle",
}


def _said_by_a_delivery_task(facts: Facts) -> bool:
    """Whether the warehouse stage's next action is work that one of the
    delivery tasks below already says, per delivery: a reason to give, a
    count to enter, or fix pieces to receive. Mirrors the branch order of
    ``next_action`` so each piece of work is one task, never two."""
    if any(d.needs_reason or d.waiting_for_count for d in facts.deliveries):
        return True
    to_come = max(0, facts.total("passed") - facts.shipped("finished"))
    return not to_come and facts.fix_not_returned > 0


def _difference_words(delivery: Delivery) -> str:
    short = sum(max(0, r.shipped - r.counted) for r in delivery.sizes.values() if r.counted is not None)
    over = sum(max(0, r.counted - r.shipped) for r in delivery.sizes.values() if r.counted is not None)
    parts = []
    if short:
        parts.append(_plural(short, "missing piece"))
    if over:
        parts.append(f"{_plural(over, 'piece')} more than shipped")
    return " and ".join(parts)


def _order_tasks(facts: Facts, factory: str | None, on: date, report: ProdCutReport | None = None) -> list[dict]:
    """One open order's tasks, in the order the build plan gives them: its
    next action; each delivery's missing reason; each delivery not yet
    counted; fix pieces not yet back. The same work is never listed twice.

    A cut the factory reported and the QC manager has not confirmed (batch
    6b) is "Confirm the factory's cut", due the day it was reported. At the
    cutting stage it **is** the stage's work, so it takes that task's place
    rather than sitting beside "Record cut quantities"."""
    order = facts.order
    ref = {"id": order.id, "code": order.code, "style_name": order.style_name, "colour": order.colour}

    def task(key: str, title: str, who: str, due: str | None, stage: str | None, since: str | None, form: str | None):
        return {
            "key": key,
            "title": title,
            "who": who,
            "due": due,
            "order": ref,
            "stage": stage,
            "waiting_on": factory if who == "factory" else None,
            "since": since,
            "open": form,
        }

    found: list[dict] = []

    if report is not None and facts.stages["cutting"].status == "todo":
        reported = _day(business_date(report.reported_at))
        found.append(task(f"order:{order.id}:cut-report", "Confirm the factory's cut", "qc", reported, "cutting", reported, "cut"))
    else:
        report = None

    action = next_action(facts, on)
    if action is not None and report is not None and action["stage"] == "cutting":
        action = None
    if action is not None and not (action["stage"] == "warehouse" and _said_by_a_delivery_task(facts)):
        stage, who = action["stage"], action["who"]
        if stage == "sample":
            form = "sample" if who == "owner" else None  # the factory is sending the changed sample
        elif stage == "warehouse":
            # Pieces still to come are recorded as a new delivery. With everything shipped and counted
            # (a receipt the owner reopened) the last delivery is checked again.
            to_come = max(0, facts.total("passed") - facts.shipped("finished"))
            form = "delivery" if to_come or not facts.deliveries else f"delivery:{facts.deliveries[-1].row.id}"
        else:
            form = _STAGE_FORM[stage]
        found.append(task(f"order:{order.id}:stage:{stage}", action["what"], who, action["by"], stage, action["since"], form))

    several = len(facts.deliveries) > 1
    for delivery in facts.deliveries:
        row = delivery.row
        if delivery.needs_reason:
            title = f"Give a reason for {_difference_words(delivery)}"
            if several:
                title += f", delivery {row.number}"
            found.append(
                task(
                    f"delivery:{row.id}:reason", title, "qc", _day(row.counted_on), "warehouse", _day(row.counted_on),
                    f"delivery-reason:{row.id}",
                )
            )
    for delivery in facts.deliveries:
        row = delivery.row
        if delivery.waiting_for_count:
            found.append(
                task(
                    f"delivery:{row.id}:count", f"Enter Khazenly's count for delivery {row.number}", "qc",
                    _day(row.shipped_on + timedelta(days=1)), "warehouse", _day(row.shipped_on), f"delivery:{row.id}",
                )
            )

    if flags(facts, on)["fix_pieces_due"]:
        found.append(
            task(
                f"order:{order.id}:fix", f"Receive {_plural(facts.fix_not_returned, 'fix piece')}", "factory",
                _day(order.delivery_date), "warehouse", _day(facts.stages["final_inspection"].done_on), "delivery:fix",
            )
        )
    return found


def generated_tasks(db: Session, on: date | None = None) -> list[dict]:
    """The work every open order is waiting on, worked out now from the
    orders (never stored). Unsorted and ungrouped: the Tasks module does
    that, and adds the tasks people typed in by hand."""
    on = on or today()
    open_orders = list(db.scalars(select(ProdOrder).where(ProdOrder.status == "open").order_by(ProdOrder.id)))
    facts = _facts_for(db, open_orders)
    factories = _suppliers(db, [o.factory_id for o in open_orders])
    reports = waiting_cut_reports(db, [o.id for o in open_orders])
    found: list[dict] = []
    for order in open_orders:
        found.extend(_order_tasks(facts[order.id], factories.get(order.factory_id), on, reports.get(order.id)))
    # Purchases still to arrive (batch 4): chased when late, checked on arrival.
    found.extend(account.purchase_tasks(db, on))
    return found


# ── Views ─────────────────────────────────────────────────────────────────────


def _people(db: Session, ids) -> dict[int, str]:
    wanted = {i for i in ids if i}
    if not wanted:
        return {}
    return {
        row.id: (row.display_name or "").strip() or row.email
        for row in db.execute(
            select(UserAccount.id, UserAccount.display_name, UserAccount.email).where(UserAccount.id.in_(wanted))
        ).all()
    }


def _suppliers(db: Session, ids) -> dict[str, str]:
    wanted = {i for i in ids if i}
    if not wanted:
        return {}
    return dict(db.execute(select(ProductionSupplier.id, ProductionSupplier.name).where(ProductionSupplier.id.in_(wanted))).all())


def _images(db: Session, product_ids) -> dict[str, str]:
    """The Shopify photo of each linked product that has one, so a row of the
    order lists can show what the style looks like."""
    wanted = {i for i in product_ids if i}
    if not wanted:
        return {}
    return {
        pid: url
        for pid, url in db.execute(
            select(Product.shopify_product_id, Product.image_url).where(Product.shopify_product_id.in_(wanted))
        ).all()
        if url
    }


def row_context(db: Session, orders: list[ProdOrder]) -> tuple[dict[str, str], dict[str, str]]:
    """What :func:`_row` needs besides the order's facts: the names of every
    factory and print house on the orders, and each linked product's photo."""
    suppliers = _suppliers(db, [o.factory_id for o in orders] + [o.print_supplier_id for o in orders])
    return suppliers, _images(db, [o.shopify_product_id for o in orders])


def _row(facts: Facts, suppliers: dict[str, str], on: date, images: dict[str, str] | None = None) -> dict:
    order = facts.order
    # A cancelled or closed order is at no stage: it is not going anywhere.
    current = facts.current if order.status == "open" else None
    finished_counted = [d for d in facts.of_kind("finished") if d.row.counted_on is not None]
    warehouse = facts.stages["warehouse"]
    return {
        "id": order.id,
        "code": order.code,
        "style_name": order.style_name,
        "colour": order.colour,
        "status": order.status,
        "factory": {"id": order.factory_id, "name": suppliers.get(order.factory_id)},
        "stage": None
        if current is None
        else {"key": current.stage, "label": STAGE_LABELS[current.stage], "position": current.position},
        "steps": [facts.stages[key].status for key in STAGES],
        "planned_total": facts.total("planned"),
        "cut_total": facts.total("cut") if facts.recorded("cut") else None,
        "shipped_total": facts.shipped("finished"),
        "received_total": sum(d.counted or 0 for d in finished_counted) if finished_counted else None,
        "target_date": _day(order.target_date),
        "delivery_date": _day(order.delivery_date),
        "lateness_days": lateness_days(facts, on),
        "finished_on": _day(warehouse.done_on) if warehouse.status == "done" else None,
        "next_action": next_action(facts, on),
        "flags": flags(facts, on),
        # The style's photo, and what else the lists' search box looks through.
        "image_url": (images or {}).get(order.shopify_product_id or ""),
        "colour_code": order.colour_code,
        "fabric_type": order.fabric_type,
        "print_supplier_name": suppliers.get(order.print_supplier_id) if order.print_supplier_id else None,
        "notes": order.notes,
    }


def rows(db: Session, status: str) -> list[dict]:
    query = select(ProdOrder)
    if status == "open":
        query = query.where(ProdOrder.status == "open").order_by(ProdOrder.delivery_date, ProdOrder.id)
    else:
        query = query.where(ProdOrder.status.in_(("closed", "cancelled"))).order_by(ProdOrder.updated_at.desc())
    orders = list(db.scalars(query))
    facts = _facts_for(db, orders)
    suppliers, images = row_context(db, orders)
    on = today()
    return [_row(facts[order.id], suppliers, on, images) for order in orders]


#: The role a purchase's part gives its supplier on the product.
_PURCHASE_ROLES = {
    "fabric": "Fabric",
    "printing": "Printing",
    "accessories": "Accessories",
    "packaging": "Packaging",
    "other": "Other",
}
#: The order roles are told in: the factory's, the print house's, then the purchases'.
_ROLE_ORDER = ("Factory", "Printing", "Fabric", "Accessories", "Packaging", "Other")


def product_suppliers(db: Session, order: ProdOrder) -> list[dict]:
    """Who supplies this product, by name and role, **no money**: the factory,
    the outside print house, and the supplier of every purchase tied to the
    order that is not voided. One entry a supplier; the factory first, then by
    name."""
    roles: dict[str, set[str]] = {order.factory_id: {"Factory"}}
    if order.printing == "outside" and order.print_supplier_id:
        roles.setdefault(order.print_supplier_id, set()).add("Printing")
    for supplier_id, part in db.execute(
        select(ProdPurchase.supplier_id, ProdPurchase.cost_part).where(
            ProdPurchase.order_id == order.id, ProdPurchase.voided_at.is_(None)
        )
    ).all():
        roles.setdefault(supplier_id, set()).add(_PURCHASE_ROLES.get(part, "Other"))
    names = _suppliers(db, roles)
    ordered = sorted(roles, key=lambda sid: (sid != order.factory_id, (names.get(sid) or "").lower(), sid))
    return [
        {"id": sid, "name": names.get(sid), "roles": [role for role in _ROLE_ORDER if role in roles[sid]]}
        for sid in ordered
    ]


def _product_files(db: Session, order_id: int) -> dict[str, list[dict]]:
    from app.modules.production.orders.services import files  # files imports this module

    rows = list(
        db.scalars(
            select(ProdOrderFile)
            .where(
                ProdOrderFile.order_id == order_id,
                ProdOrderFile.deleted_at.is_(None),
                ProdOrderFile.kind.is_not(None),
            )
            .order_by(ProdOrderFile.created_at.desc(), ProdOrderFile.id.desc())
        )
    )
    people = _people(db, [row.uploaded_by for row in rows])
    return {
        kind: [files.view(row, people) for row in rows if row.kind == kind]
        for kind in ("pattern", "size_chart")
    }


def product_view(db: Session, order: ProdOrder) -> dict:
    """The Product card: the details, who supplies it, its pattern files and
    size charts. For anybody who reads Production; no money."""
    found = _product_files(db, order.id)
    return {
        "colour_code": order.colour_code,
        "fabric_type": order.fabric_type,
        "decoration_type": order.decoration_type,
        "decoration_width_cm": _width_text(order.decoration_width_cm),
        "suppliers": product_suppliers(db, order),
        "pattern_files": found["pattern"],
        "size_charts": found["size_chart"],
    }


def view(db: Session, order_id: int, *, with_money: bool) -> dict:
    order = _order(db, order_id)
    facts = _facts(db, order)
    on = today()
    suppliers = _suppliers(db, [order.factory_id, order.print_supplier_id])
    changes = list(
        db.scalars(
            select(ProdOrderDateChange)
            .where(ProdOrderDateChange.order_id == order.id)
            .order_by(ProdOrderDateChange.created_at, ProdOrderDateChange.id)
        )
    )
    people = _people(
        db,
        [order.created_by, order.sample_decided_by, order.settled_by]
        + [s.done_by for s in facts.stages.values()]
        + [c.created_by for c in changes],
    )
    files_count = db.scalar(
        select(func.count()).select_from(ProdOrderFile).where(
            ProdOrderFile.order_id == order.id, ProdOrderFile.deleted_at.is_(None)
        )
    )

    def per_size(size: str) -> dict:
        row = facts.sizes.get(size)
        finished = [d.sizes[size] for d in facts.of_kind("finished") if size in d.sizes]
        fixes = [d.sizes[size] for d in facts.of_kind("fix") if size in d.sizes]
        return {
            "size": size,
            "planned": row.planned if row else 0,
            "cut": row.cut if row else None,
            "passed": row.passed if row else None,
            "to_fix": row.to_fix if row else None,
            "rejected": row.rejected if row else None,
            "shipped": sum(r.shipped for r in finished),
            "counted": sum(r.counted or 0 for r in finished if r.counted is not None),
            "fix_shipped": sum(r.shipped for r in fixes),
            "fix_counted": sum(r.counted or 0 for r in fixes if r.counted is not None),
        }

    sizes = [per_size(size) for size in SIZES if size in facts.sizes]
    totals = {
        key: (sum(s[key] or 0 for s in sizes) if any(s[key] is not None for s in sizes) else None)
        for key in ("planned", "cut", "passed", "to_fix", "rejected", "shipped", "counted", "fix_shipped", "fix_counted")
    }
    warehouse = facts.stages["warehouse"]
    current = facts.current if order.status == "open" else None
    body = {
        **_row(facts, suppliers, on, _images(db, [order.shopify_product_id])),
        "shopify_product_id": order.shopify_product_id,
        "fabric_bought_by": order.fabric_bought_by,
        "printing": order.printing,
        "print_supplier": None
        if order.print_supplier_id is None
        else {"id": order.print_supplier_id, "name": suppliers.get(order.print_supplier_id)},
        "repeat_run": order.repeat_run,
        "notes": order.notes,
        "created_at": _iso(order.created_at),
        "created_by": people.get(order.created_by),
        "current_stage": current.stage if current is not None else None,
        "sample": {
            "status": order.sample_status,
            "note": order.sample_note,
            "decided_by": people.get(order.sample_decided_by),
            "decided_at": _iso(order.sample_decided_at),
        },
        "stages": [
            {
                "key": key,
                "label": STAGE_LABELS[key],
                "position": facts.stages[key].position,
                "status": facts.stages[key].status,
                "expected_date": _day(facts.stages[key].expected_date),
                "done_on": _day(facts.stages[key].done_on),
                "done_by": people.get(facts.stages[key].done_by),
                "note": facts.stages[key].note,
            }
            for key in STAGES
        ],
        "sizes": sizes,
        "totals": totals,
        "reasons": {
            kind: [{"id": r.id, "reason": r.reason, "quantity": r.quantity} for r in facts.reasons if r.kind == kind]
            for kind in ("cut_short", "rejected", "to_fix")
        },
        "date_history": [
            {
                "id": c.id,
                "old_date": _day(c.old_date),
                "new_date": _day(c.new_date),
                "set_by": c.set_by,
                "reason": c.reason,
                "created_at": _iso(c.created_at),
                "created_by": people.get(c.created_by),
            }
            for c in changes
        ],
        "deliveries": [
            {
                "id": d.row.id,
                "number": d.row.number,
                "kind": d.row.kind,
                "shipped_on": _day(d.row.shipped_on),
                "counted_on": _day(d.row.counted_on),
                "mismatch_reason": d.row.mismatch_reason,
                "sizes": [
                    {"size": size, "shipped": d.sizes[size].shipped, "counted": d.sizes[size].counted}
                    for size in SIZES
                    if size in d.sizes
                ],
                "shipped_total": d.shipped,
                "counted_total": d.counted,
                "waiting_for_count": d.waiting_for_count,
                "mismatch": d.mismatch,
                "needs_reason": d.needs_reason,
            }
            for d in facts.deliveries
        ],
        "fix_not_returned": facts.fix_not_returned if facts.done("final_inspection") else None,
        "files_count": files_count,
        "product": product_view(db, order),
        "warehouse_done_on": _day(warehouse.done_on),
        #: What the factory reported cutting, waiting for the QC manager
        #: (batch 6b): the Cutting stage shows it and the cut form opens with
        #: it. Only while cutting is still to record.
        "cut_report": cut_report_view(waiting_cut_reports(db, [order.id]).get(order.id))
        if facts.stages["cutting"].status == "todo"
        else None,
    }
    # The fabric it took from storage, for everybody; what that cost, for the
    # owner only, over the pieces cut once cutting is done, else those planned.
    cut_done = facts.done("cutting")
    body.update(
        _storage().order_fabric(
            db, order, facts.total("cut") if cut_done else facts.total("planned"),
            "cut" if cut_done else "planned", with_money=with_money,
        )
    )
    if with_money:
        body["cost"] = cost(order)
        # What the purchases tied to this order say each part costs per piece:
        # over the pieces cut once cutting is done, else over those planned.
        body["cost"]["from_purchases"] = account.from_purchases(
            db, order.id, facts.total("cut") if cut_done else facts.total("planned"),
            "cut" if cut_done else "planned",
        )
        body["cost"]["cogs"] = cogs(facts)
        body["settlement"] = settlement(facts) if facts.done("cutting") else None
    return body


# ── History ───────────────────────────────────────────────────────────────────


def history(db: Session, order_id: int) -> dict:
    order = _order(db, order_id)
    events = list(
        db.scalars(
            select(AuditEvent)
            .where(AuditEvent.subject == f"production:order:{order.id}")
            .order_by(AuditEvent.created_at.desc(), AuditEvent.id.desc())
            .limit(500)
        )
    )
    people = _people(db, [e.actor_id for e in events])
    return {
        "events": [
            {
                "id": e.id,
                "at": _iso(e.created_at),
                "who": people.get(e.actor_id) or e.actor_email,
                "action": e.action,
                "summary": (e.after_json or {}).get("summary"),
            }
            for e in events
        ]
    }
