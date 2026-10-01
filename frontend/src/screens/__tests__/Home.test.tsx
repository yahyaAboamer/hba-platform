// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Outlet, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { MyMonth } from "../MyMonth";

/*
 * Home, batch L (the owner, 27 September), drawn from FITBROS10's September
 * on staging: 16 code uses beside 10 delivered, 3 pending, 0 failed - and 3
 * cancelled orders no chip used to show.
 */

const ok = (body: unknown) =>
  Promise.resolve({
    ok: true,
    status: 200,
    headers: { get: () => "application/json" },
    json: () => Promise.resolve(body),
    text: () => Promise.resolve(JSON.stringify(body)),
  } as unknown as Response);

const home = {
  month: "2026-09",
  earnings: {
    month: "2026-09",
    state: "open",
    policy: "pending_inclusive",
    is_working_month: true,
    not_started: false,
    sales: {
      counted_piastres: 1123287,
      counted: "EGP 11,232.87",
      counted_orders: 13,
      average_order_piastres: 86407,
      average_order: "EGP 864.07",
    },
    window: { opens: "2026-09-01", closes: "2026-09-30", progress_pct: 90, days_left: 3 },
    orders: { earned: 10, pending: 3, void: 3, failed_delivery: 0, counted: 13, uses: 16 },
    amount_piastres: 112300,
    amount: "EGP 1,123.00",
    makeup: [],
    carried_in: [],
    carried_out: [],
    guarantee_applied: false,
    guarantee: null,
    commission_rate_bp: 1000,
    waiting_on: [],
  },
  outcomes: { delivered: 10, pending: 3, failed: 0, cancelled: 3, refunded: 0 },
  payments: { months: [], payments: [], adjustments: [], outstanding_piastres: 0 },
  year: {
    months: [
      { month: "2026-08", sales_piastres: 1410000, uses: 19, in_progress: false },
      { month: "2026-09", sales_piastres: 1123287, uses: 16, in_progress: true },
    ],
  },
  rank: { rank: 4, of: 18 },
  content: null,
  best_seller: { title: "Everyday set", quantity: 5, sales_piastres: 400000, sales: "EGP 4,000.00" },
  comparison: {
    previous_month: "2026-08",
    window: "1–27 Aug",
    running: true,
    now: "EGP 11,232.87",
    before: "EGP 10,000.00",
    change_pct: 12,
  },
  share: { code: "FITBROS10", url: "https://hba-wear.myshopify.com/discount/FITBROS10" },
};

let fetchMock: ReturnType<typeof vi.fn>;

beforeEach(() => {
  // The expected payment date is judged against today; fix today.
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(new Date("2026-09-27T10:00:00Z"));
  fetchMock = vi.fn((url: string) =>
    String(url).includes("/api/me/home/") ? ok(home) : ok({}),
  );
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

function renderHome() {
  const context = {
    me: {},
    month: "2026-09",
    months: ["2026-09", "2026-08"],
    setMonth: vi.fn(),
    reload: vi.fn(),
  };
  render(
    <MemoryRouter initialEntries={["/"]}>
      <Routes>
        <Route element={<Outlet context={context} />}>
          <Route index element={<MyMonth />} />
        </Route>
      </Routes>
    </MemoryRouter>,
  );
  return context;
}

describe("Home", () => {
  it("asks the server once, for everything", async () => {
    renderHome();
    await waitFor(() => expect(screen.getByText("EGP 1,123.00")).toBeTruthy());

    const homeCalls = fetchMock.mock.calls.filter(([url]) => String(url).includes("/api/me/"));
    expect(homeCalls.map(([url]) => String(url))).toEqual(["/api/me/home/2026-09"]);
  });

  it("shows her orders in the Orders tab's three states, failed holding every void one", async () => {
    fetchMock.mockImplementation((url: string) =>
      String(url).includes("/api/me/home/")
        ? ok({ ...home, outcomes: { delivered: 10, pending: 3, failed: 1, cancelled: 2, refunded: 1 } })
        : ok({}),
    );
    renderHome();
    await waitFor(() => expect(screen.getByText("4 failed")).toBeTruthy());

    expect(screen.getByText("10 delivered")).toBeTruthy();
    expect(screen.getByText("3 pending")).toBeTruthy();
    // Cancelled, refunded and a failed delivery are one state here, as they
    // are one filter on the Orders tab; each row there still names which.
    expect(screen.queryByText(/cancelled|refunded|failed delivery/)).toBeNull();
  });

  it("opens each count's own orders, and the head opens them all", async () => {
    renderHome();
    await waitFor(() => expect(screen.getByText("10 delivered")).toBeTruthy());

    const orders = screen.getByRole("region", { name: "Orders" });
    const links = Array.from(orders.querySelectorAll("a"), (a) => a.getAttribute("href"));
    expect(links).toEqual(["/orders", "/orders?status=earned", "/orders?status=pending", "/orders?status=void"]);
    // Never a link inside a link: the card itself is not one.
    expect(orders.tagName).toBe("SECTION");
    expect(orders.querySelector("a a")).toBeNull();
    expect(screen.getByRole("link", { name: /16 code uses\s*, see all orders/ })).toBeTruthy();
  });

  it("does not paint a count of nothing as a warning, or offer a way into it", async () => {
    fetchMock.mockImplementation((url: string) =>
      String(url).includes("/api/me/home/")
        ? ok({ ...home, outcomes: { delivered: 10, pending: 3, failed: 0, cancelled: 0, refunded: 0 } })
        : ok({}),
    );
    renderHome();
    await waitFor(() => expect(screen.getByText("0 failed")).toBeTruthy());

    expect(screen.getByText("0 failed").className).toContain("home__key--none");
    expect(screen.getByText("0 failed").closest("a")).toBeNull();
  });

  it("compares like for like, and names the window", async () => {
    renderHome();
    await waitFor(() => expect(screen.getByText(/12% in sales vs 1–27 Aug/)).toBeTruthy());
  });

  it("names the month once, as the control that changes it", async () => {
    renderHome();
    await waitFor(() => expect(screen.getByRole("button", { name: /September 2026/ })).toBeTruthy());

    expect(screen.getAllByText("September 2026")).toHaveLength(1);
    fireEvent.click(screen.getByRole("button", { name: /September 2026/ }));
    expect(screen.getByRole("dialog", { name: "Choose a month" })).toBeTruthy();
  });

  it("says when the money arrives, in the first card", async () => {
    renderHome();
    await waitFor(() => expect(screen.getByText("Next payment")).toBeTruthy());

    expect(screen.getByText("Around 3 October")).toBeTruthy();
  });

  it("offers her code as a shop link, beside where she stands", async () => {
    renderHome();
    await waitFor(() => expect(screen.getByText("Share your code")).toBeTruthy());

    expect(screen.getByRole("button", { name: /Share/ })).toBeTruthy();
    expect(screen.getByText("#4")).toBeTruthy();
    expect(screen.getByText("of 18 models")).toBeTruthy();
    expect(screen.getByText("EGP 864.07")).toBeTruthy();
  });

  /*
   * Audit, 1 October 2026: Sara's October opened at EGP 10,000.00 earned above
   * EGP 0.00 in sales, with nothing saying the 10,000 was her salary.
   */
  it("splits a salaried month into her salary and her commission", async () => {
    fetchMock.mockImplementation((url: string) =>
      String(url).includes("/api/me/home/")
        ? ok({
            ...home,
            earnings: {
              ...home.earnings,
              amount_piastres: 1112300,
              amount: "EGP 11,123.00",
              split: {
                salary_piastres: 1000000,
                salary: "EGP 10,000.00",
                commission_piastres: 112300,
                commission: "EGP 1,123.00",
              },
            },
          })
        : ok({}),
    );
    renderHome();
    await waitFor(() => expect(screen.getByText("Monthly salary")).toBeTruthy());

    expect(screen.getByText("EGP 11,123.00")).toBeTruthy();
    expect(screen.getByText("EGP 10,000.00")).toBeTruthy();
    expect(screen.getByText("EGP 1,123.00")).toBeTruthy();
    expect(screen.getByText("10% of EGP 11,232.87 in sales")).toBeTruthy();
    // The single line is replaced, not repeated under the split.
    expect(screen.queryByText(/% commission/)).toBeNull();
  });

  /*
   * Owner, 1 October 2026: a guaranteed minimum is split out the way a salary
   * is. Ali's October: EGP 2,000.00 minimum, targets not recorded, so the
   * figure is his commission and the commission tile carries the accent.
   */
  const guaranteed = (applied: boolean, amount: string, commission: string) => ({
    ...home,
    earnings: {
      ...home.earnings,
      amount,
      guarantee_applied: applied,
      guarantee: {
        piastres: 200000,
        amount: "EGP 2,000.00",
        applied,
        commission_piastres: 0,
        commission,
        targets_achieved: applied ? true : null,
        targets_verified: applied,
      },
    },
  });

  it("splits a guaranteed month into the minimum and the commission", async () => {
    fetchMock.mockImplementation((url: string) =>
      String(url).includes("/api/me/home/")
        ? ok(guaranteed(false, "EGP 1,123.00", "EGP 1,123.00"))
        : ok({}),
    );
    renderHome();
    await waitFor(() => expect(screen.getByText("Guaranteed minimum")).toBeTruthy());

    expect(screen.getByText("EGP 2,000.00")).toBeTruthy();
    expect(screen.getByText("targets not recorded yet")).toBeTruthy();
    expect(screen.getByText("Commission")).toBeTruthy();
    expect(screen.getByText("10% of EGP 11,232.87 in sales")).toBeTruthy();
    // The rule is behind the minimum's ⓘ (owner, 1 October 2026).
    expect(screen.queryByText(/paid the higher of the two/)).toBeNull();
    const info = screen.getByRole("button", { name: "How the guaranteed minimum works" });
    expect(info.getAttribute("aria-expanded")).toBe("false");
    fireEvent.click(info);
    expect(info.getAttribute("aria-expanded")).toBe("true");
    expect(screen.getByText(/paid the higher of the two/)).toBeTruthy();
    // The commission is the figure, so it carries the accent.
    expect(
      screen.getByText("Commission").parentElement?.className,
    ).toContain("home__split--grows");
    expect(screen.queryByText(/% commission/)).toBeNull();
  });

  /*
   * Owner, 1 October 2026: what the month waits on was a paragraph under the
   * card. It is one line now, and the sentence is behind its ⓘ.
   */
  it("keeps what the month is waiting on behind an ⓘ", async () => {
    const sentence = "Nobody has recorded what you posted this month yet.";
    fetchMock.mockImplementation((url: string) =>
      String(url).includes("/api/me/home/")
        ? ok({
            ...home,
            earnings: { ...home.earnings, waiting_on: [{ who: "hba", text: sentence }] },
          })
        : ok({}),
    );
    renderHome();
    await waitFor(() => expect(screen.getByText("Waiting on HBA")).toBeTruthy());

    expect(screen.queryByText(sentence)).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "What this month is waiting on" }));
    expect(screen.getByText(sentence)).toBeTruthy();
  });

  it("says in words when the minimum is what is paid", async () => {
    fetchMock.mockImplementation((url: string) =>
      String(url).includes("/api/me/home/")
        ? ok(guaranteed(true, "EGP 2,000.00", "EGP 112.30"))
        : ok({}),
    );
    renderHome();
    await waitFor(() => expect(screen.getByText("targets met · paid this month")).toBeTruthy());

    expect(screen.getByText("EGP 112.30")).toBeTruthy();
    expect(
      screen.getByText("Guaranteed minimum").closest(".home__split > div")?.className,
    ).toContain("home__split--grows");
  });

  /*
   * ADR 0054: a settled month is a normal month. Only its pill and its
   * payment line say otherwise.
   */
  it("shows a settled month like any other, paid directly by HBA", async () => {
    fetchMock.mockImplementation((url: string) =>
      String(url).includes("/api/me/home/")
        ? ok({ ...home, earnings: { ...home.earnings, state: "historical" } })
        : ok({}),
    );
    renderHome();
    await waitFor(() => expect(screen.getByText("Paid directly by HBA")).toBeTruthy());

    expect(screen.getByText("Settled")).toBeTruthy();
    expect(screen.getByText("Earned")).toBeTruthy();
    expect(screen.getByText("EGP 1,123.00")).toBeTruthy();
    expect(screen.getByText("EGP 864.07")).toBeTruthy();
    expect(screen.queryByText(/not available/)).toBeNull();
  });

  it("shows a settled month with no terms as its sales, never as 'not available yet'", async () => {
    fetchMock.mockImplementation((url: string) =>
      String(url).includes("/api/me/home/")
        ? ok({
            ...home,
            earnings: {
              ...home.earnings,
              state: "historical",
              amount_piastres: null,
              amount: null,
              commission_rate_bp: null,
              note: "HBA settled this month with you directly, so only your sales are shown here.",
            },
          })
        : ok({}),
    );
    renderHome();
    await waitFor(() => expect(screen.getByText("Sales")).toBeTruthy());

    expect(document.querySelector(".home__amount")?.textContent).toBe("EGP 11,232.87");
    expect(screen.getByText(/settled this month with you directly/)).toBeTruthy();
    expect(screen.queryByText(/yet\./)).toBeNull();
  });
});
