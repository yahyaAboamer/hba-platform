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
exactly the case that blocks her month later (§11.3). Returning her with nulls
puts the gap where somebody will see it, rather than leaving her absent and
therefore invisible.

## Recording and verifying are different permissions

`targets.record` writes actuals; `targets.verify` confirms them. Today one role
holds both (ADR 0018), so the split is enforced against a distinction HBA's
staffing does not yet make — which is the point: roles change, and the check is
what will still be here.
"""

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
    get_target,
    record_actuals,
    set_requirements,
    targets_for,
    unverify,
    verify,
)

router = APIRouter(prefix="/api/targets")


class GridRow(BaseModel):
    affiliate_id: int
    required_videos: int = Field(ge=0)
    required_stories: int = Field(ge=0)
    #: Both or neither. A half-recorded month cannot answer whether she
    #: achieved, and the database refuses it too.
    actual_videos: int | None = Field(default=None, ge=0)
    actual_stories: int | None = Field(default=None, ge=0)


class GridBody(BaseModel):
    rows: list[GridRow]


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
        "required_videos": target.required_videos if target else None,
        "required_stories": target.required_stories if target else None,
        "actual_videos": target.actual_videos if target else None,
        "actual_stories": target.actual_stories if target else None,
        # Three answers, not two. `null` means nobody has recorded what she
        # did - which blocks her month, where missing the target does not.
        "achieved": target.is_achieved if target else None,
        "verified": bool(target and target.is_verified),
        "verified_at": target.verified_at.isoformat()
        if target and target.verified_at
        else None,
        "recorded_at": target.recorded_at.isoformat()
        if target and target.recorded_at
        else None,
    }


@router.get("/{month}")
def target_grid(
    month: str,
    include_archived: bool = False,
    _actor: UserAccount = Depends(require_permission(Permission.TARGETS_RECORD)),
    db: Session = Depends(get_session),
) -> dict:
    """Every model down the side, one month across.

    Models with no target appear with nulls rather than being omitted. An
    absent row is an invisible gap, and the gap is what blocks her month.
    """
    month = _month_or_400(month)
    affiliates = list_affiliates(db, include_archived=include_archived)
    found = targets_for(db, month)

    return {
        "month": month,
        "rows": [
            _render(
                affiliate,
                found.get(affiliate.id),
                determines_pay=_determines_pay(db, affiliate, month),
            )
            for affiliate in affiliates
        ],
    }


def _determines_pay(db: Session, affiliate: AffiliateProfile, month: str) -> bool:
    """Whether this month's target decides what she is paid.

    Only a base guarantee turns a target into money. For everyone else the
    numbers are worth recording and worth looking at, and nothing at all
    depends on them.
    """
    terms = terms_for(db, affiliate, month)
    return bool(
        terms and terms.compensation_type == CompensationType.BASE_GUARANTEE
    )


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

    by_id = {
        affiliate.id: affiliate
        for affiliate in list_affiliates(db, include_archived=True)
    }
    saved = 0

    for index, row in enumerate(body.rows):
        affiliate = by_id.get(row.affiliate_id)
        if affiliate is None:
            raise HTTPException(
                400, f"Row {index + 1}: no affiliate {row.affiliate_id}. Nothing saved."
            )

        if (row.actual_videos is None) != (row.actual_stories is None):
            raise HTTPException(
                400,
                f"Row {index + 1} ({affiliate.name}): record both videos and "
                "stories or neither - half a month cannot say whether she "
                "achieved. Nothing saved.",
            )

        try:
            target = set_requirements(
                db,
                affiliate,
                month,
                videos=row.required_videos,
                stories=row.required_stories,
                actor_id=actor.id,
                actor_email=actor.email,
            )
            if row.actual_videos is not None:
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
    return {"month": month, "saved": saved}


@router.post("/{month}/verify")
def verify_targets(
    month: str,
    body: VerifyBody,
    actor: UserAccount = Depends(require_permission(Permission.TARGETS_VERIFY)),
    db: Session = Depends(get_session),
) -> dict:
    """Confirm the recorded numbers, one model or many.

    This is what unlocks a base guarantee (§9.5). It confirms the **numbers**,
    not the outcome - verifying a target she missed is a normal thing to do.
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
