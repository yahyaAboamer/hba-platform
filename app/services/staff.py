"""The people who run the platform, not the people it pays.

Distinct from `app/services/affiliates.py`: a model reaches her own portal by
owning an `affiliate_profile`, never by holding a role here (§6.1, ADR 0006).
This module is the roster of staff - who has access, what they may do, and
the three things a person actually needs to do about that day to day: change
somebody's role, suspend an account gone wrong, and withdraw an invitation
sent by mistake.

`app/core/permissions.py` is explicit that roles are not composable through
the interface, and that the flexibility actually needed is assigning a person
to one, changing it, and revoking access - "none of which requires code."
This is where that promise is kept. `settings.manage`, `invitations.send` and
`audit.view` were defined with this screen in mind and had no UI until now.
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.businesstime import utcnow
from app.core.permissions import VALID_ROLES
from app.models.identity import Invitation, RoleAssignment, UserAccount
from app.services.audit import record_audit

#: 'affiliate' is the no-permission default a person falls back to when no
#: assignment exists at all (app/api/deps.py, active_role) - nobody is
#: deliberately given it, so it is not offered as a target here.
ASSIGNABLE_ROLES = frozenset(VALID_ROLES - {"affiliate"})


def list_staff(db: Session) -> list[dict]:
    """Every account that has ever held a staff role, with what it holds now.

    "Has ever held one" rather than "holds one now": a suspended account still
    needs to be visible, or reactivating it would have nowhere to happen from.
    """
    from app.api.deps import active_role  # avoids a module-level import cycle

    account_ids = list(db.scalars(select(RoleAssignment.user_account_id).distinct()))
    if not account_ids:
        return []

    accounts = db.scalars(
        select(UserAccount)
        .where(UserAccount.id.in_(account_ids))
        .order_by(UserAccount.display_name, UserAccount.email)
    )
    return [
        {
            "id": account.id,
            "email": account.email,
            "display_name": account.display_name,
            "role": active_role(db, account),
            "status": account.status,
            "last_login_at": account.last_login_at,
            "created_at": account.created_at,
        }
        for account in accounts
    ]


def list_pending_invitations(db: Session) -> list[Invitation]:
    """Invitations sent and not yet used, oldest first.

    An expired one is included rather than hidden - nobody accepted it before
    it lapsed, which is exactly the kind of thing worth noticing and
    re-sending, not a fact to bury.
    """
    return list(
        db.scalars(
            select(Invitation)
            .where(Invitation.accepted_at.is_(None))
            .order_by(Invitation.created_at)
        )
    )


def _admin_count(db: Session, *, excluding: int | None = None) -> int:
    query = (
        select(RoleAssignment.user_account_id)
        .join(UserAccount, UserAccount.id == RoleAssignment.user_account_id)
        .where(RoleAssignment.role == "admin")
        .where(RoleAssignment.revoked_at.is_(None))
        .where(UserAccount.status == "active")
    )
    if excluding is not None:
        query = query.where(RoleAssignment.user_account_id != excluding)
    return len(set(db.scalars(query)))


def _assert_leaves_an_admin(db: Session, user: UserAccount) -> None:
    """Refuse a change that would leave nobody able to administer the platform.

    `settings.manage` - the one permission that can grant it back - is held by
    `admin` alone. An account locked out of every admin has no lever left to
    reverse itself, which is worth three lines to prevent (ADR 0019): the cost
    of checking is trivial, and the cost of not checking is a live payroll
    platform nobody can administer until someone edits the database by hand.
    """
    if _admin_count(db, excluding=user.id) == 0:
        raise ValueError(
            "This is the only active admin. Make somebody else admin first."
        )


def change_role(
    db: Session,
    user: UserAccount,
    new_role: str,
    *,
    actor_id: int | None,
    actor_email: str | None,
) -> RoleAssignment:
    """Move an account onto a new role, revoking the one it holds now.

    A new row rather than an edit to the old one - `role_assignment` exists
    precisely so "what access did they have on this date" survives a later
    change, the same reasoning that makes a rate change a new compensation
    period rather than an edit (Phase 3).
    """
    from app.api.deps import active_role

    if new_role not in ASSIGNABLE_ROLES:
        raise ValueError(f"Not an assignable role: {new_role!r}")

    before = active_role(db, user)
    if before == new_role:
        raise ValueError(f"{user.display_name or user.email} already holds {new_role}")

    if before == "admin" and user.status == "active":
        _assert_leaves_an_admin(db, user)

    live = db.scalar(
        select(RoleAssignment)
        .where(RoleAssignment.user_account_id == user.id)
        .where(RoleAssignment.revoked_at.is_(None))
        .order_by(RoleAssignment.id.desc())
    )
    if live is not None:
        live.revoked_at = utcnow()

    created = RoleAssignment(user_account_id=user.id, role=new_role, granted_by=actor_id)
    db.add(created)
    db.flush()

    record_audit(
        db,
        action="staff.role_changed",
        subject=f"user:{user.id}",
        actor_id=actor_id,
        actor_email=actor_email,
        before={"role": before},
        after={"role": new_role},
    )
    return created


def suspend_staff(
    db: Session,
    user: UserAccount,
    *,
    reason: str,
    actor_id: int | None,
    actor_email: str | None,
) -> UserAccount:
    """Lock an account out without deleting anything it has done.

    **Takes effect immediately, not at next sign-in** - `resolve_session`
    checks `status` on every request (app/services/auth.py), so an open tab is
    refused on its very next call rather than left to run until its session
    happens to expire.
    """
    from app.api.deps import active_role

    if not str(reason or "").strip():
        raise ValueError("Suspending an account needs a written reason")
    if user.status == "suspended":
        raise ValueError(f"{user.display_name or user.email} is already suspended")

    if active_role(db, user) == "admin":
        _assert_leaves_an_admin(db, user)

    before_status = user.status
    user.status = "suspended"

    record_audit(
        db,
        action="staff.suspended",
        subject=f"user:{user.id}",
        actor_id=actor_id,
        actor_email=actor_email,
        before={"status": before_status},
        after={"status": "suspended"},
        reason=reason.strip(),
    )
    return user


def reactivate_staff(
    db: Session,
    user: UserAccount,
    *,
    actor_id: int | None,
    actor_email: str | None,
) -> UserAccount:
    """Reverse a suspension. No reason required - a suspension is the act that
    needs explaining; undoing one needs only doing."""
    if user.status != "suspended":
        raise ValueError(f"{user.display_name or user.email} is not suspended")

    user.status = "active"

    record_audit(
        db,
        action="staff.reactivated",
        subject=f"user:{user.id}",
        actor_id=actor_id,
        actor_email=actor_email,
        before={"status": "suspended"},
        after={"status": "active"},
    )
    return user


def revoke_invitation(
    db: Session,
    invitation: Invitation,
    *,
    actor_id: int | None,
    actor_email: str | None,
) -> Invitation:
    """Withdraw an invitation nobody has used yet.

    No separate "revoked" state on the row. `accept_invitation` already
    refuses anything past `expires_at`, so backdating it to now closes the
    link through the **same** check accepting uses, rather than a second one
    that could disagree with the first.
    """
    if invitation.accepted_at is not None:
        raise ValueError("This invitation has already been used")
    if invitation.expires_at <= utcnow():
        raise ValueError("This invitation has already expired")

    invitation.expires_at = utcnow()

    record_audit(
        db,
        action="invitation.revoked",
        subject=f"invitation:{invitation.email}",
        actor_id=actor_id,
        actor_email=actor_email,
        after={"email": invitation.email, "role": invitation.role},
    )
    return invitation
