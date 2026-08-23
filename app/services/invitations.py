"""Staff invitations.

There is no public staff signup. An administrator invites a person and chooses
their role; the invitee sets their own password. Nobody ever sets or sees
another person's credentials, which is also why the spec forbids shared
accounts.

The invitation link is a credential until it is used, so only its hash is
stored and it is single-use.
"""

import hashlib
import secrets
from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.businesstime import utcnow
from app.core.passwords import hash_password
from app.core.permissions import VALID_ROLES
from app.models.identity import Invitation, RoleAssignment, UserAccount

TOKEN_BYTES = 32
DEFAULT_VALID_HOURS = 72


def _hash(token: str) -> str:
    return hashlib.sha256(str(token).encode("utf-8")).hexdigest()


def create_invitation(
    db: Session,
    email: str,
    role: str,
    invited_by: int | None,
    valid_hours: int = DEFAULT_VALID_HOURS,
) -> tuple[str, Invitation]:
    """Create an invitation and return (token, row).

    The caller emails the token as a link. Only its hash is kept.
    """
    if role not in VALID_ROLES:
        raise ValueError(f"Unknown role: {role}")
    token = secrets.token_urlsafe(TOKEN_BYTES)
    invitation = Invitation(
        email=str(email or "").strip().lower(),
        role=role,
        token_hash=_hash(token),
        expires_at=utcnow() + timedelta(hours=valid_hours),
        invited_by=invited_by,
    )
    db.add(invitation)
    return token, invitation


def accept_invitation(
    db: Session, token: str, password: str, display_name: str
) -> UserAccount:
    """Turn an invitation into an active account with the invited role.

    Raises ValueError with a message safe to show the invitee. The password is
    validated before the invitation is consumed, so a rejected weak password
    does not burn the link.
    """
    if not token:
        raise ValueError("This invitation link is not valid")

    invitation = db.scalar(
        select(Invitation).where(Invitation.token_hash == _hash(token))
    )
    if invitation is None:
        raise ValueError("This invitation link is not valid")
    if invitation.accepted_at is not None:
        raise ValueError("This invitation has already been used")
    if invitation.expires_at <= utcnow():
        raise ValueError("This invitation has expired")

    existing = db.scalar(
        select(UserAccount).where(
            func.lower(UserAccount.email) == invitation.email.lower()
        )
    )
    if existing is not None:
        raise ValueError("An account already exists for this email address")

    # Hash first: this raises on a password that is too short, and doing it
    # before consuming the invitation means the link survives a failed attempt.
    password_hash = hash_password(password)

    user = UserAccount(
        email=invitation.email,
        password_hash=password_hash,
        status="active",
        display_name=str(display_name or "").strip() or None,
    )
    db.add(user)
    db.flush()
    db.add(
        RoleAssignment(
            user_account_id=user.id,
            role=invitation.role,
            granted_by=invitation.invited_by,
        )
    )
    invitation.accepted_at = utcnow()
    return user
