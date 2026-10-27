"""Identity spine.

Identity is rooted in user_account, not in any business record. Staff exist as
user accounts today; affiliates will hang an affiliate_profile off the same
table in a later phase, and Production and Operations staff will do the same
without any change here.

Rooting identity in the affiliate record instead would have been the easy
shortcut and the wrong one: the "generic" spine would have been shaped around
models, and every later module would have had to work around that.

Role and status values are constrained by the database as well as the
application. The role list is generated from app.core.permissions, so a role
that exists in code is accepted and one that does not is refused at the point
of write, whatever the calling code believes.
"""

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.permissions import VALID_ROLES
from app.db import Base

_ROLE_LIST = ", ".join(f"'{role}'" for role in sorted(VALID_ROLES))
_STATUS_LIST = "'invited', 'active', 'suspended'"


class UserAccount(Base):
    """Anyone who can sign in. Staff and affiliates alike."""

    __tablename__ = "user_account"
    __table_args__ = (
        CheckConstraint(f"status IN ({_STATUS_LIST})", name="user_account_status_valid"),
        CheckConstraint(
            "maintainer_theme IS NULL OR maintainer_theme IN ('dark', 'light', 'system')",
            name="user_account_maintainer_theme_valid",
        ),
        # Unique on lower(email): addresses are case-insensitive in practice, and
        # two accounts differing only by case would be an account-takeover route.
        Index("user_account_email_lower_key", text("lower(email)"), unique=True),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="invited")
    display_name: Mapped[str | None] = mapped_column(String(120))
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    #: A staff member's theme for the admin tool, on the account so it follows
    #: them between devices (Settings audit P1). `None` is the dark default.
    maintainer_theme: Mapped[str | None] = mapped_column(String(6))
    #: When this person turned on **codes by email** for a new browser (ADR
    #: 0067, decision 5 as amended 27 October 2026). Empty means off. Only
    #: the choice is kept here; somebody whose access needs email codes is
    #: asked for one whatever this says, while the owner's switch is on.
    two_step_email_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )

    # passive_deletes lets the database's ON DELETE CASCADE do the work. Without
    # it SQLAlchemy tries to null the foreign key first, which violates the NOT
    # NULL constraint and fails the delete outright. The schema is the authority
    # on referential behaviour; the ORM should not second-guess it.
    roles: Mapped[list["RoleAssignment"]] = relationship(
        back_populates="user",
        foreign_keys="RoleAssignment.user_account_id",
        passive_deletes=True,
    )


class RoleAssignment(Base):
    """Which role a person holds, and who granted it. A person may hold
    several at once; what they may do is all of them together (ADR 0067).

    Assignments are revoked rather than deleted, so the audit trail can always
    answer what access someone had at the time they did something.
    """

    __tablename__ = "role_assignment"
    __table_args__ = (
        CheckConstraint(f"role IN ({_ROLE_LIST})", name="role_assignment_role_valid"),
        # One operations manager at a time (ADR 0057). The service refuses a
        # second with the reason; this holds when two invitations race.
        Index(
            "role_assignment_one_operations_manager",
            "role",
            unique=True,
            postgresql_where=text("role = 'operations_manager' AND revoked_at IS NULL"),
        ),
        # A person may hold several roles (ADR 0067), but never the same one
        # twice at once: a second live row would make removing it ambiguous.
        Index(
            "role_assignment_one_live_role_per_person",
            "user_account_id",
            "role",
            unique=True,
            postgresql_where=text("revoked_at IS NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_account_id: Mapped[int] = mapped_column(
        ForeignKey("user_account.id", ondelete="CASCADE"), nullable=False, index=True
    )
    role: Mapped[str] = mapped_column(String(40), nullable=False)
    granted_by: Mapped[int | None] = mapped_column(ForeignKey("user_account.id"))
    granted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    user: Mapped["UserAccount"] = relationship(
        back_populates="roles", foreign_keys=[user_account_id]
    )


class AuthSession(Base):
    """A browser session.

    Only hashes are stored. The raw session token lives in an HttpOnly cookie
    and the CSRF token in a header, so a database leak cannot be replayed as a
    login. There is deliberately no column that could hold a raw token.
    """

    __tablename__ = "auth_session"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_account_id: Mapped[int] = mapped_column(
        ForeignKey("user_account.id", ondelete="CASCADE"), nullable=False, index=True
    )
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    csrf_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ip_address: Mapped[str | None] = mapped_column(String(64))
    user_agent: Mapped[str | None] = mapped_column(String(400))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class Invitation(Base):
    """A single-use invitation.

    There is no public staff signup. An administrator invites a person and
    chooses their role; the invitee sets their own password, so nobody ever
    sets or sees another person's credentials.
    """

    __tablename__ = "invitation"
    __table_args__ = (
        CheckConstraint(f"role IN ({_ROLE_LIST})", name="invitation_role_valid"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(320), nullable=False, index=True)
    #: The first name the admin typed beside the address, if any. The email
    #: greets her by it; without one it says "Hello," rather than a bare "Hi,".
    name: Mapped[str | None] = mapped_column(String(120))
    role: Mapped[str] = mapped_column(String(40), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    #: Withdrawn on purpose, as opposed to simply lapsed.
    #:
    #: Withdrawing works by backdating `expires_at`, which is deliberate - the
    #: link then dies through the same check accepting already applies, rather
    #: than a second rule that could disagree with the first. But it left the
    #: two indistinguishable afterwards: a link somebody cancelled and one
    #: nobody opened in time both read "Link expired", and only one of them is
    #: worth resending.
    withdrawn_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    invited_by: Mapped[int | None] = mapped_column(ForeignKey("user_account.id"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class PasswordReset(Base):
    """A single-use link back into an account whose password is lost.

    **Without this there was no way back at all.** No reset route existed, and
    re-inviting was refused too - `create_invitation` turns away an address
    that already holds an account ("already on the programme"). A model who
    forgot their password could only be helped by editing the database by
    hand. Survivable with one administrator who knows their own password;
    not survivable with twenty people.

    The same shape as `Invitation` and for the same reasons: the raw token is
    a credential, so only its hash is stored, and it is single-use. Shorter
    lived, though - an invitation waits on somebody who has not heard of the
    platform yet, while a reset is answered by somebody already at the screen
    asking for it.
    """

    __tablename__ = "password_reset"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_account_id: Mapped[int] = mapped_column(
        ForeignKey("user_account.id", ondelete="CASCADE"), nullable=False, index=True
    )
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    #: Set the moment it is spent. Kept rather than deleted so "when did
    #: somebody last reset this account" survives, which is the question asked
    #: when an account behaves oddly.
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    #: What asked for it. Not shown to anybody; recorded because a reset
    #: request nobody made is the first sign of somebody probing addresses.
    requested_ip: Mapped[str | None] = mapped_column(String(45))

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class StaffPreference(Base):
    """One of Settings → Appearance's switches, turned off by one staff account.

    **Absence means on**, as the export's defaults (`prefs: { notices: true,
    weekly: true }`): a row exists only once somebody has changed a switch, so
    an account nobody has touched gets both.
    """

    __tablename__ = "staff_preference"
    __table_args__ = (
        UniqueConstraint("user_account_id", "key", name="staff_preference_unique"),
        CheckConstraint(
            "key IN ('home_notices', 'weekly_targets_reminder')",
            name="staff_preference_key_valid",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_account_id: Mapped[int] = mapped_column(
        ForeignKey("user_account.id", ondelete="CASCADE"), nullable=False
    )
    key: Mapped[str] = mapped_column(String(40), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


# ── Two-step sign-in (ADR 0067, decision 5; Phase 1 batch 3) ─────────────────


class TwoStepSecret(Base):
    """A person's authenticator-app secret, one per account.

    **Encrypted, never stored readable.** The secret is what makes the codes,
    so a copy of it is a copy of the person's phone; it is kept with the same
    Fernet key as the other secrets saved from Settings
    (`app/core/secrets.py`). A database that leaks without the key leaks
    nothing anybody can make codes from.

    A row with no `enabled_at` is one being set up: the QR code has been shown
    and no code has confirmed it yet. It turns nothing on, and starting again
    replaces it.
    """

    __tablename__ = "two_step_secret"
    __table_args__ = (
        UniqueConstraint("user_account_id", name="two_step_secret_one_per_account"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_account_id: Mapped[int] = mapped_column(
        ForeignKey("user_account.id", ondelete="CASCADE"), nullable=False
    )
    #: Fernet ciphertext of the base32 secret. There is deliberately no column
    #: that could hold it readable.
    secret_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    #: When a code confirmed it, which is when it was turned on. Empty while
    #: it is still being set up.
    enabled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    #: The last 30-second step a code was accepted for. **A code works once**:
    #: a step at or before this one is refused, so a code read over somebody's
    #: shoulder, or replayed from a captured request, does not work again.
    last_used_step: Mapped[int | None] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class RecoveryCode(Base):
    """One of the ten one-time codes for a lost phone.

    Shown once, when they are made, and stored only as a salted, slow hash:
    whoever reads this table cannot sign in with what they read. Spent ones
    are kept with the time they were used rather than deleted, so "how many
    are left" and "when was one last used" can both be answered.
    """

    __tablename__ = "recovery_code"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_account_id: Mapped[int] = mapped_column(
        ForeignKey("user_account.id", ondelete="CASCADE"), nullable=False, index=True
    )
    #: `pbkdf2_sha256$<iterations>$<salt>$<hash>` (`app/services/two_step.py`).
    code_hash: Mapped[str] = mapped_column(String(200), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class PendingSignIn(Base):
    """The half-way point of a two-step sign-in: the password was right, and
    a code is still owed.

    **Not a session.** It opens nothing; the only thing it can be exchanged for
    is a session, and only together with a code. Short-lived and single-use,
    and only its hash is stored, like every other token here - a leaked
    database cannot finish somebody's sign-in.
    """

    __tablename__ = "pending_sign_in"
    __table_args__ = (
        CheckConstraint(
            "method IS NULL OR method IN ('authenticator', 'email')",
            name="pending_sign_in_method_valid",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_account_id: Mapped[int] = mapped_column(
        ForeignKey("user_account.id", ondelete="CASCADE"), nullable=False, index=True
    )
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    #: Set when it is exchanged for a session, or cancelled (a password reset,
    #: a suspension). Either way it never works again.
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    #: Where the password was typed. Not shown to anybody; kept because a
    #: right password followed by wrong codes is worth being able to trace.
    ip_address: Mapped[str | None] = mapped_column(String(64))
    #: Which code is owed: `authenticator` (or a recovery code) or `email`.
    #: Empty only on rows made before email codes existed, which were all
    #: authenticator sign-ins.
    method: Mapped[str | None] = mapped_column(String(20))
    #: The emailed code, as HMAC-SHA256 keyed by the **raw** pending token -
    #: which only the browser holds. Six digits are a million guesses, so a
    #: plain hash would be undone from a copy of this table in a moment; keyed
    #: by a token the table does not contain, the copy is no help.
    email_code_hash: Mapped[str | None] = mapped_column(String(64))
    #: When the current code was sent, for the once-a-minute resend limit.
    email_code_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    #: How many codes this sign-in has sent, for the five-per-sign-in limit.
    email_codes_sent: Mapped[int | None] = mapped_column(Integer)
    #: Wrong codes typed for this sign-in. At ten it stops working, so going
    #: on needs the password again - and, for an emailed code, a new email
    #: the owner of the inbox sees.
    wrong_codes: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class TrustedBrowser(Base):
    """A browser somebody chose to remember for 30 days (ADR 0067, decision 5
    as amended): on it, the right password is enough and no code is asked.

    **Never instead of the password.** It only skips the second step, only
    for the account that remembered it, and only while it is live. The cookie
    holds a random token; only its hash is here, so a copy of this table
    remembers nobody's browser.

    Forgotten - `revoked_at` set, never deleted, so *when* survives - on a
    password reset, a suspension, the owner's reset of the person's two-step,
    turning two-step off, *sign out everywhere else*, and by hand.
    """

    __tablename__ = "trusted_browser"
    __table_args__ = (
        CheckConstraint(
            "method IN ('authenticator', 'email')", name="trusted_browser_method_valid"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_account_id: Mapped[int] = mapped_column(
        ForeignKey("user_account.id", ondelete="CASCADE"), nullable=False, index=True
    )
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_used_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    #: The header it was remembered with, named for people as "Chrome on
    #: Windows" (`app/core/user_agent.py`). Truncated, never trusted.
    user_agent: Mapped[str | None] = mapped_column(String(400))
    ip_address: Mapped[str | None] = mapped_column(String(64))
    #: Which code proved this browser. One proved by an emailed code skips the
    #: step only while email is still what the person would be asked for: not
    #: once they have the app on, and never for the owner.
    method: Mapped[str] = mapped_column(String(20), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
