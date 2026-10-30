"""What Affiliates says is waiting, for Today (Phase 2, batch 2.2).

Only for somebody holding ``affiliates.view``, and each item only for whoever
acts on it. Every number is the screen's own:

- applications: the Models screen's *Applications* segment
  (``applications.waiting_applications``, also the sidebar's badge);
- targets not set: the Targets grid's roster (``targets.targets_not_set``);
- payments: the Payments screen's *Awaiting approval*, on the month that screen
  opens on (``payments.awaiting_approval`` on ``working_month()``).
"""

from datetime import date, datetime, timedelta

from sqlalchemy.orm import Session

from app.core.businesstime import at_words, business_date, business_month, month_add, month_name, month_words
from app.core.permissions import Permission
from app.modules.affiliates.services.applications import waiting_applications
from app.modules.affiliates.services.payments import awaiting_approval
from app.modules.affiliates.services.payroll import working_month
from app.modules.affiliates.services.targets import targets_not_set
from app.shared.models.identity import UserAccount
from app.shared.services.today import DEADLINE, ELAPSED, Item, Look

DEPARTMENT = "affiliates"

#: An application unanswered for longer than this is late.
APPLICATION_LATE_AFTER = timedelta(days=2)
#: Next month's targets are asked for from this day of the month (Cairo).
TARGETS_FROM_DAY = 24
#: ...and are late within this many days of the month starting.
TARGETS_LATE_WITHIN = 3

_WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")


def _applications(n: int, oldest: datetime | None, now: datetime) -> Item:
    return Item(
        key="affiliates.applications",
        department=DEPARTMENT,
        what="1 model application to review" if n == 1 else f"{n} model applications to review",
        detail=f"The oldest arrived {at_words(oldest, now)}" if oldest else "",
        go_label="Review",
        go_to="/affiliates/models?segment=applications",
        late=oldest is not None and now - oldest > APPLICATION_LATE_AFTER,
        since=oldest,
        when=ELAPSED if oldest else None,
    )


def _targets(db: Session, now: datetime) -> Item | None:
    today = business_date(now)
    if today.day < TARGETS_FROM_DAY:
        return None
    month = month_add(business_month(now), 1)
    missing, models = targets_not_set(db, month)
    if not missing:
        return None
    starts = date(int(month[:4]), int(month[5:]), 1)
    name = month_name(month)
    what = (
        f"{name} targets are not set"
        if missing == models
        else f"{name} targets are not set for {missing} model{'' if missing == 1 else 's'}"
    )
    return Item(
        key="affiliates.targets_not_set",
        department=DEPARTMENT,
        what=what,
        # The Targets list's open rows, which include models not yet approved:
        # not "active", which means something narrower elsewhere.
        detail=f"{models} model{'' if models == 1 else 's'} on the Targets list; {name} starts {_WEEKDAYS[starts.weekday()]}",
        go_label="Set targets",
        go_to=f"/affiliates/targets?month={month}",
        late=(starts - today).days <= TARGETS_LATE_WITHIN,
        due=starts,
        when=DEADLINE,
    )


def _payments(n: int, month: str) -> Item:
    return Item(
        key="affiliates.payments_awaiting_approval",
        department=DEPARTMENT,
        what="1 payment waiting for approval" if n == 1 else f"{n} payments waiting for approval",
        detail=month_words(month),
        go_label="Review",
        go_to=f"/affiliates/payments?month={month}",
    )


def look(db: Session, permissions: frozenset[str], now: datetime) -> Look:
    """Affiliates' items, and the sidebar's two numbers."""
    found = Look()
    if Permission.AFFILIATES_VIEW not in permissions:
        return found

    applications, oldest = waiting_applications(db)
    found.counts["models_awaiting_approval"] = applications
    if applications and Permission.AFFILIATES_MANAGE in permissions:
        found.items.append(_applications(applications, oldest, now))

    if Permission.TARGETS_MANAGE in permissions:
        item = _targets(db, now)
        if item is not None:
            found.items.append(item)

    month = working_month()
    payments = awaiting_approval(db, month)
    found.counts["payments_awaiting_approval"] = payments
    if payments and Permission.PAYROLL_APPROVE in permissions:
        found.items.append(_payments(payments, month))
    return found


def waiting(db: Session, user: UserAccount, now: datetime) -> list[Item]:
    """What waits in Affiliates for this person; nothing if they do not hold it."""
    from app.shared.api.deps import permissions_of

    return look(db, permissions_of(db, user), now).items
