"""Setting and reading pay terms.

Nothing here calculates anything. It records what an affiliate is owed *on*,
for which months; Phase 4 turns that into an amount.
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.businesstime import parse_month
from app.core.money import BASIS_POINTS
from app.core.periods import OPEN_ENDED, validate_period
from app.models.affiliates import AffiliateProfile
from app.models.compensation import VALID_TYPES, CompensationPeriod, CompensationType
from app.services.audit import record_audit

#: Which money field each type requires, and which it must not carry. Mirrors
#: the database check constraint; this is the half that produces a readable
#: message.
_REQUIRED_FIELD = {
    CompensationType.COMMISSION: None,
    CompensationType.FIXED_PLUS_COMMISSION: "fixed_amount_piastres",
    CompensationType.BASE_GUARANTEE: "base_amount_piastres",
}


def _require_money(value: object, name: str) -> int:
    """Piastres are integers. A float is a rounding error waiting to be paid."""
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} must be an integer number of piastres")
    if value < 0:
        raise ValueError(f"{name} cannot be negative")
    return value


def set_terms(
    db: Session,
    affiliate: AffiliateProfile,
    *,
    start_month: str,
    compensation_type: str,
    commission_rate_bp: int,
    end_month: str | None = OPEN_ENDED,
    fixed_amount_piastres: int | None = None,
    base_amount_piastres: int | None = None,
    expected_customer_discount_bp: int | None = None,
    actor_id: int | None = None,
    actor_email: str | None = None,
) -> CompensationPeriod:
    """Record what an affiliate is paid on, for a run of months.

    A rate change is a **new period**, never an edit to an existing one. The
    database refuses two periods that overlap, so the months an affiliate was
    on 8% cannot later become months they were on 10%.
    """
    if compensation_type not in VALID_TYPES:
        raise ValueError(f"Unknown compensation type: {compensation_type!r}")

    start_month, end_month = validate_period(start_month, end_month)

    if isinstance(commission_rate_bp, bool) or not isinstance(commission_rate_bp, int):
        raise TypeError("commission_rate_bp must be an integer")
    if not 0 < commission_rate_bp <= BASIS_POINTS:
        raise ValueError(
            "Commission rate must be above 0 and at most 10000 basis points"
        )

    # Each type carries exactly the money fields it uses, and no others.
    required = _REQUIRED_FIELD[compensation_type]
    supplied = {
        "fixed_amount_piastres": fixed_amount_piastres,
        "base_amount_piastres": base_amount_piastres,
    }
    for name, value in supplied.items():
        if name == required:
            if value is None:
                raise ValueError(
                    f"{compensation_type} requires {name}"
                )
            _require_money(value, name)
        elif value is not None:
            raise ValueError(
                f"{compensation_type} must not carry {name} - a field nothing "
                "reads looks like money that is being paid"
            )

    if expected_customer_discount_bp is not None:
        if (
            isinstance(expected_customer_discount_bp, bool)
            or not isinstance(expected_customer_discount_bp, int)
        ):
            raise TypeError("expected_customer_discount_bp must be an integer")
        if not 0 <= expected_customer_discount_bp <= BASIS_POINTS:
            raise ValueError(
                "Customer discount must be between 0 and 10000 basis points"
            )

    terms = CompensationPeriod(
        affiliate_id=affiliate.id,
        start_month=start_month,
        end_month=end_month,
        compensation_type=compensation_type,
        commission_rate_bp=commission_rate_bp,
        fixed_amount_piastres=fixed_amount_piastres,
        base_amount_piastres=base_amount_piastres,
        expected_customer_discount_bp=expected_customer_discount_bp,
    )
    db.add(terms)
    db.flush()

    record_audit(
        db,
        action="compensation.set",
        subject=f"affiliate:{affiliate.id}",
        actor_id=actor_id,
        actor_email=actor_email,
        after={
            "start_month": start_month,
            "end_month": end_month,
            "compensation_type": compensation_type,
            "commission_rate_bp": commission_rate_bp,
            "fixed_amount_piastres": fixed_amount_piastres,
            "base_amount_piastres": base_amount_piastres,
            "expected_customer_discount_bp": expected_customer_discount_bp,
        },
    )
    return terms


def terms_for(
    db: Session, affiliate: AffiliateProfile, month: str
) -> CompensationPeriod | None:
    """The terms in force for this affiliate in this month, if any.

    Asks about a month rather than "current terms", because a historical month
    must be calculated on the terms that were in force then.
    """
    parse_month(month)
    return db.scalar(
        select(CompensationPeriod)
        .where(CompensationPeriod.affiliate_id == affiliate.id)
        .where(CompensationPeriod.start_month <= month)
        .where(
            (CompensationPeriod.end_month.is_(None))
            | (CompensationPeriod.end_month >= month)
        )
    )
