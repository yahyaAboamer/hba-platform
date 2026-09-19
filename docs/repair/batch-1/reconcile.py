"""Batch 1's reconciliation dry run. Reads; never writes.

ADR 0040 changed which orders a month pays for. Every month agreed before it
was agreed under the old rule, and this reports what that means for the data
actually in a database — before anybody ships the change to it.

It answers four questions:

1. **How many agreed months are legacy?** Those carry no `policy` in their
   snapshot payload, and are recalculated under the delivered-only rule for
   the rest of their lives.
2. **What is in the carry backlog?** Orders a delivered-only approval left
   out, now delivered, not yet settled by any later payroll. These are real
   sales still owed, and they are what the next payroll will pay. The set can
   only shrink.
3. **Is anything at risk of being paid twice?** An order settled by one
   month's snapshot while its own month's snapshot also counted it. There
   should be none; if there are, they are named.
4. **Which agreed months would now show a correction?** Compared under each
   month's own recorded policy, so the policy change itself is never reported
   as a difference.

Run it against a disposable copy of the data you care about:

    DATABASE_URL='postgresql+psycopg://…' .venv/Scripts/python.exe \\
        docs/repair/batch-1/reconcile.py

**The transaction is read-only, enforced by the database.** It issues `SET
TRANSACTION READ ONLY` before it reads anything, so a write attempted from
here — by this script or by anything it calls — is refused by PostgreSQL
rather than by good intentions. It also imports no pytest fixture, so it
cannot truncate anything.

Even so, prefer a restored copy over a live database: this is a report, and a
report is worth nothing that a restore cannot repeat.
"""

import json
import os
import sys

from sqlalchemy import select, text

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..")))

from app.db import SessionLocal  # noqa: E402
from app.models.affiliates import AffiliateProfile  # noqa: E402
from app.models.attributed_orders import AttributedOrder  # noqa: E402
from app.models.payroll import CalculationState, PayrollMonth  # noqa: E402
from app.services.corrections import correction_for  # noqa: E402
from app.services.payroll import (  # noqa: E402
    PENDING_INCLUSIVE,
    counted_in_snapshot,
    policy_of,
)


def report(db) -> dict:
    approved = [
        row
        for row in db.scalars(
            select(PayrollMonth).where(
                PayrollMonth.calculation_state == CalculationState.APPROVED
            )
        )
        if row.active_snapshot is not None
    ]
    legacy = [row for row in approved if policy_of(row.active_snapshot) != PENDING_INCLUSIVE]
    by_id = {row.id: row for row in approved}

    backlog = []
    paid_twice = []
    for order in db.scalars(select(AttributedOrder)):
        own = next(
            (
                row
                for row in approved
                if row.affiliate_id == order.affiliate_id
                and row.month == order.business_month
            ),
            None,
        )
        if own is None:
            continue
        counted = counted_in_snapshot(own.active_snapshot, order.shopify_order_id)
        settled = order.settled_in_snapshot_id

        if not counted and settled is None and order.counts_toward_payout:
            backlog.append(
                {
                    "shopify_order_id": order.shopify_order_id,
                    "affiliate_id": order.affiliate_id,
                    "business_month": order.business_month,
                    "base_piastres": order.commission_base_piastres,
                }
            )
        if counted and settled is not None:
            elsewhere = next(
                (
                    month
                    for month in by_id.values()
                    if month.active_snapshot is not None
                    and month.active_snapshot.id == settled
                    and month.month != order.business_month
                ),
                None,
            )
            if elsewhere is not None:
                paid_twice.append(
                    {
                        "shopify_order_id": order.shopify_order_id,
                        "counted_in": order.business_month,
                        "also_settled_in": elsewhere.month,
                        "base_piastres": order.commission_base_piastres,
                    }
                )

    differences = []
    for month in approved:
        affiliate = db.get(AffiliateProfile, month.affiliate_id)
        if affiliate is None:
            continue
        found = correction_for(db, affiliate, month.month)
        if found is None or found.outstanding_piastres <= 0:
            continue
        differences.append(
            {
                "affiliate_id": affiliate.id,
                "name": affiliate.name,
                "month": month.month,
                "policy": policy_of(month.active_snapshot),
                "agreed_piastres": found.agreed_piastres,
                "now_piastres": found.now_piastres,
                "outstanding_piastres": found.outstanding_piastres,
                "recoverable_piastres": found.recoverable_piastres,
                "review_reason": found.review_reason,
            }
        )

    return {
        "approved_months": len(approved),
        "agreed_under_the_old_rule": len(legacy),
        "agreed_under_the_new_rule": len(approved) - len(legacy),
        "carry_backlog": {
            "orders": len(backlog),
            "sales_piastres": sum(row["base_piastres"] for row in backlog),
            "detail": backlog,
        },
        # Expected to be empty. It is reported rather than asserted because a
        # dry run that hides a surprise is worse than no dry run.
        "counted_and_settled_elsewhere": paid_twice,
        "months_with_an_open_difference": differences,
    }


if __name__ == "__main__":
    db = SessionLocal()
    try:
        # Enforced by the database, not by this file's good intentions: any
        # write from here on is refused with `read-only transaction`. It is
        # what makes the promise at the top of this file checkable.
        db.execute(text("SET TRANSACTION READ ONLY"))
        print(json.dumps(report(db), indent=2))
    finally:
        db.rollback()
        db.close()
