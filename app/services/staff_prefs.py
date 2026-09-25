"""Settings → Appearance's two switches, per staff account.

The approved export draws them (Admin lines 749-757, `prefRows` 3600-3611):
*Show pop-up notices on Home* and *Weekly reminder to record achieved
content*, both on by default. Each person's own: turning one off changes what
that account sees or receives, nobody else's.

**Absence means on**, as the export's defaults. A row exists only once
somebody has changed a switch.

What each one does:

* ``home_notices`` - whether Home opens with its notice cards. Off, Home says
  how many are hidden and offers to show them (the export's own *hidden* line),
  so nothing reached only through a notice - a correction, say - becomes
  unreachable.
* ``weekly_targets_reminder`` - a weekly email, to staff who may record
  achieved content, saying how many models have nothing recorded for the
  month yet, with the way to Targets.
"""

from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.businesstime import business_month, utcnow
from app.core.permissions import Permission, has_permission
from app.models.affiliates import AccountKind, AffiliateProfile, AffiliateStatus
from app.models.identity import RoleAssignment, StaffPreference, UserAccount
from app.models.targets import MonthlyTarget
from app.services.audit import record_audit
from app.services.jobs import JobKind
from app.worker import register_handler

#: key -> the words on the switch. The keys are the table's check constraint.
SWITCHES = {
    "home_notices": "Show pop-up notices on Home",
    "weekly_targets_reminder": "Weekly reminder to record achieved content",
}

#: Roughly weekly: the gap after the last run finished (app.services.schedule).
REMINDER_INTERVAL = timedelta(days=7)


def preferences_for(db: Session, account_id: int) -> dict[str, bool]:
    """Every switch for this account, off only where it was turned off."""
    stored = dict(
        db.execute(
            select(StaffPreference.key, StaffPreference.enabled).where(
                StaffPreference.user_account_id == account_id
            )
        ).all()
    )
    return {key: bool(stored.get(key, True)) for key in SWITCHES}


def set_preference(
    db: Session, account: UserAccount, key: str, enabled: bool
) -> dict[str, bool]:
    """Change one switch for this account. Leaves the transaction to the caller."""
    if key not in SWITCHES:
        raise ValueError(f"There is no switch called {key!r}.")
    row = db.scalar(
        select(StaffPreference).where(
            StaffPreference.user_account_id == account.id, StaffPreference.key == key
        )
    )
    before = row.enabled if row is not None else True
    if row is None:
        row = StaffPreference(user_account_id=account.id, key=key, enabled=enabled)
        db.add(row)
    else:
        row.enabled = enabled
        row.updated_at = utcnow()
    db.flush()
    if before != enabled:
        record_audit(
            db,
            action="staff.preference_changed",
            subject=f"user:{account.id}",
            actor_id=account.id,
            actor_email=account.email,
            before={"switch": SWITCHES[key], "on": before},
            after={"switch": SWITCHES[key], "on": enabled},
        )
    return preferences_for(db, account.id)


def reminder_recipients(db: Session) -> list[UserAccount]:
    """Active staff who may record achieved content and have not turned it off."""
    rows = db.execute(
        select(UserAccount, RoleAssignment.role)
        .join(RoleAssignment, RoleAssignment.user_account_id == UserAccount.id)
        .where(UserAccount.status == "active", RoleAssignment.revoked_at.is_(None))
        .order_by(UserAccount.id, RoleAssignment.id.desc())
    ).all()
    seen: set[int] = set()
    recipients = []
    for account, role in rows:
        if account.id in seen:
            continue  # the newest live assignment is the role, as `active_role`
        seen.add(account.id)
        if not has_permission(role, Permission.TARGETS_RECORD):
            continue
        if preferences_for(db, account.id)["weekly_targets_reminder"]:
            recipients.append(account)
    return recipients


def unrecorded_count(db: Session, month: str) -> tuple[int, int]:
    """(models with nothing recorded for the month, active models)."""
    models = db.scalars(
        select(AffiliateProfile.id).where(
            AffiliateProfile.status == AffiliateStatus.ACTIVE,
            AffiliateProfile.account_kind != AccountKind.HOUSE,
        )
    ).all()
    recorded = set(
        db.scalars(
            select(MonthlyTarget.affiliate_id).where(
                MonthlyTarget.month == month,
                MonthlyTarget.actual_videos.is_not(None),
            )
        )
    )
    return sum(1 for model in models if model not in recorded), len(models)


def send_weekly_reminders(db: Session) -> int:
    """Queue this week's reminder to everyone who wants it. Returns how many."""
    from app.services import notifications

    month = business_month(utcnow())
    missing, total = unrecorded_count(db, month)
    sent = 0
    for account in reminder_recipients(db):
        if notifications.targets_reminder(db, account, month, missing, total):
            sent += 1
    return sent


@register_handler(JobKind.TARGETS_REMINDER)
def _handle_targets_reminder(db: Session, payload: dict) -> None:
    send_weekly_reminders(db)
