"""Writing down whose order this is, and what it is worth.

Phase 3's `resolve()` decided; nothing recorded the decision. This does, and it
is where the three pure modules meet the database:

    attribution.resolve   whose order is it            (§9.2)
    base.base_for_order   what is it worth             (§9.3, ADR 0011)
    state.commission_state does it count yet           (§9.4, ADR 0012)

## It runs on ingestion, not on a schedule

Called from `upsert_order_index`, so **every** path that indexes an order
attributes it - webhook, reconciliation sweep, and bulk import alike. Hooking
the three call sites separately would work until somebody adds a fourth, and a
missed attribution is not a visible failure: the order simply belongs to
nobody, quietly, for as long as it takes someone to notice the sales are
missing.

## Three things it refuses to do

**It never moves an order between models.** If an order already has an
affiliate and now resolves to a different one, nothing is written and an anomaly
is raised. The trigger would refuse it anyway (§17); this reports *why* rather
than letting an IntegrityError surface from somewhere unrelated. It means a code
changed hands with overlapping months, or a period was registered wrongly.

**It never touches a finished order.** ADR 0025: delivered or void is the end of
the story. A late webhook carrying an exchange's edited subtotal would otherwise
rewrite a figure a payroll has already been approved on.

**It never writes a held order.** Two registered codes on one order is §9.2's
financial hold: no row, an anomaly, and the order waits for a person. Writing a
guess would either pay the wrong person or pay twice.
"""

from sqlalchemy.orm import Session

from app.core.businesstime import utcnow
from app.core.signals import Anomaly, report
from app.models.attributed_orders import AttributedOrder, CommissionState
from app.models.orders import OrderIndex
from app.services.attribution import AttributionOutcome, resolve
from app.services.commission.base import base_for_order
from app.services.commission.state import commission_state, is_final


def attribute_order(db: Session, order: OrderIndex) -> AttributedOrder | None:
    """Decide this order and record it. Returns the row, or None.

    None means one of: nobody owns the codes, two people do, or the order is
    finalised and was deliberately left alone. Each is a normal outcome, not an
    error.
    """
    existing = db.get(AttributedOrder, order.shopify_order_id)
    decision = resolve(db, order.discount_codes or [], order.business_month)

    if decision.outcome == AttributionOutcome.HELD:
        # §9.2. The order waits rather than silently paying the wrong person.
        report(
            Anomaly.ATTRIBUTION_HELD,
            order=order.shopify_order_id,
            month=order.business_month,
            codes=",".join(decision.matched_codes),
        )
        return None

    if decision.outcome == AttributionOutcome.UNATTRIBUTED:
        # Indexed and belonging to nobody. If a row already exists, the codes
        # were removed from an order that had been attributed - which does not
        # un-attribute it. Orders do not move, and that includes moving to
        # nobody.
        return existing

    if existing is not None and existing.affiliate_id != decision.affiliate_id:
        report(
            Anomaly.ATTRIBUTION_CONFLICT,
            order=order.shopify_order_id,
            month=order.business_month,
            belongs_to=existing.affiliate_id,
            resolved_to=decision.affiliate_id,
        )
        return existing

    if existing is not None and is_final(existing.commission_state):
        # ADR 0025. Delivered or void is the end of the story, so nothing is
        # recalculated and Shopify is not read for it again.
        return existing

    state = commission_state(
        delivery_state=order.delivery_state,
        cancelled_at=order.cancelled_at,
        financial_status=order.financial_status,
    )

    base = base_for_order(
        total_piastres=order.total_piastres,
        shipping_piastres=order.shipping_piastres,
        tax_piastres=order.tax_piastres,
        delivered=state == CommissionState.EARNED,
        stored_base_piastres=existing.commission_base_piastres if existing else None,
    )

    if existing is None:
        existing = AttributedOrder(
            shopify_order_id=order.shopify_order_id,
            affiliate_id=decision.affiliate_id,
            # Copied, never joined, and frozen by trigger. The month the order
            # was *placed* (ADR 0005).
            business_month=order.business_month,
        )
        db.add(existing)

    existing.commission_base_piastres = base.piastres
    existing.base_frozen_at = order.delivered_at if base.is_final else None
    existing.commission_state = state
    existing.refunded_merchandise_piastres = order.refunded_merchandise_piastres or 0
    existing.financial_status = order.financial_status
    existing.fulfillment_status = order.fulfillment_status
    existing.delivered_at = order.delivered_at
    existing.return_status = order.return_status
    existing.updated_at = utcnow()

    db.flush()
    return existing
