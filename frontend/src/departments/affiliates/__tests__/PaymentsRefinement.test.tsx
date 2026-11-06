// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { Session } from "../../../lib/api";
import { PaymentCorrection } from "../PaymentCorrection";
import { PaymentDetail, PaymentReceipt } from "../PaymentDetail";
import { PaymentRecord } from "../PaymentRecord";
import { PaymentRow, Payments } from "../Payments";
import type { Balance } from "../Payments";

/**
 * The Payments refinement of 6 November 2026 (docs/design-refinement/payments).
 * Each test names the finding it holds in place.
 */

const reply = (status: number, body: unknown) =>
  Promise.resolve({
    ok: status < 400,
    status,
    headers: { get: () => "application/json" },
    json: () => Promise.resolve(body),
    text: () => Promise.resolve(JSON.stringify(body)),
  } as unknown as Response);

const row = (extra: Partial<Balance>): Balance => ({
  affiliate_id: 1,
  name: "Sara Edris",
  status: "active",
  month: "2026-10",
  terms: "commission",
  state: "unpaid",
  payroll_snapshot_id: 18,
  obligation_piastres: 1_000_000,
  paid_piastres: 0,
  adjusted_piastres: 0,
  credited_piastres: 0,
  balance_piastres: 1_000_000,
  forecast_piastres: null,
  forecast_blockers: [],
  required_kind: "approved",
  required_piastres: 1_000_000,
  ...extra,
});

const session = {
  permissions: ["payroll.approve", "payments.record"],
  platform: { start_month: "2026-08", working_month: "2026-10", go_live_month: "2026-10" },
} as unknown as Session;

let routes: Record<string, unknown>;
let fetchMock: ReturnType<typeof vi.fn>;
beforeEach(() => {
  routes = {};
  fetchMock = vi.fn((url: string, init?: RequestInit) => {
    if (init?.method && init.method !== "GET") return reply(418, { detail: "no writes in tests" });
    const path = String(url).split("?")[0];
    if (path in routes) return reply(200, routes[path]);
    return reply(500, { detail: "The payments service did not answer." });
  });
  vi.stubGlobal("fetch", fetchMock);
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const at = (path: string, pattern: string, element: React.ReactElement) =>
  render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path={pattern} element={element} />
      </Routes>
    </MemoryRouter>,
  );

const desk = {
  month: "2026-10",
  affiliates: [
    row({ affiliate_id: 1, state: "partially_paid", paid_piastres: 400_000, balance_piastres: 600_000 }),
    row({
      affiliate_id: 2,
      name: "Laila",
      state: "not_approved",
      required_kind: "forecast",
      obligation_piastres: 0,
      balance_piastres: 0,
      forecast_piastres: 300_000,
      required_piastres: 300_000,
    }),
  ],
  totals: {
    affiliates: 2,
    required_piastres: 1_300_000,
    forecast_piastres: 300_000,
    approved_piastres: 1_000_000,
    recorded_piastres: 400_000,
    still_owed_affiliates: 1,
    still_owed_piastres: 600_000,
  },
};

describe("the desk", () => {
  const list = () => at("/affiliates/payments", "/affiliates/payments", <Payments session={session} />);

  it("shows two cash figures, with the estimate said apart (F-L1, F2-1)", async () => {
    routes["/api/payments/2026-10"] = desk;
    list();
    const totals = await screen.findByRole("region", { name: "Month-end payment totals" });
    const text = totals.textContent ?? "";
    expect(text).toBe("Left to sendEGP 6,000.00RecordedEGP 4,000.00");
    // The estimate is not a debt, so it is outside the cards, and labelled.
    const note = screen.getByText(/Not approved yet: 1 model/);
    expect(note.textContent).toContain("about EGP 3,000.00");
  });

  /* Regression for F2-1: an overpaid month put what was *sent* under *To
   * receive*, and a *Total to send* card counted that money as still to send. */
  const overpaidDesk = {
    month: "2026-10",
    affiliates: [
      row({ affiliate_id: 1, name: "Mona", balance_piastres: 980_000, obligation_piastres: 980_000, required_piastres: 980_000 }),
      row({
        affiliate_id: 3,
        name: "Hana",
        state: "overpaid",
        obligation_piastres: 800_000,
        paid_piastres: 850_000,
        balance_piastres: -50_000,
        required_piastres: 850_000,
      }),
    ],
    totals: {
      affiliates: 2,
      required_piastres: 1_830_000,
      forecast_piastres: 0,
      approved_piastres: 1_780_000,
      recorded_piastres: 850_000,
      still_owed_affiliates: 1,
      still_owed_piastres: 980_000,
    },
  };

  it("never counts money already sent as still to send (F2-1)", async () => {
    routes["/api/payments/2026-10"] = overpaidDesk;
    list();
    const totals = await screen.findByRole("region", { name: "Month-end payment totals" });
    // The server's two cash totals, as they are: nothing summed here.
    expect(totals.textContent).toBe("Left to sendEGP 9,800.00RecordedEGP 8,500.00");
    expect(screen.queryByText(/Total to send/)).toBeNull();
    expect(screen.getByText(/^Overpaid:/).textContent).toBe("Overpaid: Hana by EGP 500.00");
  });

  it("shows an overpaid month at what she is due, and the excess apart (F2-1)", async () => {
    routes["/api/payments/2026-10"] = overpaidDesk;
    list();
    const hana = (await screen.findByText("Hana")).closest("tr") as HTMLElement;
    const amount = hana.querySelector(".payments__amount")?.textContent ?? "";
    expect(amount).toBe("EGP 8,000.00EGP 500.00 to settle");
    expect(amount).not.toContain("8,500");
  });

  it("offers Copy only where money is still to be sent (F2-4)", async () => {
    routes["/api/payments/2026-10"] = {
      ...overpaidDesk,
      affiliates: overpaidDesk.affiliates.map((r) => ({
        ...r,
        destination: { method: "instapay" },
        destination_line: "InstaPay · 0100",
        destination_card: { method: "instapay", rows: [{ label: "Number", value: "0100", copy: "number" }] },
      })),
    };
    list();
    const mona = (await screen.findByText("Mona")).closest("tr") as HTMLElement;
    const hana = screen.getByText("Hana").closest("tr") as HTMLElement;
    expect(within(mona).queryByRole("button", { name: "Copy destination" })).toBeTruthy();
    expect(within(hana).queryByRole("button", { name: "Copy destination" })).toBeNull();
  });

  it("does not repeat a fully paid row's figure as *recorded* (F2-4)", async () => {
    routes["/api/payments/2026-10"] = {
      ...desk,
      affiliates: [row({ state: "settled", paid_piastres: 1_000_000, balance_piastres: 0 })],
    };
    list();
    const sara = (await screen.findByText("Sara Edris")).closest("tr") as HTMLElement;
    expect(sara.querySelector(".payments__amount")?.textContent).toBe("EGP 10,000.00");
  });

  it("hides a filter with nothing in it (F-L5)", async () => {
    routes["/api/payments/2026-10"] = desk;
    list();
    const filters = await screen.findByRole("group", { name: "Filter payment states" });
    const names = within(filters).getAllByRole("button").map((b) => b.textContent);
    expect(names).toEqual(["All2", "Awaiting approval1", "Partly paid1"]);
  });

  it("offers a way back from an empty search (F-L7)", async () => {
    routes["/api/payments/2026-10"] = desk;
    list();
    fireEvent.change(await screen.findByRole("searchbox"), { target: { value: "zzz" } });
    fireEvent.click(screen.getByRole("button", { name: "Show all models" }));
    expect((screen.getByRole("searchbox") as HTMLInputElement).value).toBe("");
    expect(screen.getByText("Sara Edris")).toBeTruthy();
  });

  it("can try again after a failed load (F-L6)", async () => {
    list();
    const retry = await screen.findByRole("button", { name: "Try again" });
    routes["/api/payments/2026-10"] = desk;
    fireEvent.click(retry);
    expect(await screen.findByText("Sara Edris")).toBeTruthy();
  });
});

describe("recording a transfer", () => {
  const record = () =>
    at(
      "/affiliates/payments/2026-10/1/record",
      "/affiliates/payments/:month/:affiliateId/record",
      <PaymentRecord />,
    );

  it("says what a smaller amount leaves, and asks why right under it (F-R2)", async () => {
    routes["/api/payments/2026-10"] = { affiliates: [row({})] };
    record();
    const amount = await screen.findByLabelText("Amount transferred, EGP");
    fireEvent.change(amount, { target: { value: "4000" } });

    expect(screen.getByText(/will still be left to send/).textContent).toContain("EGP 6,000.00");
    const why = screen.getByLabelText("Why is it less than EGP 10,000.00?");
    const date = screen.getByLabelText("Transfer date");
    expect(why.compareDocumentPosition(date) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(screen.getByText(/Say why the amount is different/)).toBeTruthy();
  });

  it("ties a future date's message to the date field (F-R1)", async () => {
    routes["/api/payments/2026-10"] = { affiliates: [row({})] };
    record();
    const date = (await screen.findByLabelText("Transfer date")) as HTMLInputElement;
    fireEvent.change(date, { target: { value: "2999-01-01" } });
    expect(date.getAttribute("aria-invalid")).toBe("true");
    const message = document.getElementById(date.getAttribute("aria-describedby") ?? "");
    expect(message?.textContent).toContain("in the future");
  });

  it("shows where it went as a fact, not a locked control (F-R3)", async () => {
    routes["/api/payments/2026-10"] = { affiliates: [row({ destination_line: "InstaPay · 01000000001" })] };
    record();
    expect(await screen.findByText("InstaPay · 01000000001")).toBeTruthy();
    expect(screen.queryByRole("combobox")).toBeNull();
  });
});

describe("a model's month", () => {
  const statement = {
    affiliate_id: 1,
    name: "Sara Edris",
    month: "2026-10",
    basis: "approved",
    policy: "pending_inclusive",
    version: 1,
    approved_at: "2026-11-02T09:00:00Z",
    compensation_type: "commission",
    commission_rate_bp: 1000,
    counted_sales_piastres: 8_000_000,
    commission_piastres: 800_000,
    fixed_piastres: 0,
    guarantee_top_up_piastres: 0,
    bonus_piastres: 0,
    carried_piastres: 0,
    total_piastres: 800_000,
    guarantee: { base_amount_piastres: 0, target_known: false },
    blockers: [],
    source_version: null,
  };
  beforeEach(() => {
    routes["/api/payroll/2026-10/statement/1"] = statement;
    routes["/api/affiliates/1/payments"] = { name: "Sara Edris", payments: [] };
    routes["/api/affiliates/1/corrections"] = { corrections: [] };
  });
  const detail = () =>
    at(
      "/affiliates/payments/2026-10/1",
      "/affiliates/payments/:month/:affiliateId",
      <PaymentDetail session={session} />,
    );

  it("says the next act when the month is waiting to be sent (F-D2)", async () => {
    routes["/api/payments/2026-10"] = {
      affiliates: [
        row({ obligation_piastres: 800_000, balance_piastres: 800_000, destination: { method: "instapay" } }),
      ],
    };
    detail();
    const next = await screen.findByText(/then record the transfer here/);
    expect(next.textContent).toContain("Send EGP 8,000.00 to Sara’s InstaPay");
  });

  it("turns an overpayment into a warning that carries its act (F-D4)", async () => {
    routes["/api/payments/2026-10"] = {
      affiliates: [
        row({ state: "overpaid", obligation_piastres: 800_000, paid_piastres: 850_000, balance_piastres: -50_000 }),
      ],
    };
    detail();
    const warning = (await screen.findByText(/still to settle/)).closest(".pay-detail__warn") as HTMLElement;
    expect(warning.textContent).toContain("EGP 500.00 overpaid, still to settle.");
    // One source for the approved figure: the headline, not the warning (F2-1).
    expect(warning.textContent).not.toMatch(/EGP 8,[05]00/);
    expect(screen.getByRole("link", { name: "Settle the difference" }).getAttribute("href")).toBe(
      "/affiliates/payments/2026-10/1/reconcile",
    );
  });

  it("does not say EGP 0 remaining before anything is approved (F-D3)", async () => {
    routes["/api/payroll/2026-10/statement/1"] = {
      ...statement,
      basis: "estimate",
      source_version: "v1",
      approved_at: null,
      version: null,
    };
    routes["/api/payments/2026-10"] = {
      affiliates: [
        row({ state: "not_approved", required_kind: "forecast", obligation_piastres: 0, balance_piastres: 0 }),
      ],
    };
    detail();
    // No empty Transfers card before approval (F2-6), and never *EGP 0 remaining*.
    expect(await screen.findByRole("heading", { name: "Approval" })).toBeTruthy();
    expect(screen.queryByRole("heading", { name: "Transfers" })).toBeNull();
    expect(screen.queryByText(/remaining/)).toBeNull();
  });
});

describe("review round 2", () => {
  it("calls an overpayment's figure what is left to settle, not what was sent", () => {
    // Approved 8,000, sent 8,500, then 300 of the excess absorbed: still
    // overpaid, 200 open. "200 too much sent" would have been false.
    render(
      <MemoryRouter>
        <table><tbody>
          <PaymentRow
            row={row({ state: "overpaid", obligation_piastres: 800_000, paid_piastres: 850_000, adjusted_piastres: 30_000, balance_piastres: -20_000, required_piastres: 850_000 })}
            month="2026-10"
            canRecord
            canApprove
          />
        </tbody></table>
      </MemoryRouter>,
    );
    expect(document.querySelector(".payments__amount")?.textContent).toBe("EGP 8,000.00EGP 200.00 to settle");
  });
});
describe("a transfer's page", () => {
  it("is titled for the transfer and dated by when it was sent (F-T1, F-T2)", async () => {
    routes["/api/affiliates/1/payments"] = {
      name: "Sara Edris",
      payments: [
        {
          id: 5,
          amount_piastres: 500_000,
          occurred_at: "2026-11-03T12:00:00Z",
          reference: "IPN-1",
          note: null,
          has_proof: false,
          destination: null,
          allocations: [{ month: "2026-10", snapshot_id: 1, snapshot_version: 1, allocated_piastres: 500_000 }],
        },
      ],
    };
    at(
      "/affiliates/payments/2026-10/1/receipts/5",
      "/affiliates/payments/:month/:affiliateId/receipts/:paymentId",
      <PaymentReceipt />,
    );
    expect(await screen.findByRole("heading", { name: "Transfer" })).toBeTruthy();
    expect(screen.getByText("Sent on")).toBeTruthy();
    // Said once, in its row, not again as an empty box.
    expect(screen.getByText("Not attached")).toBeTruthy();
    expect(screen.queryByText(/No receipt attached/)).toBeNull();
  });
});

describe("a correction", () => {
  it("makes neither decision for them (F-C2)", async () => {
    routes["/api/affiliates/1/corrections"] = {
      name: "Sara Edris",
      corrections: [
        {
          affiliate_id: 1,
          month: "2026-10",
          agreed_piastres: 1_200_000,
          now_piastres: 1_080_000,
          paid_piastres: 500_000,
          recoverable_piastres: 120_000,
          snapshot_version: 1,
          shortfall_piastres: 120_000,
          resolved_piastres: 0,
          outstanding_piastres: 120_000,
          review_reason: null,
        },
      ],
    };
    at(
      "/affiliates/payments/2026-10/1/correction",
      "/affiliates/payments/:month/:affiliateId/correction",
      <PaymentCorrection session={session} />,
    );
    const options = await screen.findAllByRole("radio");
    expect(options.every((option) => option.getAttribute("aria-checked") === "false")).toBe(true);
    expect(
      (screen.getByRole("button", { name: "Choose what happens to it" }) as HTMLButtonElement).disabled,
    ).toBe(true);
    // Equal to the open difference, so said once (F-C1).
    expect(screen.queryByText(/Can be recovered/)).toBeNull();
  });
});
