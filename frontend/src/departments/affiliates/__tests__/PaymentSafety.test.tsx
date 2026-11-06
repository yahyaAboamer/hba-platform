// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { Session } from "../../../lib/api";
import { PaymentDetail } from "../PaymentDetail";
import { PaymentRecord } from "../PaymentRecord";
import type { Balance } from "../Payments";

/**
 * The payments audit of 6 November 2026, walked as a first-time payer.
 *
 * Approving froze a month on one click, the form only said it records rather
 * than sends after its button, a transfer could be dated in the future, and
 * sales × rate visibly failed to match a commission rounded to whole pounds.
 */

const reply = (status: number, body: unknown) =>
  Promise.resolve({
    ok: status < 400,
    status,
    headers: { get: () => "application/json" },
    json: () => Promise.resolve(body),
    text: () => Promise.resolve(JSON.stringify(body)),
  } as unknown as Response);

const balance = (extra: Partial<Balance> = {}): Balance => ({
  affiliate_id: 1,
  name: "Sara",
  status: "active",
  month: "2026-10",
  state: "not_approved",
  payroll_snapshot_id: null,
  obligation_piastres: 0,
  paid_piastres: 0,
  adjusted_piastres: 0,
  credited_piastres: 0,
  balance_piastres: 0,
  forecast_piastres: 1_432_600,
  forecast_blockers: [],
  required_kind: "forecast",
  required_piastres: 1_432_600,
  ...extra,
});

const statement = {
  affiliate_id: 1,
  name: "Sara",
  month: "2026-10",
  basis: "estimate",
  policy: null,
  version: null,
  approved_at: null,
  compensation_type: "fixed_plus_commission",
  commission_rate_bp: 1000,
  counted_sales_piastres: 4_326_480,
  commission_piastres: 432_600,
  fixed_piastres: 1_000_000,
  guarantee_top_up_piastres: 0,
  bonus_piastres: 0,
  carried_piastres: 0,
  total_piastres: 1_432_600,
  guarantee: { base_amount_piastres: 0, target_known: false },
  blockers: [],
  source_version: "v-1",
};

const session = { permissions: ["payroll.approve", "payments.record"] } as unknown as Session;

let fetchMock: ReturnType<typeof vi.fn>;
beforeEach(() => {
  fetchMock = vi.fn((url: string, init?: RequestInit) => {
    if (init?.method === "POST") {
      return reply(200, { results: [{ approved: true, stale: false, blockers: [] }] });
    }
    if (url.includes("/statement/")) return reply(200, statement);
    if (url.includes("/corrections")) return reply(200, { corrections: [] });
    if (url.includes("/api/affiliates/1/payments")) return reply(200, { name: "Sara", payments: [] });
    if (url.includes("/api/payments/2026-10")) {
      return reply(200, { affiliates: [balance()] });
    }
    return reply(404, { detail: "unexpected " + url });
  });
  vi.stubGlobal("fetch", fetchMock);
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const posts = () => fetchMock.mock.calls.filter(([, init]) => init?.method === "POST");

function detail() {
  render(
    <MemoryRouter initialEntries={["/affiliates/payments/2026-10/1"]}>
      <Routes>
        <Route
          path="/affiliates/payments/:month/:affiliateId"
          element={<PaymentDetail session={session} />}
        />
      </Routes>
    </MemoryRouter>,
  );
}

describe("approving a month", () => {
  it("asks once, naming who, which month and how much, before anything is sent", async () => {
    detail();
    fireEvent.click(await screen.findByRole("button", { name: "Approve this month" }));

    expect(posts()).toHaveLength(0);
    const question = screen.getByRole("group", { name: /Approve Sara’s October 2026 at/ });
    expect(question.textContent).toContain("EGP 14,326.00");
    expect(question.textContent).toMatch(/can.t undo this/);
    expect(document.activeElement).toBe(screen.getByRole("button", { name: /^Approve EGP 14,326\.00$/ }));
  });

  it("does nothing when cancelled", async () => {
    detail();
    fireEvent.click(await screen.findByRole("button", { name: "Approve this month" }));
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));

    expect(posts()).toHaveLength(0);
    // Focus goes back to the button that asked, not to the top of the page.
    expect(document.activeElement).toBe(
      screen.getByRole("button", { name: "Approve this month" }),
    );
  });

  it("approves on the second, deliberate press", async () => {
    detail();
    fireEvent.click(await screen.findByRole("button", { name: "Approve this month" }));
    fireEvent.click(screen.getByRole("button", { name: /^Approve EGP 14,326\.00$/ }));

    await waitFor(() => expect(posts()).toHaveLength(1));
    expect(String(posts()[0][0])).toContain("/api/payroll/2026-10/approve");
  });

  it("says the total is rounded to whole pounds", async () => {
    detail();
    expect(await screen.findByText(/rounded to the nearest whole pound/i)).toBeTruthy();
  });
});

describe("recording a transfer", () => {
  beforeEach(() => {
    fetchMock.mockImplementation((url: string) =>
      url.includes("/api/payments/2026-10")
        ? reply(200, {
            affiliates: [
              balance({
                state: "unpaid",
                required_kind: "approved",
                payroll_snapshot_id: 18,
                obligation_piastres: 1_432_600,
                balance_piastres: 1_432_600,
              }),
            ],
          })
        : reply(404, {}),
    );
  });

  function record() {
    render(
      <MemoryRouter initialEntries={["/affiliates/payments/2026-10/1/record"]}>
        <Routes>
          <Route path="/affiliates/payments/:month/:affiliateId/record" element={<PaymentRecord />} />
        </Routes>
      </MemoryRouter>,
    );
  }

  it("says it records rather than sends before anything else on the form", async () => {
    record();
    const lead = await screen.findByText(/Nothing is sent from here/);
    const amount = screen.getByLabelText("Amount transferred, EGP");
    expect(lead.compareDocumentPosition(amount) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it("refuses a transfer date in the future", async () => {
    record();
    const date = (await screen.findByLabelText("Transfer date")) as HTMLInputElement;
    expect(date.max).toMatch(/^\d{4}-\d{2}-\d{2}$/);

    fireEvent.change(date, { target: { value: "2999-01-01" } });

    expect(screen.getByRole("alert").textContent).toContain("in the future");
    expect(
      (screen.getByRole("button", { name: "Record payment" }) as HTMLButtonElement).disabled,
    ).toBe(true);
  });
});

/**
 * The phone shows the card for the month's next act first (CSS `order`,
 * keyed on `data-stage`). The stage is the logic worth holding: approve, then
 * send elsewhere, then nothing left.
 */
describe("what the month is waiting for", () => {
  const approvedStatement = { ...statement, basis: "approved", source_version: null, approved_at: "2026-11-06T10:00:00Z", version: 1 };

  function serve(row: Partial<Balance>, found: object) {
    fetchMock.mockImplementation((url: string) => {
      if (url.includes("/statement/")) return reply(200, found);
      if (url.includes("/corrections")) return reply(200, { corrections: [] });
      if (url.includes("/api/affiliates/1/payments")) return reply(200, { name: "Sara", payments: [] });
      if (url.includes("/api/payments/2026-10")) return reply(200, { affiliates: [balance(row)] });
      return reply(404, {});
    });
  }

  const side = () => document.querySelector(".pay-detail__side") as HTMLElement;

  it("is approval while the figure is an estimate, with no progress bar", async () => {
    detail();
    await screen.findByRole("button", { name: "Approve this month" });
    expect(side().dataset.stage).toBe("approve");
    expect(document.querySelector(".pay-detail__progress")).toBeNull();
  });

  it("is sending once approved with money left, and the bar shows the share recorded", async () => {
    serve(
      { state: "partially_paid", payroll_snapshot_id: 18, obligation_piastres: 1_000_000, paid_piastres: 250_000, balance_piastres: 750_000, required_kind: "approved" },
      approvedStatement,
    );
    detail();
    await screen.findByText("Transfers");
    expect(side().dataset.stage).toBe("send");
    expect((document.querySelector(".pay-detail__progress > span") as HTMLElement).style.width).toBe("25%");
  });

  it("is done once nothing is left to send", async () => {
    serve(
      { state: "settled", payroll_snapshot_id: 18, obligation_piastres: 1_000_000, paid_piastres: 1_000_000, balance_piastres: 0, required_kind: "approved" },
      approvedStatement,
    );
    detail();
    await screen.findByText("Transfers");
    expect(side().dataset.stage).toBe("done");
    expect((document.querySelector(".pay-detail__progress > span") as HTMLElement).style.width).toBe("100%");
  });
});
