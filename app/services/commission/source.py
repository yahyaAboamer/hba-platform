"""05A source facts, independent of which legacy payroll settled an order.

Read-only: legacy attribution can be terminal even while Shopify keeps storing
new facts. Do not rewrite that evidence to preview the replacement policy.
"""

from dataclasses import dataclass

from app.models.attributed_orders import AttributedOrder, CommissionState
from app.services.commission.state import commission_state
from app.services.shopify.fulfilment import DELIVERED, FAILED, IN_FLIGHT


@dataclass(frozen=True)
class SourceOrder:
    shopify_order_id: str
    state: str
    base_piastres: int
    display_base_piastres: int | None
    settled_in_snapshot_id: int | None
    issues: tuple[str, ...] = ()


def source_order(row: AttributedOrder) -> SourceOrder:
    """Use verified delivery facts; a missing signal is not a pending sale.

    Retain the stored delivery basis through refunds/exchanges. A later explicit
    delivery failure changes current performance, never an approved snapshot.
    Unknown original money stays unavailable, not a fabricated struck-out zero.
    """
    index = row.order
    issues = []
    if index.delivery_state not in (DELIVERED, FAILED, IN_FLIGHT):
        state = "unavailable"
        issues.append("delivery_status_unavailable")
    elif index.delivery_state == FAILED:
        state = CommissionState.VOID
    elif row.commission_state == CommissionState.EARNED:
        state = CommissionState.EARNED
    else:
        state = commission_state(
            delivery_state=index.delivery_state,
            cancelled_at=index.cancelled_at,
            financial_status=index.financial_status,
        )
        if row.commission_state == CommissionState.VOID and state != CommissionState.VOID:
            issues.append("delivery_status_revision_requires_review")

    # The existing attribution base is authoritative once delivery was seen.
    # If an exchange/refund had already happened on first observation, it is
    # only a candidate. No original shipping/tax history exists to repair it.
    if (
        state == CommissionState.EARNED
        and (index.return_activity or index.refunded_total_piastres
             or str(index.financial_status or "").lower() in ("refunded", "partially_refunded"))
        and (index.delivered_at is None or index.first_seen_at > index.delivered_at)
    ):
        issues.append("original_delivery_basis_unavailable")

    base = row.commission_base_piastres
    display_base = base
    if state == CommissionState.VOID and base == 0:
        # Original total without original shipping/tax cannot establish the
        # original commission basis. The index retains it for later review.
        display_base = None
    return SourceOrder(
        shopify_order_id=row.shopify_order_id,
        state=state,
        base_piastres=base,
        display_base_piastres=display_base,
        settled_in_snapshot_id=row.settled_in_snapshot_id,
        issues=tuple(issues),
    )
