"""Authentication endpoints."""

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import (
    SESSION_COOKIE,
    actor_payload,
    current_user,
    permission_list,
    require_permission,
)
from app.config import settings
from app.core.passwords import MINIMUM_PASSWORD_LENGTH, hash_password
from app.core.permissions import VALID_ROLES, Permission
from app.db import get_session
from app.models.identity import RoleAssignment, UserAccount
from app.services.audit import record_audit
from app.services.auth import authenticate, issue_session, revoke_session
from app.services.invitations import accept_invitation, create_invitation
from app.services.payroll import go_live_month, working_month

router = APIRouter(prefix="/api/auth")


class BootstrapBody(BaseModel):
    email: EmailStr
    display_name: str = Field(min_length=1, max_length=120)
    password: str = Field(min_length=MINIMUM_PASSWORD_LENGTH, max_length=256)


class LoginBody(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=256)


class InviteBody(BaseModel):
    email: EmailStr
    role: str


class AcceptInviteBody(BaseModel):
    token: str = Field(min_length=1, max_length=200)
    display_name: str = Field(min_length=1, max_length=120)
    password: str = Field(min_length=MINIMUM_PASSWORD_LENGTH, max_length=256)


def _client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


def _set_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=settings.session_hours * 3600,
        httponly=True,
        secure=settings.is_production,
        samesite="lax",
        path="/",
    )


@router.post("/bootstrap", status_code=201)
def bootstrap(
    body: BootstrapBody,
    request: Request,
    response: Response,
    db: Session = Depends(get_session),
) -> dict:
    """Create the very first administrator.

    Refused once any account exists, so it cannot be used to add a second
    admin later. There is no default password: the first administrator
    chooses their own, and nobody else ever sees it.
    """
    if db.scalar(select(func.count()).select_from(UserAccount)):
        raise HTTPException(409, "An account already exists")

    user = UserAccount(
        email=str(body.email).lower(),
        password_hash=hash_password(body.password),
        status="active",
        display_name=body.display_name.strip(),
    )
    db.add(user)
    db.flush()
    db.add(RoleAssignment(user_account_id=user.id, role="admin"))

    token, csrf, _ = issue_session(
        db, user.id, _client_ip(request), request.headers.get("user-agent")
    )
    record_audit(
        db,
        action="auth.bootstrap",
        subject=f"user:{user.id}",
        actor_id=user.id,
        actor_email=user.email,
        after={"email": user.email, "role": "admin"},
        ip_address=_client_ip(request),
    )
    db.commit()
    _set_cookie(response, token)
    return {"actor": actor_payload(db, user), "csrf": csrf}


@router.get("/status")
def status(db: Session = Depends(get_session)) -> dict:
    """Whether the platform still needs its first administrator."""
    return {
        "setup_required": not db.scalar(select(func.count()).select_from(UserAccount))
    }


@router.post("/login")
def login(
    body: LoginBody,
    request: Request,
    response: Response,
    db: Session = Depends(get_session),
) -> dict:
    user = authenticate(db, str(body.email), body.password)
    if user is None:
        # One message for both causes. Distinguishing them would confirm which
        # email addresses have accounts.
        raise HTTPException(401, "Incorrect email or password")

    token, csrf, _ = issue_session(
        db, user.id, _client_ip(request), request.headers.get("user-agent")
    )
    record_audit(
        db,
        action="auth.login",
        subject=f"user:{user.id}",
        actor_id=user.id,
        actor_email=user.email,
        ip_address=_client_ip(request),
    )
    db.commit()
    _set_cookie(response, token)
    return {"actor": actor_payload(db, user), "csrf": csrf}


@router.post("/logout")
def logout(
    request: Request,
    response: Response,
    user: UserAccount = Depends(current_user),
    db: Session = Depends(get_session),
) -> dict:
    revoke_session(db, request.cookies.get(SESSION_COOKIE, ""))
    record_audit(
        db,
        action="auth.logout",
        subject=f"user:{user.id}",
        actor_id=user.id,
        actor_email=user.email,
        ip_address=_client_ip(request),
    )
    db.commit()
    response.delete_cookie(SESSION_COOKIE, path="/")
    return {"success": True}


@router.get("/me")
def me(
    user: UserAccount = Depends(current_user), db: Session = Depends(get_session)
) -> dict:
    """The caller's identity, everything they may do, and where the platform is.

    `platform` rides along because every screen needs it before it can render a
    single figure, and this request is already made once at start-up. A second
    round trip to ask "which month are we in" would be one more thing that can
    fail between signing in and seeing anything.
    """
    return {
        "actor": actor_payload(db, user),
        "permissions": permission_list(db, user),
        "platform": {
            "working_month": working_month(),
            "go_live_month": go_live_month() or None,
        },
    }


@router.post("/invitations", status_code=201)
def invite(
    body: InviteBody,
    request: Request,
    actor: UserAccount = Depends(require_permission(Permission.INVITATIONS_SEND)),
    db: Session = Depends(get_session),
) -> dict:
    """Invite a member of staff and choose their role.

    Returns the token so the caller can deliver the link. Email delivery
    arrives in a later phase.
    """
    if body.role not in VALID_ROLES:
        raise HTTPException(422, f"Unknown role: {body.role}")

    token, invitation = create_invitation(db, str(body.email), body.role, actor.id)
    record_audit(
        db,
        action="invitation.create",
        subject=f"invitation:{body.email}",
        actor_id=actor.id,
        actor_email=actor.email,
        after={"email": str(body.email).lower(), "role": body.role},
        ip_address=_client_ip(request),
    )
    db.commit()
    return {
        "invitation": {
            "email": invitation.email,
            "role": invitation.role,
            "expires_at": invitation.expires_at.isoformat(),
        },
        "token": token,
    }


@router.post("/invitations/accept", status_code=201)
def accept(
    body: AcceptInviteBody,
    request: Request,
    response: Response,
    db: Session = Depends(get_session),
) -> dict:
    """Turn an invitation into an account, then sign the new person in."""
    try:
        user = accept_invitation(db, body.token, body.password, body.display_name)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc

    token, csrf, _ = issue_session(
        db, user.id, _client_ip(request), request.headers.get("user-agent")
    )
    record_audit(
        db,
        action="invitation.accept",
        subject=f"user:{user.id}",
        actor_id=user.id,
        actor_email=user.email,
        after={"email": user.email},
        ip_address=_client_ip(request),
    )
    db.commit()
    _set_cookie(response, token)
    return {"actor": actor_payload(db, user), "csrf": csrf}
