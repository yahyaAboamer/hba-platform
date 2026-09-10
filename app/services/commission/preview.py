"""Pending-inclusive financial rules rehearsal. No approval or ledger writes.

D01 still owns transition. Legacy settlement links are shown for reconciliation,
never subtracted from source sales or automatically turned into new debt.
"""

from dataclasses import asdict
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.money import commission_numerator, exact_commission_piastres
from app.models.affiliates import AffiliateProfile
from app.models.attributed_orders import AttributedOrder
from app.models.payroll import PayrollMonth, PayrollSnapshot
from app.services.commission.calculate import calculate_month
from app.services.commission.source import source_order
from app.services.payments import allocated_to_month, balance_for
from app.services.payroll import get_month, is_historical


def preview_month(db: Session, affiliate: AffiliateProfile, month: str) -> dict:
    # Reuse the same validation, monthly terms, targets and money arithmetic as
    # the legacy calculation; the source selection is the policy difference.
    from app.core.businesstime import parse_month

    parse_month(month)
    orders = list(db.scalars(
        select(AttributedOrder)
        .where(AttributedOrder.affiliate_id == affiliate.id)
        .where(AttributedOrder.business_month == month)
        .order_by(AttributedOrder.shopify_order_id)
    ))
    facts = [source_order(row) for row in orders]
    calculation = calculate_month(db, affiliate, month, source_orders=facts)
    payroll = get_month(db, affiliate, month)
    snapshot = payroll.active_snapshot if payroll else None
    balance = balance_for(db, affiliate, month)

    # Include both outgoing and incoming carry links so neither end disappears
    # from the transition inventory. Preserve all snapshot IDs, including old
    # versions; approval is evidence of allocation, not proof of a transfer.
    links = db.execute(
        select(AttributedOrder, PayrollSnapshot, PayrollMonth)
        .join(PayrollSnapshot, PayrollSnapshot.id == AttributedOrder.settled_in_snapshot_id)
        .join(PayrollMonth, PayrollMonth.id == PayrollSnapshot.payroll_month_id)
        .where(AttributedOrder.affiliate_id == affiliate.id)
        .where(PayrollMonth.affiliate_id == affiliate.id)
        .where(AttributedOrder.business_month != PayrollMonth.month)
        .where((AttributedOrder.business_month == month) | (PayrollMonth.month == month))
        .order_by(AttributedOrder.shopify_order_id)
    ).all()
    legacy_links = [
        {
            "shopify_order_id": order.shopify_order_id,
            "source_month": order.business_month,
            "allocated_month": destination.month,
            "snapshot_id": settled.id,
            "snapshot_version": settled.version,
        }
        for order, settled, destination in links
    ]
    order_lines = []
    for fact in facts:
        commission = None
        if (fact.display_base_piastres is not None
                and calculation.commission_rate_bp is not None and not fact.issues):
            exact = exact_commission_piastres(commission_numerator(
                fact.display_base_piastres, calculation.commission_rate_bp,
            ))
            # Display only. The month was already aggregated exactly above;
            # these rounded rows must never feed its payout.
            commission = 0 if calculation.is_house else int(
                exact.quantize(Decimal(1), rounding=ROUND_HALF_UP)
            )
        order_lines.append({**asdict(fact), "display_commission_piastres": commission})
    return {
        "policy": "pending_inclusive_preview",
        "month": month,
        "can_approve": False,
        "activation_blockers": ["live_transition_not_enabled"],
        "source_complete": not any(fact.issues for fact in facts),
        "performance": {
            "counted_sales_piastres": calculation.earned_base_piastres + calculation.pending_base_piastres,
            "counted_orders": calculation.earned_orders + calculation.pending_orders,
            "delivered_orders": calculation.earned_orders,
            "pending_orders": calculation.pending_orders,
            "failed_orders": calculation.void_orders,
            "unavailable_orders": sum(fact.state == "unavailable" for fact in facts),
        },
        "current_entitlement": {
            "compensation_type": calculation.compensation_type,
            "commission_rate_bp": calculation.commission_rate_bp,
            "commission_piastres": str(calculation.commission_piastres),
            "fixed_piastres": calculation.fixed_piastres,
            "base_amount_piastres": calculation.base_amount_piastres,
            "guarantee_applied": calculation.guarantee_applied,
            "target_achieved": calculation.target_achieved,
            "target_verified": calculation.target_verified,
            "payout": {
                "piastres": calculation.payout_piastres,
                "exact_unrounded_piastres": str(calculation.exact_unrounded_piastres),
            },
            "blockers": calculation.blockers,
            "is_house": calculation.is_house,
        },
        "approval": {
            "snapshot_id": snapshot.id,
            "version": snapshot.version,
            "approved_obligation_piastres": snapshot.approved_obligation_piastres,
        } if snapshot else None,
        # Historical settlement classification is inherited, never changed or
        # used to manufacture payment rows during this preview.
        "settled_outside": is_historical(month),
        "settlement": {
            "state": balance["state"],
            "recorded_allocations_piastres": allocated_to_month(db, payroll) if payroll else 0,
            "legacy_balance_piastres": balance["balance_piastres"],
        },
        "legacy_allocations": legacy_links,
        "requires_transition_reconciliation": bool(legacy_links),
        "orders": order_lines,
    }
