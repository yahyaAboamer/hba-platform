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

**Staff invitations are the owner's** (Batch 2.3, Choice 4): resending or
withdrawing one needs `settings.manage`, as sending one does, and the owner
reads them on the roster. A model's invitation stays `invitations.send` -
Affiliates → Models → Invite resends and withdraws through the same two
routes. `GET /api/staff/invitations`, the affiliate manager's own list
(Settings audit X2), was retired with it: nothing asked for it any more.
"""

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.shared.api.deps import client_address, holds, require_permission, require_staff, roles_of
from app.core import throttle
from app.config import settings
from app.core.businesstime import at_words, utcnow
from app.core.permissions import (
    DEPARTMENT_LEVELS,
    DEPARTMENT_NAMES,
    GRANT_REFUSED,
    INVITATION_BRINGS,
    LEVELS,
    MODEL_ROLE,
    NOT_OFFERED,
    ROLE_WORDS,
    Permission,
    access_words,
    can_invite,
    invitation_permission,
    permissions_for,
    sorted_roles,
)
from app.db import get_session
from app.shared.models.identity import Invitation, UserAccount
from app.shared.services import trusted_browsers, two_step
from app.shared.services.audit import record_audit
from app.shared.services.auth import live_sessions, revoke_all_sessions, session_rows
from app.shared.services.invitations import create_invitation
from app.shared.services.notifications import (
    invitation_link,
    invitation_sent,
    two_step_reminder,
)
from app.shared.services.staff import (
    ASSIGNABLE_ROLES,
    REMINDER_EVERY,
    give_role,
    invitable_roles,
    last_two_step_reminder,
    list_pending_invitations,
    list_staff,
    reactivate_staff,
    remove_role,
    revoke_invitation,
    set_level,
    suspend_staff,
    suspended_refusal,
)

router = APIRouter(prefix="/api/staff")


class RoleBody(BaseModel):
    role: str


class LevelBody(BaseModel):
    level: Literal["none", "viewer", "staff", "manager"]


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
    themselves.

    A staff invitation is the owner's besides (Batch 2.3): the affiliate
    manager may resend or withdraw a model's, not a colleague's."""
    needed = invitation_permission(invitation.role)
    if not holds(db, actor, needed):
        raise HTTPException(403, f"Permission required: {needed}")
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
        # The same moment under the name Batch 2.4's contract gives it.
        "sent_at": _isoformat(invitation.created_at),
        # "Inbox staff" - what accepting it gives, every role it brings
        # included (an operations manager's brings the Inbox).
        "access_words": access_words(
            (invitation.role, *INVITATION_BRINGS.get(invitation.role, ()))
        ),
    }


def _staff_row(row: dict) -> dict:
    return {
        **row,
        "last_login_at": _isoformat(row["last_login_at"]),
        "created_at": _isoformat(row["created_at"]),
        "joined_at": _isoformat(row["joined_at"]),
    }


def _departments() -> list[dict]:
    """Every department Team and access draws, and each of its four levels
    with the role behind it - `None` and not offered where no role grants it
    yet. From `DEPARTMENT_LEVELS` itself, so the screen cannot offer a level
    the server would refuse."""
    return [
        {
            "key": key,
            "name": DEPARTMENT_NAMES[key],
            "levels": [
                {
                    "level": level,
                    "role": levels.get(level),
                    "offered": level == "none" or levels.get(level) is not None,
                }
                for level in LEVELS
            ],
        }
        for key, levels in DEPARTMENT_LEVELS.items()
    ]


@router.get("")
def roster(
    _actor: UserAccount = Depends(require_permission(Permission.SETTINGS_MANAGE)),
    db: Session = Depends(get_session),
) -> dict:
    """Everyone who has ever held a staff role, and every invitation still
    waiting on somebody to open it."""
    now = utcnow()
    return {
        "staff": [_staff_row(row) for row in list_staff(db)],
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
        #: Each department and its levels (Batch 2.4), and each role in the
        #: words staff are shown it.
        "departments": _departments(),
        "role_words": dict(ROLE_WORDS),
    }


def _role_permissions() -> dict[str, list[str]]:
    return {role: sorted(permissions_for(role)) for role in sorted(ASSIGNABLE_ROLES)}


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


def _staff_or_404(db: Session, user_id: int) -> tuple[UserAccount, dict]:
    """An account on the roster, and its row there. Anybody else - a model,
    an id nobody has - is no member of staff to act on here."""
    user = _user_or_404(db, user_id)
    rows = list_staff(db, only=user.id)
    if not rows:
        raise HTTPException(404, "No such member of staff")
    return user, rows[0]


@router.put("/{user_id}/access/{department}")
def set_department_access(
    user_id: int,
    department: str,
    body: LevelBody,
    actor: UserAccount = Depends(require_permission(Permission.SETTINGS_MANAGE)),
    db: Session = Depends(get_session),
) -> dict:
    """Team and access: one department of somebody's access set to one level
    (Batch 2.4). `give_role` then `remove_role` in one transaction, so every
    rule they keep still refuses, with today's words, and a refusal leaves
    nothing half changed. Answers the person's roster row as it is after."""
    if department not in DEPARTMENT_LEVELS:
        raise HTTPException(404, "No such department")
    if body.level != "none" and DEPARTMENT_LEVELS[department].get(body.level) is None:
        raise HTTPException(422, NOT_OFFERED)
    user, _row = _staff_or_404(db, user_id)
    try:
        set_level(
            db,
            user,
            department,
            body.level,
            actor_roles=roles_of(db, actor),
            actor_id=actor.id,
            actor_email=actor.email,
        )
        db.commit()
    except IntegrityError as exc:
        # Two presses racing past the checks: a database index refused the
        # second, and every step of it goes back with it.
        db.rollback()
        raise HTTPException(409, "This access was changed a moment ago.") from exc
    except ValueError as exc:
        db.rollback()
        raise HTTPException(400, str(exc)) from exc
    return _staff_row(list_staff(db, only=user.id)[0])


@router.post("/{user_id}/two-step/remind", status_code=201)
def remind_two_step(
    user_id: int,
    request: Request,
    actor: UserAccount = Depends(require_permission(Permission.SETTINGS_MANAGE)),
    db: Session = Depends(get_session),
) -> dict:
    """Team and access, *Send a reminder* (Batch 2.4): email somebody whose
    two-step sign-in is off what it is, whether their access needs it, and
    where to turn it on. One per person per day, and never yourself."""
    user = _user_or_404(db, user_id)
    if user.id == actor.id:
        raise HTTPException(400, "This is your own account. Turn two-step sign-in on in Settings → Me.")
    # Locked first, so two presses at once send one reminder, not two.
    db.execute(select(UserAccount.id).where(UserAccount.id == user.id).with_for_update())
    user, row = _staff_or_404(db, user_id)
    name = user.display_name or user.email
    if user.status != "active":
        raise HTTPException(409, suspended_refusal(user))
    if row["two_step_enabled"]:
        raise HTTPException(409, f"Two-step sign-in is already on for {name}.")
    sent_at = last_two_step_reminder(db, user.id)
    if sent_at is not None:
        now = utcnow()
        wait = max(1, int((sent_at + REMINDER_EVERY - now).total_seconds()))
        raise HTTPException(
            429,
            f"A reminder was sent {at_words(sent_at, now)}. "
            "You can send another a day after it.",
            headers={"Retry-After": str(wait)},
        )

    # Whether their access asks for it today: the roster row's own answer
    # (`two_step.required_now`), so the email and the screen say the same.
    required = row["two_step_required"]
    queued = two_step_reminder(db, user, required=required)
    record_audit(
        db,
        action="staff.two_step_reminded",
        subject=f"user:{user.id}",
        actor_id=actor.id,
        actor_email=actor.email,
        after={"required": required},
        ip_address=client_address(request),
    )
    db.commit()
    return {"emailed": queued is not None and settings.mail_configured}


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
    # Their remembered browsers too: a lost laptop must ask for a code.
    trusted_browsers.forget_audited(
        db, user, actor=actor, why="ended_by_owner", ip_address=client_address(request)
    )
    db.commit()
    return {"ended": ended}


@router.get("/{user_id}/trusted-browsers")
def their_trusted_browsers(
    user_id: int,
    _actor: UserAccount = Depends(require_permission(Permission.SETTINGS_MANAGE)),
    db: Session = Depends(get_session),
) -> dict:
    """Somebody's remembered browsers, on their page. None is the owner's
    own, so `current` is always false."""
    user = _user_or_404(db, user_id)
    return {"browsers": trusted_browsers.rows(trusted_browsers.live_rows(db, user.id), None)}


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
    # Their remembered browsers too: whoever has the lost phone may have one.
    trusted_browsers.forget_audited(
        db, user, actor=actor, why="two_step_reset", ip_address=client_address(request)
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
    from app.shared.services.staff_prefs import DESCRIPTIONS, SWITCHES, preferences_for

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
    from app.shared.services.staff_prefs import set_preference

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
    from app.shared.services.staff_prefs import set_theme

    try:
        set_theme(db, actor, body.theme)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    db.commit()
    return _preferences_body(db, actor)
