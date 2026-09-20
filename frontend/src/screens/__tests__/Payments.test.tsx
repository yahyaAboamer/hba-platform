import { renderToStaticMarkup } from "react-dom/server";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";

import {
  PaymentRow,
  paymentRowPresentation,
  type Balance,
} from "../Payments";
import { PaymentDestination, paymentRequest } from "../PaymentRecord";

const approved: Balance = {
  affiliate_id: 7,
  name: "Nour",
  status: "active",
  month: "2026-09",
  state: "settled",
  payroll_snapshot_id: 18,
  obligation_piastres: 200_000,
  paid_piastres: 0,
  adjusted_piastres: 0,
  credited_piastres: 200_000,
  balance_piastres: 0,
  forecast_piastres: null,
  forecast_blockers: [],
  required_kind: "approved",
  required_piastres: 0,
};

describe("the month-end payment row", () => {
  it("calls a correction-covered zero a valid no-transfer month", () => {
    const view = paymentRowPresentation(approved);

    expect(view.label).toBe("No transfer due");
    expect(view.explanation).toContain("already sent in an earlier month");
    expect(view.explanation).toContain("not sent again");
    expect(view.action).toBe("Open");
  });

  it("keeps an unapproved forecast separate from money already agreed", () => {
    const view = paymentRowPresentation({
      ...approved,
      state: "not_approved",
      payroll_snapshot_id: undefined,
      obligation_piastres: 0,
      credited_piastres: 0,
      balance_piastres: 0,
      forecast_piastres: 200_000,
      required_kind: "forecast",
      required_piastres: 200_000,
    });

    // The export names each state after the filter that collects it, so a
    // pill and the button beside it never disagree about which bucket a row
    // is in. The forecast half of F14 is said by the `Estimated` badge on the
    // total and by the row's own second line, not by a longer state.
    expect(view.label).toBe("Awaiting approval");
    expect(view.action).toBe("Review");
  });

  it("sends a part-paid model back to the transfer record", () => {
    const view = paymentRowPresentation({
      ...approved,
      state: "partially_paid",
      paid_piastres: 50_000,
      credited_piastres: 0,
      balance_piastres: 150_000,
    });

    expect(view.label).toBe("Partly paid");
    expect(view.action).toBe("Record payment");
  });

  it("will not calculate for a model who has no arrangement", () => {
    // The one state on this screen that is somebody's mistake rather than
    // somebody's turn, and the export gives it its own colour and its own act.
    const view = paymentRowPresentation({
      ...approved,
      state: "not_approved",
      terms: null,
      payroll_snapshot_id: undefined,
      obligation_piastres: 0,
      credited_piastres: 0,
      balance_piastres: 0,
      required_kind: "unavailable",
      required_piastres: 0,
    });

    expect(view.label).toBe("Terms missing");
    expect(view.action).toBe("Fix terms");
  });
});

describe("recording the external transfer", () => {
  it("keeps the same operation identity and the selected transfer date", () => {
    expect(
      paymentRequest({
        operationKey: "06a-browser-act-0001",
        affiliateId: 7,
        amountPiastres: 150_000,
        payrollSnapshotId: 18,
        transferDate: "2026-09-03",
        reference: "IPN-118",
        note: "InstaPay limit",
        proofFileId: "proof-7",
      }),
    ).toEqual({
      operation_key: "06a-browser-act-0001",
      affiliate_id: 7,
      amount_piastres: 150_000,
      allocations: [{ payroll_snapshot_id: 18, piastres: 150_000 }],
      occurred_at: "2026-09-03T12:00:00Z",
      reference: "IPN-118",
      note: "InstaPay limit",
      proof_file_id: "proof-7",
    });
  });

  it.each([
    [
      "InstaPay",
      {
        method: "instapay" as const,
        instapay_address_url: "https://ipn.eg/S/nour?source=hba",
        instapay_phone: "01001234567",
      },
      ["https://ipn.eg/S/nour?source=hba", "01001234567", "Open InstaPay"],
    ],
    [
      "bank/card",
      {
        method: "bank" as const,
        bank_name: "CIB",
        bank_account_holder: "Nour Ahmed",
        bank_account_number: "1234 5678 1234 5678",
      },
      ["CIB", "Nour Ahmed", "1234 5678 1234 5678"],
    ],
    [
      "WE Pay wallet",
      {
        method: "wallet" as const,
        wallet_provider: "WE Pay",
        wallet_phone: "01551234567",
      },
      ["WE Pay", "01551234567"],
    ],
  ])("shows the complete authorized %s destination", (_name, destination, facts) => {
    const html = renderToStaticMarkup(
      <PaymentDestination
        revealed={destination}
        copied={null}
        copyMessage={null}
        onCopy={() => undefined}
      />,
    );

    for (const fact of facts) expect(html).toContain(fact);
  });
});

/**
 * A02. The amount column, rendered, from the shape the API actually sends.
 *
 * The defect the audit confirmed in the browser: the row always rendered
 * `balance_piastres`. That is what is *left to send*, which the server sets to
 * zero on any month nobody has approved - so the list showed E£0.00 beside a
 * model whose own detail screen showed an estimated E£14,224. The same zero
 * appeared once a month was fully paid, where the export shows what was sent.
 *
 * These are fixtures in the server's own response shape rather than hand-made
 * numbers, and they are rendered through the real row, because the bug was
 * never in the arithmetic. Every figure involved was correct and on the wire;
 * the column was bound to the wrong one.
 */
describe("the amount column, rendered", () => {
  const rowHtml = (over: Partial<Balance>) =>
    renderToStaticMarkup(
      <MemoryRouter>
        <table>
          <tbody>
            <PaymentRow
              row={{ ...approved, ...over }}
              month="2026-09"
              canRecord
              canApprove
            />
          </tbody>
        </table>
      </MemoryRouter>,
    );

  /**
   * The headline figure alone, and the line under it alone.
   *
   * Asserting against the whole cell is how a broken binding passes: a
   * settled row rendering `balance_piastres` shows E£0.00 as its figure and
   * E£2,000.00 on its second line, and a test that only asks whether
   * E£2,000.00 is *somewhere* in the markup is satisfied by the bug.
   */
  const figure = (html: string) => html.split('class="payments__part"')[0];
  const under = (html: string) => html.split('class="payments__part"').slice(1).join("");

  it("shows the forecast on a month nobody has approved", () => {
    const html = rowHtml({
      state: "not_approved",
      payroll_snapshot_id: undefined,
      obligation_piastres: 0,
      paid_piastres: 0,
      credited_piastres: 0,
      balance_piastres: 0,
      forecast_piastres: 1_422_400,
      required_kind: "forecast",
      required_piastres: 1_422_400,
    });

    // The figure her detail screen shows, on the row that used to say nothing.
    expect(figure(html)).toContain("E£14,224.00");
    expect(html).not.toContain("E£0.00");
  });

  it("says nothing rather than guessing when the month cannot be calculated", () => {
    const html = rowHtml({
      state: "not_approved",
      payroll_snapshot_id: undefined,
      obligation_piastres: 0,
      paid_piastres: 0,
      credited_piastres: 0,
      balance_piastres: 0,
      forecast_piastres: null,
      forecast_blockers: ["no_terms_for_this_month"],
      required_kind: "unavailable",
      required_piastres: 0,
    });

    expect(html).toContain("Unavailable");
    expect(html).not.toContain("E£");
  });

  it("shows the approved total on a month nothing has been sent for", () => {
    const html = rowHtml({
      state: "unpaid",
      obligation_piastres: 200_000,
      paid_piastres: 0,
      credited_piastres: 0,
      balance_piastres: 200_000,
      forecast_piastres: null,
      required_kind: "approved",
      required_piastres: 200_000,
    });

    expect(figure(html)).toContain("E£2,000.00");
    // Nothing sent and nothing deducted, so there is no second line to draw.
    expect(html).not.toContain("payments__part");
  });

  it("keeps the whole month in the figure when part of it has been sent", () => {
    const html = rowHtml({
      state: "partially_paid",
      obligation_piastres: 200_000,
      paid_piastres: 50_000,
      credited_piastres: 0,
      balance_piastres: 150_000,
      forecast_piastres: null,
      required_kind: "approved",
      required_piastres: 200_000,
    });

    // The month, then what has gone - not the remainder on its own, which is
    // what made a part-paid row read as a smaller month than it is.
    expect(figure(html)).toContain("E£2,000.00");
    expect(under(html)).toContain("E£500.00");
    expect(under(html)).toContain("recorded");
  });

  it("still shows what a fully paid month came to", () => {
    const html = rowHtml({
      state: "settled",
      obligation_piastres: 200_000,
      paid_piastres: 200_000,
      credited_piastres: 0,
      balance_piastres: 0,
      forecast_piastres: null,
      required_kind: "approved",
      required_piastres: 200_000,
    });

    expect(figure(html)).toContain("E£2,000.00");
    expect(under(html)).toContain("E£2,000.00");
    expect(under(html)).toContain("recorded");
  });

  it("explains a correction-covered month rather than showing a bare zero", () => {
    // D04: the deduction takes the whole month, so nothing is transferred.
    // The row has to say why, or a valid zero looks like a broken one.
    const html = rowHtml({
      state: "settled",
      obligation_piastres: 200_000,
      paid_piastres: 0,
      credited_piastres: 200_000,
      balance_piastres: 0,
      forecast_piastres: null,
      required_kind: "approved",
      required_piastres: 0,
    });

    expect(figure(html)).toContain("E£0.00");
    expect(under(html)).toContain("E£2,000.00");
    expect(under(html)).toContain("deducted");
  });

  it("shows a month settled outside the platform as owing nothing", () => {
    const html = rowHtml({
      state: "settled_externally",
      obligation_piastres: 0,
      paid_piastres: 0,
      credited_piastres: 0,
      balance_piastres: 0,
      forecast_piastres: null,
      required_kind: "settled_externally",
      required_piastres: 0,
    });

    expect(figure(html)).toContain("E£0.00");
    expect(html).not.toContain("payments__part");
  });
});
