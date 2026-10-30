// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Outlet, Route, Routes, useLocation } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { MyOrder } from "../../lib/portal";
import { MyOrders } from "../MyOrders";

/*
 * The Orders tab as a screen: which orders each filter holds, what an empty
 * one says, and what she sees when the list cannot be read (the Orders
 * audit of 27 September).
 */

const reply = (status: number, body: unknown) =>
  Promise.resolve({
    ok: status < 400,
    status,
    headers: { get: () => "application/json" },
    json: () => Promise.resolve(body),
    text: () => Promise.resolve(JSON.stringify(body)),
  } as unknown as Response);

const order = (number: string, patch: Partial<MyOrder>): MyOrder =>
  ({
    order_number: number,
    shopify_order_id: number,
    placed_at: "2026-09-08T12:00:00+00:00",
    contents: [],
    base_piastres: 100_000,
    base: "EGP 1,000.00",
    state: "earned",
    status: "delivered",
    state_text: "Delivered",
    rate_bp: 1000,
    failed_after_approval: false,
    net_sales: { kind: "known", piastres: 100_000, amount: "EGP 1,000.00" },
    counts_towards: { decision: "counted", month: "2026-09" },
    delivered_at: null,
    paid_in_month: null,
    commission_piastres: 10_000,
    commission: "EGP 100.00",
    counted: true,
    rate_missing: false,
    placed_piastres: null,
    placed: null,
    forgone_piastres: null,
    forgone: null,
    ...patch,
  }) as MyOrder;

const voided = { state: "void" as const, commission: null, commission_piastres: null, counted: false };

const everyCase = [
  order("#1", {}),
  order("#2", { state: "pending", status: "pending", state_text: "Pending" }),
  order("#3", { ...voided, status: "failed", state_text: "Failed delivery" }),
  order("#4", { ...voided, status: "cancelled", state_text: "Cancelled" }),
  order("#5", { ...voided, status: "refunded", state_text: "Refunded" }),
];

const earnings = (orders: MyOrder[], daysLeft: number | null = 3) => ({
  month: "2026-09",
  window: { opens: "2026-09-01", closes: "2026-09-30", progress_pct: 90, days_left: daysLeft },
  orders_detail: orders,
});

let fetchMock: ReturnType<typeof vi.fn>;

beforeEach(() => {
  fetchMock = vi.fn(() => reply(200, earnings(everyCase)));
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

function Where() {
  return <span data-testid="where">{useLocation().search}</span>;
}

function renderOrders(path = "/orders", showWhere = false) {
  const context = { me: {}, month: "2026-09", months: ["2026-09"], setMonth: vi.fn(), reload: vi.fn() };
  render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route element={<Outlet context={context} />}>
          <Route path="/orders" element={<><MyOrders />{showWhere && <Where />}</>} />
        </Route>
      </Routes>
    </MemoryRouter>,
  );
}

const pressed = () =>
  screen.getAllByRole("button").find((button) => button.getAttribute("aria-pressed") === "true")?.textContent;

describe("the Orders tab", () => {
  it("files every order that did not count under Failed, each row naming which", async () => {
    renderOrders();
    await waitFor(() => expect(screen.getByRole("button", { name: "Failed 3" })).toBeTruthy());

    expect(screen.getByRole("button", { name: "All 5" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Delivered 1" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Pending 1" })).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "Failed 3" }));
    for (const chip of ["Failed delivery", "Cancelled", "Refunded"]) expect(screen.getByText(chip)).toBeTruthy();
    expect(screen.queryByText("Delivered", { selector: ".orders__pill" })).toBeNull();
  });

  it("opens on the filter Home's counts link to", async () => {
    renderOrders("/orders?status=void");
    await waitFor(() => expect(pressed()).toBe("Failed 3"));
  });

  it("says an empty filter is empty, in the month on screen", async () => {
    fetchMock.mockImplementation(() => reply(200, earnings([everyCase[1]])));
    renderOrders();
    await waitFor(() => expect(screen.getByRole("button", { name: "Delivered 0" })).toBeTruthy());

    // Pending orders count (ADR 0040): *nothing has counted yet* was untrue.
    fireEvent.click(screen.getByRole("button", { name: "Delivered 0" }));
    expect(screen.getByText("No delivered orders in September 2026.")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Failed 0" }));
    expect(screen.getByText("No failed orders in September 2026.")).toBeTruthy();
  });

  it("says *yet* only while the month can still take an order", async () => {
    fetchMock.mockImplementation(() => reply(200, earnings([], 3)));
    renderOrders();
    await waitFor(() => expect(screen.getByText("No orders used your code in September 2026 yet.")).toBeTruthy());
    cleanup();

    fetchMock.mockImplementation(() => reply(200, earnings([], null)));
    renderOrders();
    await waitFor(() => expect(screen.getByText("No orders used your code in September 2026.")).toBeTruthy());
  });

  it("keeps the why of a pending order behind an ⓘ, and says when it is open (ADR 0050)", async () => {
    renderOrders();
    await waitFor(() => expect(screen.getByText("#2")).toBeTruthy());

    fireEvent.click(screen.getByText("#2"));
    const info = screen.getByRole("button", { name: "How this order is counted" });
    expect(info.getAttribute("aria-expanded")).toBe("false");
    expect(screen.queryByText(/while it is on its way/)).toBeNull();

    fireEvent.click(info);
    expect(info.getAttribute("aria-expanded")).toBe("true");
    expect(screen.getByText(/Counted in September 2026 while it is on its way/)).toBeTruthy();
  });

  it("gives a delivered order no ⓘ: its facts say it all", async () => {
    renderOrders();
    await waitFor(() => expect(screen.getByText("#1")).toBeTruthy());

    fireEvent.click(screen.getByText("#1"));
    expect(screen.getByText("10% of net sales")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "How this order is counted" })).toBeNull();
  });

  it("keeps the chosen filter in the address, so Back and a refresh return to it", async () => {
    renderOrders("/orders", true);
    await waitFor(() => expect(screen.getByRole("button", { name: "Failed 3" })).toBeTruthy());

    fireEvent.click(screen.getByRole("button", { name: "Failed 3" }));
    expect(screen.getByTestId("where").textContent).toBe("?status=void");
    fireEvent.click(screen.getByRole("button", { name: "All 5" }));
    expect(screen.getByTestId("where").textContent).toBe("");
  });

  it("says it is loading in the page's own shape", async () => {
    fetchMock.mockImplementation(() => new Promise(() => {}));
    renderOrders();
    expect(screen.getByRole("status").textContent).toContain("Loading your orders");
  });

  it("says what happens next under an empty month still open, and not under an ended one", async () => {
    fetchMock.mockImplementation(() => reply(200, earnings([], 3)));
    renderOrders();
    await waitFor(() => expect(screen.getByText(/Orders appear here as soon as someone uses your code/)).toBeTruthy());
    cleanup();

    fetchMock.mockImplementation(() => reply(200, earnings([], null)));
    renderOrders();
    await waitFor(() => expect(screen.getByText("No orders used your code in September 2026.")).toBeTruthy());
    expect(screen.queryByText(/Orders appear here/)).toBeNull();
  });

  it("keeps its title when the list cannot be read, and tries again", async () => {
    fetchMock.mockImplementationOnce(() => reply(500, { detail: "Internal error" }));
    renderOrders();
    await waitFor(() => expect(screen.getByRole("alert").textContent).toContain("Could not load your orders."));

    expect(screen.getByRole("heading", { name: "Orders" })).toBeTruthy();
    expect(screen.getByText("September 2026")).toBeTruthy();
    expect(screen.queryByText("Internal error")).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "All 5" })).toBeTruthy());
  });
});
