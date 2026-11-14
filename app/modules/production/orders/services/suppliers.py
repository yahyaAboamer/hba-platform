"""Production's Suppliers (ADR 0084, decision 9; build plan
``docs/plans/2026-11-14-production-suppliers-build.md``).

Sections, the suppliers in them, what HBA bought from each, and each
supplier's running account. Every write here only stages; the route commits on
success and rolls back on a refusal (``Refused`` -> 422, ``Locked`` -> 409,
``NotFound`` -> 404), as in ``orders``.

**Money is integer piastres** (ADR 0002) and the owner's alone: a view carries
a price, a total, an account, an amount owed or held, or a receipt only when
asked ``with_money=True``; without it those keys are absent, not null. The
history (``audit_event``) never carries an amount: its sentences are words.

**The account is append-only.** A line is never edited or deleted (the
database refuses it); a mistake is undone by a reversing line, once. Whoever
changes an account takes the supplier's row lock first (``account.lock_supplier``)
and only then reads a balance.

What HBA owes a supplier now is the sum of its lines plus what its open orders
(cutting done, not yet settled) would pay it so far, which is worked out on
each read and is **not** a line until the order is settled; settling replaces
it with the real line, so nothing is counted twice.
"""

import uuid
from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from sqlalchemy import func, or_, select, text
from sqlalchemy.orm import Session

from app.core.businesstime import utcnow
from app.modules.inbox.public import file_bucket
from app.modules.production.models import ProductionSupplier
from app.modules.production.orders.models import (
    PAY_KINDS,
    PAY_METHODS,
    PURCHASE_PARTS,
    PURCHASE_UNITS,
    STAGE_LABELS,
    ProdOrder,
    ProdPurchase,
    ProdSection,
    ProdSupplierEntry,
    ProdSupplierReceipt,
    ProdSupplierSection,
)
from app.modules.production.orders.services import account
from app.modules.production.orders.services.files import MAX_BYTES, file_type
from app.modules.production.orders.services.orders import (
    Facts,
    Locked,
    NotFound,
    Refused,
    _day,
    _facts_for,
    _iso,
    _not_future,
    _people,
    _text,
    _words,
    settlement,
    today,
)
from app.shared.models.identity import UserAccount
from app.shared.services.audit import record_audit

#: The most one account line may be: EGP 100,000,000, as a guard against a slipped zero.
MAX_LINE_PIASTRES = 10_000_000_000
#: The most one unit may cost: EGP 1,000,000.
MAX_UNIT_PIASTRES = 100_000_000
#: The most one purchase may be of: a million units.
MAX_QUANTITY = Decimal("1000000")

METHOD_LABELS = {
    "bank_transfer": "Bank transfer",
    "cash": "Cash",
    "instapay": "InstaPay",
    "wallet": "Mobile wallet",
    "cheque": "Cheque",
}
PAY_KIND_LABELS = {"weekly": "Weekly payment", "deposit": "Deposit", "final": "Final payment"}

#: The locks two simultaneous saves queue on, so neither can take the same
#: ``SUP-NNN`` code or the same section name and have one fail on a unique key.
_SUPPLIER_CODE_LOCK = 840_002
_SECTION_LOCK = 840_003


# ── Small helpers ─────────────────────────────────────────────────────────────


def _audit(db: Session, subject: str, actor: UserAccount, what: str, summary: str, **extra) -> None:
    """One history entry. **Never an amount**: the history is read by
    everybody in Production, and a reason typed by the owner stays out of it
    too (it is kept with the purchase or the line, for the owner)."""
    record_audit(
        db,
        action=f"production.{what}",
        subject=subject,
        actor_id=actor.id,
        actor_email=actor.email,
        after={"summary": summary[:500], **extra},
    )


def _subject(supplier: ProductionSupplier) -> str:
    return f"production:supplier:{supplier.id}"


def _supplier(db: Session, supplier_id: str | None, *, for_update: bool = False) -> ProductionSupplier:
    supplier = None
    if supplier_id:
        supplier = (
            account.lock_supplier(db, supplier_id) if for_update else db.get(ProductionSupplier, supplier_id)
        )
    if supplier is None or supplier.deleted_at is not None:
        raise NotFound("There is no such supplier.")
    return supplier


def _amount(value, what: str, *, signed: bool = False) -> int:
    """A whole number of piastres: above 0, or (``signed``) anything but 0."""
    if not isinstance(value, int) or isinstance(value, bool):
        raise Refused(f"{what} must be a whole number of piastres.")
    if value == 0 or (value < 0 and not signed):
        raise Refused(f"{what} must be more than 0." if not signed else f"{what} can't be 0.")
    if abs(value) > MAX_LINE_PIASTRES:
        raise Refused(f"{what} is too large. Check the number.")
    return value


def _choice(value, allowed: tuple[str, ...], what: str) -> str:
    if value not in allowed:
        raise Refused(f"Choose {what} from the list.")
    return value


def quantity_text(quantity: Decimal) -> str:
    """A quantity as a plain decimal string: 12.5, never 12.500 or 1.25E+1."""
    text_ = format(quantity.normalize(), "f")
    return text_


def purchase_total(quantity: Decimal, unit_price_piastres: int) -> int:
    """Quantity times unit price, rounded half up to a whole piastre. Decimal
    all the way: never a float."""
    return int((quantity * Decimal(unit_price_piastres)).quantize(Decimal(1), rounding=ROUND_HALF_UP))


# ── Sections ──────────────────────────────────────────────────────────────────


def _live_sections(db: Session) -> list[ProdSection]:
    return list(
        db.scalars(
            select(ProdSection).where(ProdSection.deleted_at.is_(None)).order_by(ProdSection.position, ProdSection.id)
        )
    )


def sections_view(db: Session) -> list[dict]:
    counts = dict(
        db.execute(
            select(ProdSupplierSection.section_id, func.count())
            .join(ProductionSupplier, ProductionSupplier.id == ProdSupplierSection.supplier_id)
            .where(ProductionSupplier.deleted_at.is_(None))
            .group_by(ProdSupplierSection.section_id)
        ).all()
    )
    return [
        {"id": s.id, "name": s.name, "position": s.position, "supplier_count": counts.get(s.id, 0)}
        for s in _live_sections(db)
    ]


def _section_audit(db: Session, section: ProdSection, actor: UserAccount, what: str, summary: str) -> None:
    _audit(db, f"production:section:{section.id}", actor, f"section_{what}", summary)


def _section_name(db: Session, value: str | None, *, keep: int | None = None) -> str:
    name = _text(value, limit=60, what="the section's name", required=True) or ""
    db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": _SECTION_LOCK})
    other = db.scalar(
        select(ProdSection).where(func.lower(ProdSection.name) == name.lower(), ProdSection.id != (keep or 0))
    )
    if other is not None and other.deleted_at is None:
        raise Refused(f"There is already a section called {other.name}.")
    if other is not None:
        # The name of a removed section is not free until it is brought back.
        raise Refused(f"{other.name} was a section that was removed. Add it again to bring it back.")
    return name


def add_section(db: Session, name: str, actor: UserAccount) -> ProdSection:
    cleaned = _text(name, limit=60, what="the section's name", required=True) or ""
    db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": _SECTION_LOCK})
    last = db.scalar(select(func.coalesce(func.max(ProdSection.position), 0)))
    existing = db.scalar(select(ProdSection).where(func.lower(ProdSection.name) == cleaned.lower()))
    if existing is not None and existing.deleted_at is None:
        raise Refused(f"There is already a section called {existing.name}.")
    if existing is not None:
        # Adding a removed section's name again brings it back, at the end.
        existing.name = cleaned
        existing.deleted_at = None
        existing.position = last + 1
        section = existing
    else:
        section = ProdSection(name=cleaned, position=last + 1, created_by=actor.id)
        db.add(section)
    db.flush()
    _section_audit(db, section, actor, "added", f"Added the supplier section {section.name}")
    return section


def rename_section(db: Session, section_id: int, name: str, actor: UserAccount) -> ProdSection:
    section = db.get(ProdSection, section_id, with_for_update=True)
    if section is None or section.deleted_at is not None:
        raise NotFound("There is no such section.")
    cleaned = _section_name(db, name, keep=section.id)
    if cleaned != section.name:
        before = section.name
        section.name = cleaned
        db.flush()
        _section_audit(db, section, actor, "renamed", f"Renamed the supplier section {before} to {cleaned}")
    return section


def remove_section(db: Session, section_id: int, actor: UserAccount) -> ProdSection:
    section = db.get(ProdSection, section_id, with_for_update=True)
    if section is None or section.deleted_at is not None:
        raise NotFound("There is no such section.")
    inside = db.scalar(
        select(func.count())
        .select_from(ProdSupplierSection)
        .join(ProductionSupplier, ProductionSupplier.id == ProdSupplierSection.supplier_id)
        .where(ProdSupplierSection.section_id == section.id, ProductionSupplier.deleted_at.is_(None))
    )
    if inside:
        noun = "supplier is" if inside == 1 else "suppliers are"
        raise Refused(f"{inside} {noun} still in {section.name}. Move them to another section first.")
    section.deleted_at = utcnow()
    _section_audit(db, section, actor, "removed", f"Removed the supplier section {section.name}")
    return section


# ── Suppliers ─────────────────────────────────────────────────────────────────

_FIELDS = {
    "name": ("the name", 180),
    "contact_person": ("the contact person", 180),
    "phone": ("the phone", 180),
    "whatsapp": ("the WhatsApp number", 180),
    "city": ("the city", 180),
    "notes": ("the notes", 2000),
}


def _sections_for(db: Session, ids) -> list[ProdSection]:
    wanted = list(dict.fromkeys(ids or []))
    if not wanted:
        return []
    found = {s.id: s for s in db.scalars(select(ProdSection).where(ProdSection.id.in_(wanted)))}
    for section_id in wanted:
        section = found.get(section_id)
        if section is None or section.deleted_at is not None:
            raise Refused("Choose the sections from the list.")
    return [found[section_id] for section_id in wanted]


def _next_code(db: Session) -> str:
    db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": _SUPPLIER_CODE_LOCK})
    sequence = (db.scalar(select(func.count()).select_from(ProductionSupplier)) or 0) + 1
    while db.scalar(select(ProductionSupplier.id).where(ProductionSupplier.code == f"SUP-{sequence:03d}")):
        sequence += 1
    return f"SUP-{sequence:03d}"


def add_supplier(db: Session, data: dict, actor: UserAccount) -> ProductionSupplier:
    name = _text(data.get("name"), limit=180, what="the supplier's name", required=True)
    sections = _sections_for(db, data.get("section_ids"))
    values = {
        key: _text(data.get(key), limit=limit, what=what)
        for key, (what, limit) in _FIELDS.items()
        if key != "name"
    }
    supplier = ProductionSupplier(
        id=str(uuid.uuid4()), code=_next_code(db), name=name, active=True, **values
    )
    db.add(supplier)
    db.flush()
    for section in sections:
        db.add(ProdSupplierSection(supplier_id=supplier.id, section_id=section.id))
    db.flush()
    where = f" in {_words([s.name for s in sections])}" if sections else ""
    _audit(db, _subject(supplier), actor, "supplier_added", f"Added the supplier {name}{where}")
    return supplier


def edit_supplier(db: Session, supplier_id: str, data: dict, actor: UserAccount) -> ProductionSupplier:
    """Change what was sent; what is left out stays as it was. A supplier is
    never deleted, only made inactive."""
    supplier = _supplier(db, supplier_id, for_update=True)
    changed: list[str] = []
    for key, (what, limit) in _FIELDS.items():
        if key not in data:
            continue
        value = _text(data[key], limit=limit, what=what, required=key == "name")
        if value != getattr(supplier, key):
            setattr(supplier, key, value)
            changed.append(what)
    if "section_ids" in data:
        sections = _sections_for(db, data["section_ids"])
        current = set(db.scalars(select(ProdSupplierSection.section_id).where(ProdSupplierSection.supplier_id == supplier.id)))
        wanted = {s.id for s in sections}
        if wanted != current:
            for link in db.scalars(select(ProdSupplierSection).where(ProdSupplierSection.supplier_id == supplier.id)):
                if link.section_id not in wanted:
                    db.delete(link)
            for section_id in wanted - current:
                db.add(ProdSupplierSection(supplier_id=supplier.id, section_id=section_id))
            changed.append("the sections")
    flipped = data.get("active") is not None and bool(data["active"]) != supplier.active
    if flipped:
        supplier.active = bool(data["active"])
    if changed or flipped:
        supplier.updated_at = utcnow()
        db.flush()
    if changed:
        _audit(db, _subject(supplier), actor, "supplier_changed", f"Changed {_words(changed)} of {supplier.name}")
    if flipped:
        _audit(
            db, _subject(supplier), actor,
            "supplier_activated" if supplier.active else "supplier_deactivated",
            f"Made {supplier.name} {'active again' if supplier.active else 'inactive'}",
        )
    return supplier


# ── Purchases (the owner's) ───────────────────────────────────────────────────


def _quantity(value) -> Decimal:
    try:
        quantity = value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise Refused("Give the quantity as a number.") from None
    if not quantity.is_finite() or quantity <= 0:
        raise Refused("The quantity must be more than 0.")
    if quantity > MAX_QUANTITY:
        raise Refused("That quantity is too large. Check the number.")
    if quantity != quantity.quantize(Decimal("0.001")):
        raise Refused("The quantity can have at most three decimal places.")
    return quantity


def add_purchase(db: Session, supplier_id: str, data: dict, actor: UserAccount) -> tuple[ProductionSupplier, ProdPurchase]:
    """Record a purchase: one purchase line on the account, and, when a
    deposit is paid now, a second line for it. The total is worked out here,
    never typed."""
    supplier = _supplier(db, supplier_id, for_update=True)
    if not supplier.active:
        raise Refused(f"{supplier.name} is not an active supplier.")
    item = _text(data.get("item"), limit=200, what="what was bought", required=True)
    unit = _choice(data.get("unit"), PURCHASE_UNITS, "how it is measured")
    part = _choice(data.get("part"), PURCHASE_PARTS, "which part of the cost it is")
    quantity = _quantity(data.get("quantity"))
    price = _amount(data.get("unit_price_piastres"), "The price per unit")
    if price > MAX_UNIT_PIASTRES:
        raise Refused("The price per unit is too large. Check the number.")
    total = purchase_total(quantity, price)
    if total < 1:
        raise Refused("That comes to less than a piastre. Check the quantity and the price.")
    if total > MAX_LINE_PIASTRES:
        raise Refused("That total is too large. Check the quantity and the price.")
    order = None
    if data.get("order_id"):
        order = db.get(ProdOrder, data["order_id"])
        if order is None or order.status != "open":
            raise Refused("Pick an order that is still in production.")
    bought_on = _not_future(data.get("bought_on"), "The purchase date")
    deposit = data.get("deposit_piastres") or 0
    method = data.get("deposit_method")
    if deposit:
        _amount(deposit, "The deposit")
        if deposit > total:
            raise Refused("The deposit can't be more than the total.")
        _choice(method, PAY_METHODS, "how the deposit was paid")
    purchase = ProdPurchase(
        supplier_id=supplier.id, order_id=order.id if order else None, item=item, quantity=quantity, unit=unit,
        unit_price_piastres=price, total_piastres=total, cost_part=part, expected_on=data.get("expected_on"),
        note=_text(data.get("note"), limit=2000, what="the note"), created_by=actor.id,
    )
    db.add(purchase)
    db.flush()
    account.append(
        db, supplier_id=supplier.id, kind="purchase", amount=total, happened_on=bought_on,
        purchase_id=purchase.id, order_id=purchase.order_id, actor_id=actor.id,
    )
    if deposit:
        account.append(
            db, supplier_id=supplier.id, kind="payment", amount=-deposit, happened_on=bought_on,
            purchase_id=purchase.id, order_id=purchase.order_id, method=method, payment_kind="deposit",
            actor_id=actor.id,
        )
    for_order = f" for {order.code}" if order else ""
    _audit(
        db, _subject(supplier), actor, "purchase_added",
        f"Recorded a purchase of {item} from {supplier.name}{for_order}", purchase=purchase.id,
    )
    return supplier, purchase


def edit_purchase(
    db: Session, purchase_id: int, data: dict, actor: UserAccount
) -> tuple[ProductionSupplier, ProdPurchase]:
    """The only things that change on a purchase: when it is expected, when it
    came, and its note. Money never does (void it instead)."""
    purchase = db.get(ProdPurchase, purchase_id)
    if purchase is None:
        raise NotFound("There is no such purchase.")
    supplier = _supplier(db, purchase.supplier_id, for_update=True)
    db.refresh(purchase)
    if purchase.voided_at is not None:
        raise Locked("This purchase was voided. Nothing on it can change now.")
    subject = _subject(supplier)
    changed: list[str] = []
    if "expected_on" in data and data["expected_on"] != purchase.expected_on:
        purchase.expected_on = data["expected_on"]
        changed.append("the expected date")
    if "note" in data:
        note = _text(data["note"], limit=2000, what="the note")
        if note != purchase.note:
            purchase.note = note
            changed.append("the note")
    if changed:
        _audit(db, subject, actor, "purchase_changed", f"Changed {_words(changed)} of the {purchase.item} purchase from {supplier.name}", purchase=purchase.id)
    if "received_on" in data and data["received_on"] != purchase.received_on:
        received = data["received_on"]
        if received is not None:
            received = _not_future(received, "The date it arrived")
        purchase.received_on = received
        _audit(
            db, subject, actor, "purchase_received" if received else "purchase_unreceived",
            f"Marked the {purchase.item} purchase from {supplier.name} as "
            + ("received" if received else "not received yet"),
            purchase=purchase.id,
        )
    db.flush()
    return supplier, purchase


def _live_lines(db: Session, **where) -> list[ProdSupplierEntry]:
    """Lines that still stand: not reversed, and not themselves reversals."""
    reversed_ids = select(ProdSupplierEntry.reverses_id).where(ProdSupplierEntry.reverses_id.is_not(None))
    query = select(ProdSupplierEntry).where(
        ProdSupplierEntry.reverses_id.is_(None), ProdSupplierEntry.id.not_in(reversed_ids)
    )
    for column, value in where.items():
        query = query.where(getattr(ProdSupplierEntry, column) == value)
    return list(db.scalars(query.order_by(ProdSupplierEntry.id)))


def _reverse_line(db: Session, entry: ProdSupplierEntry, reason: str, actor: UserAccount) -> ProdSupplierEntry:
    return account.append(
        db, supplier_id=entry.supplier_id, kind=entry.kind, amount=-entry.amount_piastres, happened_on=today(),
        order_id=entry.order_id, purchase_id=entry.purchase_id, method=entry.method,
        payment_kind=entry.payment_kind, note=reason, reverses_id=entry.id, actor_id=actor.id,
    )


def void_purchase(
    db: Session, purchase_id: int, reason: str, actor: UserAccount
) -> tuple[ProductionSupplier, ProdPurchase]:
    """Void a purchase: it stays, struck through, and its line and its
    deposit's line are each reversed by a line of their own."""
    reason = _text(reason, limit=400, what="the reason", required=True)
    purchase = db.get(ProdPurchase, purchase_id)
    if purchase is None:
        raise NotFound("There is no such purchase.")
    supplier = _supplier(db, purchase.supplier_id, for_update=True)
    db.refresh(purchase)
    if purchase.voided_at is not None:
        raise Locked("This purchase was already voided.")
    purchase.voided_at = utcnow()
    purchase.voided_by = actor.id
    purchase.void_reason = reason
    for line in _live_lines(db, purchase_id=purchase.id):
        _reverse_line(db, line, reason, actor)
    db.flush()
    _audit(
        db, _subject(supplier), actor, "purchase_voided",
        f"Voided the purchase of {purchase.item} from {supplier.name}", purchase=purchase.id,
    )
    return supplier, purchase


# ── The account (the owner's) ─────────────────────────────────────────────────


def record_payment(db: Session, supplier_id: str, data: dict, actor: UserAccount) -> tuple[ProductionSupplier, ProdSupplierEntry]:
    """A lump sum paid to a supplier (not to an order): one line, negative."""
    supplier = _supplier(db, supplier_id, for_update=True)
    amount = _amount(data.get("amount_piastres"), "The amount")
    method = _choice(data.get("method"), PAY_METHODS, "how it was paid")
    kind = _choice(data.get("kind"), PAY_KINDS, "what the payment is")
    paid_on = _not_future(data.get("paid_on"), "The payment date")
    entry = account.append(
        db, supplier_id=supplier.id, kind="payment", amount=-amount, happened_on=paid_on, method=method,
        payment_kind=kind, note=_text(data.get("note"), limit=500, what="the note"), actor_id=actor.id,
    )
    _audit(db, _subject(supplier), actor, "payment_recorded", f"Recorded a payment to {supplier.name}", entry=entry.id)
    return supplier, entry


def _live_opening(db: Session, supplier_id: str) -> bool:
    return bool(_live_lines(db, supplier_id=supplier_id, kind="opening"))


def record_opening(db: Session, supplier_id: str, data: dict, actor: UserAccount) -> tuple[ProductionSupplier, ProdSupplierEntry]:
    """The balance brought forward: one line a supplier, positive when HBA
    owes, negative when HBA has overpaid. Corrected later by an adjustment."""
    supplier = _supplier(db, supplier_id, for_update=True)
    amount = _amount(data.get("amount_piastres"), "The balance", signed=True)
    on = _not_future(data.get("happened_on"), "The date")
    if _live_opening(db, supplier.id):
        raise Refused(
            f"{supplier.name} already has a balance brought forward. Correct it with an adjustment, "
            "or reverse it first."
        )
    entry = account.append(
        db, supplier_id=supplier.id, kind="opening", amount=amount, happened_on=on,
        note=_text(data.get("note"), limit=500, what="the note"), actor_id=actor.id,
    )
    _audit(
        db, _subject(supplier), actor, "supplier_opening_recorded",
        f"Recorded the balance brought forward for {supplier.name}", entry=entry.id,
    )
    return supplier, entry


def record_adjustment(db: Session, supplier_id: str, data: dict, actor: UserAccount) -> tuple[ProductionSupplier, ProdSupplierEntry]:
    supplier = _supplier(db, supplier_id, for_update=True)
    amount = _amount(data.get("amount_piastres"), "The adjustment", signed=True)
    note = _text(data.get("note"), limit=500, what="the note that says why", required=True)
    on = _not_future(data.get("happened_on"), "The date")
    entry = account.append(
        db, supplier_id=supplier.id, kind="adjustment", amount=amount, happened_on=on, note=note, actor_id=actor.id
    )
    _audit(
        db, _subject(supplier), actor, "supplier_adjusted",
        f"Recorded an adjustment on {supplier.name}'s account", entry=entry.id,
    )
    return supplier, entry


def reverse_entry(db: Session, entry_id: int, reason: str, actor: UserAccount) -> tuple[ProductionSupplier, ProdSupplierEntry]:
    """Undo a line with a reversing one, once. A work line comes from settling
    an order and can't be reversed; a purchase's line goes with the purchase
    (void it)."""
    reason = _text(reason, limit=400, what="the reason", required=True)
    entry = db.get(ProdSupplierEntry, entry_id)
    if entry is None:
        raise NotFound("There is no such line on the account.")
    supplier = _supplier(db, entry.supplier_id, for_update=True)
    if entry.kind == "work":
        raise Refused("A work line comes from settling the order and can't be reversed.")
    if entry.kind == "purchase":
        raise Refused("A purchase is undone by voiding it, which reverses its lines.")
    if entry.reverses_id is not None:
        raise Refused("That line is itself a reversal. Record a new line instead.")
    if db.scalar(select(ProdSupplierEntry.id).where(ProdSupplierEntry.reverses_id == entry.id)) is not None:
        raise Locked("That line has already been reversed.")
    reversal = _reverse_line(db, entry, reason, actor)
    words = {
        "payment": ("payment_reversed", f"Reversed a payment to {supplier.name}"),
        "opening": ("supplier_line_reversed", f"Reversed the balance brought forward for {supplier.name}"),
        "adjustment": ("supplier_line_reversed", f"Reversed an adjustment on {supplier.name}'s account"),
    }
    what, summary = words[entry.kind]
    _audit(db, _subject(supplier), actor, what, summary, entry=entry.id)
    return supplier, reversal


# ── Receipts (the owner's) ────────────────────────────────────────────────────


def _payment_entry(db: Session, entry_id: int) -> ProdSupplierEntry:
    entry = db.get(ProdSupplierEntry, entry_id)
    if entry is None:
        raise NotFound("There is no such payment.")
    if entry.kind != "payment" or entry.reverses_id is not None:
        raise Refused("A receipt goes on a payment.")
    return entry


def _live_receipt(db: Session, entry_id: int) -> ProdSupplierReceipt | None:
    return db.scalar(
        select(ProdSupplierReceipt).where(ProdSupplierReceipt.entry_id == entry_id, ProdSupplierReceipt.deleted_at.is_(None))
    )


def add_receipt(
    db: Session, entry_id: int, *, content: bytes, actor: UserAccount
) -> ProductionSupplier:
    """Attach (or replace) the photo of a payment. Checked before anything is
    stored; the bucket is written last, once the row is staged, so a refusal
    never leaves a stored file behind. The replaced copy stays in the bucket."""
    entry = _payment_entry(db, entry_id)
    supplier = _supplier(db, entry.supplier_id, for_update=True)
    if not content:
        raise Refused("Choose a photo to upload.")
    if len(content) > MAX_BYTES:
        raise Refused("Files must be 20 MB or smaller.")
    mime = file_type(content)
    if mime is None:
        raise Refused("Use a JPG, PNG, WebP or GIF photo, or a PDF.")
    old = _live_receipt(db, entry.id)
    if old is not None:
        old.deleted_at = utcnow()
        db.flush()
    key = f"production/suppliers/{supplier.id}/{uuid.uuid4()}"
    db.add(
        ProdSupplierReceipt(
            entry_id=entry.id, storage_key=key, mime_type=mime, size_bytes=len(content), uploaded_by=actor.id
        )
    )
    db.flush()
    _audit(
        db, _subject(supplier), actor, "payment_receipt_added",
        f"{'Replaced' if old else 'Added'} the receipt photo of a payment to {supplier.name}", entry=entry.id,
    )
    file_bucket().put(key, content, mime)
    return supplier


def remove_receipt(db: Session, entry_id: int, actor: UserAccount) -> ProductionSupplier:
    entry = db.get(ProdSupplierEntry, entry_id)
    if entry is None:
        raise NotFound("There is no such payment.")
    supplier = _supplier(db, entry.supplier_id, for_update=True)
    receipt = _live_receipt(db, entry.id)
    if receipt is None:
        raise NotFound("That payment has no receipt.")
    receipt.deleted_at = utcnow()
    _audit(
        db, _subject(supplier), actor, "payment_receipt_removed",
        f"Removed the receipt photo of a payment to {supplier.name}", entry=entry.id,
    )
    return supplier


def receipt_for_download(db: Session, entry_id: int) -> ProdSupplierReceipt | None:
    return _live_receipt(db, entry_id)


# ── What is owed ──────────────────────────────────────────────────────────────


@dataclass
class Standing:
    """One supplier's money, now."""

    ledger: int = 0
    #: Open orders at this factory with cutting done and not settled: each
    #: with what it would pay so far (batch 1's ``settlement``).
    so_far: list[tuple[ProdOrder, Facts, dict]] = field(default_factory=list)

    @property
    def not_settled(self) -> int:
        return sum(figures["payable_piastres"] for _, _, figures in self.so_far)

    @property
    def owed(self) -> int:
        return self.ledger + self.not_settled

    @property
    def held(self) -> int:
        return sum(figures["held_piastres"] for _, _, figures in self.so_far)


def standings(db: Session, supplier_ids: list[str]) -> dict[str, Standing]:
    found = {sid: Standing(ledger=amount) for sid, amount in account.ledger_sums(db, supplier_ids).items()}
    if not supplier_ids:
        return found
    orders = list(
        db.scalars(
            select(ProdOrder)
            .where(ProdOrder.status == "open", ProdOrder.factory_id.in_(supplier_ids))
            .order_by(ProdOrder.id)
        )
    )
    facts = _facts_for(db, orders)
    for order in orders:
        if facts[order.id].done("cutting"):
            found[order.factory_id].so_far.append((order, facts[order.id], settlement(facts[order.id])))
    return found


def _paid_this_year(db: Session, supplier_id: str) -> int:
    year = today().year
    reversed_ids = select(ProdSupplierEntry.reverses_id).where(ProdSupplierEntry.reverses_id.is_not(None))
    return int(
        db.scalar(
            select(func.coalesce(func.sum(-ProdSupplierEntry.amount_piastres), 0)).where(
                ProdSupplierEntry.supplier_id == supplier_id,
                ProdSupplierEntry.kind == "payment",
                ProdSupplierEntry.reverses_id.is_(None),
                ProdSupplierEntry.id.not_in(reversed_ids),
                ProdSupplierEntry.happened_on >= date(year, 1, 1),
                ProdSupplierEntry.happened_on <= date(year, 12, 31),
            )
        )
        or 0
    )


# ── Views ─────────────────────────────────────────────────────────────────────


def _section_map(db: Session, ids: list[str]) -> dict[str, list[dict]]:
    found: dict[str, list[dict]] = {i: [] for i in ids}
    if not ids:
        return found
    for supplier_id, section_id, name in db.execute(
        select(ProdSupplierSection.supplier_id, ProdSection.id, ProdSection.name)
        .join(ProdSection, ProdSection.id == ProdSupplierSection.section_id)
        .where(ProdSupplierSection.supplier_id.in_(ids), ProdSection.deleted_at.is_(None))
        .order_by(ProdSection.position, ProdSection.id)
    ):
        found[supplier_id].append({"id": section_id, "name": name})
    return found


def _open_order_counts(db: Session, ids: list[str]) -> dict[str, int]:
    wanted = set(ids)
    counts = {i: 0 for i in ids}
    for _, factory, printer in db.execute(
        select(ProdOrder.id, ProdOrder.factory_id, ProdOrder.print_supplier_id).where(ProdOrder.status == "open")
    ):
        for supplier_id in {factory, printer} & wanted:
            counts[supplier_id] += 1
    return counts


def _open_purchase_counts(db: Session, ids: list[str]) -> dict[str, int]:
    counts = {i: 0 for i in ids}
    if ids:
        counts.update(
            db.execute(
                select(ProdPurchase.supplier_id, func.count())
                .where(
                    ProdPurchase.supplier_id.in_(ids),
                    ProdPurchase.voided_at.is_(None),
                    ProdPurchase.received_on.is_(None),
                )
                .group_by(ProdPurchase.supplier_id)
            ).all()
        )
    return counts


def _row(
    supplier: ProductionSupplier, sections: list[dict], open_orders: int, open_purchases: int
) -> dict:
    return {
        "id": supplier.id,
        "code": supplier.code,
        "name": supplier.name,
        "contact_person": supplier.contact_person,
        "phone": supplier.phone,
        "whatsapp": supplier.whatsapp,
        "city": supplier.city,
        "notes": supplier.notes,
        "active": supplier.active,
        "sections": sections,
        "open_orders": open_orders,
        "open_purchases": open_purchases,
    }


def listing(db: Session, *, with_money: bool) -> dict:
    suppliers = list(
        db.scalars(
            select(ProductionSupplier)
            .where(ProductionSupplier.deleted_at.is_(None))
            .order_by(ProductionSupplier.active.desc(), func.lower(ProductionSupplier.name), ProductionSupplier.id)
        )
    )
    ids = [s.id for s in suppliers]
    sections = _section_map(db, ids)
    orders = _open_order_counts(db, ids)
    purchases = _open_purchase_counts(db, ids)
    money = standings(db, ids) if with_money else {}
    rows = []
    for supplier in suppliers:
        row = _row(supplier, sections[supplier.id], orders[supplier.id], purchases[supplier.id])
        if with_money:
            row["owed_piastres"] = money[supplier.id].owed
            row["held_piastres"] = money[supplier.id].held
        rows.append(row)
    body = {
        "sections": sections_view(db),
        "suppliers": rows,
        "unsectioned": sum(1 for s in suppliers if not sections[s.id]),
    }
    if with_money:
        body["owed_total_piastres"] = sum(max(0, row["owed_piastres"]) for row in rows)
    return body


def _purchase_views(db: Session, purchases: list[ProdPurchase], *, with_money: bool) -> list[dict]:
    if not purchases:
        return []
    ids = [p.id for p in purchases]
    orders = {
        o.id: o for o in db.scalars(select(ProdOrder).where(ProdOrder.id.in_({p.order_id for p in purchases if p.order_id})))
    } if any(p.order_id for p in purchases) else {}
    bought = dict(
        db.execute(
            select(ProdSupplierEntry.purchase_id, func.min(ProdSupplierEntry.happened_on))
            .where(
                ProdSupplierEntry.purchase_id.in_(ids),
                ProdSupplierEntry.kind == "purchase",
                ProdSupplierEntry.reverses_id.is_(None),
            )
            .group_by(ProdSupplierEntry.purchase_id)
        ).all()
    )
    deposits: dict[int, int] = {}
    if with_money:
        reversed_ids = select(ProdSupplierEntry.reverses_id).where(ProdSupplierEntry.reverses_id.is_not(None))
        for purchase_id, amount in db.execute(
            select(ProdSupplierEntry.purchase_id, func.sum(-ProdSupplierEntry.amount_piastres))
            .where(
                ProdSupplierEntry.purchase_id.in_(ids),
                ProdSupplierEntry.kind == "payment",
                ProdSupplierEntry.reverses_id.is_(None),
                ProdSupplierEntry.id.not_in(reversed_ids),
            )
            .group_by(ProdSupplierEntry.purchase_id)
        ):
            deposits[purchase_id] = int(amount)
    views = []
    for p in purchases:
        order = orders.get(p.order_id)
        view = {
            "id": p.id,
            "supplier_id": p.supplier_id,
            "item": p.item,
            "quantity": quantity_text(p.quantity),
            "unit": p.unit,
            "part": p.cost_part,
            "order": None
            if order is None
            else {"id": order.id, "code": order.code, "style_name": order.style_name, "colour": order.colour,
                  "status": order.status},
            "bought_on": _day(bought.get(p.id)),
            "expected_on": _day(p.expected_on),
            "received_on": _day(p.received_on),
            "note": p.note,
            "voided": p.voided_at is not None,
            "voided_at": _iso(p.voided_at),
        }
        if with_money:
            view["unit_price_piastres"] = p.unit_price_piastres
            view["total_piastres"] = p.total_piastres
            view["deposit_piastres"] = deposits.get(p.id, 0)
            view["void_reason"] = p.void_reason
        views.append(view)
    return views


def _order_views(db: Session, supplier_id: str) -> list[dict]:
    orders = list(
        db.scalars(
            select(ProdOrder)
            .where(or_(ProdOrder.factory_id == supplier_id, ProdOrder.print_supplier_id == supplier_id))
            .order_by((ProdOrder.status == "open").desc(), ProdOrder.id.desc())
            .limit(200)
        )
    )
    facts = _facts_for(db, orders)
    views = []
    for order in orders:
        current = facts[order.id].current if order.status == "open" else None
        views.append(
            {
                "id": order.id,
                "code": order.code,
                "style_name": order.style_name,
                "colour": order.colour,
                "status": order.status,
                "role": "factory" if order.factory_id == supplier_id else "print",
                "stage": None
                if current is None
                else {"key": current.stage, "label": STAGE_LABELS[current.stage], "position": current.position},
            }
        )
    return views


def _what(entry: ProdSupplierEntry, purchase_items: dict[int, str], codes: dict[int, str]) -> str:
    if entry.kind == "opening":
        base = "Balance brought forward"
    elif entry.kind == "purchase":
        base = f"Purchase · {purchase_items.get(entry.purchase_id, 'item')}"
    elif entry.kind == "work":
        base = f"Work on {codes.get(entry.order_id, 'an order')}"
    elif entry.kind == "payment":
        base = f"{PAY_KIND_LABELS[entry.payment_kind]} · {METHOD_LABELS[entry.method]}"
        if entry.purchase_id:
            base += f" · {purchase_items.get(entry.purchase_id, 'a purchase')}"
    else:
        base = "Adjustment"
    return f"Reversal · {base}" if entry.reverses_id is not None else base


def _account_lines(db: Session, supplier_id: str, standing: Standing) -> list[dict]:
    """The account, newest first, each line with what HBA owes after it. The
    orders not yet settled come first, marked, and are not ledger lines."""
    entries = list(
        db.scalars(
            select(ProdSupplierEntry)
            .where(ProdSupplierEntry.supplier_id == supplier_id)
            .order_by(ProdSupplierEntry.happened_on, ProdSupplierEntry.id)
        )
    )
    reversed_by = {e.reverses_id: e.id for e in entries if e.reverses_id is not None}
    ids = [e.id for e in entries]
    receipts = {
        r.entry_id: r
        for r in db.scalars(
            select(ProdSupplierReceipt).where(ProdSupplierReceipt.entry_id.in_(ids), ProdSupplierReceipt.deleted_at.is_(None))
        )
    } if ids else {}
    items = dict(
        db.execute(
            select(ProdPurchase.id, ProdPurchase.item).where(ProdPurchase.id.in_({e.purchase_id for e in entries if e.purchase_id}))
        ).all()
    ) if any(e.purchase_id for e in entries) else {}
    order_ids = {e.order_id for e in entries if e.order_id}
    codes = dict(db.execute(select(ProdOrder.id, ProdOrder.code).where(ProdOrder.id.in_(order_ids))).all()) if order_ids else {}
    people = _people(db, [e.created_by for e in entries])

    lines: list[dict] = []
    running = 0
    for e in entries:
        running += e.amount_piastres
        receipt = receipts.get(e.id)
        lines.append(
            {
                "id": e.id,
                "kind": e.kind,
                "what": _what(e, items, codes),
                "amount_piastres": e.amount_piastres,
                "balance_after_piastres": running,
                "happened_on": _day(e.happened_on),
                "order": None if e.order_id is None else {"id": e.order_id, "code": codes.get(e.order_id)},
                "purchase": None if e.purchase_id is None else {"id": e.purchase_id, "item": items.get(e.purchase_id)},
                "method": e.method,
                "payment_kind": e.payment_kind,
                "note": e.note,
                "reversal": e.reverses_id is not None,
                "reverses_id": e.reverses_id,
                "reversed": e.id in reversed_by,
                "reversed_by_id": reversed_by.get(e.id),
                "not_settled": False,
                "receipt": None
                if receipt is None
                else {
                    "url": f"/api/prod/entries/{e.id}/receipt",
                    "mime_type": receipt.mime_type,
                    "size_bytes": receipt.size_bytes,
                },
                "created_by": people.get(e.created_by),
                "created_at": _iso(e.created_at),
            }
        )
    lines.reverse()
    pending = []
    for order, _, figures in standing.so_far:
        running += figures["payable_piastres"]
        pending.append(
            {
                "id": None,
                "kind": "work",
                "what": f"Work on {order.code} so far, not settled",
                "amount_piastres": figures["payable_piastres"],
                "balance_after_piastres": running,
                "happened_on": None,
                "order": {"id": order.id, "code": order.code},
                "purchase": None,
                "method": None,
                "payment_kind": None,
                "note": None,
                "reversal": False,
                "reverses_id": None,
                "reversed": False,
                "reversed_by_id": None,
                "not_settled": True,
                "receipt": None,
                "created_by": None,
                "created_at": None,
            }
        )
    pending.reverse()
    return pending + lines


def page(db: Session, supplier_id: str, *, with_money: bool) -> dict:
    """One supplier's page: its details, purchases and orders, and for the
    owner its money."""
    supplier = _supplier(db, supplier_id)
    sections = _section_map(db, [supplier.id])[supplier.id]
    purchases = list(
        db.scalars(select(ProdPurchase).where(ProdPurchase.supplier_id == supplier.id).order_by(ProdPurchase.id.desc()))
    )
    body = _row(
        supplier, sections, _open_order_counts(db, [supplier.id])[supplier.id],
        _open_purchase_counts(db, [supplier.id])[supplier.id],
    )
    body["purchases"] = _purchase_views(db, purchases, with_money=with_money)
    body["orders"] = _order_views(db, supplier.id)
    if with_money:
        standing = standings(db, [supplier.id])[supplier.id]
        body["owed_piastres"] = standing.owed
        body["held_piastres"] = standing.held
        body["paid_piastres"] = _paid_this_year(db, supplier.id)
        body["paid_year"] = today().year
        body["has_opening"] = _live_opening(db, supplier.id)
        body["account"] = _account_lines(db, supplier.id, standing)
    return body
