import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import type { MyOrder } from "../../lib/portal";
import { commissionRule } from "../MyCalculation";
import { explain, Row } from "../MyOrders";
import { countedSalesDetail } from "../PaymentDetail";

/**
 * F02 / ADR 0040 in the words on three screens: delivered and pending count,
 * a failed delivery does not, and a month agreed before the switch is
 * described by the rule it was agreed under.
 */

const order = (patch: Partial<MyOrder>): MyOrder =>
  ({
    order_number: "#9801",
    shopify_order_id: "9801",
    placed_at: "2026-09-10T12:00:00+00:00",
    contents: [],
    base_piastres: 200_000,
    base: "EGP 2,000.00",
    state: "pending",
    state_text: "Pending",
    delivered_at: null,
    paid_in_month: null,
    commission_piastres: 20_000,
    commission: "EGP 200.00",
    counted: true,
    rate_missing: false,
    placed_piastres: null,
    placed: null,
    forgone_piastres: null,
    forgone: null,
    ...patch,
  }) as MyOrder;

const row = (patch: Partial<MyOrder>) =>
  renderToStaticMarkup(
    <Row order={order(patch)} month="2026-09" open={false} onToggle={() => {}} />,
  );

describe("My Calculation's rule line", () => {
  it("is the export's sentence under the live rule", () => {
    expect(commissionRule("pending_inclusive", 1000, "2026-09")).toBe(
      "Commission is 10% of net sales on delivered and pending orders. Failed deliveries are excluded.",
    );
  });

  it("describes an older agreement as it was agreed", () => {
    const line = commissionRule("delivered_only", 1000, "2026-08");
    expect(line).toContain("August 2026 was agreed counting delivered orders only");
    expect(line).not.toContain("pending");
  });
});

describe("Payment detail's counted sales", () => {
  it("is delivered and pending on a month nobody has approved", () => {
    expect(countedSalesDetail(null)).toBe("Delivered and pending orders. Failed deliveries excluded.");
  });

  it("is the export's *As approved* under the live rule", () => {
    expect(countedSalesDetail("pending_inclusive")).toBe("As approved. Failed deliveries excluded.");
  });

  it("never claims an older snapshot counted pending orders", () => {
    const line = countedSalesDetail("delivered_only");
    expect(line).toContain("delivered orders only");
    expect(line).not.toMatch(/delivered and pending/);
  });
});

describe("an order's commission on My Orders", () => {
  it("shows a pending order's figure, unstruck", () => {
    const html = row({});
    expect(html).toContain("EGP 200.00");
    expect(html).not.toContain("money--void");
  });

  it("strikes a failed delivery's figure through", () => {
    const html = row({
      state: "void",
      state_text: "Did not arrive",
      counted: false,
      commission_piastres: null,
      commission: null,
      forgone_piastres: 20_000,
      forgone: "EGP 200.00",
    });
    expect(html).toContain("money--void");
    expect(html).toContain("EGP 200.00");
  });

  it("prints a real zero as a figure", () => {
    const html = row({ base_piastres: 0, base: "EGP 0.00", commission_piastres: 0, commission: "EGP 0.00" });
    expect(html).toContain("EGP 0.00");
    expect(html).not.toContain("orders__fee--none");
  });

  it("prints a dash, and says why, when no rate is set", () => {
    const missing = { commission_piastres: null, commission: null, rate_missing: true };
    expect(row(missing)).toContain("orders__fee--none");
    expect(explain(order(missing), "2026-09")).toContain(
      "No commission rate is set for September 2026, so what it earns is not available yet.",
    );
  });

  it("explains a pending order in the export's words", () => {
    expect(explain(order({}), "2026-09")).toBe(
      "Counted in September 2026 while it is on its way. If it fails, it is removed and the difference is settled in a later month.",
    );
  });

  it("does not apply today's rule to a month agreed delivered-only", () => {
    const text = explain(order({ counted: false, commission_piastres: null, commission: null }), "2026-08");
    expect(text).toContain("August 2026 was agreed counting delivered orders only");
    expect(text).not.toContain("Counted in");
  });
});
