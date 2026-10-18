"""A model's portal, as staff may look at it. ADR 0064.

Read only, and a **second gate rather than a merged one**. `current_affiliate`
still answers only to the model who owns the record (§6.1, ADR 0006); these
routes answer to `affiliates.view` - whoever may already open her profile - and
name the model in the path.

Each route calls the `/api/me` handler of the same name for the profile in the
path, so what staff see here and what she sees on her phone are one
implementation. Two would be two answers waiting to disagree, and catching
the portal saying something wrong is the reason this exists.

**No writes, and none to add.** `tests/test_portal_preview.py` fails if a method
other than GET appears on this router. The unmasked payout read is left out on
purpose: the preview keeps her details shortened, and staff who must see them in
full have the audited reveal on the payments side.
"""

from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session

from app.api import affiliate_self as mine
from app.api.affiliates import _get_affiliate_or_404
from app.api.deps import require_permission
from app.core.permissions import Permission
from app.db import get_session
from app.models.affiliates import AffiliateProfile
from app.models.identity import UserAccount
from app.services.audit import record_audit

router = APIRouter(prefix="/api/affiliates/{affiliate_id}/portal")

#: Built once, so a route that asks for both the viewer and the model checks
#: the permission once - FastAPI caches a dependency by the callable.
GUARD = require_permission(Permission.AFFILIATES_VIEW)


def previewed_affiliate(
    affiliate_id: int,
    _viewer: UserAccount = Depends(GUARD),
    db: Session = Depends(get_session),
) -> AffiliateProfile:
    """The model named in the path, for somebody allowed to open her profile."""
    return _get_affiliate_or_404(db, affiliate_id)


@router.get("")
def her_record(
    affiliate: AffiliateProfile = Depends(previewed_affiliate),
    viewer: UserAccount = Depends(GUARD),
    db: Session = Depends(get_session),
) -> dict:
    """What `/api/me` tells her, payout destination masked as it is for her.

    The portal reads this once when it opens, so it is where the look is
    audited: under the staff member, against her, and never as her.
    """
    body = mine.me(affiliate=affiliate, db=db)
    record_audit(
        db,
        action="portal.previewed",
        subject=f"affiliate:{affiliate.id}",
        actor_id=viewer.id,
        actor_email=viewer.email,
    )
    db.commit()
    return body


@router.get("/application")
def her_application(affiliate: AffiliateProfile = Depends(previewed_affiliate)) -> dict:
    """What `/api/applications/mine` tells her: applied, and in which state.

    Always applied - a profile is what an application creates, and a preview
    needs one to name.
    """
    return {"applied": True, "status": affiliate.status}


@router.get("/notifications")
def her_notifications(
    affiliate: AffiliateProfile = Depends(previewed_affiliate),
    db: Session = Depends(get_session),
) -> dict:
    return mine.my_notification_preferences(affiliate=affiliate, db=db)


@router.get("/months")
def her_months(
    affiliate: AffiliateProfile = Depends(previewed_affiliate),
    db: Session = Depends(get_session),
) -> dict:
    return mine.my_months(affiliate=affiliate, db=db)


@router.get("/earnings/{month}")
def her_earnings(
    month: str,
    affiliate: AffiliateProfile = Depends(previewed_affiliate),
    db: Session = Depends(get_session),
) -> dict:
    return mine.my_earnings(month=month, affiliate=affiliate, db=db)


@router.get("/home/{month}")
def her_home(
    month: str,
    affiliate: AffiliateProfile = Depends(previewed_affiliate),
    db: Session = Depends(get_session),
) -> dict:
    return mine.my_home(month=month, affiliate=affiliate, db=db)


@router.get("/payments")
def her_payments(
    affiliate: AffiliateProfile = Depends(previewed_affiliate),
    db: Session = Depends(get_session),
) -> dict:
    return mine.my_payment_history(affiliate=affiliate, db=db)


@router.get("/payments/{payment_id}/proof")
def her_payment_proof(
    payment_id: int,
    affiliate: AffiliateProfile = Depends(previewed_affiliate),
    db: Session = Depends(get_session),
) -> Response:
    """Her transfer screenshot. Staff with `affiliates.view` already see it on
    the payments side (`/api/payments/{id}/proof`); this is the same file."""
    return mine.my_payment_proof(payment_id=payment_id, affiliate=affiliate, db=db)


@router.get("/policy/{policy_version_id}")
def her_policy(
    policy_version_id: int,
    affiliate: AffiliateProfile = Depends(previewed_affiliate),
    db: Session = Depends(get_session),
) -> dict:
    return mine.my_policy_version(
        policy_version_id=policy_version_id, _affiliate=affiliate, db=db
    )


@router.get("/wardrobe")
def her_wardrobe(
    affiliate: AffiliateProfile = Depends(previewed_affiliate),
    db: Session = Depends(get_session),
) -> dict:
    return mine.my_wardrobe(affiliate=affiliate, db=db)


@router.get("/best-sellers")
def her_best_sellers(
    month: str | None = None,
    affiliate: AffiliateProfile = Depends(previewed_affiliate),
    db: Session = Depends(get_session),
) -> dict:
    return mine.my_best_sellers(month=month, affiliate=affiliate, db=db)


@router.get("/targets")
def her_targets(
    affiliate: AffiliateProfile = Depends(previewed_affiliate),
    db: Session = Depends(get_session),
) -> dict:
    return mine.my_targets_view(affiliate=affiliate, db=db)


@router.get("/ranking/{month}")
def her_ranking(
    month: str,
    affiliate: AffiliateProfile = Depends(previewed_affiliate),
    db: Session = Depends(get_session),
) -> dict:
    """The board as she sees it: her own sales, and only names and positions
    for everybody else (M02)."""
    return mine.my_ranking(month=month, affiliate=affiliate, db=db)
