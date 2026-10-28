"""Remembered browsers: where the password alone is enough for 30 days.

ADR 0067, decision 5 as amended by the owner on 27 October 2026. After a code
on a new browser, the person may tick *Remember this browser for 30 days*;
the server then sets the `hba_trusted` cookie (HttpOnly, SameSite=Lax, Secure
as the session cookie is) holding a random token, and keeps only its hash.

**What it does and does not do.** It skips the second step only - the
password is still asked every time - and only for the account that
remembered it: the same cookie meeting another account's right password
skips nothing. It is never a session, and ending a session does not forget
it.

**Forgotten** on a password reset, a suspension, the owner's reset of the
person's two-step, turning two-step off, *sign out everywhere else* (all but
this browser), the owner's *end all*, and by hand. Forgetting sets
`revoked_at`; rows are not deleted, so when a browser was forgotten survives.
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.businesstime import utcnow
from app.core.user_agent import device_label
from app.shared.models.identity import TrustedBrowser, UserAccount
from app.shared.services.audit import record_audit

COOKIE = "hba_trusted"
DAYS = 30
TOKEN_BYTES = 32
USER_AGENT_LIMIT = 400


def _hash(token: str) -> str:
    return hashlib.sha256(str(token).encode("utf-8")).hexdigest()


def remember(
    db: Session,
    user_id: int,
    user_agent: str | None,
    ip_address: str | None,
    method: str,
) -> str:
    """Remember this browser for this account, proved by `method`
    ('authenticator' - the app or a recovery code - or 'email'). Returns the
    raw token for the cookie; only its hash is stored."""
    token = secrets.token_urlsafe(TOKEN_BYTES)
    now = utcnow()
    db.add(
        TrustedBrowser(
            user_account_id=user_id,
            token_hash=_hash(token),
            expires_at=now + timedelta(days=DAYS),
            last_used_at=now,
            user_agent=(user_agent or "")[:USER_AGENT_LIMIT] or None,
            ip_address=ip_address,
            method=method,
        )
    )
    db.flush()
    return token


def _live_query(user_id: int):
    return select(TrustedBrowser).where(
        TrustedBrowser.user_account_id == user_id,
        TrustedBrowser.revoked_at.is_(None),
        TrustedBrowser.expires_at > utcnow(),
    )


def live_for(db: Session, user_id: int, token: str | None) -> TrustedBrowser | None:
    """The live remembered browser this cookie names **for this account** -
    or None: unknown, forgotten, expired, or somebody else's."""
    if not token or len(token) > 200:
        return None
    return db.scalar(_live_query(user_id).where(TrustedBrowser.token_hash == _hash(token)))


def use(
    db: Session,
    user_id: int,
    token: str | None,
    *,
    method_now: str,
    roles: frozenset[str],
) -> bool:
    """Whether this cookie skips the second step for this account, noting
    that it was used.

    **Only as strong as the code that proved it.** A browser proved by the
    app (or a recovery code) skips whatever is asked now. One proved by an
    emailed code skips only while an emailed code is what would be asked -
    not once the person has turned the app on, and never for the owner, whose
    second step is the app.
    """
    row = live_for(db, user_id, token)
    if row is None:
        return False
    if row.method != "authenticator" and (method_now != "email" or "admin" in roles):
        return False
    row.last_used_at = utcnow()
    return True


def live_rows(db: Session, user_id: int) -> list[TrustedBrowser]:
    return list(
        db.scalars(
            _live_query(user_id).order_by(
                TrustedBrowser.last_used_at.desc(), TrustedBrowser.id.desc()
            )
        )
    )


def forget_one(db: Session, user_id: int, browser_id: int) -> bool:
    """Forget one live remembered browser **of this account**. False when it
    has no such browser - somebody else's reads as not there."""
    row = db.scalar(_live_query(user_id).where(TrustedBrowser.id == browser_id))
    if row is None:
        return False
    row.revoked_at = utcnow()
    db.flush()
    return True


def forget_all(db: Session, user_id: int, *, keep_id: int | None = None) -> int:
    """Forget every live remembered browser of an account, but `keep_id`.
    Returns how many."""
    rows = [row for row in live_rows(db, user_id) if row.id != keep_id]
    now = utcnow()
    for row in rows:
        row.revoked_at = now
    db.flush()
    return len(rows)


def forget_audited(
    db: Session,
    user: UserAccount,
    *,
    actor: UserAccount,
    why: str,
    ip_address: str | None,
    keep_id: int | None = None,
) -> int:
    """`forget_all`, audited as `auth.trusted_browser.forgotten` with the
    count and the reason - when there were any to forget."""
    forgotten = forget_all(db, user.id, keep_id=keep_id)
    if forgotten:
        record_audit(
            db,
            action="auth.trusted_browser.forgotten",
            subject=f"user:{user.id}",
            actor_id=actor.id,
            actor_email=actor.email,
            after={"forgotten": forgotten, "why": why},
            ip_address=ip_address,
        )
    return forgotten


def rows(browsers: list[TrustedBrowser], current_id: int | None) -> list[dict]:
    """As *Remembered browsers* shows them."""
    return [
        {
            "id": row.id,
            "device": device_label(row.user_agent),
            "ip_address": row.ip_address,
            "created_at": row.created_at.isoformat(),
            "last_used_at": row.last_used_at.isoformat(),
            "expires_at": row.expires_at.isoformat(),
            "current": current_id is not None and row.id == current_id,
        }
        for row in browsers
    ]
