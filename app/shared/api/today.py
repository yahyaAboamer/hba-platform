"""``GET /api/today``: what waits for this person, everywhere they work
(Phase 2, batch 2.2).

Any member of staff may read it; a model may not. It carries each held
department's items, the sidebar's numbers from the same reads, and - for
somebody holding both the Inbox and Operations - the week's orders.

**Departments are reached only through their ``public``** (the import check
in ``pyproject.toml``), and every number there is the one the department's own
screen shows, so Today and the screen it opens never disagree.

One department that cannot be read leaves the rest in place: it is logged,
its items and numbers are left out (never a made-up 0), and it is named in
``unread`` so the page can say so.
"""

import logging
from collections.abc import Callable
from datetime import datetime

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.businesstime import utcnow
from app.core.permissions import Permission
from app.db import get_session
from app.modules.affiliates import public as affiliates
from app.modules.inbox import public as inbox
from app.modules.operations import public as operations
from app.shared.api.deps import permissions_of, require_staff
from app.shared.models.identity import UserAccount
from app.shared.services import order_week
from app.shared.services.today import Item, Look

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/today", tags=["today"])

#: Each department, the permission that makes somebody hold it, and how its
#: part of Today is read - in the order the page lists them.
DEPARTMENTS: tuple[tuple[str, str, Callable[[Session, frozenset[str], datetime], Look]], ...] = (
    ("inbox", Permission.INBOX_USE, inbox.today_look),
    ("operations", Permission.ORDER_OPS_VIEW, operations.today_look),
    ("affiliates", Permission.AFFILIATES_VIEW, affiliates.today_look),
)

_ORDER = {name: index for index, (name, _, _) in enumerate(DEPARTMENTS)}


def _sort_key(item: Item) -> tuple:
    """Broken first; then the longest waiting; items with no time last, in
    department order."""
    return (
        not item.broken,
        item.since is None,
        item.since.timestamp() if item.since else 0.0,
        _ORDER.get(item.department, len(_ORDER)),
    )


def _read(db: Session, name: str, reader, permissions, now) -> Look | None:
    """One department's part, or None when it could not be read.

    Inside a savepoint, so a failed query leaves the session usable for the
    departments after it.
    """
    try:
        with db.begin_nested():
            return reader(db, permissions, now)
    except Exception:
        logger.exception("today: %s could not be read", name)
        return None


def today_body(db: Session, user: UserAccount, now: datetime) -> dict:
    permissions = permissions_of(db, user)
    held = [name for name, permission, _ in DEPARTMENTS if permission in permissions]

    items: list[Item] = []
    counts: dict[str, int] = {}
    failures: dict[str, str | None] = {}
    unread: list[str] = []
    for name, permission, reader in DEPARTMENTS:
        if permission not in permissions:
            continue
        found = _read(db, name, reader, permissions, now)
        if found is None:
            unread.append(name)
            continue
        items.extend(found.items)
        counts.update(found.counts)
        failures.update(found.failures)

    # Stable, so items equal on all of these keep their department's order.
    items.sort(key=_sort_key)

    orders = None
    if "inbox" in held and "operations" in held:
        try:
            with db.begin_nested():
                orders = order_week.week(db, now)
        except Exception:
            # The panel is left out (null), as when it is not this person's.
            logger.exception("today: the order week could not be read")

    return {
        "now": now.isoformat(),
        "departments": held,
        "items": [item.body() for item in items],
        "counts": counts,
        "failures": failures,
        "orders": orders,
        "unread": unread,
    }


@router.get("")
def today(
    user: UserAccount = Depends(require_staff),
    db: Session = Depends(get_session),
) -> dict:
    """What waits for the signed-in member of staff."""
    return today_body(db, user, utcnow())
