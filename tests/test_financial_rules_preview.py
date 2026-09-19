"""05A: real PostgreSQL source facts, shared arithmetic and legacy evidence."""

import json
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import func, select

from app.config import settings
from app.core.passwords import hash_password
from app.models.attributed_orders import AttributedOrder
from app.models.identity import UserAccount
from app.models.orders import OrderIndex
from app.models.payroll import PayrollSnapshot
from app.services.affiliates import create_affiliate
from app.services.codes import register_code
from app.services.commission.attribute import attribute_order
from app.services.commission.calculate import calculate_month
from app.services.commission.preview import preview_month
from app.services.commission.source import source_order
from app.services.compensation import set_terms
from app.services.payroll import approve_month, content_hash
from app.services.payments import record_payment
from app.services.targets import record_actuals, set_requirements, verify
from tests.support_policy import approved_before_the_switch

MONTH = "2026-04"
EXAMPLES = {
    row["id"]: row for row in json.loads((
        Path(__file__).resolve().parents[1] / "docs/redesign/evidence/financial-examples.json"
    ).read_text(encoding="utf-8"))["examples"]
}


@pytest.fixture
def model(db, monkeypatch):
    monkeypatch.setattr(settings, "go_live_month", "2026-01")
    account = UserAccount(email="preview@example.com", password_hash=hash_password("quiet-harbour-lantern"),
                          status="active", display_name="Preview Model")
    db.add(account)
    db.flush()
    affiliate = create_affiliate(db, user_account_id=account.id, name="Preview Model", account_kind="model")
    register_code(db, affiliate, "PREVIEW10", "2026-01")
    set_terms(db, affiliate, start_month="2026-01", compensation_type="commission",
              commission_rate_bp=1000)
    return affiliate


def _order(db, order_id="1", **extra):
    values = dict(shopify_order_id=order_id, order_number=f"#{order_id}",
                  placed_at=datetime(2026, 4, 15, tzinfo=timezone.utc), business_month=MONTH,
                  discount_codes=["PREVIEW10"], subtotal_piastres=106_200,
                  total_piastres=115_700, shipping_piastres=9_500, tax_piastres=0,
                  currency="EGP", delivery_state="delivered",
                  delivered_at=datetime(2026, 4, 20, tzinfo=timezone.utc))
    values.update(extra)
    row = OrderIndex(**values)
    db.add(row)
    db.flush()
    return row


def pending(db, order_id="pending", **extra):
    index = _order(db, order_id=order_id, delivery_state="in_flight", delivered_at=None, **extra)
    attribute_order(db, index)
    return index


def test_the_two_entry_points_stay_separate_and_agree(db, model):
    """ADR 0040. One policy, still two functions.

    The approval path does not take supplied source facts - it reads the
    ledger - and that separation is kept: the reconciliation view reports
    per-order issues no ledger column carries, and handing those to approval
    would make a screen's diagnostics into an obligation.

    What is no longer true is that they produce different money. A pending
    order is worth the same to both, which is the whole of the repair.
    """
    pending(db)
    facts = [source_order(db.get(AttributedOrder, "pending"))]

    with pytest.raises(TypeError, match="source_orders"):
        calculate_month(db, model, MONTH, source_orders=facts)

    live = calculate_month(db, model, MONTH).payout_piastres
    assert live > 0
    assert preview_month(db, model, MONTH)["current_entitlement"]["payout"]["piastres"] == live
    assert approve_month(db, model, MONTH).approved_obligation_piastres == live


def test_pending_once_example_delivery_adds_nothing_in_either_month(db, model):
    """F02's worked example: counted once, in the month it belongs to.

    The name held through the transition and the figures moved under it. The
    order used to be worth nothing until it was delivered and then worth
    something to a *later* month; now it is worth the same to its own month
    throughout, and the delivery adds nothing anywhere - which is what the
    example was always asserting.
    """
    example = EXAMPLES["pending_once"]
    index = pending(db, total_piastres=example["source_sales_piastres"], shipping_piastres=0)
    before = preview_month(db, model, MONTH)
    assert before["current_entitlement"]["payout"]["piastres"] == example["commission_piastres"]
    assert before["performance"]["pending_orders"] == 1
    assert calculate_month(db, model, MONTH).payout_piastres == example["commission_piastres"]

    snapshot = approve_month(db, model, MONTH)
    assert snapshot.approved_obligation_piastres == example["commission_piastres"]

    index.delivery_state = "delivered"
    index.delivered_at = datetime(2026, 5, 2, tzinfo=timezone.utc)
    attribute_order(db, index)

    after = preview_month(db, model, MONTH)
    assert after["current_entitlement"]["payout"] == before["current_entitlement"]["payout"]
    assert after["performance"]["delivered_orders"] == 1
    # May pays nothing for it: April counted it, and the settlement link says
    # so whatever the courier does afterwards.
    assert preview_month(db, model, "2026-05")["current_entitlement"]["payout"]["piastres"] == 0
    assert calculate_month(db, model, "2026-05").payout_piastres == 0


def test_legacy_carry_allocation_keeps_source_sales_and_both_snapshot_links(db, model):
    """The backlog ADR 0040 inherited, and the view that reconciles it.

    April is agreed **before the transition**, so the order still travelling
    is left out of it and a later payroll pays it - exactly as it happened for
    every month approved under the old rule. That link is what the transition
    has to be able to see, and it is still reported at both ends.
    """
    index = pending(db, total_piastres=2_000_000, shipping_piastres=0)
    with approved_before_the_switch():
        source = approve_month(db, model, MONTH)
    index.delivery_state = "delivered"
    index.delivered_at = datetime(2026, 5, 2, tzinfo=timezone.utc)
    attribute_order(db, index)
    destination = approve_month(db, model, "2026-05")
    before_hashes = (source.content_hash, destination.content_hash)
    expected_link = [{"shopify_order_id": "pending", "source_month": MONTH,
                      "allocated_month": "2026-05", "snapshot_id": destination.id,
                      "snapshot_version": 1}]
    for _ in range(2):
        original = preview_month(db, model, MONTH)
        later = preview_month(db, model, "2026-05")
        assert original["performance"]["counted_sales_piastres"] == 2_000_000
        assert original["current_entitlement"]["payout"]["piastres"] == 200_000
        assert later["performance"]["counted_sales_piastres"] == 0
        assert later["current_entitlement"]["payout"]["piastres"] == 0
        assert original["legacy_allocations"] == later["legacy_allocations"] == expected_link
        assert original["requires_transition_reconciliation"] is True
        assert later["approval"]["approved_obligation_piastres"] == 200_000
    # April's own recalculation excludes it, because May settled it. The
    # backlog order is paid once, by the month that actually paid it.
    assert calculate_month(db, model, MONTH).payout_piastres == 0
    assert db.get(AttributedOrder, "pending").settled_in_snapshot_id == destination.id
    assert (content_hash(source.payload_json), content_hash(destination.payload_json)) == before_hashes
    assert db.scalar(select(func.count()).select_from(PayrollSnapshot)) == 2


@pytest.mark.parametrize("cancelled", [False, True])
def test_failed_delivery_excludes_sales_without_requiring_cancellation(db, model, cancelled):
    index = pending(db)
    index.delivery_state = "failed"
    if cancelled:
        index.cancelled_at = datetime(2026, 4, 20, tzinfo=timezone.utc)
    index.total_piastres = 0
    attribute_order(db, index)
    view = preview_month(db, model, MONTH)
    assert view["performance"]["counted_sales_piastres"] == 0
    assert view["performance"]["failed_orders"] == 1
    assert view["current_entitlement"]["payout"]["piastres"] == 0
    # The known pre-failure amount must survive a webhook zeroing Shopify totals.
    assert view["orders"][0]["display_base_piastres"] == 106_200
    # Raw source diagnostics must not imply that a failed order earned money.
    # Order-screen commission/forgone presentation belongs to the portal helper.
    assert "display_commission_piastres" not in view["orders"][0]


def test_failed_first_seen_without_original_money_is_unavailable_not_zero(db, model):
    index = _order(db, delivery_state="failed", total_piastres=0, delivered_at=None)
    attribute_order(db, index)
    detail = preview_month(db, model, MONTH)["orders"][0]
    assert detail["display_base_piastres"] is None


@pytest.mark.parametrize("state", [None, "unrecognised"])
def test_missing_delivery_evidence_does_not_become_trustworthy_pending(db, model, state):
    index = pending(db)
    index.delivery_state = state
    view = preview_month(db, model, MONTH)
    assert view["source_complete"] is False
    assert view["performance"]["unavailable_orders"] == 1
    assert view["performance"]["counted_sales_piastres"] == 0
    assert "delivery_status_unavailable" in view["current_entitlement"]["blockers"]


def test_attempted_delivery_remains_pending(db, model):
    pending(db, delivery_status="ATTEMPTED_DELIVERY")
    view = preview_month(db, model, MONTH)
    assert view["performance"]["pending_orders"] == 1
    assert view["current_entitlement"]["payout"]["piastres"] == 10_600


def test_refund_exchange_after_observed_delivery_keeps_the_original_basis(db, model):
    index = pending(db, first_seen_at=datetime(2026, 4, 15, tzinfo=timezone.utc))
    index.delivery_state = "delivered"
    index.delivered_at = datetime(2026, 4, 20, tzinfo=timezone.utc)
    attribute_order(db, index)
    snapshot = approve_month(db, model, MONTH)
    index.total_piastres = 999_999
    index.return_activity = True
    index.refunded_total_piastres = 115_700
    index.financial_status = "refunded"
    index.cancelled_at = datetime(2026, 4, 22, tzinfo=timezone.utc)
    attribute_order(db, index)
    view = preview_month(db, model, MONTH)
    assert view["source_complete"] is True
    assert view["performance"]["counted_sales_piastres"] == 106_200
    assert view["current_entitlement"]["payout"]["piastres"] == 10_600
    assert view["approval"]["approved_obligation_piastres"] == 10_600
    assert content_hash(snapshot.payload_json) == snapshot.content_hash


def test_first_seen_after_exchange_reports_uncertain_original_basis(db, model):
    index = _order(db, return_activity=True, first_seen_at=datetime(2026, 4, 25, tzinfo=timezone.utc))
    attribute_order(db, index)
    view = preview_month(db, model, MONTH)
    assert view["source_complete"] is False
    assert "original_delivery_basis_unavailable" in view["current_entitlement"]["blockers"]


def test_explicit_later_failure_changes_source_performance_only(db, model):
    index = _order(db)
    attribute_order(db, index)
    snapshot = approve_month(db, model, MONTH)
    index.delivery_state = "failed"
    attribute_order(db, index)  # legacy terminal row remains earned
    view = preview_month(db, model, MONTH)
    assert view["performance"]["counted_sales_piastres"] == 0
    assert view["current_entitlement"]["payout"]["piastres"] == 0
    assert view["approval"]["approved_obligation_piastres"] == 10_600
    assert snapshot.content_hash == content_hash(snapshot.payload_json)


def test_real_payment_remains_distinct_from_revised_source_and_external_history(db, model, monkeypatch):
    index = _order(db)
    attribute_order(db, index)
    snapshot = approve_month(db, model, MONTH)
    payment = record_payment(db, model, amount_piastres=5_000, allocations={snapshot.id: 5_000},
                             reference="synthetic-05A-transfer")
    index.delivery_state = "failed"
    view = preview_month(db, model, MONTH)
    assert view["current_entitlement"]["payout"]["piastres"] == 0
    assert view.get("settlement", {}).get("recorded_allocations_piastres") == 5_000
    assert view["settlement"]["legacy_balance_piastres"] == 5_600
    assert view["settlement"]["state"] == "partially_paid"
    monkeypatch.setattr(settings, "go_live_month", "2026-09")
    historical = preview_month(db, model, MONTH)
    assert historical["settled_outside"] is True
    assert historical["settlement"]["recorded_allocations_piastres"] == 5_000
    assert historical["settlement"]["legacy_balance_piastres"] == 0
    assert payment.amount_piastres == 5_000
    assert payment.reference == "synthetic-05A-transfer"


def test_reversed_failure_is_retained_for_d09_review(db, model):
    index = _order(db, delivery_state="failed", delivered_at=None)
    attribute_order(db, index)
    index.delivery_state = "in_flight"
    view = preview_month(db, model, MONTH)
    assert "delivery_status_revision_requires_review" in view["current_entitlement"]["blockers"]


def test_base_and_rounding_example_uses_customer_total_not_subtotal(db, model):
    example = EXAMPLES["base_and_rounding"]
    pending(db, subtotal_piastres=167_500, total_piastres=example["customer_total_piastres"],
            shipping_piastres=example["shipping_piastres"], tax_piastres=example["tax_piastres"])
    view = preview_month(db, model, MONTH)
    assert view["performance"]["counted_sales_piastres"] == example["base_piastres"]
    assert Decimal(view["current_entitlement"]["commission_piastres"]) == Decimal(example["exact_commission_piastres"])
    assert view["current_entitlement"]["payout"]["piastres"] == example["payout_piastres_under_existing_rule"]


def test_fractional_pending_and_delivered_commissions_are_aggregated_once(db, model):
    set_terms(db, model, start_month="2026-04", compensation_type="commission", commission_rate_bp=333)
    for i in range(40):
        index = pending(db, str(i), total_piastres=10_015, shipping_piastres=0)
        if i % 2:
            index.delivery_state = "delivered"
            index.delivered_at = datetime(2026, 4, 20, tzinfo=timezone.utc)
            attribute_order(db, index)
    view = preview_month(db, model, MONTH)
    assert Decimal(view["current_entitlement"]["commission_piastres"]) == Decimal("13339.98")
    assert view["current_entitlement"]["payout"]["piastres"] == 13_300
    assert view["performance"]["counted_orders"] == 40


@pytest.mark.parametrize("outcome,verified,expected,blocker", [
    (None, False, 10_600, "no_target_recorded_for_this_month"),
    (False, False, 10_600, None),
    (True, False, 10_600, "targets_achieved_but_not_verified"),
    (True, True, 200_000, None),
])
def test_guarantee_reuses_three_valued_verified_evidence(db, model, outcome, verified, expected, blocker):
    set_terms(db, model, start_month=MONTH, compensation_type="base_guarantee",
              commission_rate_bp=1000, base_amount_piastres=200_000)
    pending(db)
    if outcome is not None:
        target = set_requirements(db, model, MONTH, videos=1, stories=1)
        record_actuals(db, target, videos=int(outcome), stories=int(outcome))
        if verified:
            verify(db, target)
    result = preview_month(db, model, MONTH)["current_entitlement"]
    assert result["payout"]["piastres"] == expected
    assert result["blockers"] == ([blocker] if blocker else [])


def test_fixed_pay_is_added_and_house_sales_are_never_payable(db, model):
    set_terms(db, model, start_month=MONTH, compensation_type="fixed_plus_commission",
              commission_rate_bp=1000, fixed_amount_piastres=100_000)
    pending(db, total_piastres=500_000, shipping_piastres=0)
    assert preview_month(db, model, MONTH)["current_entitlement"]["payout"]["piastres"] == 150_000
    model.account_kind = "house"
    db.flush()
    view = preview_month(db, model, MONTH)
    assert view["performance"]["counted_sales_piastres"] == 500_000
    assert view["current_entitlement"]["payout"]["piastres"] == 0


def test_monthly_rate_and_empty_historical_month_remain_source_scoped(db, model, monkeypatch):
    pending(db)
    set_terms(db, model, start_month="2026-05", compensation_type="commission", commission_rate_bp=2000)
    assert preview_month(db, model, MONTH)["current_entitlement"]["payout"]["piastres"] == 10_600
    monkeypatch.setattr(settings, "go_live_month", "2026-09")
    view = preview_month(db, model, "2026-07")
    assert view["settled_outside"] is True
    assert view["performance"]["counted_orders"] == 0
    assert view["current_entitlement"]["payout"]["piastres"] == 0
    assert db.scalar(select(func.count()).select_from(PayrollSnapshot)) == 0
