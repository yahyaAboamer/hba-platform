"""Reviewing and finalising the months that happened before the platform. A09.

ADR 0036 made a pre-go-live month an ordinary month: calculated, approved and
frozen like any other, and **never payable** - the transfer happened outside
the platform and `balance_for` returns zero for it by construction, before the
snapshot is even loaded.

What was missing was a way to *do* that for everybody at once. The approved
export has the entry - a **Review months from January 2026** button in
Settings, and a result line reading:

    Months from January 2026 recalculated from Shopify using each model's
    historical terms. No receipts were created; months without an imported
    transfer stay marked as having none.

Every clause of that sentence is a constraint, and this module is written to
obey them rather than to reproduce the words.

## What it may do

Approve a historical month that **can** be calculated: her terms cover it, and
where the arrangement is a guaranteed minimum the outcome is recorded. That is
the whole of finalisation. The figure comes from the ordinary engine reading
her recorded terms and her attributed orders - the same engine every other
month goes through, which is what stops this becoming a second answer.

## What it may never do

**Invent a value.** A month missing terms, or a guarantee missing its outcome,
is *reported* and skipped. There is no default rate, no assumed outcome and no
"nearest" arrangement - F06 is explicit that unknown qualifying information
blocks a decision rather than reading as a failure, and H02 that fabricating
evidence for a figure that decides money is the one thing never to do.

**Create a payment, a receipt or an opening debt.** Nothing here writes to the
ledger. A historical month with no imported transfer keeps having none, which
is what the approved result line promises in as many words.

**Touch a live month.** The cut is `is_historical`, so anything from go-live
onwards is outside this entirely and is approved the way it always was, by
somebody looking at it.

**Change a month already agreed.** An approved month is skipped, which is also
what makes running this twice harmless.

## Why it is safe to run again

Every step is *approve this month if it is not approved and can be
calculated*. Running it a second time finds them approved and does nothing, so
a half-finished run - a timeout, a browser closed, a deploy - is finished by
running it again rather than by working out where it stopped. 05B does the
rest: an agreed month is never unmade, so nothing here can quietly restate one.
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.businesstime import month_add
from app.models.affiliates import AffiliateProfile
from app.models.targets import MonthlyTarget
from app.services.affiliates import list_affiliates
from app.services.compensation import all_terms
from app.services.payroll import (
    approve_month,
    get_month,
    is_historical,
    working_month,
)

#: Why a historical month cannot be finalised. The same vocabulary
#: `setup_readiness` uses, because it is the same question asked of the same
#: rows - see `month_gaps`, which both call.
from app.services.setup import (
    NO_TARGET_OUTCOME,
    NO_TERMS,
    TARGET_NOT_VERIFIED,
    eligible_months,
    month_gaps,
)

__all__ = [
    "NO_TARGET_OUTCOME",
    "NO_TERMS",
    "TARGET_NOT_VERIFIED",
    "FinalisationLocked",
    "finalise_historical",
    "historical_review",
]


class FinalisationLocked(RuntimeError):
    """The act is refused until the history itself has been checked. A09.

    Two things have to be true before finalising is safe, and neither is
    something the software can establish about itself:

    1. The recorded collaboration starts, terms and guarantee outcomes match
       what HBA actually agreed with each model.
    2. The order import for those months is complete.

    Approving on top of a partial import freezes a figure that is simply
    wrong, and 05B means an agreed month is never unmade - so the mistake
    would be permanent and would have to be corrected rather than fixed.

    The **review** is not gated: finding out what is missing is how the first
    of those gets done, and a check that required permission to perform would
    be a check nobody performs.
    """


def _historical_months(
    db: Session, affiliate: AffiliateProfile, working: str
) -> list[str]:
    """Her eligible months that are **before go-live**, oldest first."""
    return [m for m in eligible_months(db, affiliate, working) if is_historical(m)]


def _terms_by_month(db: Session, affiliate: AffiliateProfile, working: str) -> dict:
    covers: dict[str, object] = {}
    for period in all_terms(db, affiliate):
        cursor = period.start_month
        while cursor <= (period.end_month or working):
            covers[cursor] = period
            cursor = month_add(cursor, 1)
    return covers


def _targets_by_month(db: Session, affiliate: AffiliateProfile) -> dict:
    return {
        row.month: row
        for row in db.scalars(
            select(MonthlyTarget).where(MonthlyTarget.affiliate_id == affiliate.id)
        )
    }


def historical_review(db: Session, *, working: str | None = None) -> dict:
    """What finalising would do, without doing any of it.

    A dry run, and the only thing the screen calls before somebody presses the
    button. It answers the two questions that are actually different:

    - **What can the software finish on its own?** Months with everything they
      need, waiting to be approved.
    - **What is waiting on a person?** Months missing terms or a guarantee
      outcome, named per model and per month, because that is information only
      HBA holds and no amount of code will produce it.

    Reads only.
    """
    working = working or working_month()
    models = [a for a in list_affiliates(db) if a.is_payable]

    ready: list[dict] = []
    blocked: list[dict] = []
    finalised: list[dict] = []

    for affiliate in models:
        months = _historical_months(db, affiliate, working)
        if not months:
            continue
        covers = _terms_by_month(db, affiliate, working)
        targets = _targets_by_month(db, affiliate)
        for month in months:
            row = get_month(db, affiliate, month)
            entry = {
                "affiliate_id": affiliate.id,
                "name": affiliate.name,
                "month": month,
            }
            if row is not None and row.is_approved:
                finalised.append(entry)
                continue
            gaps = month_gaps(covers.get(month), targets.get(month), historical=True)
            if gaps:
                blocked.append({**entry, "missing": gaps})
            else:
                ready.append(entry)

    everything = ready + blocked + finalised
    return {
        "working_month": working,
        #: The earliest month anything here could touch. `None` when no model
        #: has a historical month at all, which is the ordinary state once the
        #: programme has been running a while.
        "from_month": min((row["month"] for row in everything), default=None),
        "ready": ready,
        "blocked": blocked,
        "already_finalised": finalised,
        "totals": {
            "models": len({row["affiliate_id"] for row in ready + blocked}),
            "ready": len(ready),
            "blocked": len(blocked),
            "already_finalised": len(finalised),
        },
    }


def finalise_historical(
    db: Session,
    *,
    working: str | None = None,
    actor_id: int | None = None,
    actor_email: str | None = None,
) -> dict:
    """Approve every historical month that can be calculated. A09.

    Idempotent: a month already approved is skipped, so running this again
    after an interruption finishes it rather than repeating it.

    Returns what it did and what it left, in the same shape as the dry run, so
    the screen can show the result without asking a second question.

    **Nothing is invented and nothing is paid.** A month missing terms or an
    outcome comes back in `blocked` exactly as the review reported it, and no
    ledger row is written here at all.
    """
    from app.config import settings

    if not settings.historical_finalisation_unlocked:
        raise FinalisationLocked(
            "Historical finalisation is locked. Verify each model's recorded "
            "start, terms and guarantee outcomes against what HBA agreed, and "
            "confirm the order import for those months is complete, then set "
            "HISTORICAL_FINALISATION_UNLOCKED on the environment being "
            "finalised. The review below is open and needs no unlock."
        )

    working = working or working_month()
    plan = historical_review(db, working=working)

    approved: list[dict] = []
    refused: list[dict] = []
    for row in plan["ready"]:
        affiliate = db.get(AffiliateProfile, row["affiliate_id"])
        if affiliate is None:  # pragma: no cover - a model removed mid-run
            continue
        try:
            snapshot = approve_month(
                db,
                affiliate,
                row["month"],
                actor_id=actor_id,
                actor_email=actor_email,
            )
        except ValueError as refusal:
            # A blocker the readiness rule does not model - a house account, a
            # month with no go-live configured, an order held for multi-code
            # review. Reported rather than raised: one model's problem must not
            # stop the other twenty, which is the same reasoning `approve_month`
            # already applies to a version clash on a run of twenty.
            refused.append({**row, "reason": str(refusal)})
            continue
        approved.append(
            {**row, "obligation_piastres": snapshot.approved_obligation_piastres}
        )

    return {
        "working_month": working,
        "from_month": plan["from_month"],
        "approved": approved,
        "refused": refused,
        "blocked": plan["blocked"],
        "already_finalised": plan["already_finalised"],
        "totals": {
            "approved": len(approved),
            "refused": len(refused),
            "blocked": len(plan["blocked"]),
            "already_finalised": len(plan["already_finalised"]),
        },
    }
