"""Operations → Returns: refunds owed to customers, and whether sent (ADR 0079).

**A record, never a payment.** Nothing here moves money, writes to Shopify
or Khazenly, or is read by anything that decides pay.

Each row is one customer owed a refund for a return or an exchange. It is
added by its Khazenly number; Khazenly's public tracking
(``khazenly_tracking``) is read at once and then every 30 minutes until it
says *Return Completed*, and only then can the row be marked paid. A paid
row is locked; undoing it needs a reason, kept in the activity log.

The customer's name and phone are read from the Shopify order Khazenly
names, best effort: when Shopify gives none, a person types them. They are
never written to the activity log or the server log.
"""

import logging
import re
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.businesstime import BUSINESS_TIMEZONE, business_date, utcnow
from app.modules.operations.models import REFUND_KINDS, REFUND_METHODS, OpsRefund
from app.modules.operations.services import khazenly_tracking as tracking
from app.shared.models.identity import UserAccount
from app.shared.services.audit import record_audit
from app.shared.services.jobs import JobKind
from app.worker import register_handler

logger = logging.getLogger(__name__)

#: How often the rows not yet received are read again (ADR 0079, decision 4).
TRACK_EVERY = timedelta(minutes=30)
#: A pause between two of Khazenly's answers, so the read is never a burst.
PAUSE_SECONDS = 0.3
#: The most rows one read takes; far more than are ever on the way back.
READ_BATCH = 300
#: How long one read may run, well inside the operations lane's 5-minute
#: lease (app.worker), and how many failures in a row mean Khazenly is down.
READ_BUDGET = timedelta(minutes=3)
GIVE_UP_AFTER = 5
#: The most Khazenly numbers one paste adds.
MAX_PASTED = 20
#: The paid rows the tab lists, newest first.
PAID_SHOWN = 100

#: Needs attention (ADR 0079, decision 6).
STUCK_AFTER = timedelta(days=3)
UNPAID_AFTER = timedelta(days=2)

#: The largest refund the tab takes, as a guard against a slipped zero.
MAX_AMOUNT = Decimal("1000000")

TRACKING_URL = "https://track.khazenly.com/?referenceNumber={number}&lang=en"

METHOD_WORDS = {
    "instapay": "InstaPay",
    "vodafone_cash": "Vodafone Cash",
    "bank_transfer": "Bank transfer",
    "other": "Other",
}


class Refused(ValueError):
    """A change refused, in words a person can act on."""


class Locked(Refused):
    """The row is paid, so it cannot change."""


# ── Words in, checked ─────────────────────────────────────────────────────────


_EGYPTIAN_MOBILE = re.compile(r"20(10|11|12|15)\d{8}")
_INSTAPAY_HANDLE = re.compile(r"[^\s@]{1,80}@instapay", re.IGNORECASE)


def local_mobile(raw: object) -> str | None:
    """An Egyptian mobile as people write it, ``01XXXXXXXXX``, or None."""
    from app.modules.inbox.public import egyptian_mobile

    digits = egyptian_mobile(raw)
    return f"0{digits[2:]}" if digits else None


def amount_of(raw) -> Decimal | None:
    """EGP to two places, or None for nothing. Refused when not a positive
    amount."""
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        return None
    try:
        value = Decimal(str(raw).replace(",", "").strip())
    except InvalidOperation:
        raise Refused("The amount must be a number of pounds, such as 395 or 736.10.") from None
    if not value.is_finite() or value <= 0:
        raise Refused("The amount must be more than 0.")
    if value >= MAX_AMOUNT:
        raise Refused("That amount is too large to be a refund. Check the number.")
    if value != value.quantize(Decimal("0.01")):
        raise Refused("The amount can have at most two decimal places.")
    return value.quantize(Decimal("0.01"))


def method_of(raw) -> str | None:
    if raw is None or raw == "":
        return None
    if raw not in REFUND_METHODS:
        raise Refused("Choose how the refund is sent.")
    return raw


def kind_of(raw) -> str:
    if raw not in REFUND_KINDS:
        raise Refused("Choose Return or Exchange.")
    return raw


def refund_to_of(method: str | None, raw) -> str | None:
    """Where the refund goes, checked against how it is sent.

    InstaPay takes a mobile, an ``…@instapay`` address or an ``ipn.eg``
    link (pasted InstaPay text is cut down to the link, as on Payments).
    Vodafone Cash takes a mobile. A bank transfer or *Other* takes what
    was typed.
    """
    from app.modules.affiliates.public import extract_instapay_link, normalise_instapay_address

    text = re.sub(r"\s+", " ", str(raw or "")).strip()
    if not text:
        return None
    if len(text) > 200:
        raise Refused("That is too long for a refund ID. Keep it to 200 characters.")
    if method == "instapay":
        if "ipn.eg" in extract_instapay_link(text).lower():
            try:
                return normalise_instapay_address(text)
            except ValueError:
                raise Refused("That InstaPay link isn't one. Copy it from the Link button in InstaPay.") from None
        handle = text.replace(" ", "")
        if _INSTAPAY_HANDLE.fullmatch(handle):
            name, _, _ = handle.rpartition("@")
            return f"{name}@instapay"
        mobile = local_mobile(text)
        if mobile:
            return mobile
        raise Refused(
            "For InstaPay, enter the customer's mobile number, their …@instapay address, "
            "or their ipn.eg link."
        )
    if method == "vodafone_cash":
        mobile = local_mobile(text)
        if not mobile:
            raise Refused("For Vodafone Cash, enter the customer's mobile number, such as 01012345678.")
        return mobile
    return text


def _name(raw) -> str | None:
    text = re.sub(r"\s+", " ", str(raw or "")).strip()
    if len(text) > 120:
        raise Refused("That name is too long. Keep it to 120 characters.")
    return text or None


def _phone(raw) -> str | None:
    text = re.sub(r"\s+", " ", str(raw or "")).strip()
    if not text:
        return None
    if len(text) > 30:
        raise Refused("That phone number is too long.")
    return local_mobile(text) or text


# ── Shopify: who the customer is ──────────────────────────────────────────────

_CUSTOMER_FULL = """
query RefundCustomer($q: String!) {
  orders(first: 1, query: $q) {
    nodes {
      name
      phone
      customer { firstName lastName phone }
      shippingAddress { firstName lastName phone }
    }
  }
}
"""

#: What the inbox already reads in production, should the full one be refused.
_CUSTOMER_SHORT = """
query RefundCustomerShort($q: String!) {
  orders(first: 1, query: $q) {
    nodes { name phone customer { firstName phone } shippingAddress { phone } }
  }
}
"""


@dataclass(frozen=True)
class Customer:
    name: str | None
    phone: str | None


def _customer_from(node: dict) -> Customer:
    customer = node.get("customer") or {}
    shipping = node.get("shippingAddress") or {}
    name = None
    for source in (shipping, customer):
        parts = [str(source.get(key) or "").strip() for key in ("firstName", "lastName")]
        joined = " ".join(part for part in parts if part)
        if joined:
            name = joined
            break
    phone = None
    for raw in (node.get("phone"), customer.get("phone"), shipping.get("phone")):
        if raw:
            phone = local_mobile(raw) or str(raw).strip()[:30]
            break
    return Customer(name=name[:120] if name else None, phone=phone)


def shopify_customer(order_number: str | None, client=None) -> Customer | None:
    """The name and phone on a Shopify order, or None if Shopify gives none.

    Best effort: any failure is None, and the person types them.
    """
    if not order_number:
        return None
    from app.shared.services.shopify.client import ShopifyError
    from app.shared.services.shopify.sync import build_client

    try:
        client = client or build_client()
    except Exception:  # noqa: BLE001 - no Shopify connection is "type them in"
        logger.info("returns: no Shopify connection to read a customer with")
        return None
    query = {"q": f"name:{order_number}"}
    for document in (_CUSTOMER_FULL, _CUSTOMER_SHORT):
        try:
            data = client.execute(document, query)
        except ShopifyError as exc:
            # The type alone: a message may carry the order's fields.
            logger.info("returns: Shopify refused a customer read (%s)", type(exc).__name__)
            continue
        except Exception as exc:  # noqa: BLE001
            logger.info("returns: Shopify customer read failed (%s)", type(exc).__name__)
            return None
        nodes = ((data or {}).get("orders") or {}).get("nodes") or []
        node = next((n for n in nodes if n and n.get("name") == order_number), None)
        return _customer_from(node) if node else None
    return None


# ── Khazenly's answer, onto a row ─────────────────────────────────────────────


def apply_tracking(row: OpsRefund, found: tracking.Tracking, now: datetime) -> None:
    """Khazenly's answer onto the row. **Received is never taken back**: a
    later answer with a shorter timeline does not un-receive a parcel that is
    back, and its first time is kept."""
    latest = found.latest
    row.timeline = [entry.as_json() for entry in found.timeline]
    row.step = latest.step if latest else None
    row.step_at = latest.at if latest else None
    row.merchant_order = found.merchant_order or row.merchant_order
    row.order_number = found.order_number or row.order_number
    if found.received and row.received_at is None:
        # Completed with no time on the step: the moment it was seen.
        row.received_at = found.received_at or now
    row.checked_at = now
    row.check_error = None


def check_one(db: Session, row: OpsRefund, client: tracking.Client, now: datetime | None = None) -> None:
    """Ask Khazenly about one row. A failure is kept on the row, never raised."""
    now = now or utcnow()
    try:
        apply_tracking(row, client.track(row.khazenly_number), now)
    except tracking.TrackingError as exc:
        row.checked_at = now
        row.check_error = str(exc)[:200]


def waiting(db: Session) -> list[OpsRefund]:
    """The rows still on the way back, least recently checked first."""
    return list(
        db.scalars(
            select(OpsRefund)
            .where(OpsRefund.received_at.is_(None), OpsRefund.paid_on.is_(None))
            .order_by(OpsRefund.checked_at.asc().nulls_first(), OpsRefund.id)
            .limit(READ_BATCH)
        )
    )


def read_waiting(
    db: Session,
    client: tracking.Client | None = None,
    pause: float | None = None,
    budget_seconds: float | None = None,
    clock=time.monotonic,
) -> int:
    """Read the rows not yet received, least recently checked first.
    Returns how many were asked about.

    **Bounded**, so a Khazenly that hangs never holds the operations lane
    (its lease is 5 minutes, and Shopify, Bosta and E-stebdal wait behind
    it): the read stops after ``READ_BUDGET``, or after
    ``GIVE_UP_AFTER`` failures in a row, and the next read starts with the
    rows this one did not reach.
    """
    rows = waiting(db)
    if not rows:
        return 0
    pause = PAUSE_SECONDS if pause is None else pause
    budget = READ_BUDGET.total_seconds() if budget_seconds is None else budget_seconds
    started = clock()
    owned = client is None
    client = client or tracking.Client()
    asked = 0
    failed_in_a_row = 0
    try:
        for row in rows:
            if asked and clock() - started >= budget:
                break
            if failed_in_a_row >= GIVE_UP_AFTER:
                break
            if asked and pause:
                time.sleep(pause)
            check_one(db, row, client)
            asked += 1
            failed = row.check_error is not None and row.check_error != tracking.NOT_FOUND
            failed_in_a_row = failed_in_a_row + 1 if failed else 0
    finally:
        if owned:
            client.close()
    db.flush()
    logger.info("returns: asked Khazenly about %d of %d, %d failed in a row at the end", asked, len(rows), failed_in_a_row)
    return asked


@register_handler(JobKind.ORDER_OPS_RETURNS)
def _handle_read(db: Session, payload: dict) -> None:
    read_waiting(db)


# ── Changes ───────────────────────────────────────────────────────────────────


def _audit(db: Session, action: str, row: OpsRefund, actor: UserAccount, reason: str | None = None, **extra) -> None:
    # The Khazenly number and amount only: never the customer.
    record_audit(
        db,
        action=action,
        subject=f"refund:{row.khazenly_number}",
        actor_id=actor.id,
        actor_email=actor.email,
        after={
            "number": row.khazenly_number,
            "amount": str(row.amount) if row.amount is not None else None,
            **extra,
        },
        reason=reason,
    )


def _numbers(raw: list[str]) -> list[str]:
    seen: list[str] = []
    for item in raw:
        for piece in re.split(r"[\s,;]+", str(item or "")):
            number = tracking.normalise(piece)
            if number and number not in seen:
                seen.append(number)
    return seen


def add(
    db: Session,
    raw_numbers: list[str],
    kind: str,
    actor: UserAccount,
    details: dict | None = None,
    *,
    client: tracking.Client | None = None,
    shopify=None,
) -> dict:
    """Add one refund, or several pasted Khazenly numbers.

    Each number is read from Khazenly first; one it does not know, or one
    already listed, is refused with the reason and the rest still added.
    The details (amount, method, refund ID, customer) are taken only when a
    single number is added.
    """
    kind = kind_of(kind)
    numbers = _numbers(raw_numbers)
    if not numbers:
        raise Refused("Enter a Khazenly number, such as KH-HBA-08997921.")
    if len(numbers) > MAX_PASTED:
        raise Refused(f"Add at most {MAX_PASTED} numbers at a time.")
    details = details if len(numbers) == 1 else None
    checked = _details(details or {})
    shopify = shopify or shopify_customer

    listed = set(
        db.scalars(select(OpsRefund.khazenly_number).where(OpsRefund.khazenly_number.in_(numbers)))
    )
    added: list[OpsRefund] = []
    refused: list[dict] = []
    owned = client is None
    client = client or tracking.Client()
    now = utcnow()
    try:
        for number in numbers:
            if not tracking.is_kh_number(number):
                refused.append({"number": number, "reason": "That isn't a Khazenly number, such as KH-HBA-08997921."})
                continue
            if number in listed:
                refused.append({"number": number, "reason": "Already listed."})
                continue
            try:
                found = client.track(number)
            except tracking.NotFound:
                refused.append({"number": number, "reason": tracking.NOT_FOUND})
                continue
            except tracking.TrackingError as exc:
                refused.append({"number": number, "reason": f"{exc} Try again in a few minutes."})
                continue
            row = OpsRefund(khazenly_number=number, kind=kind, created_by=actor.id, updated_by=actor.id)
            apply_tracking(row, found, now)
            for key, value in checked.items():
                setattr(row, key, value)
            if not row.customer_name or not row.customer_phone:
                customer = shopify(row.order_number)
                if customer:
                    row.customer_name = row.customer_name or customer.name
                    row.customer_phone = row.customer_phone or customer.phone
            try:
                # Someone else adding the same number this moment loses
                # only this row, not the rest of the paste.
                with db.begin_nested():
                    db.add(row)
                    db.flush()
            except IntegrityError:
                refused.append({"number": number, "reason": "Already listed."})
                continue
            listed.add(number)
            added.append(row)
            _audit(db, "order_ops.refund_added", row, actor, kind=kind)
    finally:
        if owned:
            client.close()
    return {"added": [serialise(row, now) for row in added], "refused": refused}


#: The fields a person may change on an unpaid row.
EDITABLE = ("kind", "amount", "method", "refund_to", "customer_name", "customer_phone")


def _details(values: dict) -> dict:
    """The given fields, checked. The refund ID is checked against the
    method given with it."""
    checked: dict = {}
    if "kind" in values:
        checked["kind"] = kind_of(values["kind"])
    if "amount" in values:
        checked["amount"] = amount_of(values["amount"])
    if "method" in values:
        checked["method"] = method_of(values["method"])
    if "customer_name" in values:
        checked["customer_name"] = _name(values["customer_name"])
    if "customer_phone" in values:
        checked["customer_phone"] = _phone(values["customer_phone"])
    if "refund_to" in values:
        checked["refund_to"] = refund_to_of(checked.get("method", values.get("method")), values["refund_to"])
    return checked


def _get(db: Session, refund_id: int, *, lock: bool = True) -> OpsRefund:
    statement = select(OpsRefund).where(OpsRefund.id == refund_id)
    if lock:
        statement = statement.with_for_update()
    row = db.scalar(statement)
    if row is None:
        raise LookupError("There is no such refund.")
    return row


def edit(db: Session, refund_id: int, values: dict, actor: UserAccount) -> OpsRefund:
    row = _get(db, refund_id)
    if row.paid_on is not None:
        raise Locked("This refund is marked paid, so it can't change. Undo paid first.")
    values = {key: value for key, value in values.items() if key in EDITABLE}
    if "refund_to" in values and "method" not in values:
        values["method"] = row.method
    if "method" in values and "refund_to" not in values and row.refund_to:
        # A new method re-checks the refund ID already there.
        values["refund_to"] = row.refund_to
    checked = _details(values)
    changed = [key for key, value in checked.items() if getattr(row, key) != value]
    for key in changed:
        setattr(row, key, checked[key])
    if changed:
        row.updated_by = actor.id
        row.updated_at = utcnow()
        db.flush()
        _audit(db, "order_ops.refund_edited", row, actor, fields=sorted(changed))
    return row


def mark_paid(db: Session, refund_id: int, values: dict, actor: UserAccount, today: date | None = None) -> OpsRefund:
    """Record that the refund was sent: the day, and the amount, method and
    refund ID as sent. Only once Khazenly said *Return Completed*."""
    row = _get(db, refund_id)
    if row.paid_on is not None:
        raise Locked("This refund is already marked paid.")
    if row.received_at is None:
        raise Refused("Khazenly hasn't said this return is completed yet, so it can't be marked paid.")
    today = today or business_date(utcnow())
    try:
        paid_on = date.fromisoformat(str(values.get("paid_on") or today.isoformat()))
    except ValueError:
        raise Refused("Choose the day the refund was sent.") from None
    if paid_on > today:
        raise Refused("The day it was sent can't be in the future.")
    if paid_on < business_date(row.received_at):
        raise Refused("The day it was sent can't be before Khazenly received the return.")
    edits = {key: values[key] for key in ("amount", "method", "refund_to") if key in values}
    if edits:
        edit(db, refund_id, edits, actor)
    missing = [
        words
        for words, value in (("the amount", row.amount), ("how it was sent", row.method), ("the refund ID", row.refund_to))
        if value is None
    ]
    if missing:
        raise Refused(f"Add {' and '.join(missing)} before marking it paid.")
    row.paid_on = paid_on
    row.paid_recorded_at = utcnow()
    row.paid_by = actor.id
    row.updated_by = actor.id
    row.updated_at = row.paid_recorded_at
    db.flush()
    _audit(db, "order_ops.refund_paid", row, actor, paid_on=paid_on.isoformat(), method=row.method)
    return row


def undo_paid(db: Session, refund_id: int, reason: str, actor: UserAccount) -> OpsRefund:
    row = _get(db, refund_id)
    if row.paid_on is None:
        raise Refused("This refund isn't marked paid.")
    reason = re.sub(r"\s+", " ", str(reason or "")).strip()
    if len(reason) < 3:
        raise Refused("Say why it is no longer paid. It goes in the activity log.")
    if len(reason) > 300:
        raise Refused("Keep the reason to 300 characters.")
    was = row.paid_on.isoformat()
    row.paid_on = None
    row.paid_recorded_at = None
    row.paid_by = None
    row.updated_by = actor.id
    row.updated_at = utcnow()
    db.flush()
    _audit(db, "order_ops.refund_unpaid", row, actor, reason=reason, was_paid_on=was)
    return row


def delete(db: Session, refund_id: int, actor: UserAccount) -> None:
    row = _get(db, refund_id)
    if row.paid_on is not None:
        raise Locked("A paid refund can't be deleted. Undo paid first.")
    _audit(db, "order_ops.refund_deleted", row, actor)
    db.delete(row)
    db.flush()


def recheck(db: Session, refund_id: int, client: tracking.Client | None = None) -> OpsRefund:
    """Ask Khazenly again now, for a person waiting on one row."""
    row = _get(db, refund_id)
    if row.paid_on is not None:
        raise Locked("This refund is paid; Khazenly isn't checked for it any more.")
    owned = client is None
    client = client or tracking.Client()
    try:
        check_one(db, row, client)
    finally:
        if owned:
            client.close()
    db.flush()
    return row


# ── The tab ───────────────────────────────────────────────────────────────────


def attention(row: OpsRefund, now: datetime) -> list[str]:
    """Why a row needs a look, as short codes the screen words."""
    reasons: list[str] = []
    if row.paid_on is not None:
        return reasons
    if row.received_at is None:
        if row.check_error:
            reasons.append("not_found" if row.check_error == tracking.NOT_FOUND else "unreadable")
        if row.step == tracking.CONTACT_SUCCESS_MANAGER:
            reasons.append("contact_success_manager")
        moved = row.step_at or row.created_at
        if moved is not None and now - moved >= STUCK_AFTER:
            reasons.append("stuck")
    elif now - row.received_at >= UNPAID_AFTER:
        reasons.append("unpaid_late")
    if row.amount is None or row.method is None or row.refund_to is None:
        reasons.append("details_missing")
    return reasons


def group_of(row: OpsRefund, now: datetime) -> str:
    if row.paid_on is not None:
        return "paid"
    if row.received_at is not None:
        return "ready"
    if any(reason != "details_missing" for reason in attention(row, now)):
        return "attention"
    return "on_the_way"


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def serialise(row: OpsRefund, now: datetime | None = None, names: dict[int, str] | None = None) -> dict:
    now = now or utcnow()
    return {
        "id": row.id,
        "khazenly_number": row.khazenly_number,
        "kind": row.kind,
        "merchant_order": row.merchant_order,
        "order_number": row.order_number,
        "customer_name": row.customer_name,
        "customer_phone": row.customer_phone,
        "amount": str(row.amount) if row.amount is not None else None,
        "method": row.method,
        "refund_to": row.refund_to,
        "step": row.step,
        "step_at": _iso(row.step_at),
        "timeline": row.timeline or [],
        "received_at": _iso(row.received_at),
        "checked_at": _iso(row.checked_at),
        "check_error": row.check_error,
        "paid_on": row.paid_on.isoformat() if row.paid_on else None,
        "paid_by": (names or {}).get(row.paid_by) if row.paid_by else None,
        "created_at": _iso(row.created_at),
        "group": group_of(row, now),
        "attention": attention(row, now),
        "tracking_url": TRACKING_URL.format(number=row.khazenly_number),
    }


def one(db: Session, refund_id: int) -> dict:
    """One refund as the tab shows it, for the answer to a change."""
    row = _get(db, refund_id, lock=False)
    return serialise(row, utcnow(), _names(db, {row.paid_by} if row.paid_by else set()))


def _names(db: Session, ids: set[int]) -> dict[int, str]:
    if not ids:
        return {}
    rows = db.execute(select(UserAccount.id, UserAccount.display_name, UserAccount.email).where(UserAccount.id.in_(ids)))
    return {user_id: (name or email) for user_id, name, email in rows}


def tab(db: Session, now: datetime | None = None) -> dict:
    """Every unpaid refund and the latest paid ones, grouped by the next act,
    with what is owed now and what was refunded this month."""
    now = now or utcnow()
    unpaid = list(
        db.scalars(select(OpsRefund).where(OpsRefund.paid_on.is_(None)).order_by(OpsRefund.created_at.desc(), OpsRefund.id.desc()))
    )
    paid = list(
        db.scalars(
            select(OpsRefund)
            .where(OpsRefund.paid_on.is_not(None))
            .order_by(OpsRefund.paid_on.desc(), OpsRefund.paid_recorded_at.desc())
            .limit(PAID_SHOWN)
        )
    )
    names = _names(db, {row.paid_by for row in paid if row.paid_by})
    rows = [serialise(row, now, names) for row in unpaid + paid]

    ready = [row for row in unpaid if row.received_at is not None]
    owed = sum((row.amount for row in ready if row.amount is not None), Decimal("0"))

    today = business_date(now)
    month_start = today.replace(day=1)
    refunded, refunded_count = db.execute(
        select(func.coalesce(func.sum(OpsRefund.amount), 0), func.count(OpsRefund.id)).where(
            OpsRefund.paid_on >= month_start, OpsRefund.paid_on <= today
        )
    ).one()

    on_the_way = [row for row in unpaid if row.received_at is None]
    checked = [row.checked_at for row in on_the_way if row.checked_at]
    # Khazenly down: every row on the way back failed its latest read.
    khazenly_down = bool(on_the_way) and all(
        row.check_error and row.check_error != tracking.NOT_FOUND for row in on_the_way
    )
    return {
        "refunds": rows,
        "totals": {
            "owed_now": str(owed.quantize(Decimal("0.01"))),
            "owed_count": len(ready),
            "owed_missing_amount": sum(1 for row in ready if row.amount is None),
            "refunded_this_month": str(Decimal(refunded).quantize(Decimal("0.01"))),
            "refunded_count": refunded_count,
            "month": month_start.isoformat()[:7],
        },
        "tracking": {
            "checked_at": _iso(max(checked)) if checked else None,
            "every_minutes": int(TRACK_EVERY.total_seconds() // 60),
            "khazenly_down": khazenly_down,
        },
        "paid_shown": PAID_SHOWN,
        "methods": [{"value": value, "label": METHOD_WORDS[value]} for value in REFUND_METHODS],
    }
