"""Is a model's history actually set up, month by month?

Rule H06, and `DESIGN_REVIEW.md`'s **V09**, which is the reason this file
exists rather than a boolean somewhere:

> Historical readiness still uses the first `m.terms` entry rather than every
> monthly assignment. Probe reports missing terms after all eligible overrides
> were supplied.

That is the whole failure. A model who has *some* terms looks arranged, and a
screen that asks "does she have terms" gets a yes for a woman with four months
and eleven eligible ones. **This asks the question once per month.**

H06 again, on what does not count:

> A first terms record or a clicked Reviewed button does not prove readiness.

So nothing here is stored. There is no `is_ready` column and no Reviewed
button to press; the verdict is computed from the rows that decide money, every
time it is asked. A stored flag would be a claim about the past that the
present can contradict, which is exactly what happens when somebody edits a
month after review.

## What a month needs

Two things, and the second only sometimes:

1. **Compensation terms covering it.** Without them the calculator has no rate
   and the month cannot be worked out at all - `NO_TERMS` in the commission
   engine says so, and it is the single most common reason a payroll is stuck.

2. **A target outcome, if and only if the arrangement is a guaranteed
   minimum.** F06: *only guarantee depends on targets.* A commission month and
   a salary month are complete with terms alone, and demanding an outcome for
   them would block payroll on evidence that decides nothing.

   For a month **settled outside the platform** (ADR 0036), the outcome is the
   recorded met/missed - the counts were never kept and inventing them would be
   fabricating evidence for a figure that decides money (H02). For a **live**
   month, the existing verification is the gate, because that is what already
   releases a guarantee.

## What "eligible" means

From the month she actually started (H01, and the column 02A added) to the
working month. Not from the platform's horizon: a model who joined in June has
no January to arrange, and offering one invites somebody to fill in five months
that never existed.

Where no start is recorded the derivation stands, and the payload says which of
the two was used - a screen should be able to tell "she started in June" from
"we are guessing from her earliest order".
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.businesstime import month_add
from app.core.periods import PLATFORM_START_MONTH
from app.models.affiliates import AffiliateProfile
from app.models.attributed_orders import AttributedOrder
from app.models.compensation import CompensationType
from app.models.payroll import CalculationState, PayrollMonth
from app.models.targets import MonthlyTarget
from app.services.compensation import all_terms

#: Why a month is not ready. Strings rather than an enum because they cross the
#: wire, and each one is a sentence the interface turns into a reason.
NO_TERMS = "no_terms"
NO_TARGET_OUTCOME = "no_target_outcome"
TARGET_NOT_VERIFIED = "target_not_verified"


def eligible_months(db: Session, affiliate: AffiliateProfile, working: str) -> list[str]:
    """Every month this model can be arranged for, oldest first.

    Her recorded collaboration start where there is one, floored at the
    platform's horizon; otherwise the earliest month she has an order in. See
    the module docstring - the two are different facts and this prefers the one
    somebody actually knows.
    """
    first = affiliate.collaboration_start_month
    if first:
        first = max(first, PLATFORM_START_MONTH)
    else:
        first = db.scalar(
            select(AttributedOrder.business_month)
            .where(AttributedOrder.affiliate_id == affiliate.id)
            .order_by(AttributedOrder.business_month)
            .limit(1)
        )

    if not first or first > working:
        return []

    months: list[str] = []
    cursor = first
    # Bounded at both ends by real values, and capped anyway: a mis-set go-live
    # month is exactly the sort of thing that makes a month walk run away.
    while cursor <= working and len(months) < 120:
        months.append(cursor)
        cursor = month_add(cursor, 1)
    return months


def month_gaps(terms, target, *, historical: bool) -> list[str]:
    """What one month is still missing, or nothing. H06, F06.

    Extracted so the per-model payload and the whole-roster summary decide a
    month **the same way** (A09). The roster used to answer this question by
    comparing two dates instead, and two implementations of a readiness rule
    is two answers to *can she be paid*.
    """
    if terms is None:
        return [NO_TERMS]
    if terms.compensation_type != CompensationType.BASE_GUARANTEE:
        # **Only guarantee depends on targets** (F06). A commission or salary
        # month is complete with terms alone, and asking for an outcome would
        # block payroll on evidence that decides nothing.
        return []
    if historical:
        # ADR 0036: the counts were never kept, so the outcome *is* the
        # evidence. Absent, the guarantee cannot be decided - and F06 is
        # explicit that unknown qualifying information blocks a decision
        # rather than being read as a failure.
        if target is None or target.recorded_outcome is None:
            return [NO_TARGET_OUTCOME]
        return []
    # Live months keep the existing gate. Verification is what releases a
    # guarantee today, and adding a second approval would be a duplicate
    # process for one fact.
    if target is None or target.verified_at is None:
        return [TARGET_NOT_VERIFIED]
    return []


def setup_readiness(
    db: Session,
    affiliate: AffiliateProfile,
    *,
    working: str,
    is_historical,
) -> dict:
    """Month by month, whether she is set up - and what is missing where not.

    `is_historical` is passed in rather than imported, because importing it
    means importing `payroll`, which imports the commission engine, which
    imports this module's neighbours. The callers already hold it.

    One pass over each of three tables, not three queries per month. Eleven
    months and twenty models is otherwise six hundred round trips for something
    the database answers in three.
    """
    months = eligible_months(db, affiliate, working)
    if not months:
        return {
            "start_month": None,
            "start_is_recorded": affiliate.collaboration_start_month is not None,
            "months": [],
            "eligible": 0,
            "ready": 0,
            "blocking": 0,
        }

    # Terms, expanded across the months each period covers. `all_terms` returns
    # the periods; readiness is a question about months.
    covers: dict[str, object] = {}
    for period in all_terms(db, affiliate):
        cursor = period.start_month
        while cursor <= (period.end_month or working) and cursor <= months[-1]:
            covers[cursor] = period
            cursor = month_add(cursor, 1)

    targets = {
        row.month: row
        for row in db.scalars(
            select(MonthlyTarget).where(MonthlyTarget.affiliate_id == affiliate.id)
        )
    }
    approved = set(
        db.scalars(
            select(PayrollMonth.month)
            .where(PayrollMonth.affiliate_id == affiliate.id)
            .where(PayrollMonth.calculation_state == CalculationState.APPROVED)
        )
    )

    rows = []
    for month in months:
        terms = covers.get(month)
        historical = is_historical(month)
        missing = month_gaps(terms, targets.get(month), historical=historical)

        rows.append(
            {
                "month": month,
                "has_terms": terms is not None,
                "compensation_type": terms.compensation_type if terms else None,
                "settled_outside": historical,
                # An approved month is finished whatever else is true of it:
                # its terms are frozen in the snapshot and nothing here can or
                # should ask it to change.
                "approved": month in approved,
                "missing": [] if month in approved else missing,
                "ready": month in approved or not missing,
            }
        )

    ready = sum(1 for row in rows if row["ready"])
    return {
        "start_month": months[0],
        #: Whether the first month came from somebody who knew or from her
        #: earliest order. A screen should be able to tell those apart (H01).
        "start_is_recorded": affiliate.collaboration_start_month is not None,
        "months": rows,
        "eligible": len(rows),
        "ready": ready,
        "blocking": len(rows) - ready,
    }


def roster_readiness(
    db: Session,
    affiliates: list[AffiliateProfile],
    *,
    working: str,
    is_historical,
) -> dict[int, dict]:
    """The same verdict as `setup_readiness`, for a whole roster at once. A09.

    ## What this replaces, and why it is not the same question

    Settings' *Historical setup* column decided "Covered from the start" by
    comparing **two dates**: her earliest terms month against her collaboration
    start. That answers *do her terms begin early enough* and nothing else.

    It cannot see a gap in the middle - terms from January to March and from
    June onwards passes, with April and May uncalculable. It cannot see a
    guaranteed month with no recorded outcome, which blocks the figure just as
    completely as missing terms. And "Start month not recorded" was reported as
    a state of its own, when a model with no recorded start still has eligible
    months derived from her orders and can be perfectly ready across all of
    them.

    So the column now says how many of her eligible months are actually ready,
    from the same per-month rule the profile screen uses (`month_gaps`). H06 is
    explicit that a first terms record does not prove readiness; neither does
    an early one.

    ## Set-wise, because this is the screen with everybody on it

    Four queries for the whole roster rather than three per model. The loop
    this avoids is the shape that made the products screen slow (03D), and
    `setup_readiness` says the same thing about its own months.
    """
    from sqlalchemy import func

    from app.models.compensation import CompensationPeriod

    ids = [a.id for a in affiliates]
    if not ids:
        return {}

    first_order = dict(
        db.execute(
            select(
                AttributedOrder.affiliate_id,
                func.min(AttributedOrder.business_month),
            )
            .where(AttributedOrder.affiliate_id.in_(ids))
            .group_by(AttributedOrder.affiliate_id)
        ).all()
    )

    periods: dict[int, list] = {}
    for period in db.scalars(
        select(CompensationPeriod).where(CompensationPeriod.affiliate_id.in_(ids))
    ):
        periods.setdefault(period.affiliate_id, []).append(period)

    targets: dict[int, dict[str, object]] = {}
    for target in db.scalars(
        select(MonthlyTarget).where(MonthlyTarget.affiliate_id.in_(ids))
    ):
        targets.setdefault(target.affiliate_id, {})[target.month] = target

    approved: dict[int, set[str]] = {}
    for affiliate_id, month in db.execute(
        select(PayrollMonth.affiliate_id, PayrollMonth.month)
        .where(PayrollMonth.affiliate_id.in_(ids))
        .where(PayrollMonth.calculation_state == CalculationState.APPROVED)
    ).all():
        approved.setdefault(affiliate_id, set()).add(month)

    out: dict[int, dict] = {}
    for affiliate in affiliates:
        start = affiliate.collaboration_start_month
        first = (
            max(start, PLATFORM_START_MONTH)
            if start
            else first_order.get(affiliate.id)
        )
        if not first or first > working:
            out[affiliate.id] = {
                "eligible": 0,
                "ready": 0,
                "blocking": 0,
                "first_gap": None,
                "start_is_recorded": start is not None,
            }
            continue

        covers: dict[str, object] = {}
        for period in periods.get(affiliate.id, []):
            cursor = period.start_month
            while cursor <= (period.end_month or working):
                covers[cursor] = period
                cursor = month_add(cursor, 1)

        settled = approved.get(affiliate.id, set())
        mine = targets.get(affiliate.id, {})
        eligible = 0
        blocking = 0
        first_gap = None
        cursor = first
        while cursor <= working:
            eligible += 1
            # An approved month is finished whatever else is true of it: its
            # terms are frozen in the snapshot and nothing here can or should
            # ask it to change.
            if cursor not in settled and month_gaps(
                covers.get(cursor), mine.get(cursor), historical=is_historical(cursor)
            ):
                blocking += 1
                if first_gap is None:
                    first_gap = cursor
            cursor = month_add(cursor, 1)

        out[affiliate.id] = {
            "eligible": eligible,
            "ready": eligible - blocking,
            "blocking": blocking,
            #: The earliest month that cannot be calculated, so the screen can
            #: send somebody to it rather than to the top of a year.
            "first_gap": first_gap,
            #: H01. "She started in June" and "we are guessing from her
            #: earliest order" are different facts and a screen should be able
            #: to tell them apart - but neither of them is a readiness verdict,
            #: which is why this sits beside the counts rather than replacing
            #: them.
            "start_is_recorded": start is not None,
        }
    return out
