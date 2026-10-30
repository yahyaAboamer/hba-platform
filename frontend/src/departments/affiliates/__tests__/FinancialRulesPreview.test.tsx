import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { RulesPreviewResult, type RulesPreview } from "../FinancialRulesPreview";

// Synthetic server response. The component must display these authoritative
// figures independently, never derive approval or transfers from current sales.
const view: RulesPreview = {
  month: "2026-04", source_complete: true,
  performance: { counted_sales_piastres: 2_000_000, delivered_orders: 0,
    pending_orders: 1, failed_orders: 0, unavailable_orders: 0 },
  current_entitlement: { payout: { piastres: 200_000 }, blockers: [], is_house: false },
  approval: { approved_obligation_piastres: 210_000 },
  settlement: { recorded_allocations_piastres: 150_000, legacy_balance_piastres: 60_000 },
  requires_transition_reconciliation: false, legacy_allocations: [],
};

describe("financial rules review", () => {
  it("keeps candidate earnings, approved amount and actual transfers separate", () => {
    const html = renderToStaticMarkup(<RulesPreviewResult view={view} />);
    expect(html).toContain("EGP 2,000.00");
    expect(html).toContain("EGP 2,100.00");
    expect(html).toContain("EGP 1,500.00");
    expect(html).not.toContain("<button");
  });
  it("does not present an incomplete candidate as money to pay", () => {
    const html = renderToStaticMarkup(<RulesPreviewResult view={{ ...view, source_complete: false,
      current_entitlement: { ...view.current_entitlement, blockers: ["delivery_status_unavailable"] } }} />);
    expect(html).not.toContain("EGP 2,000.00");
    expect(html).not.toContain("EGP 20,000.00");
    expect(html).toContain("EGP 2,100.00");
    expect(html).toContain("Delivery status is unavailable");
  });
  it("shows legacy carry as an allocation requiring review, not another transfer", () => {
    const html = renderToStaticMarkup(<RulesPreviewResult view={{ ...view,
      requires_transition_reconciliation: true, legacy_allocations: [{ shopify_order_id: "123",
        source_month: "2026-04", allocated_month: "2026-05", snapshot_id: 7 }] }} />);
    expect(html).toContain("reconciliation");
    expect(html).toContain("Order 123");
    expect(html).toContain("statement 7");
  });
});
