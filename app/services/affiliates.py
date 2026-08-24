"""Creating and maintaining affiliates.

Nothing here decides what anyone is owed - that is Phase 4. This is the
registry: who exists, what kind of account they are, and where they are in
their life with the business.
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.businesstime import business_month, utcnow
from app.models.affiliates import (
    VALID_KINDS,
    VALID_STATUSES,
    AccountKind,
    AffiliateProfile,
    AffiliateStatus,
)
from app.services.audit import record_audit
from app.services.codes import close_codes_for, verified_codes_for


def create_affiliate(
    db: Session,
    *,
    user_account_id: int,
    name: str,
    phone: str | None = None,
    account_kind: str = AccountKind.MODEL,
    actor_id: int | None = None,
    actor_email: str | None = None,
) -> AffiliateProfile:
    """Register an affiliate against an existing account.

    Created ``pending``: applied, not yet approved. Approval is a deliberate
    later act, after the discount code has been verified against Shopify
    (§10.4) and compensation terms are set.
    """
    if account_kind not in VALID_KINDS:
        raise ValueError(f"Unknown account kind: {account_kind!r}")

    affiliate = AffiliateProfile(
        user_account_id=user_account_id,
        name=str(name or "").strip(),
        phone=(str(phone).strip() or None) if phone else None,
        account_kind=account_kind,
        status=AffiliateStatus.PENDING,
    )
    db.add(affiliate)
    db.flush()

    record_audit(
        db,
        action="affiliate.created",
        subject=f"affiliate:{affiliate.id}",
        actor_id=actor_id,
        actor_email=actor_email,
        after={"name": affiliate.name, "account_kind": account_kind},
    )
    return affiliate


def set_status(
    db: Session,
    affiliate: AffiliateProfile,
    status: str,
    *,
    actor_id: int | None = None,
    actor_email: str | None = None,
    reason: str | None = None,
) -> None:
    """Move an affiliate to a new status, recording what it changed from.

    "Who deactivated Nour, and when" is a question that gets asked, and the new
    value alone does not answer it.

    Setting the status it already has records nothing. An audit trail full of
    non-events is one nobody reads.
    """
    if status not in VALID_STATUSES:
        raise ValueError(f"Unknown affiliate status: {status!r}")

    previous = affiliate.status
    if previous == status:
        return

    if status == AffiliateStatus.ACTIVE and not verified_codes_for(db, affiliate):
        # Spec 10.4: Shopify code verification is a *required gate* before
        # approval, and this is the gate.
        #
        # Approving a mistyped code is the failure it exists to catch. Nothing
        # errors: the code simply matches no order, the model earns nothing,
        # and the first anyone notices is when she asks why her dashboard is
        # empty - by which point months of her sales have gone to nobody.
        #
        # Enforced here rather than in the API so it holds for every caller,
        # the same reasoning as closing code ownership on archive.
        raise ValueError(
            "This affiliate has no code confirmed to exist in Shopify. Verify "
            "the code first - an unverified code that turns out to be mistyped "
            "attributes nothing, silently."
        )

    affiliate.status = status
    record_audit(
        db,
        action="affiliate.status_changed",
        subject=f"affiliate:{affiliate.id}",
        actor_id=actor_id,
        actor_email=actor_email,
        before={"status": previous},
        after={"status": status},
        reason=reason,
    )


def archive_affiliate(
    db: Session,
    affiliate: AffiliateProfile,
    *,
    actor_id: int | None = None,
    actor_email: str | None = None,
    reason: str | None = None,
) -> None:
    """Retire an affiliate without removing them.

    Nothing is deleted: an archived affiliate's past payroll still has to
    resolve, and so does every payment already made to them.

    The timestamp is set once. When somebody left is a fact, not a function of
    who pressed the button last.

    **Also closes any code they still hold**, from this month forward. Archiving
    says "from now on, not theirs"; it must never say "was never theirs" -
    close_codes_for only touches open-ended periods and only from the current
    month on, so nothing already approved and paid is rewritten. Without this,
    an archived affiliate would keep silently owning their code, and an order
    placed after they left would still attribute to them.
    """
    now = utcnow()
    if affiliate.archived_at is None:
        affiliate.archived_at = now

    close_codes_for(
        db,
        affiliate,
        business_month(now),
        actor_id=actor_id,
        actor_email=actor_email,
    )

    set_status(
        db,
        affiliate,
        AffiliateStatus.ARCHIVED,
        actor_id=actor_id,
        actor_email=actor_email,
        reason=reason,
    )


def get_affiliate(db: Session, affiliate_id: int) -> AffiliateProfile | None:
    """One affiliate, archived or not. History has to stay reachable."""
    return db.get(AffiliateProfile, affiliate_id)


def list_affiliates(
    db: Session, *, include_archived: bool = False
) -> list[AffiliateProfile]:
    """Every affiliate, by name.

    Archived ones are excluded by default: the common question is "who is on
    the programme", not "who ever was".
    """
    query = select(AffiliateProfile).order_by(AffiliateProfile.name)
    if not include_archived:
        query = query.where(AffiliateProfile.status != AffiliateStatus.ARCHIVED)
    return list(db.scalars(query))
