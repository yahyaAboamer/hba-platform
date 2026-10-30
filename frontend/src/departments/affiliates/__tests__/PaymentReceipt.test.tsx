import { describe, expect, it } from "vitest";

import { receiptFor } from "../PaymentDetail";

/**
 * A11. A receipt may not put a real transfer under a month it never paid for.
 *
 * `PaymentReceipt` finds the transfer by id, looks for an allocation matching
 * the month in the URL, and used to fall back to the transfer's **whole
 * amount** when that allocation was missing — while still titling the page
 * with the month from the URL.
 *
 * So a stale bookmark, a mistyped month, or a link copied from the wrong row
 * produced a page that looked exactly like a genuine receipt and said this
 * transfer paid for a month it had nothing to do with. Nothing on it
 * disagreed, because every fact on it was true except the one the heading
 * implied.
 *
 * §14 allows one transfer to cover two months, so "the allocation for this
 * month" is a real question with a real answer, and the answer is sometimes
 * "none of it".
 */
const transfer = (allocations: { month: string; piastres: number }[]) => ({
  id: 9,
  amount_piastres: 300_000,
  occurred_at: "2026-09-03T09:00:00+00:00",
  reference: "TRX-77",
  note: null,
  has_proof: true,
  destination: null,
  allocations: allocations.map((row, index) => ({
    month: row.month,
    snapshot_id: index + 1,
    snapshot_version: 1,
    allocated_piastres: row.piastres,
  })),
});

describe("which month a receipt belongs to", () => {
  it("shows the part of the transfer that settled this month", () => {
    // One transfer covering two months, which §14 explicitly allows. The
    // receipt for August is the August part, not the whole EGP 3,000.
    const match = receiptFor(
      transfer([
        { month: "2026-08", piastres: 100_000 },
        { month: "2026-09", piastres: 200_000 },
      ]),
      "2026-08",
    );

    expect(match).toEqual({ kind: "settled", piastres: 100_000 });
  });

  it("refuses to claim a transfer for a month it never settled", () => {
    // The defect: this used to return the transfer's full EGP 3,000 and the
    // page titled it July.
    const match = receiptFor(
      transfer([
        { month: "2026-08", piastres: 100_000 },
        { month: "2026-09", piastres: 200_000 },
      ]),
      "2026-07",
    );

    expect(match.kind).toBe("elsewhere");
    expect(match).toEqual({ kind: "elsewhere", months: ["2026-08", "2026-09"] });
  });

  it("names the months it did settle, so a wrong link is a wrong turning", () => {
    const match = receiptFor(transfer([{ month: "2026-09", piastres: 300_000 }]), "2026-08");

    expect(match).toEqual({ kind: "elsewhere", months: ["2026-09"] });
  });

  it("shows a transfer nobody has assigned yet without claiming a month", () => {
    // Not an error. §14 lets money be recorded before anybody decides which
    // months it covers, and forcing a split at that moment invents an answer.
    const match = receiptFor(transfer([]), "2026-08");

    expect(match).toEqual({ kind: "unassigned", piastres: 300_000 });
  });

  it("does not mistake a zero allocation for a missing one", () => {
    // A recorded allocation of nothing is a decision somebody made. It is this
    // month's receipt, for nothing - which is not the same as this transfer
    // having nothing to do with this month.
    const match = receiptFor(transfer([{ month: "2026-08", piastres: 0 }]), "2026-08");

    expect(match).toEqual({ kind: "settled", piastres: 0 });
  });
});
