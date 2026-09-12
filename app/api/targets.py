"""Targets over HTTP, and the grid Sara actually uses.

§12.2: *"Sara's target entry is a bulk grid — every model down the side, one
month across, tab straight through, single save."*

## One save, and it is all or nothing

Twenty models arrive in one request and are written in one transaction. If row
eleven is invalid, **nothing is written** and the response says which affiliate
and why.

A partial save on a grid is worse than a rejection: the person cannot see which
half landed, and the natural next move — fix it and press save again — writes the
good half twice while they are still wondering.

## Every model appears, including the ones with no target

A model missing from the grid is a model nobody records a target for, and that is
exactly the case that blocks their month later (§11.3). Returning them with nulls
puts the gap where somebody will see it, rather than leaving their absent and
therefore invisible.

## Recording and verifying are different permissions

`targets.record` writes actuals; `targets.verify` confirms them. Today one role
holds both (ADR 0018), so the split is enforced against a distinction HBA's
staffing does not yet make — which is the point: roles change, and the check is
what will still be here.
"""

import hashlib

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import require_permission
from app.core.businesstime import parse_month
from app.core.permissions import Permission
from app.db import get_session
from app.models.affiliates import AffiliateProfile
from app.models.identity import UserAccount
from app.models.compensation import CompensationType
from app.models.targets import MonthlyTarget
from app.services.affiliates import list_affiliates
from app.services.compensation import terms_for
from app.services.targets import (
    clear_actuals as clear_actuals_service,
    get_target,
    record_actuals,
    set_requirements,
    set_requirements_for_year,
    targets_for,
    unverify,
    verify,
)

router = APIRouter(prefix="/api/targets")


class GridRow(BaseModel):
    affiliate_id: int
    required_videos: int = Field(ge=0)
    required_stories: int = Field(ge=0)
    #: Both or neither. A half-recorded month cannot answer whether they
    #: achieved, and the database refuses it too.
    actual_videos: int | None = Field(default=None, ge=0)
    actual_stories: int | None = Field(default=None, ge=0)
    #: **Put this month back to unrecorded** (A06).
    #:
    #: `null` on the two above means *leave what is there alone*, which is what
    #: a screen editing only a requirement sends. It cannot also mean *take the
    #: counts off*, so this says so explicitly - and without it the only way to
    #: undo a count typed against the wrong model was to set it to zero, which
    #: claims she produced nothing and is the claim that fails a guarantee.
    clear_actuals: bool = False


class GridBody(BaseModel):
    rows: list[GridRow]
    #: Write these requirements to **every month of the year**, not just this
    #: one (owner, 11 September 2026): a model's targets are fixed across a
    #: year, and varying a single month is the exception you opt out into.
    #:
    #: Off by default, because that is how it was described - *if we wanted to
    #: edit a model's month, not the entire year, we just don't click this*.
    #: Counts are never year-wide: what she produced is a fact about one month.
    apply_to_year: bool = False
    #: What the screen was looking at when it started editing.
    #:
    #: Optional, and its absence is not treated as agreement: a save without
    #: one is refused rather than allowed through, because the callers that
    #: send nothing are the ones that have not been taught to check.
    revision: str | None = None


class VerifyBody(BaseModel):
    affiliate_ids: list[int]


class UnverifyBody(BaseModel):
    affiliate_ids: list[int]
    reason: str = Field(min_length=1, max_length=500)


def _month_or_400(month: str) -> str:
    try:
        return parse_month(month)
    except ValueError as exc:
        raise HTTPException(400, "A month looks like 2026-04") from exc


def _render(
    affiliate: AffiliateProfile,
    target: MonthlyTarget | None,
    *,
    determines_pay: bool = False,
    arrangement: str | None = None,
) -> dict:
    return {
        "affiliate_id": affiliate.id,
        "name": affiliate.name,
        # A house code publishes nothing and is never paid, so it has no
        # target. Listed rather than dropped server-side, because "who is
        # on this grid" is a screen's question and a payload that quietly
        # omits rows is one nobody can reconcile against the registry.
        "account_kind": affiliate.account_kind,
        # §15. Targets are **informational** for commission and
        # fixed_plus_commission, and decide what is paid only for
        # base_guarantee - which is also the only kind §11.3 blocks payroll on.
        #
        # A screen that cannot tell them apart marks every empty row as urgent,
        # and a warning that is always on is one nobody reads.
        "determines_pay": determines_pay,
        # The raw compensation type she was on that month, for the line the
        # approved grid writes beside every name. Raw, and labelled in the
        # browser: the words belong to the screen, and sending them from here
        # is how two screens start disagreeing about what to call one thing.
        "arrangement": arrangement,
        "required_videos": target.required_videos if target else None,
        "required_stories": target.required_stories if target else None,
        "actual_videos": target.actual_videos if target else None,
        "actual_stories": target.actual_stories if target else None,
        # Three answers, not two. `null` means nobody has recorded what they
        # did - which blocks their month, where missing the target does not.
        "achieved": target.is_achieved if target else None,
        "verified": bool(target and target.is_verified),
        "verified_at": target.verified_at.isoformat()
        if target and target.verified_at
        else None,
        "recorded_at": target.recorded_at.isoformat()
        if target and target.recorded_at
        else None,
    }


def _pace(db: Session, affiliate: AffiliateProfile, month: str) -> dict:
    """Whether she is keeping up with the month, week by week. D08.

    **On this screen and nowhere else.** The owner was asked directly and chose
    to keep it internal, so nothing about being behind reaches a model's own
    screens in any wording. The consequence he accepted: she cannot catch up on
    a warning she never sees.

    It decides no money. §15 is untouched - a target pays only on a guaranteed
    minimum, only at month end, and only when met *and* verified.
    """
    from app.services.pace import pace_for

    found = pace_for(db, affiliate, month)
    return {
        "state": found.state,
        "week": found.week,
        "required": found.required,
        "expected_by_now": found.expected_by_now,
        "done": found.done,
        "week_started": found.week_started.isoformat(),
    }


def _revision(targets: dict) -> str:
    """What this month looked like when it was handed out.

    **Derived, not stored.** A version column would need writing on every path
    that touches a target and would be wrong the first time somebody forgot;
    this is computed from the rows themselves, so it cannot drift from them.

    `updated_at` alone is not enough - a row *added* since the load changes no
    existing timestamp, and adding a model to the programme mid-edit is an
    ordinary thing to do. The count comes along for that.
    """
    stamps = sorted(
        (target.updated_at.isoformat() if target.updated_at else "")
        for target in targets.values()
    )
    return f"{len(stamps)}:" + hashlib.sha256(
        "|".join(stamps).encode("utf-8")
    ).hexdigest()[:16]


@router.get("/{month}")
def target_grid(
    month: str,
    include_archived: bool = False,
    _actor: UserAccount = Depends(require_permission(Permission.TARGETS_RECORD)),
    db: Session = Depends(get_session),
) -> dict:
    """Every model down the side, one month across.

    Models with no target appear with nulls rather than being omitted. An
    absent row is an invisible gap, and the gap is what blocks their month.
    """
    month = _month_or_400(month)
    affiliates = list_affiliates(db, include_archived=include_archived)
    found = targets_for(db, month)

    return {
        "month": month,
        # Handed out with the rows and handed back on save. Two people editing
        # one month is not hypothetical - the same two people run payroll.
        "revision": _revision(found),
        "rows": [
            {
                **_render(
                    affiliate,
                    found.get(affiliate.id),
                    determines_pay=arrangement
                    == CompensationType.BASE_GUARANTEE,
                    arrangement=arrangement,
                ),
                "pace": _pace(db, affiliate, month),
            }
            for affiliate, arrangement in (
                (affiliate, _arrangement(db, affiliate, month))
                for affiliate in affiliates
            )
        ],
    }


def _arrangement(
    db: Session, affiliate: AffiliateProfile, month: str
) -> str | None:
    """Which arrangement she was on that month, or `None` for nobody.

    **Only a base guarantee turns a target into money.** For everyone else the
    numbers are worth recording and worth looking at, and nothing at all
    depends on them - which is why the grid needs the whole arrangement and
    not just the yes-or-no it used to ask for. A screen that cannot tell them
    apart marks every empty row as urgent, and a warning that is always on is
    one nobody reads.
    """
    terms = terms_for(db, affiliate, month)
    return terms.compensation_type if terms else None


@router.put("/{month}")
def save_grid(
    month: str,
    body: GridBody,
    actor: UserAccount = Depends(require_permission(Permission.TARGETS_RECORD)),
    db: Session = Depends(get_session),
) -> dict:
    """One save for the whole grid. All of it, or none of it.

    Nothing is committed until every row has been applied, so a bad row leaves
    the month exactly as it was rather than half-written.
    """
    month = _month_or_400(month)

    # **Refuse a save built on figures somebody else has already changed.**
    #
    # Two people run payroll and both open Targets at month end. Without this
    # the second save silently overwrites the first, and the losing edit is
    # invisible - there is no error, no conflict, and no way to notice except
    # by re-reading a number you already believed.
    current = _revision(targets_for(db, month))
    if body.revision != current:
        raise HTTPException(
            409,
            "Somebody else changed this month while you were editing it. "
            "Nothing was saved. Reload to see their numbers, then make your "
            "changes again.",
        )

    by_id = {
        affiliate.id: affiliate
        for affiliate in list_affiliates(db, include_archived=True)
    }
    saved = 0
    #: What a year-wide change reached and what it refused, per model. Reported
    #: rather than assumed: it rewrites months that may already have been
    #: counted, and it silently cannot touch ones that are agreed.
    year_report: list[dict] = []

    for index, row in enumerate(body.rows):
        affiliate = by_id.get(row.affiliate_id)
        if affiliate is None:
            raise HTTPException(
                400, f"Row {index + 1}: no affiliate {row.affiliate_id}. Nothing saved."
            )

        if row.clear_actuals and row.actual_videos is not None:
            raise HTTPException(
                400,
                f"Row {index + 1} ({affiliate.name}): asked to clear the "
                "recorded counts and given counts at the same time. Nothing "
                "saved.",
            )

        if (row.actual_videos is None) != (row.actual_stories is None):
            raise HTTPException(
                400,
                f"Row {index + 1} ({affiliate.name}): record both videos and "
                "stories or neither - half a month cannot say whether the "
                "target was achieved. Nothing saved.",
            )

        try:
            if body.apply_to_year:
                # The year first, so this month is written by the same call
                # that writes the rest and cannot disagree with it.
                spread = set_requirements_for_year(
                    db,
                    affiliate,
                    month,
                    videos=row.required_videos,
                    stories=row.required_stories,
                    actor_id=actor.id,
                    actor_email=actor.email,
                )
                year_report.append({"name": affiliate.name, **spread})
                target = get_target(db, affiliate, month)
                if target is None:
                    # This month itself was refused - agreed, or from before
                    # the platform. Nothing to record counts against.
                    saved += 1
                    continue
            else:
                target = set_requirements(
                    db,
                    affiliate,
                    month,
                    videos=row.required_videos,
                    stories=row.required_stories,
                    actor_id=actor.id,
                    actor_email=actor.email,
                )
            if row.clear_actuals:
                clear_actuals_service(
                    db, target, actor_id=actor.id, actor_email=actor.email
                )
            elif row.actual_videos is not None:
                record_actuals(
                    db,
                    target,
                    videos=row.actual_videos,
                    stories=row.actual_stories,
                    actor_id=actor.id,
                    actor_email=actor.email,
                )
        except ValueError as exc:
            db.rollback()
            raise HTTPException(
                400, f"Row {index + 1} ({affiliate.name}): {exc}. Nothing saved."
            ) from exc
        saved += 1

    db.commit()
    # The new revision, so a screen that saves twice in a row does not have to
    # reload between them.
    return {
        "month": month,
        "saved": saved,
        "revision": _revision(targets_for(db, month)),
        "applied_to_year": year_report,
    }


@router.post("/{month}/verify")
def verify_targets(
    month: str,
    body: VerifyBody,
    actor: UserAccount = Depends(require_permission(Permission.TARGETS_VERIFY)),
    db: Session = Depends(get_session),
) -> dict:
    """Confirm the recorded numbers, one model or many.

    This is what unlocks a base guarantee (§9.5). It confirms the **numbers**,
    not the outcome - verifying a target they missed is a normal thing to do.
    """
    month = _month_or_400(month)
    by_id = {a.id: a for a in list_affiliates(db, include_archived=True)}

    for affiliate_id in body.affiliate_ids:
        affiliate = by_id.get(affiliate_id)
        if affiliate is None:
            raise HTTPException(404, f"No affiliate {affiliate_id}. Nothing verified.")

        target = get_target(db, affiliate, month)
        if target is None:
            raise HTTPException(
                400,
                f"{affiliate.name} has no target for {month}. Nothing verified.",
            )
        try:
            verify(db, target, actor_id=actor.id, actor_email=actor.email)
        except ValueError as exc:
            db.rollback()
            raise HTTPException(
                400, f"{affiliate.name}: {exc} Nothing verified."
            ) from exc

    db.commit()
    return {"month": month, "verified": len(body.affiliate_ids)}


@router.post("/{month}/unverify")
def unverify_targets(
    month: str,
    body: UnverifyBody,
    actor: UserAccount = Depends(require_permission(Permission.TARGETS_VERIFY)),
    db: Session = Depends(get_session),
) -> dict:
    """Take a confirmation back, with a written reason.

    The only way back from a mistaken verification - and a mistaken
    verification silently pays a guarantee, so the audit has to say why.
    """
    month = _month_or_400(month)
    by_id = {a.id: a for a in list_affiliates(db, include_archived=True)}

    for affiliate_id in body.affiliate_ids:
        affiliate = by_id.get(affiliate_id)
        if affiliate is None:
            raise HTTPException(404, f"No affiliate {affiliate_id}. Nothing changed.")

        target = get_target(db, affiliate, month)
        if target is None or not target.is_verified:
            raise HTTPException(
                400,
                f"{affiliate.name} has no verified target for {month}. "
                "Nothing changed.",
            )
        unverify(
            db,
            target,
            reason=body.reason,
            actor_id=actor.id,
            actor_email=actor.email,
        )

    db.commit()
    return {"month": month, "unverified": len(body.affiliate_ids)}
