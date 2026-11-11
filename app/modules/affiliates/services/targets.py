"""Setting requirements and recording what happened.

§15, and for a `base_guarantee` model this is the input that decides their pay.

## Recording is the confirmation

`targets.record` writes what they produced, and those counts are the confirmed
ones (ADR 0081, owner, 11 November 2026). There used to be a second step,
`targets.verify`, that a met guarantee waited on. It changed money in that one
case only, and the person who recorded the counts could confirm them a second
later, so it checked nothing; the owner removed it. The `verified_by` /
`verified_at` columns stay, unread, so past confirmations remain in the record.

A **missed** target is paid its commission, the month approves, and the
guarantee simply does not apply (§11.3) - missing information blocks a month,
a quiet month never does.

## Nothing here can be changed once a month is approved

§15. Changing a target after payroll would change what a month was worth after it
was paid. Payroll months arrive in Phase 6, so `assert_recordable` is the seam and
today it blocks nothing - the same shape as `assert_correctable` for compensation
in Phase 3, and recorded as such rather than assumed closed.
"""

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.businesstime import parse_month, utcnow
from app.modules.affiliates.models.affiliates import AffiliateProfile
from app.modules.affiliates.models.targets import VALID_OUTCOMES, MonthlyTarget
from app.shared.services.audit import record_audit


def _snapshot(target: MonthlyTarget) -> dict:
    return {
        "month": target.month,
        "required_videos": target.required_videos,
        "required_stories": target.required_stories,
        "actual_videos": target.actual_videos,
        "actual_stories": target.actual_stories,
        "recorded_outcome": target.recorded_outcome,
    }


def _refuse_counts_on_a_backfilled_month(target: MonthlyTarget | None) -> None:
    """ADR 0036. A row holds counts or an outcome, and never both.

    The database refuses the mixture too. This is the half that says why, so a
    maintainer who opens the Targets screen on a month from before the platform
    is told the counts were never kept rather than shown a constraint name.
    """
    if target is not None and target.is_backfilled:
        raise ValueError(
            f"{target.month} happened before the platform and carries an "
            "outcome, not counts. The video and story numbers for that month "
            "were never kept, and typing some in now would invent evidence "
            "for a figure that decides money. Change the outcome instead."
        )


def before_her_start(affiliate: AffiliateProfile, month: str) -> bool:
    """Whether this month is before the month she started with HBA (ADR 0056).

    Only a start that is known counts: from her code on Shopify, or typed on
    her profile. With none recorded there is nothing to hold a month against.
    """
    start = affiliate.collaboration_start_month
    return start is not None and month < start


def _refuse_before_her_start(affiliate: AffiliateProfile, month: str) -> None:
    """She was not working with HBA before her start, so a target there asks
    her for work in a month that was never hers (owner, 1 October 2026)."""
    if before_her_start(affiliate, month):
        raise ValueError(
            f"she started with HBA in {affiliate.collaboration_start_month}, so "
            f"{month} is before her start and has no targets"
        )


def assert_month_recordable(db: Session, affiliate_id: int, month: str) -> None:
    """Refuse to record anything against a month that is already approved.

    The same rule as `assert_recordable`, asked of a **month** rather than of an
    existing target - because the first thing recorded for a month has no
    target row to ask about yet.

    That gap was real and it was found by a test. `record_outcome` creates the
    row it writes to, so guarding only the existing-row path let an outcome be
    recorded for a month that had already been approved: the frozen figure
    would not move, and every screen would then say a guarantee applied to a
    month calculated without it.
    """
    from app.modules.affiliates.models.payroll import CalculationState, PayrollMonth

    approved = db.scalar(
        select(PayrollMonth)
        .where(PayrollMonth.affiliate_id == affiliate_id)
        .where(PayrollMonth.month == month)
        .where(PayrollMonth.calculation_state == CalculationState.APPROVED)
    )
    if approved is not None:
        raise ValueError(
            f"{month} is approved. Recording this now would change whether a "
            "base guarantee applied, after the month was agreed. Reopen the "
            "month first - it requires a written reason."
        )


def assert_recordable(db: Session, target: MonthlyTarget) -> None:
    """Refuse to change a target belonging to an approved month.

    §15. A target decides whether a base guarantee applied, so editing one after
    payroll changes what the month was worth **after the money moved** - and the
    snapshot would disagree with the target it was calculated from.

    **A seam since Phase 5, and blocking from Phase 6**, exactly as the
    `docs/limits.md` entry said it would be.
    """
    from app.modules.affiliates.models.payroll import CalculationState, PayrollMonth

    approved = db.scalar(
        select(PayrollMonth)
        .where(PayrollMonth.affiliate_id == target.affiliate_id)
        .where(PayrollMonth.month == target.month)
        .where(PayrollMonth.calculation_state == CalculationState.APPROVED)
    )
    if approved is not None:
        raise ValueError(
            f"{target.month} is approved. Changing this target now would change "
            "whether a base guarantee applied, after the month was agreed. "
            "Reopen the month first - it requires a written reason."
        )


def get_target(
    db: Session, affiliate: AffiliateProfile, month: str
) -> MonthlyTarget | None:
    """This affiliate's target for this month, if one has been set."""
    parse_month(month)
    return db.scalar(
        select(MonthlyTarget)
        .where(MonthlyTarget.affiliate_id == affiliate.id)
        .where(MonthlyTarget.month == month)
    )


def targets_for(db: Session, month: str) -> dict[int, MonthlyTarget]:
    """Every target for one month, keyed by affiliate.

    One query for the whole grid. Twenty separate lookups would work and would
    also be twenty round trips on a screen somebody opens every month.
    """
    parse_month(month)
    return {
        row.affiliate_id: row
        for row in db.scalars(
            select(MonthlyTarget).where(MonthlyTarget.month == month)
        )
    }


def grid_roster(db: Session, *, include_archived: bool = False) -> list[AffiliateProfile]:
    """Who the Targets grid lists down the side (``GET /api/targets/{month}``).

    A declined application is nobody's model (ADR 0058). Usually it is gone
    altogether; one kept because an order is hers still has no targets.

    **A bare application is nobody's model yet** (owner, 10 November 2026):
    pending, and no terms ever set. Nothing is owed to her, so a row of empty
    boxes and an amber *No record yet* beside her name warned about nothing.
    A pending model HBA has already given terms is being onboarded and stays.
    House accounts and months before her start stay listed: the screen draws
    them (or leaves a house code out), and a payload that quietly omits rows
    is one nobody can reconcile against the registry.
    """
    from app.modules.affiliates.models.affiliates import AffiliateStatus
    from app.modules.affiliates.models.compensation import CompensationPeriod
    from app.modules.affiliates.services.affiliates import list_affiliates

    with_terms = set(db.scalars(select(CompensationPeriod.affiliate_id).distinct()))
    return [
        affiliate
        for affiliate in list_affiliates(db, include_archived=include_archived)
        if affiliate.status != AffiliateStatus.DECLINED
        and not (
            affiliate.status == AffiliateStatus.PENDING
            and affiliate.id not in with_terms
        )
    ]


def targets_not_set(db: Session, month: str) -> tuple[int, int]:
    """For Today: ``(not set, models)`` - how many models the Targets grid
    for ``month`` shows open with no target, out of how many it shows open.

    The grid's own roster (``grid_roster``, archived left out as the screen
    opens), less the rows the screen does not ask anybody to fill: a house
    code (the screen leaves it off) and a month before her start (drawn
    closed). No target means ``required_videos`` is empty, as the grid shows
    it. Not ``pace_for``: pace is about counts recorded, not targets set.
    """
    from app.modules.affiliates.models.affiliates import AccountKind

    parse_month(month)
    found = targets_for(db, month)
    open_rows = [
        affiliate
        for affiliate in grid_roster(db)
        if affiliate.account_kind != AccountKind.HOUSE and not before_her_start(affiliate, month)
    ]
    missing = sum(
        1
        for affiliate in open_rows
        if (target := found.get(affiliate.id)) is None or target.required_videos is None
    )
    return missing, len(open_rows)


def set_requirements(
    db: Session,
    affiliate: AffiliateProfile,
    month: str,
    *,
    videos: int,
    stories: int,
    actor_id: int | None = None,
    actor_email: str | None = None,
) -> MonthlyTarget:
    """What this model is asked to produce this month.

    Creates the row or updates the requirement on an existing one. Recorded
    actuals are left alone: changing what was asked for does not un-know what
    they did.
    """
    parse_month(month)
    if videos < 0 or stories < 0:
        raise ValueError("A requirement cannot be negative")

    target = get_target(db, affiliate, month)
    _refuse_counts_on_a_backfilled_month(target)
    before = _snapshot(target) if target else None

    if target is None:
        _refuse_before_her_start(affiliate, month)
        target = MonthlyTarget(
            affiliate_id=affiliate.id,
            month=month,
            required_videos=int(videos),
            required_stories=int(stories),
        )
        db.add(target)
    else:
        assert_recordable(db, target)
        if (target.required_videos, target.required_stories) == (int(videos), int(stories)):
            # The grid sends every row it shows. Asking for what is already
            # asked for is not a change: nothing to write or audit.
            return target
        # After the no-change return, so a target already on record before her
        # start can be re-sent as it is; only changing it is refused.
        _refuse_before_her_start(affiliate, month)
        target.required_videos = int(videos)
        target.required_stories = int(stories)
        target.updated_at = utcnow()

    db.flush()
    record_audit(
        db,
        action="target.requirements_set",
        subject=f"affiliate:{affiliate.id}",
        actor_id=actor_id,
        actor_email=actor_email,
        before=before,
        after=_snapshot(target),
    )
    return target


def record_actuals(
    db: Session,
    target: MonthlyTarget,
    *,
    videos: int,
    stories: int,
    actor_id: int | None = None,
    actor_email: str | None = None,
    recorded_at: datetime | None = None,
) -> MonthlyTarget:
    """What they actually produced.

    **Both numbers together.** A half-recorded month is not a state anybody has
    a rule for - "eight videos and an unknown number of stories" cannot answer
    whether they achieved, and the database refuses it too.

    **The same numbers again are not a re-recording** and change nothing.

    `recorded_at` is injectable. **When** a count was recorded became a fact with consequences in
    07A: weekly pace compares it against the week she is in, and a test that
    could not choose the date would only exercise whichever week the suite
    happened to run in.
    """
    assert_recordable(db, target)
    _refuse_counts_on_a_backfilled_month(target)
    if videos < 0 or stories < 0:
        raise ValueError("An actual cannot be negative")

    if (target.actual_videos, target.actual_stories) == (int(videos), int(stories)):
        # The same numbers again are not a re-recording. The grid sends every
        # row it shows, so without this, saving one model's count moved every
        # other model's *Last updated* to today.
        return target
    _refuse_before_her_start(db.get(AffiliateProfile, target.affiliate_id), target.month)

    before = _snapshot(target)

    target.actual_videos = int(videos)
    target.actual_stories = int(stories)
    target.recorded_by = actor_id
    target.recorded_at = recorded_at or utcnow()
    target.updated_at = utcnow()
    db.flush()

    record_audit(
        db,
        action="target.actuals_recorded",
        subject=f"affiliate:{target.affiliate_id}",
        actor_id=actor_id,
        actor_email=actor_email,
        before=before,
        after=_snapshot(target),
    )
    return target


def record_outcome(
    db: Session,
    affiliate: AffiliateProfile,
    month: str,
    *,
    outcome: str,
    actor_id: int | None = None,
    actor_email: str | None = None,
) -> MonthlyTarget:
    """Whether a month before the platform met its target. ADR 0036.

    The old dashboard kept the answer and not the arithmetic. So this records
    the answer by itself - no requirement, no counts - and the model's Targets
    card says the numbers were not kept rather than drawing a bar against a
    zero.

    ## Only before go-live, and that is the whole safety of it

    Every later month records what they produced, and the guarantee is decided
    by comparing it to what was asked. Letting an outcome be typed for
    September would let somebody unlock a guarantee by asserting it.

    Recorded is settled, as it is for counts (ADR 0081); the audit trail says
    who.
    """
    from app.modules.affiliates.services.payroll import go_live_month, is_historical

    parse_month(month)
    if str(outcome or "") not in VALID_OUTCOMES:
        raise ValueError("An outcome is either 'met' or 'missed'")

    if not go_live_month():
        raise ValueError(
            "Nobody has said which month the platform starts paying for, so "
            "there is no such thing as a month before it yet. Set the go-live "
            "month first."
        )
    if not is_historical(month):
        raise ValueError(
            f"{month} is not before the platform started paying. Record what "
            "they produced instead - an outcome asserted "
            "without numbers would unlock a guarantee on a month that can "
            "still be paid."
        )

    # Asked of the month, not of the row: the row may not exist yet, and this
    # function is the one that would create it.
    assert_month_recordable(db, affiliate.id, month)

    target = get_target(db, affiliate, month)
    if target is not None:
        if target.actual_videos is not None:
            # Somebody has counted this month for real. Clearing that to store
            # a one-word summary of it destroys the better record.
            raise ValueError(
                f"{month} already has recorded counts. An outcome replaces "
                "numbers nobody kept, not numbers somebody took the trouble "
                "to record."
            )

    before = _snapshot(target) if target else None
    recorded_at = utcnow()

    if target is None:
        target = MonthlyTarget(affiliate_id=affiliate.id, month=month)
        db.add(target)

    # Assigned outright. A requirement left behind from the Targets screen
    # would sit next to an outcome it was never compared against, which is
    # exactly the mixture the check constraint refuses.
    target.required_videos = None
    target.required_stories = None
    target.recorded_outcome = str(outcome)
    target.recorded_by = actor_id
    target.recorded_at = recorded_at
    target.updated_at = recorded_at
    db.flush()

    record_audit(
        db,
        action="target.outcome_recorded",
        subject=f"affiliate:{affiliate.id}",
        actor_id=actor_id,
        actor_email=actor_email,
        before=before,
        after=_snapshot(target),
    )
    return target


def clear_actuals(
    db: Session,
    target: MonthlyTarget,
    *,
    actor_id: int | None = None,
    actor_email: str | None = None,
) -> MonthlyTarget:
    """Put a month back to *nobody has recorded what she did*.

    **Unrecorded and zero are different facts** (A06), and until this existed
    the platform could only move one way between them. A count typed against
    the wrong model could be corrected to `0` and nothing else — which does not
    say "this was a mistake", it says *she produced nothing*, and that is the
    claim that fails a guaranteed minimum.

    A confirmation from before ADR 0081 is cleared with the counts: the
    database refuses a confirmation of nothing.

    Refused on the same months a recording is refused on — an approved month is
    frozen in its snapshot, and a backfilled one never had counts to clear.
    """
    assert_recordable(db, target)
    _refuse_counts_on_a_backfilled_month(target)

    if target.actual_videos is None and target.actual_stories is None:
        # Already unrecorded. Recording nothing about nothing is an audit entry
        # nobody can act on.
        return target

    before = _snapshot(target)

    target.actual_videos = None
    target.actual_stories = None
    target.recorded_by = None
    target.recorded_at = None
    target.verified_by = None
    target.verified_at = None
    target.updated_at = utcnow()
    db.flush()

    record_audit(
        db,
        action="target.actuals_cleared",
        subject=f"affiliate:{target.affiliate_id}",
        actor_id=actor_id,
        actor_email=actor_email,
        before=before,
        after=_snapshot(target),
    )
    return target


#: Why a month was left out of a year-wide requirement change.
ALREADY_AGREED = "already_agreed"
BEFORE_THE_PLATFORM = "before_the_platform"
BEFORE_HER_START = "before_her_start"


def set_requirements_for_year(
    db: Session,
    affiliate: AffiliateProfile,
    month: str,
    *,
    videos: int,
    stories: int,
    actor_id: int | None = None,
    actor_email: str | None = None,
) -> dict:
    """Set the same requirement on every month of that month's year.

    **Because a model's targets are fixed across a year** (owner, 11 September
    2026). Varying a single month is the exception, and the exception is what
    the caller opts out into — so this writes the whole calendar year and the
    ordinary per-month save is left alone.

    ## January included, deliberately

    Asked directly whether "the whole year" meant this month onward or every
    month including ones already gone, the owner chose **every month of the
    year, January included**. The risk was put to him in the same sentence and
    is worth repeating here, because it is the reason this function returns a
    report instead of nothing:

    **A month that has already been counted can change what it means.** Raising
    March's requirement after March's counts were recorded can turn a month
    that was achieved into one that was missed — and on a guaranteed minimum
    that is the difference between a floor applying and not applying. Nothing
    is silently rewritten: every month this touches and every month it refuses
    comes back named.

    ## What it will not touch, and why that is not a choice

    **An agreed month.** `assert_month_recordable` refuses it, and that refusal
    is the whole of 05B — an agreed month is not unmade, and its snapshot froze
    the requirement it was agreed against. Skipping is therefore forced rather
    than decided; the alternative is that a year-wide change becomes impossible
    the moment anything is approved, which by December is most of the year.

    **A month from before the platform.** ADR 0036: it carries an outcome and
    no counts, because the old dashboard never kept them. Giving it a
    requirement would invent the very evidence that record exists to say
    nobody has.
    """
    parse_month(month)
    year = month[:4]

    applied: list[str] = []
    skipped: list[dict] = []

    for index in range(1, 13):
        candidate = f"{year}-{index:02d}"
        existing = get_target(db, affiliate, candidate)

        # **Not a month she was with HBA** (ADR 0056). "The whole year" is her
        # year from her start; January to March of a model who began in April
        # were never hers to be asked for anything.
        if before_her_start(affiliate, candidate):
            skipped.append({"month": candidate, "why": BEFORE_HER_START})
            continue
        if existing is not None and existing.is_backfilled:
            skipped.append({"month": candidate, "why": BEFORE_THE_PLATFORM})
            continue
        try:
            assert_month_recordable(db, affiliate.id, candidate)
        except ValueError:
            skipped.append({"month": candidate, "why": ALREADY_AGREED})
            continue

        set_requirements(
            db,
            affiliate,
            candidate,
            videos=videos,
            stories=stories,
            actor_id=actor_id,
            actor_email=actor_email,
        )
        applied.append(candidate)

    record_audit(
        db,
        action="target.requirements_set_for_year",
        subject=f"affiliate:{affiliate.id}",
        actor_id=actor_id,
        actor_email=actor_email,
        after={
            "year": year,
            "videos": int(videos),
            "stories": int(stories),
            "applied": applied,
            "skipped": skipped,
        },
    )
    return {"applied": applied, "skipped": skipped}
