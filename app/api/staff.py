"""Who has access to the platform, over HTTP.

Distinct from `app/api/affiliates.py`: a model reaches their own portal by
owning an `affiliate_profile`, never by holding a role here (§6.1). This is
the one screen `settings.manage` and `invitations.send` were defined for and
had no UI outlet until now (app/core/permissions.py).

Listing the roster, and giving or taking somebody's roles, are gated on
`settings.manage` alone, which today only `admin` grants. A person may hold
several roles (ADR 0067), so giving one and taking one are two actions. Revoking an
invitation is gated on `invitations.send` instead - the mirror of the action
that creates one, so whoever may send an invitation may also withdraw it
without needing the broader permission.
"""

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import client_address, holds, require_permission, require_staff, roles_of
from app.core import throttle
from app.config import settings
from app.core.businesstime import utcnow
from app.core.permissions import (
    GRANT_REFUSED,
    MODEL_ROLE,
    Permission,
    can_invite,
    permissions_for,
    sorted_roles,
)
from app.db import get_session
from app.models.identity import Invitation, UserAccount
from app.services import two_step
from app.services.audit import record_audit
from app.services.auth import live_sessions, revoke_all_sessions, session_rows
from app.services.invitations import create_invitation
from app.services.notifications import invitation_link, invitation_sent
from app.services.staff import (
    ASSIGNABLE_ROLES,
    give_role,
    invitable_roles,
    list_pending_invitations,
    list_staff,
    reactivate_staff,
    remove_role,
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


def _may_act_on(db: Session, actor: UserAccount, invitation: Invitation) -> None:
    """Resending or withdrawing an invitation is granting or refusing the access
    it carries - and Resend hands back a working link - so both are held to the
    same rule as sending one (`can_grant`). Without this an affiliate manager
    could resend a pending *admin* invitation and set that account's password
    themselves."""
    if not can_invite(roles_of(db, actor), invitation.role):
        raise HTTPException(403, GRANT_REFUSED)


def _invitation_row(invitation: Invitation, now) -> dict:
    return {
        "id": invitation.id,
        "email": invitation.email,
        "role": invitation.role,
        "expires_at": _isoformat(invitation.expires_at),
        "expired": invitation.expires_at <= now,
        # When it went out - the approved panel writes *Finance - Sent
        # 3 November 2026* under each address.
        "created_at": _isoformat(invitation.created_at),
    }


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
            _invitation_row(invitation, now)
            for invitation in list_pending_invitations(
                db, exclude_roles=("affiliate",), current_only=True
            )
        ],
        "assignable_roles": sorted(ASSIGNABLE_ROLES),
        #: What *Add access* and the invite form offer: only roles this person
        #: may give, all their own roles together (ADR 0067).
        "invitable_roles": invitable_roles(roles_of(db, _actor)),
        #: What each role grants, from `ROLES` itself, so the screen's
        #: "What can each access do?" can never disagree with the server (T4).
        "role_permissions": _role_permissions(),
    }


def _role_permissions() -> dict[str, list[str]]:
    return {role: sorted(permissions_for(role)) for role in sorted(ASSIGNABLE_ROLES)}


@router.get("/invitations")
def staff_invitations(
    actor: UserAccount = Depends(require_permission(Permission.INVITATIONS_SEND)),
    db: Session = Depends(get_session),
) -> dict:
    """The pending staff invitations this person may act on, and the roles they
    may invite to.

    For whoever may invite without holding `settings.manage` - an affiliate
    manager. They used to get the invite form and nothing else: no list of what
    they had sent, so nothing to resend or withdraw (Settings audit, X2).
    """
    held = roles_of(db, actor)
    now = utcnow()
    return {
        "invitations": [
            _invitation_row(invitation, now)
            for invitation in list_pending_invitations(
                db, exclude_roles=("affiliate",), current_only=True
            )
            if can_invite(held, invitation.role)
        ],
        "invitable_roles": invitable_roles(held),
        "role_permissions": _role_permissions(),
    }


@router.post("/{user_id}/roles", status_code=201)
def give_access(
    user_id: int,
    body: RoleBody,
    actor: UserAccount = Depends(require_permission(Permission.SETTINGS_MANAGE)),
    db: Session = Depends(get_session),
) -> dict:
    """Settings → Team and access, *Add access*: one more role, keeping the
    rest (ADR 0067)."""
    user = _user_or_404(db, user_id)
    try:
        give_role(
            db,
            user,
            body.role,
            actor_roles=roles_of(db, actor),
            actor_id=actor.id,
            actor_email=actor.email,
        )
        db.commit()
    except IntegrityError as exc:
        # Two presses racing past the check: the one-live-role-per-person
        # index, or the one-operations-manager index, refused the second.
        db.rollback()
        raise HTTPException(409, "This access was given a moment ago.") from exc
    except ValueError as exc:
        db.rollback()
        raise HTTPException(400, str(exc)) from exc
    return {"id": user.id, "roles": _roles_now(db, user)}


@router.post("/{user_id}/roles/{role}/remove")
def remove_access(
    user_id: int,
    role: str,
    actor: UserAccount = Depends(require_permission(Permission.SETTINGS_MANAGE)),
    db: Session = Depends(get_session),
) -> dict:
    """Settings → Team and access: take one role away, leaving the rest."""
    user = _user_or_404(db, user_id)
    try:
        remove_role(
            db,
            user,
            role,
            actor_roles=roles_of(db, actor),
            actor_id=actor.id,
            actor_email=actor.email,
        )
    except ValueError as exc:
        db.rollback()
        raise HTTPException(400, str(exc)) from exc

    db.commit()
    return {"id": user.id, "roles": _roles_now(db, user)}


def _roles_now(db: Session, user: UserAccount) -> list[str]:
    return sorted_roles(roles_of(db, user) - {MODEL_ROLE})


@router.post("/{user_id}/suspend")
def suspend(
    user_id: int,
    body: SuspendBody,
    actor: UserAccount = Depends(require_permission(Permission.SETTINGS_MANAGE)),
    db: Session = Depends(get_session),
) -> dict:
    """Settings → Team and access, the danger strip: every role and every
    session go at once, in one transaction and one audit entry (ADR 0067,
    decision 6). The record of what the person did stays."""
    user = _user_or_404(db, user_id)
    try:
        ended = suspend_staff(
            db, user, reason=body.reason, actor_id=actor.id, actor_email=actor.email
        )
    except ValueError as exc:
        db.rollback()
        raise HTTPException(400, str(exc)) from exc

    db.commit()
    return {
        "id": user.id,
        "status": "suspended",
        "roles": _roles_now(db, user),
        "sessions_ended": ended,
    }


@router.post("/{user_id}/reactivate")
def reactivate(
    user_id: int,
    actor: UserAccount = Depends(require_permission(Permission.SETTINGS_MANAGE)),
    db: Session = Depends(get_session),
) -> dict:
    """Lets the person sign in again, holding nothing: access is given back
    deliberately, one role at a time, with *Add access*."""
    user = _user_or_404(db, user_id)
    try:
        reactivate_staff(db, user, actor_id=actor.id, actor_email=actor.email)
    except ValueError as exc:
        db.rollback()
        raise HTTPException(400, str(exc)) from exc

    db.commit()
    return {"id": user.id, "status": "active", "roles": _roles_now(db, user)}


# ── The owner, for somebody else: their devices and their two-step ───────────


@router.get("/{user_id}/sessions")
def their_sessions(
    user_id: int,
    _actor: UserAccount = Depends(require_permission(Permission.SETTINGS_MANAGE)),
    db: Session = Depends(get_session),
) -> dict:
    """*Signed in on*, for anybody, on their page. None of these is the
    owner's own browser, so `current` is always false."""
    user = _user_or_404(db, user_id)
    return {"sessions": session_rows(live_sessions(db, user.id), None)}


@router.post("/{user_id}/sessions/end-all")
def end_their_sessions(
    user_id: int,
    request: Request,
    actor: UserAccount = Depends(require_permission(Permission.SETTINGS_MANAGE)),
    db: Session = Depends(get_session),
) -> dict:
    """Sign somebody out everywhere. Their access stays as it is - this is
    for a lost laptop, not for taking anything away (that is suspending)."""
    user = _user_or_404(db, user_id)
    ended = revoke_all_sessions(db, user.id)
    record_audit(
        db,
        action="auth.sessions.ended",
        subject=f"user:{user.id}",
        actor_id=actor.id,
        actor_email=actor.email,
        after={"ended": ended, "by_owner": True},
        ip_address=client_address(request),
    )
    db.commit()
    return {"ended": ended}


class OwnCodeBody(BaseModel):
    code: str = Field(min_length=1, max_length=40)


#: Refused when the owner has no two-step sign-in of their own to prove it.
OWNER_NEEDS_TWO_STEP = "Turn on your own two-step sign-in first."


@router.post("/{user_id}/two-step/reset")
def reset_their_two_step(
    user_id: int,
    body: OwnCodeBody,
    request: Request,
    actor: UserAccount = Depends(require_permission(Permission.SETTINGS_MANAGE)),
    db: Session = Depends(get_session),
) -> dict:
    """Take somebody's two-step sign-in off, for a lost phone (ADR 0067).

    **The owner proves it is them first**, with a code from their own app -
    not a recovery code: an open session left on a desk must not be enough to
    strip somebody else's second step. Never on yourself; turning your own off
    asks for your own code at `/api/auth/two-step/turn-off`, and is refused if
    your access needs it. Audited with the person as subject and the owner as
    actor. Their sessions are left alone; *End all* is beside it.
    """
    user = _user_or_404(db, user_id)
    if user.id == actor.id:
        raise HTTPException(
            400, "This is your own account. Turn your own two-step sign-in off in Settings → Me."
        )
    if not two_step.is_enabled(db, actor.id):
        raise HTTPException(409, OWNER_NEEDS_TWO_STEP)
    if not two_step.is_enabled(db, user.id):
        raise HTTPException(
            409, f"Two-step sign-in is not on for {user.display_name or user.email}."
        )

    # The owner's own code counts against the owner's limits, the day's
    # ceiling included, as any code typed while signed in does.
    key = f"user:{actor.id}"
    wait = throttle.acquire_all(
        [(throttle.TWO_STEP_PER_DAY, key), (throttle.TWO_STEP_RECHECK, key)]
    )
    if wait:
        raise HTTPException(
            429, throttle.try_again_message(wait), headers={"Retry-After": str(wait)}
        )
    try:
        accepted = two_step.check_authenticator_code(db, actor.id, body.code)
    except two_step.KeyUnavailable as exc:
        db.rollback()
        throttle.TWO_STEP_RECHECK.release(key)
        throttle.TWO_STEP_PER_DAY.release(key)
        raise HTTPException(503, str(exc)) from None
    if not accepted:
        db.rollback()
        raise HTTPException(
            400, "That code did not work. Check the time on your phone and try again."
        )
    throttle.TWO_STEP_PER_DAY.release(key)
    throttle.TWO_STEP_RECHECK.clear(key)

    two_step.turn_off(db, user.id)
    # The one thing that lifts the person's day of wrong codes: the owner,
    # having proved it is them, starting that person's second step afresh -
    # audited just below.
    subject = f"user:{user.id}"
    throttle.TWO_STEP_PER_DAY.clear(subject)
    throttle.TWO_STEP_PER_ACCOUNT.clear(subject)
    record_audit(
        db,
        action="auth.two_step.reset",
        subject=f"user:{user.id}",
        actor_id=actor.id,
        actor_email=actor.email,
        before={"enabled": True},
        after={"enabled": False},
        ip_address=client_address(request),
    )
    db.commit()
    return {"enabled": False}


@router.post("/invitations/{invitation_id}/revoke")
def revoke(
    invitation_id: int,
    actor: UserAccount = Depends(require_permission(Permission.INVITATIONS_SEND)),
    db: Session = Depends(get_session),
) -> dict:
    invitation = _invitation_or_404(db, invitation_id)
    _may_act_on(db, actor, invitation)
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
    _may_act_on(db, actor, invitation)
    if invitation.accepted_at is not None:
        raise HTTPException(400, "This invitation has already been used")

    email, role, name = invitation.email, invitation.role, invitation.name
    invitation.expires_at = utcnow()

    try:
        token, fresh = create_invitation(db, email, role, actor.id, name=name)
    except ValueError as exc:
        db.rollback()
        raise HTTPException(409, str(exc)) from exc

    queued = invitation_sent(db, fresh.email, token, role, fresh.name)
    record_audit(
        db,
        action="invitation.resend",
        subject=f"invitation:{email}",
        actor_id=actor.id,
        actor_email=actor.email,
        after={"email": email, "role": role, "replaced": invitation.id},
        ip_address=client_address(request),
    )
    db.commit()
    return {
        "id": fresh.id,
        "email": fresh.email,
        "expires_at": fresh.expires_at.isoformat(),
        "link": invitation_link(token),
        "emailed": queued is not None and settings.mail_configured,
    }


# ── Settings → Appearance: this account's own switches ─────────────────────────


class PreferenceBody(BaseModel):
    key: str = Field(min_length=1, max_length=40)
    enabled: bool


class ThemeBody(BaseModel):
    theme: str = Field(min_length=1, max_length=6)


def _preferences_body(db: Session, actor: UserAccount) -> dict:
    from app.services.staff_prefs import DESCRIPTIONS, SWITCHES, preferences_for

    # The switches belong to the affiliate side - Home's notices, the weekly
    # targets reminder. The operations manager keeps his theme and is offered
    # none of them (ADR 0057).
    if not holds(db, actor, Permission.AFFILIATES_VIEW):
        return {
            "preferences": {},
            "labels": {},
            "descriptions": {},
            "theme": actor.maintainer_theme,
        }
    return {
        "preferences": preferences_for(db, actor.id),
        "labels": SWITCHES,
        "descriptions": DESCRIPTIONS,
        #: `None` until chosen: the screen keeps the dark default.
        "theme": actor.maintainer_theme,
    }


@router.get("/me/preferences")
def my_preferences(
    actor: UserAccount = Depends(require_staff),
    db: Session = Depends(get_session),
) -> dict:
    """The signed-in member of staff's own switches and theme. Absent means on."""
    return _preferences_body(db, actor)


@router.put("/me/preferences")
def change_my_preference(
    body: PreferenceBody,
    actor: UserAccount = Depends(require_permission(Permission.AFFILIATES_VIEW)),
    db: Session = Depends(get_session),
) -> dict:
    """Turn one of this account's own switches on or off. Nobody else's."""
    from app.services.staff_prefs import set_preference

    try:
        set_preference(db, actor, body.key, body.enabled)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    db.commit()
    return _preferences_body(db, actor)


@router.put("/me/theme")
def change_my_theme(
    body: ThemeBody,
    actor: UserAccount = Depends(require_staff),
    db: Session = Depends(get_session),
) -> dict:
    """This account's theme for the admin tool - dark, light, or the device's.
    Saved on the account so it follows the person, not the laptop (P1)."""
    from app.services.staff_prefs import set_theme

    try:
        set_theme(db, actor, body.theme)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    db.commit()
    return _preferences_body(db, actor)
