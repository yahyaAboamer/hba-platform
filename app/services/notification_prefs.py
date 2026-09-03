"""Which of the two messages a model wants.

**Absence means on.** There is no row until somebody turns something off, so a
model who has never opened their settings hears about their month closing and
about being paid - the two messages this platform exists to send. The
alternative, seeding a row per model at sign-up, silently mutes anybody the
seeding misses.

**Only two things are gateable, and neither is optional in the other
direction.** A model cannot turn off an invitation, a password reset, or the
notice that somebody moved where their money goes: those are not news, they
are security. What can be turned off is the two routine messages about money
arriving, because a model who checks the portal daily does not need them and
the ones who do need them are the reason this exists.
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.affiliates import AffiliateProfile
from app.models.notifications import (
    VALID_KINDS,
    NotificationKind,
    NotificationPreference,
)

#: Which event each switch controls. An event absent from this map is not
#: gateable and always sends - see the module docstring.
GATED_BY = {
    # `Event` values, which are dotted. Not imported from `notifications`,
    # which imports this module - a real cycle, not a style choice. The test
    # in `test_notifications.py` asserts these match the `Event` members, so
    # the two cannot drift.
    "month.approved": NotificationKind.MONTH_CLOSED,
    "payment.recorded": NotificationKind.PAYMENT_SENT,
}

#: What each switch says on the screen. Here rather than in the frontend so
#: the label and the thing it controls cannot drift apart.
LABEL = {
    NotificationKind.MONTH_CLOSED: "A month closes and my figure is final",
    NotificationKind.PAYMENT_SENT: "A payment is sent",
}


def wants(db: Session, affiliate: AffiliateProfile, kind: str) -> bool:
    """Whether this affiliate wants this kind of message.

    `True` when there is no row, which is the whole design: silence in the
    table means *nobody has asked to be left alone*.
    """
    row = db.scalar(
        select(NotificationPreference)
        .where(NotificationPreference.affiliate_id == affiliate.id)
        .where(NotificationPreference.kind == kind)
    )
    return True if row is None else bool(row.enabled)


def preferences_for(db: Session, affiliate: AffiliateProfile) -> list[dict]:
    """Both switches, with their labels, for their own screen."""
    rows = {
        row.kind: row.enabled
        for row in db.scalars(
            select(NotificationPreference).where(
                NotificationPreference.affiliate_id == affiliate.id
            )
        )
    }
    return [
        {"kind": kind, "label": LABEL[kind], "enabled": rows.get(kind, True)}
        for kind in (NotificationKind.MONTH_CLOSED, NotificationKind.PAYMENT_SENT)
    ]


def set_preference(
    db: Session, affiliate: AffiliateProfile, *, kind: str, enabled: bool
) -> None:
    """Turn one switch on or off. **Does not commit.**

    A row is written either way once somebody has touched the switch. Deleting
    it when they turn it back on would be tidier and would lose the fact that
    they made a choice - which is the thing worth keeping if anybody ever asks
    why they did or did not get an email.
    """
    if kind not in VALID_KINDS:
        raise ValueError(f"Not something we send: {kind}")

    row = db.scalar(
        select(NotificationPreference)
        .where(NotificationPreference.affiliate_id == affiliate.id)
        .where(NotificationPreference.kind == kind)
    )
    if row is None:
        row = NotificationPreference(affiliate_id=affiliate.id, kind=kind)
        db.add(row)
    row.enabled = enabled
