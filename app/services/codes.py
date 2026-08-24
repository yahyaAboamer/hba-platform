"""Registering and resolving discount code ownership.

Everything here asks about a **month**. "Who owns NOUR10?" is not a question
this module answers, because it does not have an answer - ownership is dated,
and using today's ownership for an April order would make last April's payroll
change every time a code moved.
"""

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.businesstime import parse_month
from app.core.periods import OPEN_ENDED, validate_period
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
