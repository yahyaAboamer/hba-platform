"""Whose sale is this order?

Spec section 9.2. Everything else in Phase 3 was storage; this is the rule that
turns an order into somebody's money in Phase 4.

    exactly one registered code  ->  ATTRIBUTED
    zero registered codes        ->  UNATTRIBUTED, indexed only
    two or more                  ->  HELD, a human decides

The third case is a cheap safety net rather than the elaborate conflict
subsystem the old application carried. HBA's Shopify configuration makes it
unlikely, but Shopify does permit combinable codes in general and settings
change. **The order waits rather than silently paying the wrong person or
paying twice.**

## Two things this deliberately does not do

**It does not write.** Recording attribution belongs to Phase 4, with the table
that stores it and the rule that an order's affiliate is immutable once set.
Separating the decision from the recording means the rule can be tested
exhaustively before any money depends on it.

**It does not exclude house accounts.** A house code attributes normally, to
the house affiliate. Phase 4 excludes house accounts from *payable totals* -
excluding them here would report HBA10's orders as unattributed, which is a
different and wrong answer, and would hide them from the unregistered-code
report as well.
"""

from dataclasses import dataclass, field
from typing import Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.businesstime import parse_month
from app.models.affiliates import AccountKind, AffiliateProfile
from app.models.codes import DiscountCodePeriod
from app.models.orders import OrderIndex


class AttributionOutcome:
    """What resolution concluded."""

    #: Exactly one registered code. This order is that affiliate's.
    ATTRIBUTED = "attributed"

    #: No registered codes. Indexed, belongs to nobody, no money follows.
    UNATTRIBUTED = "unattributed"

    #: More than one registered code. A person decides; nothing is guessed.
    HELD = "held"


@dataclass(frozen=True)
class Attribution:
    """The answer, and enough context to act on it."""

    outcome: str
    affiliate_id: int | None = None

    #: Every registered code found on the order. One when attributed, empty
    #: when not, and **all of them** when held - a human cannot decide a
    #: conflict without knowing what conflicted.
    matched_codes: list[str] = field(default_factory=list)

    #: Whether this affiliate can be owed money. None when nothing was
    #: attributed, because "is nobody payable?" has no answer.
    is_payable: bool | None = None


def _normalise(codes: Iterable[str]) -> list[str]:
    """Trim, upper-case, drop blanks, and de-duplicate - order preserved.

    De-duplication matters: the same code twice on one order must read as one
    code, not two, or a perfectly ordinary order goes on hold.
    """
    seen: dict[str, None] = {}
    for code in codes or ():
        cleaned = str(code or "").strip().upper()
        if cleaned:
            seen.setdefault(cleaned, None)
    return list(seen)


def resolve(db: Session, codes: Iterable[str], month: str) -> Attribution:
    """Decide whose order this is, using **that month's** ownership.

    The month is the order's own business month, never today. Using today's
    ownership would make last April's payroll change every time a code moved -
    months already approved and paid would silently re-attribute.
    """
    parse_month(month)
    candidates = _normalise(codes)
    if not candidates:
        return Attribution(outcome=AttributionOutcome.UNATTRIBUTED)

    # One query. The registry is a few dozen rows, and this runs per order.
    rows = db.execute(
        select(
            DiscountCodePeriod.code,
            DiscountCodePeriod.affiliate_id,
            AffiliateProfile.account_kind,
        )
        .join(AffiliateProfile, AffiliateProfile.id == DiscountCodePeriod.affiliate_id)
        .where(DiscountCodePeriod.code.in_(candidates))
        .where(DiscountCodePeriod.start_month <= month)
        .where(
            (DiscountCodePeriod.end_month.is_(None))
            | (DiscountCodePeriod.end_month >= month)
        )
    ).all()

    if not rows:
        return Attribution(outcome=AttributionOutcome.UNATTRIBUTED)

    if len(rows) > 1:
        # Two owners is two owners. A house account is not a lesser kind of
        # owner, so this holds even when one of them is HBA's own code.
        return Attribution(
            outcome=AttributionOutcome.HELD,
            matched_codes=sorted(row.code for row in rows),
        )

    match = rows[0]
    return Attribution(
        outcome=AttributionOutcome.ATTRIBUTED,
        affiliate_id=match.affiliate_id,
        matched_codes=[match.code],
        is_payable=match.account_kind != AccountKind.HOUSE,
    )


def resolve_order(db: Session, order: OrderIndex) -> Attribution:
    """Decide whose order this is, from the indexed row.

    Uses the order's own ``business_month`` - derived in Cairo when the order
    was indexed (ADR 0005), and never recomputed.
    """
    return resolve(db, order.discount_codes or [], order.business_month)
