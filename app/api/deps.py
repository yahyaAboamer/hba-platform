"""Request-scoped dependencies: who is calling, and may they do this?

Every permission decision happens here, server-side. Hiding a control in the
interface is presentation; this is the protection.
"""

from fastapi import Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.permissions import has_permission, permissions_for
from app.db import get_session
from app.models.identity import RoleAssignment, UserAccount
from app.services.auth import resolve_session

SESSION_COOKIE = "hba_session"
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
