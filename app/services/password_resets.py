"""Getting back into an account whose password is lost.

**There was no way back.** No reset route existed, and re-inviting was refused
too - `create_invitation` turns away an address that already holds an account.
A model who forgot their password could only be helped by editing the database
by hand, which is survivable with one administrator and not with twenty
people.

## What this deliberately does not reveal

`request_reset` behaves identically whether or not the address has an account.
No error, no different timing worth measuring, nothing in the response. An
endpoint that answered honestly would be a way to ask "is this person on the
programme", and the people on this programme are named individuals whose
association with HBA is theirs to disclose.

The person who really owns the address learns the answer the only way that
matters: an email arrives, or it does not.

## One live link at a time

Asking again invalidates whatever came before. Somebody who presses the button
twice - because the first mail was slow - would otherwise hold two working
links, and the older one is the one likelier to be sitting in a mailbox
somebody else can reach.
"""

import hashlib
import secrets
from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.businesstime import utcnow
from app.core.password_quality import password_problem
from app.core.passwords import hash_password, verify_password
from app.models.identity import PasswordReset, UserAccount

TOKEN_BYTES = 32

#: An invitation waits on somebody who has not heard of the platform yet. A
#: reset is answered by somebody already standing at the screen that offered
#: it, so it does not need to live for days - and a credential sitting in a
#: mailbox is a credential somebody else may reach.
VALID_HOURS = 2


def _hash(token: str) -> str:
    return hashlib.sha256(str(token).encode("utf-8")).hexdigest()


def request_reset(
    db: Session, email: str, *, ip_address: str | None = None
) -> tuple[str, UserAccount] | None:
    """Start a reset. Returns the token and account, or `None` if no account.

    **The caller must not tell them apart.** `None` means there is nobody to
    email, and the endpoint answers exactly as it does on success - see the
    module docstring.
    """
    address = str(email or "").strip().lower()
    if not address:
        return None

    account = db.scalar(
        select(UserAccount).where(func.lower(UserAccount.email) == address)
    )
    if account is None:
        return None

    # A suspended account is not a forgotten password, and letting one reset
    # its way back in would undo the suspension silently.
    if account.status == "suspended":
        return None

    # Every earlier request dies now, so only the newest link works.
    now = utcnow()
    for stale in db.scalars(
        select(PasswordReset)
        .where(PasswordReset.user_account_id == account.id)
        .where(PasswordReset.used_at.is_(None))
        .where(PasswordReset.expires_at > now)
    ):
        stale.expires_at = now

    token = secrets.token_urlsafe(TOKEN_BYTES)
    db.add(
        PasswordReset(
            user_account_id=account.id,
            token_hash=_hash(token),
            expires_at=now + timedelta(hours=VALID_HOURS),
            requested_ip=ip_address,
        )
    )
    return token, account


def _live_reset(db: Session, token: str) -> PasswordReset | None:
    if not token:
        return None
    row = db.scalar(
        select(PasswordReset).where(PasswordReset.token_hash == _hash(token))
    )
    if row is None or row.used_at is not None or row.expires_at <= utcnow():
        return None
    return row


def preview_reset(db: Session, token: str) -> UserAccount:
    """Whose link this is, without spending it.

    The screen checks on load rather than on submit, for the reason the
    invitation screen does: a dead link that renders a whole form makes
    somebody choose a password before telling them it was never going to work.
    """
    row = _live_reset(db, token)
    if row is None:
        raise ValueError(
            "This link has expired or has already been used. Ask for a new one."
        )
    return db.get(UserAccount, row.user_account_id)


def complete_reset(db: Session, token: str, password: str) -> UserAccount:
    """Set a new password and spend the link.

    Every other session is left to `revoke_sessions_for` in the caller: if the
    password was reset because somebody else knew it, the sessions they opened
    with it must not survive the change.
    """
    row = _live_reset(db, token)
    if row is None:
        raise ValueError(
            "This link has expired or has already been used. Ask for a new one."
        )

    account = db.get(UserAccount, row.user_account_id)

    # Checked before the link is spent, so a refused password does not burn
    # it - the same reasoning `accept_invitation` uses.
    problem = password_problem(password, personal=(account.email, account.display_name or ""))
    if problem is not None:
        raise ValueError(problem)

    # **The old password must not survive a reset.** There are only two reasons
    # to be here: it was forgotten, or somebody else has it. In the second case
    # keeping it defeats the entire exercise, and the person resetting cannot
    # tell which case they are in - so neither can we.
    if verify_password(password, account.password_hash):
        raise ValueError(
            "That is the password you already had. Choose a different one - "
            "resetting is only worth doing if the old one stops working."
        )

    account.password_hash = hash_password(password)
    row.used_at = utcnow()
    return account
