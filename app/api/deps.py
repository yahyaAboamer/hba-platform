"""Request-scoped dependencies: who is calling, and may they do this?

Every permission decision happens here, server-side. Hiding a control in the
interface is presentation; this is the protection.
"""

from fastapi import Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.permissions import has_permission, permissions_for
from app.db import get_session
from app.models.affiliates import AffiliateProfile, AffiliateStatus
from app.models.identity import RoleAssignment, UserAccount
from app.services.auth import resolve_session

SESSION_COOKIE = "hba_session"

#: The same token as the header, in a cookie the page can read. Double submit:
#: the page echoes it back, and only a page on this origin can read it to do
#: so. It exists because `sessionStorage` does not survive a closed tab and the
#: session cookie does - see `_set_cookie` in `app/api/auth.py`.
CSRF_COOKIE = "hba_csrf"

CSRF_HEADER = "x-csrf-token"
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


def active_role(db: Session, user: UserAccount) -> str:
    """The role a user currently holds.

    Revoked assignments are ignored. An account with no live assignment gets
    'affiliate', which grants no staff permission at all — failing closed
    rather than open if an assignment is ever missing.
    """
    role = db.scalar(
        select(RoleAssignment.role)
        .where(
            RoleAssignment.user_account_id == user.id,
            RoleAssignment.revoked_at.is_(None),
        )
        .order_by(RoleAssignment.id.desc())
        .limit(1)
    )
    return role or "affiliate"


def current_user(request: Request, db: Session = Depends(get_session)) -> UserAccount:
    """Resolve the caller, or refuse the request.

    On unsafe methods a CSRF header is mandatory. Its absence is rejected
    before the session is even looked up, so a cross-site form post cannot act
    on a live cookie.
    """
    token = request.cookies.get(SESSION_COOKIE, "")
    csrf = None
    if request.method not in SAFE_METHODS:
        csrf = request.headers.get(CSRF_HEADER)
        if csrf is None:
            raise HTTPException(401, "Authentication required")

    user = resolve_session(db, token, csrf)
    if user is None:
        raise HTTPException(401, "Authentication required")
    request.state.user = user
    return user


def require_permission(permission: str):
    """Build a dependency that enforces one permission.

    The permission name is validated at import time by has_permission, so a
    typo in a route definition fails loudly on startup rather than silently
    denying access in production.
    """

    def dependency(
        user: UserAccount = Depends(current_user), db: Session = Depends(get_session)
    ) -> UserAccount:
        if not has_permission(active_role(db, user), permission):
            raise HTTPException(403, f"Permission required: {permission}")
        return user

    return dependency


def actor_payload(db: Session, user: UserAccount) -> dict:
    """The caller's own details, safe to return to them."""
    return {
        "id": user.id,
        "email": user.email,
        "display_name": user.display_name,
        "role": active_role(db, user),
    }


def permission_list(db: Session, user: UserAccount) -> list[str]:
    """Everything the caller may do, so the interface can render accordingly."""
    return sorted(permissions_for(active_role(db, user)))


def current_affiliate(
    user: UserAccount = Depends(current_user), db: Session = Depends(get_session)
) -> AffiliateProfile:
    """The affiliate record this account **owns**, or refuse the request.

    §6.1 and ADR 0006. A model reaches their data by owning the record, never by
    holding a permission - `app/core/permissions.py` gives the `affiliate` role
    an empty permission set on purpose, so `require_permission` can never let
    them through and is not meant to.

    Two gates, and they are never mixed:

        require_permission   may this person do this?      staff routes
        current_affiliate    is this person the subject?    model routes

    A route accepting either would let a maintainer act *as* a model, and §6.5's
    audit trail could not then distinguish that from the model acting themselves.
    Where a maintainer needs a model's data there is already an admin route.

    **Every refusal is 403, never 404.** Whether an affiliate record exists for
    some account is not something an unauthorised caller should be able to
    establish by watching status codes.
    """
    profile = db.scalar(
        select(AffiliateProfile).where(AffiliateProfile.user_account_id == user.id)
    )
    if profile is None:
        # A staff account, or an invited affiliate who has not applied yet.
        # Both are "not the subject of this record", which is the only question
        # being asked here.
        raise HTTPException(403, "This account is not an affiliate")

    if profile.status == AffiliateStatus.ARCHIVED:
        # History still resolves - the person does not sign in.
        raise HTTPException(403, "This account is no longer active")

    # `inactive` passes deliberately. §8: *not earning, may return*. A paused
    # model must still see what they were owed from before they were paused;
    # locking them out would make "paused" and "archived" the same thing to the
    # only person they affect.
    return profile
