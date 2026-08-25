"""Registering and resolving discount code ownership.

Everything here asks about a **month**. "Who owns NOUR10?" is not a question
this module answers, because it does not have an answer - ownership is dated,
and using today's ownership for an April order would make last April's payroll
change every time a code moved.
"""

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from datetime import datetime

from app.core.businesstime import business_month, parse_month
from app.core.periods import OPEN_ENDED, PLATFORM_START_MONTH, validate_period
from app.models.affiliates import AffiliateProfile
from app.models.codes import DiscountCodePeriod
from app.services.audit import record_audit


def normalise_code(code: str) -> str:
    """The canonical form: trimmed and upper-case.

    Matches what ``normalise_order`` stores from Shopify. Anything else and a
    lookup silently attributes nothing.
    """
    cleaned = str(code or "").strip().upper()
    if not cleaned:
        raise ValueError("A discount code cannot be empty")
    return cleaned


def _covering(code: str, month: str):
    """Rows owning this code in this month."""
    return (
        select(DiscountCodePeriod)
        .where(DiscountCodePeriod.code == code)
        .where(DiscountCodePeriod.start_month <= month)
        .where(
            (DiscountCodePeriod.end_month.is_(None))
            | (DiscountCodePeriod.end_month >= month)
        )
    )


def start_month_for(created_at: datetime | None) -> str:
    """The month a code's ownership should start from.

    **The later of the platform's data horizon and the code's creation on
    Shopify** - and it is never a question anybody is asked, because there is
    exactly one right answer and a person typing it can only get it wrong.

    - A code created before 2026 starts at the horizon. There are no orders
      before then to claim; the import does not reach back further.
    - A code created in March starts in March. Claiming January would assert
      ownership of months the code did not exist for - and if it previously
      belonged to somebody else, collide with their period.

    An unknown creation date falls back to the horizon. That is the safe
    direction: it claims at most a few empty months, where starting late would
    orphan real orders and nobody would notice until the model asked why her
    dashboard was empty.
    """
    if created_at is None:
        return PLATFORM_START_MONTH
    return max(PLATFORM_START_MONTH, business_month(created_at))


def register_code(
    db: Session,
    affiliate: AffiliateProfile,
    code: str,
    start_month: str,
    end_month: str | None = OPEN_ENDED,
    *,
    verified_at: datetime | None = None,
    actor_id: int | None = None,
    actor_email: str | None = None,
) -> DiscountCodePeriod:
    """Give an affiliate ownership of a code for a run of months.

    Registration and verification are separate acts: a code can be registered
    before Shopify has confirmed it exists. §10.4 gates *approval* on
    verification, not registration.

    The database refuses an overlap with any other affiliate's ownership of the
    same code - that is the constraint that stops the wrong person being paid.
    """
    canonical = normalise_code(code)
    start_month, end_month = validate_period(start_month, end_month)

    period = DiscountCodePeriod(
        affiliate_id=affiliate.id,
        code=canonical,
        start_month=start_month,
        end_month=end_month,
        shopify_verified_at=verified_at,
    )
    db.add(period)
    db.flush()

    record_audit(
        db,
        action="code.registered",
        subject=f"affiliate:{affiliate.id}",
        actor_id=actor_id,
        actor_email=actor_email,
        after={
            "code": canonical,
            "start_month": start_month,
            "end_month": end_month,
            "verified": verified_at is not None,
        },
    )
    return period


def owner_of(db: Session, code: str, month: str) -> AffiliateProfile | None:
    """Which affiliate owned this code in this month, if any."""
    parse_month(month)
    period = db.scalar(_covering(normalise_code(code), month))
    return period.affiliate if period is not None else None


def codes_for(db: Session, affiliate: AffiliateProfile, month: str) -> list[str]:
    """Every code this affiliate owned in this month."""
    parse_month(month)
    rows = db.scalars(
        select(DiscountCodePeriod.code)
        .where(DiscountCodePeriod.affiliate_id == affiliate.id)
        .where(DiscountCodePeriod.start_month <= month)
        .where(
            (DiscountCodePeriod.end_month.is_(None))
            | (DiscountCodePeriod.end_month >= month)
        )
        .order_by(DiscountCodePeriod.code)
    )
    return list(rows)


def registered_codes(db: Session, month: str) -> dict[str, int]:
    """Every registered code in this month, mapped to its owner's id.

    One query rather than one per code: attribution runs this for every order,
    and the whole registry is a few dozen rows.
    """
    parse_month(month)
    rows = db.execute(
        select(DiscountCodePeriod.code, DiscountCodePeriod.affiliate_id)
        .where(DiscountCodePeriod.start_month <= month)
        .where(
            (DiscountCodePeriod.end_month.is_(None))
            | (DiscountCodePeriod.end_month >= month)
        )
    ).all()
    return {code: affiliate_id for code, affiliate_id in rows}


def verified_codes_for(
    db: Session, affiliate: AffiliateProfile
) -> list[DiscountCodePeriod]:
    """Codes this affiliate holds that Shopify has confirmed exist.

    Not month-scoped, deliberately. This answers "has anybody actually checked
    a code for this person", which gates approval (§10.4) - a question about
    the affiliate, not about a particular month.
    """
    return list(
        db.scalars(
            select(DiscountCodePeriod)
            .where(DiscountCodePeriod.affiliate_id == affiliate.id)
            .where(DiscountCodePeriod.shopify_verified_at.is_not(None))
            .order_by(DiscountCodePeriod.code)
        )
    )


def mark_verified(
    db: Session,
    period: DiscountCodePeriod,
    *,
    verified_at: datetime,
    start_month: str | None = None,
    actor_id: int | None = None,
    actor_email: str | None = None,
) -> None:
    """Record that Shopify has now confirmed a code that it had not before.

    ``start_month`` is corrected at the same time, because the two facts arrive
    together: until Shopify knows the code, its creation date is unknown and
    the period had to fall back to the platform horizon. Once the code exists,
    the right start is known - and leaving the horizon in place would claim
    months the code did not exist for.
    """
    before = {
        "verified": period.is_verified,
        "start_month": period.start_month,
    }
    period.shopify_verified_at = verified_at
    if start_month is not None and start_month != period.start_month:
        parse_month(start_month)
        period.start_month = start_month

    record_audit(
        db,
        action="code.verified",
        subject=f"affiliate:{period.affiliate_id}",
        actor_id=actor_id,
        actor_email=actor_email,
        before=before,
        after={"verified": True, "start_month": period.start_month},
    )


def unregistered_code_for(
    db: Session, affiliate: AffiliateProfile
) -> DiscountCodePeriod | None:
    """The affiliate's code that Shopify has not confirmed, if any.

    There is at most one in practice: a model applies with a single code, and
    it stays unverified until somebody checks it.
    """
    return db.scalar(
        select(DiscountCodePeriod)
        .where(DiscountCodePeriod.affiliate_id == affiliate.id)
        .where(DiscountCodePeriod.shopify_verified_at.is_(None))
        .order_by(DiscountCodePeriod.id)
    )


def replace_code(
    db: Session,
    period: DiscountCodePeriod,
    new_code: str,
    *,
    start_month: str,
    verified_at: datetime | None = None,
    actor_id: int | None = None,
    actor_email: str | None = None,
) -> DiscountCodePeriod:
    """Correct a mistyped code.

    Rewrites the row rather than closing it and opening another. A period that
    was never verified never attributed anything, so there is no history to
    preserve - and leaving the wrong code behind would keep it holding
    ownership that blocks the right person from claiming it.

    **Only ever used on an unverified period.** A verified code has been live
    and may have attributed orders; changing it would rewrite what those orders
    belonged to.
    """
    if period.is_verified:
        raise ValueError(
            "A verified code cannot be rewritten - it may already have "
            "attributed orders. Close its period and register the new code."
        )

    previous = period.code
    period.code = normalise_code(new_code)
    period.start_month = parse_month(start_month)
    period.shopify_verified_at = verified_at

    record_audit(
        db,
        action="code.corrected",
        subject=f"affiliate:{period.affiliate_id}",
        actor_id=actor_id,
        actor_email=actor_email,
        before={"code": previous},
        after={"code": period.code, "verified": verified_at is not None},
    )
    return period


def close_codes_for(
    db: Session,
    affiliate: AffiliateProfile,
    month: str,
    *,
    actor_id: int | None = None,
    actor_email: str | None = None,
) -> int:
    """End an affiliate's open code ownership at the given month.

    Used when somebody is archived. Closing says "from now on, not theirs"; it
    can never say "was never theirs", because that would rewrite attribution in
    months already approved and paid.

    So only open-ended periods are touched, and only ones that started on or
    before the close month. A period that already ended earlier is left alone -
    closing must not *extend* anything.
    """
    parse_month(month)

    periods = list(
        db.scalars(
            select(DiscountCodePeriod)
            .where(DiscountCodePeriod.affiliate_id == affiliate.id)
            .where(DiscountCodePeriod.end_month.is_(None))
            .where(DiscountCodePeriod.start_month <= month)
        )
    )

    for period in periods:
        period.end_month = month
        record_audit(
            db,
            action="code.closed",
            subject=f"affiliate:{affiliate.id}",
            actor_id=actor_id,
            actor_email=actor_email,
            before={"code": period.code, "end_month": None},
            after={"code": period.code, "end_month": month},
        )

    return len(periods)
