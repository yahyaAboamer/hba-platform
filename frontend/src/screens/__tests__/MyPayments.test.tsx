import { renderToStaticMarkup } from "react-dom/server";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";

import { PaymentRow } from "../MyPayments";
import type { Payment } from "../../lib/portal";

/**
 * A receipt has to survive her changing where she is paid.
 *
 * §6.4.4 freezes a masked destination on the transaction at the moment it was
 * paid, and AC40 is the case that proves it matters: she changes her InstaPay
 * address, then opens an old receipt. The screen has a *current* destination
 * at the top of it, and borrowing that would quietly claim an old transfer
 * went somewhere it never went.
 */
const payment: Payment = {
  id: 7,
  amount_piastres: 240_000,
  amount: "E£2,400.00",
  occurred_at: "2026-08-03T09:00:00+00:00",
  reference: "TRX-88",
  destination: {
    method: "instapay",
    instapay_address_url: "https://ipn.eg/S/old.address/instapay/1111",
  },
  has_proof: false,
  settles: [{ month: "2026-07", piastres: 240_000, amount: "E£2,400.00" }],
};

function render(row: Payment) {
  return renderToStaticMarkup(
    <MemoryRouter>
      <PaymentRow payment={row} />
    </MemoryRouter>,
  );
}

describe("a transfer she is looking back at", () => {
  it("names the destination it actually went to", () => {
    expect(render(payment)).toContain("old.address");
  });

  it("links to the month that explains the figure", () => {
    const html = render(payment);
    // AC41. Named by month rather than "View calculation", because one
    // transfer can settle two months and the generic label would be ambiguous.
    expect(html).toContain('href="/?month=2026-07"');
    expect(html).toContain("July 2026");
  });

  it("offers no calculation link for money not yet put against a month", () => {
    // Ordinary rather than exceptional: money can arrive before anybody has
    // decided which month it settles. A link here would go nowhere.
    const html = render({ ...payment, settles: [] });
    expect(html).not.toContain("month=");
    expect(html).toContain("Not yet put against a month");
  });

  it("says nothing about a destination it does not have", () => {
    // A transfer recorded before destinations were frozen has none. An empty
    // "Sent to" is worse than silence.
    const html = render({ ...payment, destination: null });
    expect(html).not.toContain("Sent to");
  });
});
