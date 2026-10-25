"""Request-scoped dependencies: who is calling, and may they do this?

Every permission decision happens here, server-side. Hiding a control in the
interface is presentation; this is the protection.
"""

import ipaddress

from fastapi import Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.permissions import (
    has_permission,
    is_staff,
    permissions_of_roles,
    sorted_roles,
)
from app.db import get_session
from app.models.affiliates import AffiliateProfile, AffiliateStatus
from app.models.identity import UserAccount
from app.services.access import live_roles
from app.services.auth import resolve_session

SESSION_COOKIE = "hba_session"

#: The same token as the header, in a cookie the page can read. Double submit:
#: the page echoes it back, and only a page on this origin can read it to do
#: so. It exists because `sessionStorage` does not survive a closed tab and the
#: session cookie does - see `_set_cookie` in `app/api/auth.py`.
CSRF_COOKIE = "hba_csrf"

CSRF_HEADER = "x-csrf-token"
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


def roles_of(db: Session, user: UserAccount) -> frozenset[str]:
    """Every role a person holds now (ADR 0067).

    Revoked assignments are ignored. A person may hold several, and what they
    may do is everything those grant together (`permissions_of`). An account
    with no live assignment holds nothing, which grants no staff permission
    at all - failing closed rather than open if an assignment is ever missing.
    """
    return live_roles(db, user.id)


def permissions_of(db: Session, user: UserAccount) -> frozenset[str]:
    """Everything a person may do: the union of what their live roles grant."""
    return permissions_of_roles(roles_of(db, user))


def holds(db: Session, user: UserAccount, permission: str) -> bool:
    """Whether a person's roles, together, grant one permission.

    Through `has_permission`, so a misspelt permission raises rather than
    quietly answering no.
    """
    return has_permission(roles_of(db, user), permission)


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
        if not holds(db, user, permission):
            raise HTTPException(403, f"Permission required: {permission}")
        return user

    # Named on the dependency so a test can read, from the routes themselves,
    # which permission each one asks for (tests/test_several_roles.py).
    dependency.permission = permission  # type: ignore[attr-defined]
    return dependency


def require_staff(
    user: UserAccount = Depends(current_user), db: Session = Depends(get_session)
) -> UserAccount:
    """Any member of staff, whatever their roles - never a model.

    Staff means holding any role but a model's (ADR 0067). A model is never
    recognised here by a role: she reaches her own things through
    `current_affiliate`, by owning the record.

    For what belongs to the person rather than to a permission, such as their
    own theme: the operations manager holds no affiliate permission and still
    chooses dark or light (ADR 0057).
    """
    if not is_staff(roles_of(db, user)):
        raise HTTPException(403, "Staff only")
    return user


#: Railway's private proxy tier. A connection from here is the proxy, never a
#: visitor; the visitor's address arrives in the header below.
_RAILWAY_PROXY = ipaddress.ip_network("100.64.0.0/10")


def client_address(request: Request) -> str | None:
    """The visitor's address, as far as it can be known.

    Behind Railway every connection comes from its private proxy, and Railway's
    edge puts the visitor's address in `X-Real-IP` (docs: networking, specs and
    limits). `X-Forwarded-For` will not do: its last entry is Railway's own edge
    node, not the visitor - measured on staging, 11 October 2026.

    The header is believed **only** from Railway's proxy. Any other connection
    is its own address, so a visitor cannot name themselves something else by
    sending the header. Railway's health check has no header and gets None.
    Anything that is not an address at all (a test client's name) is used as
    it is.
    """
    peer = request.client.host if request.client else None
    if not peer:
        return None
    try:
        peer_address = ipaddress.ip_address(peer)
    except ValueError:
        return peer
    if peer_address in _RAILWAY_PROXY:
        try:
            return str(ipaddress.ip_address(request.headers.get("x-real-ip", "").strip()))
        except ValueError:
            return None
    return peer


def owns_a_profile(db: Session, user: UserAccount) -> bool:
    """Whether this account owns a model's record - what makes it a model
    (ADR 0006, ADR 0067 decision 2), whatever roles it holds."""
    return (
        db.scalar(
            select(AffiliateProfile.id)
            .where(AffiliateProfile.user_account_id == user.id)
            .limit(1)
        )
        is not None
    )


def actor_payload(db: Session, user: UserAccount) -> dict:
    """The caller's own details, safe to return to them.

    `roles` is every live role, widest first, for naming the person; the
    screens decide what to show from the permissions and from `is_staff` and
    `is_model`, never from a role's name (ADR 0067, decision 9).
    """
    roles = roles_of(db, user)
    return {
        "id": user.id,
        "email": user.email,
        "display_name": user.display_name,
        "roles": sorted_roles(roles),
        "is_staff": is_staff(roles),
        "is_model": owns_a_profile(db, user),
    }


def permission_list(db: Session, user: UserAccount) -> list[str]:
    """Everything the caller may do, so the interface can render accordingly."""
    return sorted(permissions_of(db, user))


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
