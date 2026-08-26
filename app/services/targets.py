"""Setting requirements, recording what happened, and confirming it.

§15, and for a `base_guarantee` model this is the input that decides her pay.

## Recording and confirming are separate permissions, deliberately

`targets.record` writes what she produced; `targets.verify` confirms it. They are
split because one person recording a number that unlocks a payment is one person
deciding what somebody is owed.

**HBA's `content_manager` role holds both** (ADR 0018), so today the separation is
structural rather than organisational - the platform enforces a split the staffing
does not. That is recorded in `docs/limits.md` as an accepted exposure. It is worth
keeping anyway: roles change, and the check is what will still be here.

## Verifying is not the same as approving of the result

A verified target that was **missed** is a confirmed miss. She is paid her
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
from app.models.targets import MonthlyTarget
from app.services.audit import record_audit


def _snapshot(target: MonthlyTarget) -> dict:
    return {
        "month": target.month,
        "required_videos": target.required_videos,
        "required_stories": target.required_stories,
        "actual_videos": target.actual_videos,
        "actual_stories": target.actual_stories,
        "verified": target.is_verified,
    }


def assert_recordable(db: Session, target: MonthlyTarget) -> None:
    """Refuse to change a target belonging to an approved month.

    **Blocks nothing today**, because approved months do not exist until
    Phase 6. It is here so the rule has one place to live rather than being
    remembered at three call sites later, and so the tests that will enforce it
    already have something to call.
    """
    return None


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
    she did.
    """
    parse_month(month)
    if videos < 0 or stories < 0:
        raise ValueError("A requirement cannot be negative")

    target = get_target(db, affiliate, month)
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
) -> MonthlyTarget:
    """What she actually produced.

    **Both numbers together.** A half-recorded month is not a state anybody has
    a rule for - "eight videos and an unknown number of stories" cannot answer
    whether she achieved, and the database refuses it too.

    **Re-recording clears any verification.** The confirmation was of the old
    numbers; leaving it in place would let a correction inherit somebody else's
    approval and unlock a guarantee nobody agreed to.
    """
    assert_recordable(db, target)
    if videos < 0 or stories < 0:
        raise ValueError("An actual cannot be negative")

    before = _snapshot(target)
    was_verified = target.is_verified

    target.actual_videos = int(videos)
    target.actual_stories = int(stories)
    target.recorded_by = actor_id
    target.recorded_at = utcnow()
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
    numbers, **not** the outcome - verifying a target she missed is a normal
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
