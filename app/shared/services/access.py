"""What roles a person holds now, read in one place.

ADR 0067: a person may hold several roles at once, and what they may do is
everything their live roles grant together. Every check - the route guards in
`app/api/deps.py`, the staff roster, the rule that managing models is not a
way into a staff account - reads a person's roles through here, so there is
one answer to "what does this person hold?" and not several that could drift.

Here rather than in `app/api/deps.py` so services can ask without importing
the API layer (which imports them).
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.shared.models.identity import RoleAssignment


def live_roles(db: Session, user_account_id: int) -> frozenset[str]:
    """Every role this account holds now. Revoked assignments are ignored.

    Empty for an account holding nothing, which grants no permission at all.
    """
    return frozenset(
        db.scalars(
            select(RoleAssignment.role).where(
                RoleAssignment.user_account_id == user_account_id,
                RoleAssignment.revoked_at.is_(None),
            )
        )
    )


def live_roles_by_account(db: Session, account_ids: list[int]) -> dict[int, frozenset[str]]:
    """`live_roles` for many accounts in one query, for lists."""
    if not account_ids:
        return {}
    found: dict[int, set[str]] = {account_id: set() for account_id in account_ids}
    rows = db.execute(
        select(RoleAssignment.user_account_id, RoleAssignment.role).where(
            RoleAssignment.user_account_id.in_(account_ids),
            RoleAssignment.revoked_at.is_(None),
        )
    )
    for account_id, role in rows:
        found[account_id].add(role)
    return {account_id: frozenset(roles) for account_id, roles in found.items()}
