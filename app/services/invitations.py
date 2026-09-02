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
from app.core.password_quality import password_problem
from app.core.passwords import hash_password
from app.core.permissions import VALID_ROLES
from app.models.affiliates import AffiliateProfile
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

    email = str(email or "").strip().lower()

    # The database's unique index on lower(email) already refuses a duplicate
    # account at insert time. This refuses the sharper and far more likely
    # mistake - inviting somebody who is already on the programme - while the
    # person doing it can still act on the answer.
    existing = db.scalar(
        select(UserAccount).where(func.lower(UserAccount.email) == email)
    )
    if existing is not None:
        owns_profile = db.scalar(
            select(AffiliateProfile).where(
                AffiliateProfile.user_account_id == existing.id
            )
        )
        if owns_profile is not None:
            raise ValueError(f"{email} is already on the programme")
        raise ValueError(f"An account already exists for {email}")

    token = secrets.token_urlsafe(TOKEN_BYTES)
    invitation = Invitation(
        email=email,
        role=role,
        token_hash=_hash(token),
        expires_at=utcnow() + timedelta(hours=valid_hours),
        invited_by=invited_by,
    )
    db.add(invitation)
    return token, invitation


def preview_invitation(db: Session, token: str) -> Invitation:
    """Read an invitation without consuming it, for the page it opens.

    The accept screen used to render its whole form on any URL that carried a
    token-shaped string, and only discover the token was dead when the form was
    submitted - so somebody withdrawn hours earlier still chose a name and a
    password before being refused. Worse, it made withdrawing look like it had
    done nothing.

    The checks and their wording are deliberately the same ones
    `accept_invitation` applies, so the page cannot say the link is fine and
    then refuse it a moment later.
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
    return invitation


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

    # Refused before the invitation is consumed, so a rejected password does
    # not burn the link - the same reasoning as hashing first, extended to the
    # quality rules. The invitation's own address is passed in because a
    # password containing it is guessable by anybody who has ever received an
    # email from them.
    problem = password_problem(password, personal=(invitation.email,))
    if problem is not None:
        raise ValueError(problem)

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
    accepted_at = utcnow()
    invitation.accepted_at = accepted_at

    # Every other outstanding invitation to this address dies with it.
    #
    # Sending a second invitation is allowed on purpose - it is how somebody
    # who never received the first one gets another. But accepting used to
    # close only the link that was actually used, leaving the rest live: two
    # working credentials for one person, and a row on the affiliates screen
    # for somebody who is now a model sitting right below it.
    #
    # Expired rather than deleted, and through the same `expires_at` the
    # accept check already reads, so a closed link and a lapsed one fail
    # identically and there is no second rule to disagree with the first.
    siblings = db.scalars(
        select(Invitation).where(
            func.lower(Invitation.email) == invitation.email.lower(),
            Invitation.id != invitation.id,
            Invitation.accepted_at.is_(None),
            Invitation.expires_at > accepted_at,
        )
    ).all()
    for sibling in siblings:
        sibling.expires_at = accepted_at

    return user
