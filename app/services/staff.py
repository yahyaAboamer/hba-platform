"""The people who run the platform, not the people it pays.

Distinct from `app/services/affiliates.py`: a model reaches their own portal by
owning an `affiliate_profile`, never by holding a role here (§6.1, ADR 0006).
This module is the roster of staff - who has access, what they may do, and
the things a person actually needs to do about that day to day: give somebody
a role or take one away, suspend an account gone wrong, and withdraw an
invitation sent by mistake.

**A person may hold several roles** (ADR 0067), so giving and taking are two
separate actions, each audited. Changing somebody's job is taking one role
and giving another, and each step is held to the same rules.

`app/core/permissions.py` is explicit that roles are not composable through
the interface, and that the flexibility actually needed is assigning a person
to one, changing it, and revoking access - "none of which requires code."
This is where that promise is kept. `settings.manage`, `invitations.send` and
`audit.view` were defined with this screen in mind and had no UI until now.
"""

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.businesstime import utcnow
from app.core.permissions import (
    GRANT_REFUSED,
    MODEL_ROLE,
    VALID_ROLES,
    can_grant,
    sorted_roles,
)
from app.models.identity import Invitation, RoleAssignment, UserAccount
from app.services.access import live_roles, live_roles_by_account
from app.services.audit import record_audit
from app.services.auth import revoke_all_sessions
from app.services.trusted_browsers import forget_all as forget_trusted_browsers
from app.services.two_step import cancel_pending, enabled_account_ids, method_from

#: A model's role grants nothing and makes nobody staff; a model holds it by
#: accepting her invitation, and reaches her portal by owning her record. It
#: is never given or taken here.
ASSIGNABLE_ROLES = frozenset(VALID_ROLES - {MODEL_ROLE})

#: Refused when somebody acts on their own row. Another admin does it.
OWN_ACCOUNT = "You cannot change your own access. Another admin can."

#: Roles one person holds at a time, and how a refusal names them (ADR 0057).
#: The database's partial unique index refuses a second live holder; this says
#: why before anything is written, and counts an invitation still open.
SINGLE_HOLDER_ROLES = {"operations_manager": "an operations manager"}


def assert_role_free(
    db: Session,
    role: str,
    *,
    for_user_id: int | None = None,
    accepting_invitation_id: int | None = None,
) -> None:
    """Refuse a one-holder role while somebody holds it or is invited to it.

    `for_user_id` is the person being given it, and `accepting_invitation_id`
    the invitation being accepted: neither is a rival to itself.
    """
    words = SINGLE_HOLDER_ROLES.get(role)
    if words is None:
        return
    # A resend expires the old link in this same transaction, and the session
    # does not flush on its own: make that visible before asking.
    db.flush()

    holder_query = (
        select(UserAccount)
        .join(RoleAssignment, RoleAssignment.user_account_id == UserAccount.id)
        .where(RoleAssignment.role == role, RoleAssignment.revoked_at.is_(None))
    )
    if for_user_id is not None:
        holder_query = holder_query.where(UserAccount.id != for_user_id)
    holder = db.scalar(holder_query.limit(1))
    if holder is not None:
        raise ValueError(
            f"HBA already has {words}: {holder.display_name or holder.email}. "
            "Change their access first."
        )

    open_query = select(Invitation).where(
        Invitation.role == role,
        Invitation.accepted_at.is_(None),
        Invitation.withdrawn_at.is_(None),
        Invitation.expires_at > utcnow(),
    )
    if accepting_invitation_id is not None:
        open_query = open_query.where(Invitation.id != accepting_invitation_id)
    pending = db.scalar(open_query.order_by(Invitation.id).limit(1))
    if pending is not None:
        raise ValueError(
            f"An invitation to {pending.email} is still open for this access. "
            "Withdraw it first."
        )


def invitable_roles(actor_roles: frozenset[str]) -> list[str]:
    """The staff roles this person may give somebody - never more than they
    hold themselves, all their roles together (`can_grant`). The invite form
    and *Add access* offer these and no others, so a refusal is not the first
    the person hears of it."""
    return sorted(role for role in ASSIGNABLE_ROLES if can_grant(actor_roles, role))


def list_staff(db: Session) -> list[dict]:
    """Every account that has ever held a staff role, with what it holds now.

    "Has ever held one" rather than "holds one now": a suspended account still
    needs to be visible, or reactivating it would have nowhere to happen from.

    **Models are not staff and are not listed.** Accepting an invitation gives
    an affiliate a role assignment like anybody else, so they used to appear
    here - with an account status of *active* beside an approval status that
    was still *waiting to be approved*, which reads as the platform
    contradicting itself. They belong on Affiliates, which is where their
    status means what it says.
    """
    account_ids = list(
        db.scalars(
            select(RoleAssignment.user_account_id)
            .where(RoleAssignment.role != MODEL_ROLE)
            .distinct()
        )
    )
    if not account_ids:
        return []

    accounts = list(
        db.scalars(
            select(UserAccount)
            .where(UserAccount.id.in_(account_ids))
            .order_by(UserAccount.display_name, UserAccount.email)
        )
    )
    held = live_roles_by_account(db, account_ids)
    with_two_step = enabled_account_ids(db, account_ids)
    # What a new browser would ask each of them: the app if it is on, else a
    # code by email if that applies to them, else nothing.
    methods = {
        account.id: method_from(
            account.id in with_two_step,
            held[account.id],
            account.two_step_email_at is not None,
        )
        for account in accounts
    }
    return [
        {
            "id": account.id,
            "email": account.email,
            "display_name": account.display_name,
            # Every staff role held now, widest first (ADR 0067). A model's
            # role grants nothing and is not staff access, so it is left out.
            "roles": sorted_roles(held[account.id] - {MODEL_ROLE}),
            "status": account.status,
            #: The lock beside a name on Team and access (ADR 0067): on when a
            #: new browser asks them for a code of either kind, and which.
            "two_step_enabled": methods[account.id] is not None,
            "two_step_method": methods[account.id],
            "two_step_email_on": account.two_step_email_at is not None,
            "last_login_at": account.last_login_at,
            "created_at": account.created_at,
        }
        for account in accounts
    ]


def list_pending_invitations(
    db: Session, *, exclude_roles: tuple[str, ...] = (), current_only: bool = False
) -> list[Invitation]:
    """Invitations sent and not yet used, oldest first.

    An expired one is included rather than hidden - nobody accepted it before
    it lapsed, which is exactly the kind of thing worth noticing and
    re-sending, not a fact to bury.

    `exclude_roles` keeps model invitations off the staff panel. They are not
    hidden: they appear on Affiliates, beside the models they will become, so
    every invitation is still withdrawable from the screen it belongs to.

    **An address that already has an account is not pending anything.** Only
    the invitation actually used is marked accepted, so a person invited four
    times kept three rows for ever - and they sat on the affiliates screen
    above the model they had become. Filtering on the account rather than on
    the invitation clears the ones already on file too, with no migration and
    nothing deleted.
    """
    has_account = (
        select(UserAccount.id)
        .where(func.lower(UserAccount.email) == func.lower(Invitation.email))
        .exists()
    )
    query = select(Invitation).where(
        Invitation.accepted_at.is_(None), ~has_account
    )
    if exclude_roles:
        query = query.where(Invitation.role.notin_(exclude_roles))
    # **Newest first.** They were oldest-first, so the invitation somebody
    # just sent - the only one they are usually looking for - sat at the
    # bottom under every dead one above it.
    #
    # `id` breaks the tie, and it is not decoration: `created_at` defaults to
    # `now()`, which in Postgres is the *transaction* start time, so rows
    # written together share a timestamp exactly and their order is otherwise
    # undefined. Two invitations sent in the same second would shuffle.
    rows = list(
        db.scalars(query.order_by(Invitation.created_at.desc(), Invitation.id.desc()))
    )
    if not current_only:
        return rows
    # **One line per address, the newest.** Resend replaces a link and Withdraw
    # cancels one, and both used to leave the old row behind as "Link
    # expired" - with nothing able to clear it, since an expired link cannot
    # be withdrawn. The list grew with every press of the buttons meant to
    # tidy it (Settings audit, T1). A withdrawn newest row means the person
    # meant "nobody is invited", so the address goes altogether.
    seen: set[str] = set()
    current: list[Invitation] = []
    for row in rows:
        address = row.email.lower()
        if address in seen:
            continue
        seen.add(address)
        if row.withdrawn_at is None:
            current.append(row)
    return current


def _admin_count(db: Session, *, excluding: int | None = None) -> int:
    """Active admins other than `excluding`, counted **under lock**.

    Every live admin assignment is locked first (`FOR UPDATE`, in id order so
    two callers queue rather than deadlock). Without it two admins suspending
    each other at the same moment would each count the other as the admin
    left behind, and both would go - the platform with nobody able to
    administer it. With it the second waits for the first to commit, then
    re-reads, sees the first one's assignment revoked, and is refused.
    """
    db.execute(
        select(RoleAssignment.id)
        .where(RoleAssignment.role == "admin", RoleAssignment.revoked_at.is_(None))
        .order_by(RoleAssignment.id)
        .with_for_update()
    ).all()
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


def _name(user: UserAccount) -> str:
    return user.display_name or user.email


def _refuse_own_account(user: UserAccount, actor_id: int | None) -> None:
    # Nobody changes their own access - one mis-click demoting yourself locks
    # you out of the very screen that would undo it (Settings audit, T2).
    if actor_id is not None and actor_id == user.id:
        raise ValueError(OWN_ACCOUNT)


def give_role(
    db: Session,
    user: UserAccount,
    role: str,
    *,
    actor_roles: frozenset[str],
    actor_id: int | None,
    actor_email: str | None,
) -> RoleAssignment:
    """Give an account one more role, keeping every role it holds (ADR 0067).

    The rules that held when a role could only be swapped still hold: nobody
    changes their own access; nobody gives access they do not hold, all their
    roles together (`can_grant`); there is one operations manager at a time.
    A role already held is refused here with the reason, and by the database's
    one-live-role-per-person index when two requests race.
    """
    if role not in ASSIGNABLE_ROLES:
        raise ValueError(f"Not an assignable role: {role!r}")
    _refuse_own_account(user, actor_id)
    if not can_grant(actor_roles, role):
        raise ValueError(GRANT_REFUSED)

    before = live_roles(db, user.id)
    if role in before:
        raise ValueError(f"{_name(user)} already holds this access")
    assert_role_free(db, role, for_user_id=user.id)

    created = RoleAssignment(user_account_id=user.id, role=role, granted_by=actor_id)
    db.add(created)
    db.flush()

    after = {"role": role, "roles": sorted_roles(before | {role})}
    if role == "admin":
        # The owner's second step is the app. A browser remembered on an
        # emailed code would otherwise go on skipping it for the new owner.
        after["browsers_forgotten"] = forget_trusted_browsers(db, user.id)
    record_audit(
        db,
        action="staff.role_given",
        subject=f"user:{user.id}",
        actor_id=actor_id,
        actor_email=actor_email,
        before={"roles": sorted_roles(before)},
        after=after,
    )
    return created


def remove_role(
    db: Session,
    user: UserAccount,
    role: str,
    *,
    actor_roles: frozenset[str],
    actor_id: int | None,
    actor_email: str | None,
) -> RoleAssignment:
    """Take one role from an account, leaving the rest (ADR 0067).

    Revoked, never deleted - `role_assignment` exists precisely so "what
    access did they have on this date" survives a later change.

    Held to the same rules as giving: not your own access, and not a role you
    could not have given (taking access away is the mirror of granting it, as
    withdrawing an invitation is). The last active admin cannot lose admin.

    **The last staff role cannot be taken this way.** An account left holding
    nothing would be neither staff nor a model - it could reach no screen, yet
    it could apply to become a model. Suspending is how somebody loses all
    their access, and the refusal says so.
    """
    if role not in ASSIGNABLE_ROLES:
        raise ValueError(f"Not an assignable role: {role!r}")
    _refuse_own_account(user, actor_id)
    if not can_grant(actor_roles, role):
        raise ValueError(GRANT_REFUSED)

    live = db.scalar(
        select(RoleAssignment)
        .where(
            RoleAssignment.user_account_id == user.id,
            RoleAssignment.role == role,
            RoleAssignment.revoked_at.is_(None),
        )
        .with_for_update()
    )
    if live is None:
        raise ValueError(f"{_name(user)} does not hold this access")

    before = live_roles(db, user.id)
    if not (before - {role, MODEL_ROLE}):
        raise ValueError(
            f"This is the only access {_name(user)} has. Give them other access "
            "first, or suspend the account."
        )
    if role == "admin" and user.status == "active":
        _assert_leaves_an_admin(db, user)

    _revoke(db, [live])

    record_audit(
        db,
        action="staff.role_removed",
        subject=f"user:{user.id}",
        actor_id=actor_id,
        actor_email=actor_email,
        before={"roles": sorted_roles(before)},
        after={"role": role, "roles": sorted_roles(before - {role})},
    )
    return live


def _revoke(db: Session, assignments: list[RoleAssignment]) -> None:
    """Revoke role assignments - **the one way access is taken away**, for
    removing one role and for suspending alike, so the trail reads the same
    whichever did it. Revoked, never deleted: `role_assignment` exists so that
    "what access did they have on this date" survives a later change."""
    now = utcnow()
    for assignment in assignments:
        assignment.revoked_at = now
    db.flush()


def suspend_staff(
    db: Session,
    user: UserAccount,
    *,
    reason: str,
    actor_id: int | None,
    actor_email: str | None,
) -> int:
    """Lock an account out without deleting anything it has done. Returns how
    many sessions it ended.

    **One action, one entry** (ADR 0067, decision 6): the status, every staff
    role and every session go together, and the trail records them as one
    `staff.suspended` with the roles held before. Bringing somebody back is
    then a deliberate act - reactivating gives no access back, and each role
    is given again with *Add access*.

    **A model's own role stays.** It grants nothing and is never given or
    taken here (`ASSIGNABLE_ROLES`); her portal is reached by owning her
    record, and a suspended account reaches nothing at all.

    **Takes effect immediately, not at next sign-in** - `resolve_session`
    checks `status` on every request (app/services/auth.py), and every session
    is ended besides, so an open tab is refused on its very next call.
    """
    if not str(reason or "").strip():
        raise ValueError("Suspending an account needs a written reason")
    if actor_id is not None and actor_id == user.id:
        raise ValueError("You cannot suspend your own account. Another admin can.")
    if user.status == "suspended":
        raise ValueError(f"{user.display_name or user.email} is already suspended")

    if "admin" in live_roles(db, user.id):
        _assert_leaves_an_admin(db, user)

    held = list(
        db.scalars(
            select(RoleAssignment)
            .where(
                RoleAssignment.user_account_id == user.id,
                RoleAssignment.revoked_at.is_(None),
                RoleAssignment.role != MODEL_ROLE,
            )
            .order_by(RoleAssignment.id)
            .with_for_update()
        )
    )
    before_status = user.status
    before_roles = sorted_roles(a.role for a in held)

    user.status = "suspended"
    _revoke(db, held)
    ended = revoke_all_sessions(db, user.id)
    # A sign-in half done (the password typed, the code still owed) must not
    # be finished either, nor a remembered browser skip the code later.
    cancel_pending(db, user.id)
    forgotten = forget_trusted_browsers(db, user.id)

    record_audit(
        db,
        action="staff.suspended",
        subject=f"user:{user.id}",
        actor_id=actor_id,
        actor_email=actor_email,
        before={"status": before_status, "roles": before_roles},
        after={
            "status": "suspended",
            "roles": [],
            "sessions_ended": ended,
            "browsers_forgotten": forgotten,
        },
        reason=reason.strip(),
    )
    return ended


def reactivate_staff(
    db: Session,
    user: UserAccount,
    *,
    actor_id: int | None,
    actor_email: str | None,
) -> UserAccount:
    """Reverse a suspension. No reason required - a suspension is the act that
    needs explaining; undoing one needs only doing.

    **No access comes back with it** (ADR 0067, decision 6). Suspending took
    every role; the person can sign in again and reaches nothing until each
    role is given again, deliberately, with *Add access*."""
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
    """Withdraw an invitation nobody has used yet - or, once it has lapsed,
    take it off the list.

    A lapsed link is already closed, so the second case changes nothing about
    who can get in; it records that somebody looked at it and meant *nobody is
    invited*, which is what removes the address from the pending list.

    No separate "revoked" state on the row. `accept_invitation` already
    refuses anything past `expires_at`, so backdating it to now closes the
    link through the **same** check accepting uses, rather than a second one
    that could disagree with the first.
    """
    if invitation.accepted_at is not None:
        raise ValueError("This invitation has already been used")
    if invitation.withdrawn_at is not None:
        raise ValueError("This invitation has already been withdrawn")

    now = utcnow()
    lapsed = invitation.expires_at <= now
    if not lapsed:
        invitation.expires_at = now
    # Recorded as well as expired, so a link somebody cancelled can be told
    # from one nobody opened in time. Only one of those is worth resending.
    invitation.withdrawn_at = now

    record_audit(
        db,
        action="invitation.revoked",
        subject=f"invitation:{invitation.email}",
        actor_id=actor_id,
        actor_email=actor_email,
        after={"email": invitation.email, "role": invitation.role, "lapsed": lapsed},
    )
    return invitation
