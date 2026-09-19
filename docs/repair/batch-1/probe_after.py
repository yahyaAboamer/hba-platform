"""Batch 1 evidence: the audit's four probes, asserting the repaired behaviour.

`HBA_Readiness_Audit/probe_financial_contracts.py` reproduces the defects A01,
A03, A04 and A05 by asserting what the platform did wrong. This is the same
four scenarios, same mocking, same figures — asserting what it must do
instead. The audit is explicit that its probes "demonstrate failures, not the
desired regression-test expectations", so the two files are kept side by side:
one says what was broken, this one says what was built.

It is not a substitute for the database tests. `tests/test_financial_transition.py`
and `tests/test_corrections.py` exercise these paths against real rows with
real triggers; this exists because it is directly comparable with the evidence
the audit supplied, line for line.

Run from the repository root with its own environment:

    .venv/Scripts/python.exe docs/repair/batch-1/probe_after.py

No database connection, schema operation, application write or pytest fixture
is used.
"""

import json
from decimal import Decimal
from types import SimpleNamespace as NS
from unittest.mock import MagicMock, patch

from app.models.affiliates import AccountKind
from app.models.attributed_orders import CommissionState
from app.models.compensation import CompensationType
from app.services import corrections
from app.services.commission import calculate as calc
from app.services.commission.source import SourceOrder

results = {}
affiliate = NS(id=1, name="Audit fixture", account_kind=AccountKind.MODEL)
terms = NS(compensation_type=CompensationType.COMMISSION, commission_rate_bp=1000)
carried = dict(orders=0, base_piastres=0, exact=Decimal(0), lines=[], months_without_terms=[])
db = MagicMock()

# ── A01. The live calculation pays for a pending order ──────────────────────
db.scalars.return_value = [
    NS(commission_state=CommissionState.PENDING, commission_base_piastres=1_000_000)
]
with patch.object(calc, "get_target", return_value=None), \
        patch.object(calc, "terms_for", return_value=terms), \
        patch.object(calc, "carried_forward", return_value=carried):
    live = calc.calculate_month(db, affiliate, "2026-09")
    preview = calc.preview_calculation(
        db,
        affiliate,
        "2026-09",
        source_orders=[SourceOrder("audit", CommissionState.PENDING, 1_000_000, 1_000_000, None)],
    )
    # The rule a month was agreed under still governs its own recalculation,
    # so a closed delivered-only month does not silently become worth more.
    legacy = calc.calculate_month(db, affiliate, "2026-09", policy=calc.DELIVERED_ONLY)

results["pending_order"] = {
    "sales_egp": 10000,
    "rate": "10%",
    "live_payout_egp": live.payout_piastres / 100,
    "preview_payout_egp": preview.payout_piastres / 100,
    "required_payout_egp": 1000,
    "recalculated_under_a_delivered_only_agreement_egp": legacy.payout_piastres / 100,
}
assert live.payout_piastres == 100_000, "the live policy must pay for a pending order"
assert live.payout_piastres == preview.payout_piastres, "one rule, not two"
assert legacy.payout_piastres == 0, "a closed month is recalculated under its own rule"

# ── A03. A second failure is not hidden by the first resolution ─────────────
snapshot = NS(id=1, version=1, approved_obligation_piastres=200_000,
              payload_json={"source_version": "old"})
month = NS(id=1, active_snapshot=snapshot, is_approved=True)
db.scalars.return_value = []
# One earlier credit of EGP 100 against this source month.
db.execute.return_value.all.return_value = [("credit", 10_000)]
with patch.object(corrections, "is_historical", return_value=False), \
        patch.object(corrections, "get_month", return_value=month), \
        patch.object(corrections, "calculate_month", return_value=NS(payout_piastres=170_000)), \
        patch.object(corrections, "source_version", return_value="changed-again"), \
        patch.object(corrections, "carried_into", return_value=[]), \
        patch("app.services.payments.allocated_to", return_value=200_000), \
        patch("app.services.portal.months_for", return_value=["2026-09"]):
    correction = corrections.correction_for(db, affiliate, "2026-09")
    open_rows = corrections.open_corrections(db, affiliate)

results["second_failure_after_resolution"] = {
    "approved_egp": 2000,
    "revised_egp": 1700,
    "already_resolved_egp": correction.resolved_piastres / 100,
    "cumulative_shortfall_egp": correction.shortfall_piastres / 100,
    "still_outstanding_egp": correction.outstanding_piastres / 100,
    "marked_resolved": correction.resolved,
    "open_correction_count": len(open_rows),
    "note": "The cumulative difference is compared with what has already been "
            "carried or absorbed, so only the new EGP 200 is offered again.",
}
assert correction.shortfall_piastres == 30_000
assert correction.resolved_piastres == 10_000
assert correction.outstanding_piastres == 20_000
assert not correction.resolved and len(open_rows) == 1

# ── A05. A failure before the transfer is reviewed, not hidden ──────────────
db.execute.return_value.all.return_value = []
with patch.object(corrections, "is_historical", return_value=False), \
        patch.object(corrections, "get_month", return_value=month), \
        patch.object(corrections, "calculate_month", return_value=NS(payout_piastres=180_000)), \
        patch.object(corrections, "source_version", return_value="changed"), \
        patch.object(corrections, "carried_into", return_value=[]), \
        patch("app.services.payments.allocated_to", return_value=0), \
        patch("app.services.portal.months_for", return_value=["2026-09"]):
    correction = corrections.correction_for(db, affiliate, "2026-09")
    open_rows = corrections.open_corrections(db, affiliate)

results["failure_after_approval_before_payment"] = {
    "difference_egp": correction.difference_piastres / 100,
    "paid_egp": 0,
    "recoverable_egp": correction.recoverable_piastres / 100,
    "needs_review": correction.needs_review,
    "review_reason": correction.review_reason,
    "open_correction_count": len(open_rows),
    "note": "No recoverable debt is invented for money that never moved, and "
            "the change is no longer hidden by the fact that it did not.",
}
assert correction.difference_piastres == -20_000
assert correction.recoverable_piastres == 0
assert correction.needs_review and len(open_rows) == 1

# ── A04. Insufficient earnings apply what fits and carry the rest ───────────
partial = NS(
    outcome=corrections.OVERPAID,
    resolution=None,
    resolved=False,
    outstanding_piastres=20_000,
    recoverable_piastres=20_000,
)
with patch.object(corrections, "correction_for", return_value=partial), \
        patch.object(corrections, "capacity_of", return_value=10_000), \
        patch("app.services.payments.adjust") as adjust:
    corrections.resolve(
        db,
        affiliate,
        "2026-09",
        choice="credit",
        reason="audit fixture",
        destination_month="2026-10",
    )

applied = adjust.call_args.kwargs["amount_piastres"]
results["insufficient_earnings"] = {
    "deduction_egp": 200,
    "available_egp": 100,
    "applied_egp": applied / 100,
    "retained_for_a_later_month_egp": (partial.outstanding_piastres - applied) / 100,
    "zero_value_transfer_recorded": False,
    "note": "The remainder stays against the source month and is offered "
            "again for any later month, this year or another.",
}
assert applied == 10_000, "apply what the destination has room for"

print(json.dumps(results, indent=2))
