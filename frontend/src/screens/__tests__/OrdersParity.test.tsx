import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import type { MyOrder } from "../../lib/portal";
import { explain, Row } from "../MyOrders";
import { countsTowards, orderStatus } from "../Orders";

/**
 * Batch D: the Orders experience in the approved words - and a void order
 * named by why it is void, so only a courier's failure reads *Failed delivery*.
 */

const order = (patch: Partial<MyOrder>): MyOrder =>
  ({
    order_number: "#1011",
    shopify_order_id: "1011",
    placed_at: "2026-07-08T12:00:00+00:00",
    contents: [],
    base_piastres: 949_000,
    base: "EGP 9,490.00",
    state: "earned",
    status: "delivered",
    state_text: "Delivered",
    rate_bp: 1000,
    failed_after_approval: false,
    delivered_at: null,
    paid_in_month: null,
    commission_piastres: 94_900,
    commission: "EGP 949.00",
    counted: true,
    rate_missing: false,
    placed_piastres: null,
    placed: null,
    forgone_piastres: null,
    forgone: null,
    ...patch,
  }) as MyOrder;

const html = (patch: Partial<MyOrder>, open = false) =>
  renderToStaticMarkup(<Row order={order(patch)} month="2026-07" open={open} onToggle={() => {}} />);

describe("the model's order rows", () => {
  it("explains a delivered order in the export's sentence, at its month's rate", () => {
    expect(explain(order({}), "2026-07")).toBe(
      "Delivered and counted in July 2026. Commission is 10% of EGP 9,490.00.",
    );
  });

  it("uses the month's own rate, whatever it is", () => {
    expect(explain(order({ rate_bp: 1250 }), "2026-07")).toContain("Commission is 12.5% of");
  });

  it("names a courier's failure *Failed delivery*, struck through", () => {
    const failed = {
      state: "void" as const,
      status: "failed" as const,
      state_text: "Failed delivery",
      counted: false,
      commission_piastres: null,
      commission: null,
      forgone_piastres: 15_000,
      forgone: "EGP 150.00",
    };
    expect(html(failed)).toContain("Failed delivery");
    expect(html(failed)).toContain("money--void");
    expect(explain(order(failed), "2026-07")).toBe(
      "Delivery failed, so this order is excluded from July 2026.",
    );
    expect(explain(order({ ...failed, failed_after_approval: true }), "2026-07")).toBe(
      "Delivery failed, so this order is excluded from July 2026. It failed after the month was approved, so the difference is settled in a later month.",
    );
  });

  it("never calls a cancelled or refunded order a failed delivery", () => {
    const cancelled = { state: "void" as const, status: "cancelled" as const, state_text: "Cancelled", base_piastres: 0, commission_piastres: null, commission: null };
    expect(html(cancelled)).not.toContain("Failed delivery");
    expect(explain(order(cancelled), "2026-07")).toBe(
      "This order was cancelled, so the original sales amount is not available and nothing is counted.",
    );
    expect(explain(order({ ...cancelled, placed_piastres: 150_000, placed: "EGP 1,500.00" }), "2026-07")).toBe(
      "This order was cancelled, so nothing is counted. The amount shown is what it came to when it was placed.",
    );
    const refunded = { ...cancelled, status: "refunded" as const, state_text: "Refunded" };
    expect(explain(order(refunded), "2026-07")).not.toMatch(/fail/i);
  });

  it("says *no product lines available* on the row, and nothing twice inside", () => {
    const row = html({}, true);
    expect(row).toContain("no product lines available");
    expect(row).not.toContain("not recorded");
  });

  it("lists each product with its size and price", () => {
    const row = html(
      { contents: [{ title: "Panel Track Jacket", variant: "M", quantity: 1, price_piastres: 316_333, price: "EGP 3,163.33" }] },
      true,
    );
    expect(row).toContain("Size M");
    expect(row).toContain("EGP 3,163.33");
    expect(row).toContain("1 product");
  });
});

describe("the staff order view", () => {
  it("takes its status from the server, never from raw facts", () => {
    expect(orderStatus({ status: "failed" }).label).toBe("Failed delivery");
    expect(orderStatus({ status: "cancelled" }).label).toBe("Cancelled");
    expect(orderStatus({ status: "delivered" }).label).toBe("Delivered");
  });

  it("counts a pending order in its month, as the export does", () => {
    const counts = countsTowards({
      outcome: "attributed",
      commission_state: "pending",
      cancelled: false,
      delivery_state: null,
      business_month: "2026-07",
      paid_in_month: null,
    });
    expect(counts.label).toBe("Counted in July 2026");
  });

  it("excludes a void order from its month", () => {
    const counts = countsTowards({
      outcome: "attributed",
      commission_state: "void",
      cancelled: false,
      delivery_state: "failed",
      business_month: "2026-07",
      paid_in_month: null,
    });
    expect(counts.label).toBe("Excluded from July 2026");
  });
});
