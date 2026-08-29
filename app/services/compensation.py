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


def validate_terms(
    compensation_type: str,
    commission_rate_bp: int,
    fixed_amount_piastres: int | None,
    base_amount_piastres: int | None,
    expected_customer_discount_bp: int | None,
) -> None:
    """Every rule about what a set of pay terms may say.

    Shared by creating and correcting, so the two can never drift into
    disagreeing about what a valid arrangement is - which would let a
    correction produce something creation would have refused.
    """
    if compensation_type not in VALID_TYPES:
        raise ValueError(f"Unknown compensation type: {compensation_type!r}")

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
                raise ValueError(f"{compensation_type} requires {name}")
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


def assert_correctable(db: Session, terms, *, new_end_month: str | None = "") -> None:
    """Refuse a change that an approved month was calculated from.

    §11.1 and §11.5. Changing a rate after payroll would change what a month
    was worth **after the money moved**, and the frozen snapshot would silently
    disagree with the data it came from. Reopen the month first, which requires
    a written reason.

    **A seam since Phase 3, and blocking from Phase 6.** The `docs/limits.md`
    entry recording it as unenforced said exactly this would happen.

    **Ending terms is not correcting them**, and the check is narrower for it.
    Closing a period in August does not change what April was worth - April was
    still on those terms and still says so. What is refused is a close that
    would leave an approved month **without terms at all**, which would make it
    incalculable if it were ever reopened. Pass ``new_end_month`` to get that
    reading; the default checks every month the terms cover.

    Only months the terms actually cover are ever checked. A rate that starts in
    September is not constrained by an approved August.
    """
    from app.models.payroll import CalculationState, PayrollMonth

    approved = db.scalars(
        select(PayrollMonth)
        .where(PayrollMonth.affiliate_id == terms.affiliate_id)
        .where(PayrollMonth.calculation_state == CalculationState.APPROVED)
        .where(PayrollMonth.month >= terms.start_month)
    )
    covered = [
        row.month
        for row in approved
        if terms.end_month is None or row.month <= terms.end_month
    ]

    if new_end_month != "":
        # Ending them. Only an approved month that would fall outside the new
        # coverage loses anything.
        covered = [
            month
            for month in covered
            if new_end_month is not None and month > new_end_month
        ]
        if covered:
            raise ValueError(
                f"Ending these terms in {new_end_month} would leave "
                f"{', '.join(sorted(covered))} - already approved - with no "
                "terms at all. Reopen the month first if that is intended."
            )
        return

    if covered:
        raise ValueError(
            "These terms were used to calculate an approved month "
            f"({', '.join(sorted(covered))}). Correcting them now would change "
            "what that month was worth after it was agreed. Reopen the month "
            "first - it requires a written reason."
        )


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
    validate_terms(
        compensation_type,
        commission_rate_bp,
        fixed_amount_piastres,
        base_amount_piastres,
        expected_customer_discount_bp,
    )
    start_month, end_month = validate_period(start_month, end_month)

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


def correct_terms(
    db: Session,
    terms: CompensationPeriod,
    *,
    compensation_type: str | None = None,
    commission_rate_bp: int | None = None,
    fixed_amount_piastres: int | None = None,
    base_amount_piastres: int | None = None,
    expected_customer_discount_bp: int | None = None,
    actor_id: int | None = None,
    actor_email: str | None = None,
) -> CompensationPeriod:
    """Fix a mistyped arrangement - the rate, the salary, or the base amount.

    All three are money that decides what somebody is paid, and all three are
    typed by a person. Without this, a rate entered as 100% instead of 10%, or
    a salary with a zero too many, could only be fixed in the database by hand.

    This corrects **what the arrangement says**, not when it applies. Moving a
    model onto different terms from a given month is a new period, not a
    correction - close this one and set new terms, so the months they were on the
    old arrangement keep saying so.

    An amount belonging to another type is cleared rather than left behind: a
    model moved from salary to commission-only must not keep a fixed amount
    that nothing reads, because the next person to look assumes it is paid.
    """
    assert_correctable(db, terms)

    new_type = compensation_type or terms.compensation_type
    changing_type = new_type != terms.compensation_type

    def keep_or_clear(supplied, current):
        if supplied is not None:
            return supplied
        return None if changing_type else current

    proposed = {
        "compensation_type": new_type,
        "commission_rate_bp": (
            commission_rate_bp
            if commission_rate_bp is not None
            else terms.commission_rate_bp
        ),
        "fixed_amount_piastres": keep_or_clear(
            fixed_amount_piastres, terms.fixed_amount_piastres
        ),
        "base_amount_piastres": keep_or_clear(
            base_amount_piastres, terms.base_amount_piastres
        ),
        "expected_customer_discount_bp": (
            expected_customer_discount_bp
            if expected_customer_discount_bp is not None
            else terms.expected_customer_discount_bp
        ),
    }

    validate_terms(
        proposed["compensation_type"],
        proposed["commission_rate_bp"],
        proposed["fixed_amount_piastres"],
        proposed["base_amount_piastres"],
        proposed["expected_customer_discount_bp"],
    )

    changed = {
        field: getattr(terms, field)
        for field in proposed
        if getattr(terms, field) != proposed[field]
    }
    if not changed:
        return terms

    for field, value in proposed.items():
        setattr(terms, field, value)

    record_audit(
        db,
        action="compensation.corrected",
        subject=f"affiliate:{terms.affiliate_id}",
        actor_id=actor_id,
        actor_email=actor_email,
        before=changed,
        after={field: proposed[field] for field in changed},
    )
    return terms


def close_terms(
    db: Session,
    terms: CompensationPeriod,
    end_month: str,
    *,
    actor_id: int | None = None,
    actor_email: str | None = None,
) -> CompensationPeriod:
    """End an arrangement, so a different one can start the month after.

    Without this an open-ended arrangement blocks every later one: the database
    refuses two overlapping periods, correctly, and there was no way to end the
    first. Moving a model onto new terms was simply impossible.

    Ending is not correcting. The months they were on these terms keep saying so,
    which is what makes a past month still calculable at the rate that applied
    then.
    """
    assert_correctable(db, terms, new_end_month=end_month)
    validate_period(terms.start_month, end_month)

    previous = terms.end_month
    if previous == end_month:
        return terms

    terms.end_month = end_month
    record_audit(
        db,
        action="compensation.closed",
        subject=f"affiliate:{terms.affiliate_id}",
        actor_id=actor_id,
        actor_email=actor_email,
        before={"end_month": previous},
        after={"end_month": end_month},
    )
    return terms


def get_terms(db: Session, period_id: int) -> CompensationPeriod | None:
    """One arrangement by id, for correcting or closing it."""
    return db.get(CompensationPeriod, period_id)


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
