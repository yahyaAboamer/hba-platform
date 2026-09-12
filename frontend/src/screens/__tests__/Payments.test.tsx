import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import {
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
