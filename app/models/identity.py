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
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
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
    """Which role a person holds, and who granted it.

    Assignments are revoked rather than deleted, so the audit trail can always
    answer what access someone had at the time they did something.
    """

    __tablename__ = "role_assignment"
    __table_args__ = (
        CheckConstraint(f"role IN ({_ROLE_LIST})", name="role_assignment_role_valid"),
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
    role: Mapped[str] = mapped_column(String(40), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
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
