"""Who has access to the platform, over HTTP.

Distinct from `app/api/affiliates.py`: a model reaches their own portal by
owning an `affiliate_profile`, never by holding a role here (§6.1). This is
the one screen `settings.manage` and `invitations.send` were defined for and
had no UI outlet until now (app/core/permissions.py).

Listing the roster and changing what somebody holds are gated on
`settings.manage` alone, which today only `admin` grants. Revoking an
invitation is gated on `invitations.send` instead - the mirror of the action
that creates one, so whoever may send an invitation may also withdraw it
without needing the broader permission.
"""

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import require_permission
from app.config import settings
from app.core.businesstime import utcnow
from app.core.permissions import Permission
from app.db import get_session
from app.models.identity import Invitation, UserAccount
from app.services.audit import record_audit
from app.services.invitations import create_invitation
from app.services.notifications import invitation_link, invitation_sent
from app.services.staff import (
    ASSIGNABLE_ROLES,
    change_role,
    list_pending_invitations,
    list_staff,
    reactivate_staff,
    revoke_invitation,
    suspend_staff,
)

router = APIRouter(prefix="/api/staff")


class RoleBody(BaseModel):
    role: str


class SuspendBody(BaseModel):
    reason: str = Field(min_length=1, max_length=500)


def _isoformat(value) -> str | None:
    return value.isoformat() if value else None


def _user_or_404(db: Session, user_id: int) -> UserAccount:
    user = db.get(UserAccount, user_id)
    if user is None:
        raise HTTPException(404, "No such account")
    return user


def _invitation_or_404(db: Session, invitation_id: int) -> Invitation:
    invitation = db.get(Invitation, invitation_id)
    if invitation is None:
        raise HTTPException(404, "No such invitation")
    return invitation


@router.get("")
def roster(
    _actor: UserAccount = Depends(require_permission(Permission.SETTINGS_MANAGE)),
    db: Session = Depends(get_session),
) -> dict:
    """Everyone who has ever held a staff role, and every invitation still
    waiting on somebody to open it."""
    now = utcnow()
    return {
        "staff": [
            {
                **row,
                "last_login_at": _isoformat(row["last_login_at"]),
                "created_at": _isoformat(row["created_at"]),
            }
            for row in list_staff(db)
        ],
        "invitations": [
            {
                "id": invitation.id,
                "email": invitation.email,
                "role": invitation.role,
                "expires_at": _isoformat(invitation.expires_at),
                "expired": invitation.expires_at <= now,
            }
            for invitation in list_pending_invitations(db, exclude_roles=("affiliate",))
        ],
        "assignable_roles": sorted(ASSIGNABLE_ROLES),
    }


@router.post("/{user_id}/role")
def set_role(
    user_id: int,
    body: RoleBody,
    actor: UserAccount = Depends(require_permission(Permission.SETTINGS_MANAGE)),
    db: Session = Depends(get_session),
) -> dict:
    user = _user_or_404(db, user_id)
    try:
        change_role(db, user, body.role, actor_id=actor.id, actor_email=actor.email)
    except ValueError as exc:
        db.rollback()
        raise HTTPException(400, str(exc)) from exc

    db.commit()
    return {"id": user.id, "role": body.role}


@router.post("/{user_id}/suspend")
def suspend(
    user_id: int,
    body: SuspendBody,
    actor: UserAccount = Depends(require_permission(Permission.SETTINGS_MANAGE)),
    db: Session = Depends(get_session),
) -> dict:
    user = _user_or_404(db, user_id)
    try:
        suspend_staff(
            db, user, reason=body.reason, actor_id=actor.id, actor_email=actor.email
        )
    except ValueError as exc:
        db.rollback()
        raise HTTPException(400, str(exc)) from exc

    db.commit()
    return {"id": user.id, "status": "suspended"}


@router.post("/{user_id}/reactivate")
def reactivate(
    user_id: int,
    actor: UserAccount = Depends(require_permission(Permission.SETTINGS_MANAGE)),
    db: Session = Depends(get_session),
) -> dict:
    user = _user_or_404(db, user_id)
    try:
        reactivate_staff(db, user, actor_id=actor.id, actor_email=actor.email)
    except ValueError as exc:
        db.rollback()
        raise HTTPException(400, str(exc)) from exc

    db.commit()
    return {"id": user.id, "status": "active"}


@router.post("/invitations/{invitation_id}/revoke")
def revoke(
    invitation_id: int,
    actor: UserAccount = Depends(require_permission(Permission.INVITATIONS_SEND)),
    db: Session = Depends(get_session),
) -> dict:
    invitation = _invitation_or_404(db, invitation_id)
    try:
        revoke_invitation(db, invitation, actor_id=actor.id, actor_email=actor.email)
    except ValueError as exc:
        db.rollback()
        raise HTTPException(400, str(exc)) from exc

    db.commit()
    return {"id": invitation.id, "revoked": True}


@router.post("/invitations/{invitation_id}/resend", status_code=201)
def resend(
    invitation_id: int,
    request: Request,
    actor: UserAccount = Depends(require_permission(Permission.INVITATIONS_SEND)),
    db: Session = Depends(get_session),
) -> dict:
    """Send this person a fresh link, and close the one they never used.

    **The missing control that caused the mess.** Without it, the only way to
    re-invite somebody whose email had not arrived was to invite them again -
    which created a second row rather than replacing the first, left two live
    links for one person, and grew a list nobody could clear. The withdraw
    button next to it could not help either: it refuses an invitation that has
    already lapsed, which is precisely the state of every row somebody wants to
    resend.

    A new invitation rather than an extension of the old one, because the token
    is a credential and the old one may have been seen by whoever the mail went
    astray to. The old row is expired in the same transaction, so there is never
    a moment when both work.
    """
    invitation = _invitation_or_404(db, invitation_id)
    if invitation.accepted_at is not None:
        raise HTTPException(400, "This invitation has already been used")

    email, role = invitation.email, invitation.role
    invitation.expires_at = utcnow()

    try:
        token, fresh = create_invitation(db, email, role, actor.id)
    except ValueError as exc:
        db.rollback()
        raise HTTPException(409, str(exc)) from exc

    queued = invitation_sent(db, fresh.email, token, role)
    record_audit(
        db,
        action="invitation.resend",
        subject=f"invitation:{email}",
        actor_id=actor.id,
        actor_email=actor.email,
        after={"email": email, "role": role, "replaced": invitation.id},
        ip_address=request.client.host if request.client else None,
    )
    db.commit()
    return {
        "id": fresh.id,
        "email": fresh.email,
        "expires_at": fresh.expires_at.isoformat(),
        "link": invitation_link(token),
        "emailed": queued is not None and settings.mail_configured,
    }
