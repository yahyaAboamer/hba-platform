"""One gate in front of every write that decides what a month pays. F3.

## The problem this solves, which is not the one `_lock_month` solved

Batch 1's follow-up review found that `corrections.resolve` locked the months
it was about and `payroll.approve_month` did not. Approval read the
calculation, the carried orders, the incoming deductions and the fingerprint,
and only then began writing. A carry committed in that window slipped past the
freshness check it was supposed to fail, and the snapshot froze a deduction
list that was already out of date by the time it was written.

The obvious repair — give approval the same row locks — introduces a worse
bug. `resolve` takes the **source** month then the **destination**. Approval
takes the month it is approving, which *is* a destination, and then reaches
back to the earlier months its releases return money to. Two writers taking
the same two rows in opposite orders is the textbook deadlock, and it would
have appeared at month end, under load, on the one operation nobody can safely
retry blind.

## So the gate is the model, not the month

Every writer takes one lock first: the affiliate's own row. There is only one
lock, so there is no order to get wrong and no deadlock to introduce — which
is the whole argument for it over a carefully documented month ordering that
the next person to add a writer has to find and obey.

The month-row locks stay where they are, inside this one. They cost nothing
now and they keep working if some future path forgets the gate.

**Parallelism is not lost where it matters.** Month end runs one model after
another, and two models' payrolls never touch the same rows, so they never
contend. What serialises is exactly what should: two decisions about *one*
model's money.

## Re-reading is part of taking the lock

A session that waited on this gate waited because somebody else was writing.
Its identity map still holds what it loaded before the wait — snapshots,
adjustments, months — and a check run against that reads the world as it was
before the write it just queued behind. `expire_all` is what makes the lock
mean *look again*, and it is here rather than left to each caller for the same
reason the lock is: one place to be right.
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.affiliates import AffiliateProfile


def hold_money_gate(db: Session, affiliate: AffiliateProfile) -> None:
    """Serialise this model's money writes, and re-read after the wait.

    Held until the transaction ends. Call it **before** reading anything a
    decision will be made on: the point is not to protect the write, which the
    database would serialise anyway, but to make the reads that justify the
    write happen after everybody else's writes have landed.
    """
    # Before the expiry below, and not merely for tidiness: `expire_all`
    # **discards changes that have not been flushed**. A caller that set
    # something on a loaded row and had not yet written it would silently lose
    # it here. Autoflush would do this anyway on the statement below; doing it
    # explicitly means the guarantee does not depend on a session setting.
    db.flush()
    db.execute(
        select(AffiliateProfile.id)
        .where(AffiliateProfile.id == affiliate.id)
        .with_for_update()
    ).first()
    # Everything loaded before the wait is now suspect. See the module
    # docstring: without this the lock delays a stale decision instead of
    # preventing one.
    db.expire_all()
