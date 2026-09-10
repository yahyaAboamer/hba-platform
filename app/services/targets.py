"""Setting requirements, recording what happened, and confirming it.

§15, and for a `base_guarantee` model this is the input that decides their pay.

## Recording and confirming are separate permissions, deliberately

`targets.record` writes what they produced; `targets.verify` confirms it. They are
split because one person recording a number that unlocks a payment is one person
deciding what somebody is owed.

**HBA's `content_manager` role holds both** (ADR 0018), so today the separation is
structural rather than organisational - the platform enforces a split the staffing
does not. That is recorded in `docs/limits.md` as an accepted exposure. It is worth
keeping anyway: roles change, and the check is what will still be here.

## Verifying is not the same as approving of the result

A verified target that was **missed** is a confirmed miss. They are paid their
commission, the month approves, and the guarantee simply does not apply (§11.3).
Verification confirms the *numbers*, never the outcome - conflating them would
block every model who had a quiet month.

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
from app.models.affiliates import AffiliateProfile
from app.models.targets import VALID_OUTCOMES, MonthlyTarget
from app.services.audit import record_audit


def _snapshot(target: MonthlyTarget) -> dict:
    return {
        "month": target.month,
        "required_videos": target.required_videos,
        "required_stories": target.required_stories,
        "actual_videos": target.actual_videos,
        "actual_stories": target.actual_stories,
        "recorded_outcome": target.recorded_outcome,
        "verified": target.is_verified,
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
    from app.models.payroll import CalculationState, PayrollMonth

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
    from app.models.payroll import CalculationState, PayrollMonth

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
        target = MonthlyTarget(
            affiliate_id=affiliate.id,
            month=month,
            required_videos=int(videos),
            required_stories=int(stories),
        )
        db.add(target)
    else:
        assert_recordable(db, target)
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

    **Re-recording clears any verification.** The confirmation was of the old
    numbers; leaving it in place would let a correction inherit somebody else's
    approval and unlock a guarantee nobody agreed to.

    `recorded_at` is injectable, exactly as `verify`'s is and for the same
    reason. **When** a count was recorded became a fact with consequences in
    07A: weekly pace compares it against the week she is in, and a test that
    could not choose the date would only exercise whichever week the suite
    happened to run in.
    """
    assert_recordable(db, target)
    _refuse_counts_on_a_backfilled_month(target)
    if videos < 0 or stories < 0:
        raise ValueError("An actual cannot be negative")

    before = _snapshot(target)
    was_verified = target.is_verified

    target.actual_videos = int(videos)
    target.actual_stories = int(stories)
    target.recorded_by = actor_id
    target.recorded_at = recorded_at or utcnow()
    if was_verified:
        target.verified_by = None
        target.verified_at = None
    target.updated_at = utcnow()
    db.flush()

    record_audit(
        db,
        action="target.actuals_recorded",
        subject=f"affiliate:{target.affiliate_id}",
        actor_id=actor_id,
        actor_email=actor_email,
        before=before,
        after={**_snapshot(target), "verification_cleared": was_verified},
    )
    return target


def verify(
    db: Session,
    target: MonthlyTarget,
    *,
    actor_id: int | None = None,
    actor_email: str | None = None,
    verified_at: datetime | None = None,
) -> MonthlyTarget:
    """A second person confirms the recorded numbers.

    This is what unlocks a base guarantee (§9.5, §11.3). It confirms the
    numbers, **not** the outcome - verifying a target they missed is a normal
    thing to do, and it means "these figures are right", not "well done".
    """
    assert_recordable(db, target)
    if not target.is_recorded:
        raise ValueError(
            "There is nothing to verify: no actuals have been recorded for this "
            "month. Confirming numbers nobody has entered would unlock a base "
            "guarantee on an empty month."
        )

    before = _snapshot(target)
    target.verified_by = actor_id
    target.verified_at = verified_at or utcnow()
    target.updated_at = utcnow()
    db.flush()

    record_audit(
        db,
        action="target.verified",
        subject=f"affiliate:{target.affiliate_id}",
        actor_id=actor_id,
        actor_email=actor_email,
        before=before,
        after={**_snapshot(target), "achieved": target.is_achieved},
    )
    return target


def unverify(
    db: Session,
    target: MonthlyTarget,
    *,
    reason: str,
    actor_id: int | None = None,
    actor_email: str | None = None,
) -> MonthlyTarget:
    """Take a confirmation back.

    **A written reason is required.** This is the only way back from a mistaken
    verification, and a mistaken verification silently pays a guarantee - so the
    audit trail has to say why somebody undid one.
    """
    assert_recordable(db, target)
    if not str(reason or "").strip():
        raise ValueError("Un-verifying a target requires a written reason")

    before = _snapshot(target)
    target.verified_by = None
    target.verified_at = None
    target.updated_at = utcnow()
    db.flush()

    record_audit(
        db,
        action="target.unverified",
        subject=f"affiliate:{target.affiliate_id}",
        actor_id=actor_id,
        actor_email=actor_email,
        before=before,
        after=_snapshot(target),
        reason=reason.strip(),
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

    ## Recording it also verifies it, and here is why that is not a shortcut

    Verification exists (§15) to stop one person inventing numbers that unlock
    a payment. Two things make that impossible here. There are **no numbers**:
    the outcome is the entire record, so a second person has nothing to check
    it against. And a month before go-live **cannot be paid** - its balance is
    structurally zero (ADR 0036), the payments screen refuses a transfer
    against it, and the money it refers to moved months ago outside the
    platform.

    So the split protects nothing on these months, while requiring it would
    mean a second pass through a screen built around counts, for every
    guarantee month of every model. Recorded and confirmed are one act, by the
    person who knows, and the audit trail says who.

    **This is the only place in the platform where they are one act.** Anywhere
    a month can still be paid, they are two.
    """
    from app.services.payroll import go_live_month, is_historical

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
            "they produced, and have it confirmed - an outcome asserted "
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
    target.verified_by = actor_id
    target.verified_at = recorded_at
    target.updated_at = recorded_at
    db.flush()

    record_audit(
        db,
        action="target.outcome_recorded",
        subject=f"affiliate:{affiliate.id}",
        actor_id=actor_id,
        actor_email=actor_email,
        before=before,
        # Named in the trail rather than left to be inferred from two
        # timestamps being equal: one person did both, deliberately, and the
        # reason is in this function's docstring.
        after={**_snapshot(target), "recorded_and_verified_together": True},
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

    Clearing verification with it, for the same reason `record_actuals` does:
    the confirmation was of numbers that are now gone, and leaving it would let
    an empty month inherit somebody's approval.

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
    was_verified = target.is_verified

    target.actual_videos = None
    target.actual_stories = None
    target.recorded_by = None
    target.recorded_at = None
    if was_verified:
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
        after={**_snapshot(target), "verification_cleared": was_verified},
    )
    return target
