"""Setting and reading pay terms.

Nothing here calculates anything. It records what an affiliate is owed *on*,
for which months; Phase 4 turns that into an amount.
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.businesstime import month_add, parse_month
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


def _supersede_open_terms(
    db: Session,
    affiliate: AffiliateProfile,
    start_month: str,
    end_month: str | None,
    *,
    actor_id: int | None = None,
    actor_email: str | None = None,
) -> list[CompensationPeriod]:
    """End the arrangement in force, so a new one can start.

    **A rate change is one decision** - *from September they are on 12%* - and
    the maintainer should not have to perform it as two. Doing it here means it
    happens inside the caller's transaction: the old arrangement ends and the
    new one begins together, or neither does.

    Done from the browser as two calls it can half-succeed, and the half that
    survives is the destructive one - a model left with no terms at all from
    September, whose payroll then blocks with nothing saying why. The screen
    already promised this was one act; it returned a 409 instead.

    **Only an open-ended arrangement is superseded.** One that already carries
    an end month was a deliberate choice about when it stops, and shortening
    that silently is a different act from ending the current one. New terms
    overlapping a closed period are still refused by the database.

    Backfilling earlier history is left alone: terms that end before the open
    arrangement begins do not overlap it, so nothing is closed.
    """
    open_now = list(
        db.scalars(
            select(CompensationPeriod)
            .where(CompensationPeriod.affiliate_id == affiliate.id)
            .where(CompensationPeriod.end_month.is_(None))
        )
    )

    superseded = []
    for terms in open_now:
        if end_month is not None and end_month < terms.start_month:
            continue
        if terms.start_month > start_month:
            # Strictly later, now. An arrangement starting in the *same* month
            # is handled before this is ever reached - naming that month means
            # rewriting it, which is the one control the walkthrough asked for.
            # What is still refused is starting an arrangement *before* one
            # already in force, which would swallow months nobody looked at.
            raise ValueError(
                f"An arrangement already starts in {terms.start_month}. Start "
                "the new one in that month to rewrite it, or in a later one."
            )
        close_terms(
            db,
            terms,
            month_add(start_month, -1),
            actor_id=actor_id,
            actor_email=actor_email,
        )
        superseded.append(terms)

    return superseded


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

    Which is why this also **ends the arrangement currently in force**, in
    the same transaction: without it every rate change after the first was
    refused, and doing it from the browser as two calls could leave a model
    with no terms at all. See `_supersede_open_terms`.
    """
    validate_terms(
        compensation_type,
        commission_rate_bp,
        fixed_amount_piastres,
        base_amount_piastres,
        expected_customer_discount_bp,
    )
    start_month, end_month = validate_period(start_month, end_month)

    # **Naming the month an arrangement already starts in means "I meant this
    # instead", not "a second arrangement begins here".**
    #
    # This used to be a separate control the maintainer had to choose between -
    # *changing what somebody is paid* versus *fixing what was typed* - and the
    # difference between them is real but almost impossible to hold in mind at
    # the moment of use. The walkthrough asked for one control. This is how one
    # control keeps both meanings: a later month opens a new arrangement, the
    # same month rewrites the one already there.
    #
    # Without it, deleting the second control would have left a rate typed
    # wrongly this month unfixable for ever - the only remaining move being to
    # start correct terms *next* month and leave this one wrong.
    #
    # `assert_correctable` is the guard that makes this safe: an approved month
    # refuses, because what a model was told they earned does not get rewritten
    # underneath them. Reopen it first, deliberately, with a written reason.
    replacing = db.scalar(
        select(CompensationPeriod)
        .where(CompensationPeriod.affiliate_id == affiliate.id)
        .where(CompensationPeriod.end_month.is_(None))
        .where(CompensationPeriod.start_month == start_month)
    )
    if replacing is not None:
        assert_correctable(db, replacing)
        before = {
            "compensation_type": replacing.compensation_type,
            "commission_rate_bp": replacing.commission_rate_bp,
            "fixed_amount_piastres": replacing.fixed_amount_piastres,
            "base_amount_piastres": replacing.base_amount_piastres,
        }
        # Assigned outright rather than merged. Here a `None` means "this type
        # has no such amount", where a merge would keep a salary belonging to
        # an arrangement the model is no longer on - money nothing reads, which
        # the next person to look assumes is paid.
        replacing.compensation_type = compensation_type
        replacing.commission_rate_bp = commission_rate_bp
        replacing.fixed_amount_piastres = fixed_amount_piastres
        replacing.base_amount_piastres = base_amount_piastres
        replacing.expected_customer_discount_bp = expected_customer_discount_bp
        replacing.end_month = end_month
        db.flush()
        record_audit(
            db,
            action="compensation.corrected",
            subject=f"affiliate:{affiliate.id}",
            actor_id=actor_id,
            actor_email=actor_email,
            before=before,
            after={
                "compensation_type": compensation_type,
                "commission_rate_bp": commission_rate_bp,
                "fixed_amount_piastres": fixed_amount_piastres,
                "base_amount_piastres": base_amount_piastres,
                "start_month": start_month,
            },
        )
        return replacing

    # Ends whatever is currently in force, in this same transaction, so the
    # change cannot half-happen. See `_supersede_open_terms`.
    _supersede_open_terms(
        db,
        affiliate,
        start_month,
        end_month,
        actor_id=actor_id,
        actor_email=actor_email,
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


def all_terms(db: Session, affiliate: AffiliateProfile) -> list[CompensationPeriod]:
    """Every arrangement this affiliate has ever been on, oldest first.

    `terms_for` answers *what applied in April*; this answers *what has she
    been on*, which is the question the pay-history editor opens with and the
    only one a single current period cannot answer.
    """
    return list(
        db.scalars(
            select(CompensationPeriod)
            .where(CompensationPeriod.affiliate_id == affiliate.id)
            .order_by(CompensationPeriod.start_month)
        )
    )


def _covering(periods: list[dict], month: str) -> dict | None:
    """Which of a proposed set of periods covers a month, if any."""
    for period in periods:
        if period["start_month"] <= month and (
            period["end_month"] is None or month <= period["end_month"]
        ):
            return period
    return None


def _shape(terms: CompensationPeriod | dict) -> tuple:
    """What makes two arrangements the same arrangement.

    **The months are deliberately not part of it.** Replacing an open-ended
    period with one that ends in August changes when it stops, not what it
    pays, so an approved August calculated under it is untouched. That
    distinction is what lets a whole history be rewritten around months that
    are already agreed.
    """
    read = terms.get if isinstance(terms, dict) else lambda name: getattr(terms, name)
    return (
        read("compensation_type"),
        read("commission_rate_bp"),
        read("fixed_amount_piastres"),
        read("base_amount_piastres"),
    )


def _refuse_to_move_an_approved_month(
    db: Session, affiliate: AffiliateProfile, prepared: list[dict]
) -> None:
    """Every approved month must come out on the arrangement it is on now.

    Section 11.1 and 11.5. Changing a rate after payroll would change what a
    month was worth **after the money moved**, and the frozen snapshot would
    silently disagree with the data it came from.

    Stated as *the answer does not move* rather than *the row does not change*,
    which is what lets a whole history be rewritten around months that are
    already agreed. That is the real case and the one a cruder rule would
    refuse: a model with August agreed, and February to July still to enter.
    """
    from app.models.payroll import CalculationState, PayrollMonth

    approved = db.scalars(
        select(PayrollMonth)
        .where(PayrollMonth.affiliate_id == affiliate.id)
        .where(PayrollMonth.calculation_state == CalculationState.APPROVED)
        .order_by(PayrollMonth.month)
    )

    moved = []
    for payroll_month in approved:
        now = terms_for(db, affiliate, payroll_month.month)
        proposed = _covering(prepared, payroll_month.month)
        if now is None and proposed is None:
            continue
        if now is None or proposed is None or _shape(now) != _shape(proposed):
            moved.append(payroll_month.month)

    if not moved:
        return

    months = ", ".join(moved)
    one = len(moved) == 1
    raise ValueError(
        f"{months} {'is' if one else 'are'} already approved, and this would "
        f"change what {'it was' if one else 'they were'} calculated from - "
        "after the figure was agreed and possibly paid. Reopen "
        f"{'that month' if one else 'those months'} first; it requires a "
        "written reason."
    )


def replace_pay_history(
    db: Session,
    affiliate: AffiliateProfile,
    periods: list[dict],
    *,
    actor_id: int | None = None,
    actor_email: str | None = None,
) -> list[CompensationPeriod]:
    """Write a model's whole pay history in one act. ADR 0036.

    ## Why this is not a loop over `set_terms`

    `set_terms` records **one decision**: *from September she is on 12%.* It
    ends whatever is currently open, refuses to start before an arrangement
    already in force, and reads a repeated start month as a correction. Every
    one of those is right for that act and wrong for this one.

    This act is different: *here is every arrangement she has ever been on,
    from the month she joined until now.* Applied as a sequence of `set_terms`
    calls it leaves stray remnants of whatever was there before - a one-month
    arrangement nobody chose, sitting in a month nobody looked at, quietly
    deciding what an old month is worth.

    So the whole set is written at once, and it is **all or nothing**. A
    half-written history is a model with months that cannot be calculated, and
    the screen promised one Save.

    ## What it refuses

    Anything that would change what an approved month was calculated from - see
    `_refuse_to_move_an_approved_month`, which states that as *the answer does
    not move* rather than *the row does not change*.
    """
    prepared: list[dict] = []
    for raw in periods:
        compensation_type = raw.get("compensation_type")
        commission_rate_bp = raw.get("commission_rate_bp")
        fixed = raw.get("fixed_amount_piastres")
        base = raw.get("base_amount_piastres")
        discount = raw.get("expected_customer_discount_bp")
        validate_terms(compensation_type, commission_rate_bp, fixed, base, discount)
        start_month, end_month = validate_period(
            raw.get("start_month"), raw.get("end_month", OPEN_ENDED)
        )
        prepared.append(
            {
                "start_month": start_month,
                "end_month": end_month,
                "compensation_type": compensation_type,
                "commission_rate_bp": commission_rate_bp,
                "fixed_amount_piastres": fixed,
                "base_amount_piastres": base,
                "expected_customer_discount_bp": discount,
            }
        )

    prepared.sort(key=lambda row: row["start_month"])
    for earlier, later in zip(prepared, prepared[1:]):
        # Checked here as well as by the exclusion constraint, because the
        # constraint's message names a daterange and this one names two months.
        # Both are wanted: this is the readable half, and the constraint is the
        # half nobody can forget to call.
        if earlier["end_month"] is None:
            raise ValueError(
                f"The arrangement starting {earlier['start_month']} runs until "
                "further notice, so nothing can start after it. Only the last "
                "one may be open-ended."
            )
        if later["start_month"] <= earlier["end_month"]:
            raise ValueError(
                f"{earlier['start_month']} to {earlier['end_month']} and "
                f"{later['start_month']} overlap. A month cannot have been on "
                "two arrangements at once."
            )

    _refuse_to_move_an_approved_month(db, affiliate, prepared)

    existing = all_terms(db, affiliate)
    before = [
        {
            "start_month": row.start_month,
            "end_month": row.end_month,
            "compensation_type": row.compensation_type,
            "commission_rate_bp": row.commission_rate_bp,
            "fixed_amount_piastres": row.fixed_amount_piastres,
            "base_amount_piastres": row.base_amount_piastres,
        }
        for row in existing
    ]

    # Cleared and rewritten rather than reconciled row by row. The exclusion
    # constraint refuses overlaps at every intermediate step, so a reconciling
    # update would have to find an order of operations that is valid the whole
    # way through - and there is not always one. Deleting first always has one.
    #
    # Safe only because of the refusal above: nothing deleted here is what an
    # approved month was calculated from.
    for row in existing:
        db.delete(row)
    db.flush()

    written = []
    for row in prepared:
        terms = CompensationPeriod(affiliate_id=affiliate.id, **row)
        db.add(terms)
        written.append(terms)
    db.flush()

    record_audit(
        db,
        action="compensation.history_replaced",
        subject=f"affiliate:{affiliate.id}",
        actor_id=actor_id,
        actor_email=actor_email,
        before={"periods": before},
        after={"periods": prepared},
    )
    return written
