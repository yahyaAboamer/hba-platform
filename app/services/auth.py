"""Sessions and authentication.

Only hashes are stored. The raw session token lives in an HttpOnly cookie and
the CSRF token in a response header, so a leaked database cannot be replayed
as a login.

resolve_session takes csrf=None for safe methods and the submitted header
value for unsafe ones. That distinction is deliberate: None means "not
required here", while an empty string means "required and not supplied", and
the second must fail.
"""

import hashlib
import hmac
import secrets
from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import settings
from app.core.businesstime import utcnow
from app.core.passwords import verify_password
from app.models.identity import AuthSession, UserAccount

TOKEN_BYTES = 32
USER_AGENT_LIMIT = 400


def _hash(token: str) -> str:
    return hashlib.sha256(str(token).encode("utf-8")).hexdigest()


def issue_session(
    db: Session,
    user_id: int,
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> tuple[str, str, AuthSession]:
    """Create a session and return (token, csrf, row).

    The caller sets the token as an HttpOnly cookie and returns the CSRF value
    to the client. Neither raw value is stored.
    """
    token = secrets.token_urlsafe(TOKEN_BYTES)
    csrf = secrets.token_urlsafe(TOKEN_BYTES)
    row = AuthSession(
        user_account_id=user_id,
        token_hash=_hash(token),
        csrf_hash=_hash(csrf),
        expires_at=utcnow() + timedelta(hours=settings.session_hours),
        ip_address=ip_address,
        # Truncated rather than rejected: an unusual or hostile header must not
        # be able to break sign-in.
        user_agent=(user_agent or "")[:USER_AGENT_LIMIT] or None,
    )
    db.add(row)
    return token, csrf, row


def resolve_session(
    db: Session, token: str, csrf: str | None = None
) -> UserAccount | None:
    """Return the account for a session token, or None if it is not usable.

    None for csrf means the check does not apply to this request. Any other
    value, including an empty string, must match.
    """
    if not token:
        return None
    row = db.scalar(select(AuthSession).where(AuthSession.token_hash == _hash(token)))
    if row is None or row.revoked_at is not None or row.expires_at <= utcnow():
        return None
    if csrf is not None and not hmac.compare_digest(row.csrf_hash, _hash(csrf)):
        return None
    user = db.get(UserAccount, row.user_account_id)
    # Status is checked on every request, so suspending an account ends access
    # immediately rather than whenever the session happens to expire.
    if user is None or user.status != "active":
        return None
    row.last_seen_at = utcnow()
    return user


def revoke_session(db: Session, token: str) -> bool:
    """Revoke one session. Returns whether this call changed anything."""
    if not token:
        return False
    row = db.scalar(select(AuthSession).where(AuthSession.token_hash == _hash(token)))
    if row is None or row.revoked_at is not None:
        return False
    row.revoked_at = utcnow()
    return True


def revoke_all_sessions(db: Session, user_id: int) -> int:
    """Revoke every live session for an account. Returns how many were ended."""
    rows = db.scalars(
        select(AuthSession).where(
            AuthSession.user_account_id == user_id,
            AuthSession.revoked_at.is_(None),
        )
    ).all()
    now = utcnow()
    for row in rows:
        row.revoked_at = now
    return len(rows)


def authenticate(db: Session, email: str, password: str) -> UserAccount | None:
    """Verify an email and password, returning the account or None."""
    if not email:
        return None
    user = db.scalar(
        select(UserAccount).where(func.lower(UserAccount.email) == str(email).lower())
    )
    if user is None or user.status != "active":
        return None
    if not verify_password(password or "", user.password_hash):
        return None
    user.last_login_at = utcnow()
    return user
