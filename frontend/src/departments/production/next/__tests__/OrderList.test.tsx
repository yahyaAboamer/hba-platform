// @vitest-environment jsdom
import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { makeRow, mockApi, narrowScreen, owner, qc, renderAt } from "./fixtures";

const open = [
  makeRow({
    id: 1, style_name: "Oversized hoodie", colour: "Off-white", lateness_days: 6, delivery_date: "2030-11-26",
    flags: { late: true, waiting_for_owner: false, count_mismatch: false, fix_pieces_due: false },
  }),
  makeRow({
    id: 2, style_name: "Zip hoodie", colour: "Olive", stage: { key: "sample", label: "Sample", position: 2 },
    next_action: { stage: "sample", what: "Approve the sample", who: "owner", by: "2030-11-10", since: "2020-01-01" },
    flags: { late: false, waiting_for_owner: true, count_mismatch: false, fix_pieces_due: false },
  }),
  makeRow({ id: 3, style_name: "Boxy tee", colour: "Black", planned_total: 600, received_total: 300 }),
];
const closed = [
  makeRow({
    id: 4, style_name: "Wide-leg sweatpants", colour: "Grey", status: "closed", stage: null, finished_on: "2030-10-01",
    next_action: null, received_total: 800, planned_total: 800,
  }),
];

/** `status=closed` shares a path with `status=open`, so the table keys on the query too. */
function serveBoth() {
  const calls: string[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
      calls.push(url);
      const rows = url.includes("status=closed") ? closed : open;
      return new Response(JSON.stringify({ orders: rows }), { status: 200, headers: { "Content-Type": "application/json" } });
    }),
  );
  return calls;
}

beforeEach(() => narrowScreen(false));
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("Production orders list", () => {
  it("shows each order with its stage, counts, target date and next action", async () => {
    serveBoth();
    renderAt("/production/next/orders", owner());
    const table = await screen.findByRole("table");
    const rows = within(table).getAllByRole("row");
    // The header and three orders in production.
    expect(rows).toHaveLength(4);
    const first = rows[1];
    expect(within(first).getByRole("link", { name: "Oversized hoodie · Off-white" }).getAttribute("href")).toBe("/production/next/orders/1");
    expect(first.textContent).toContain("PO-2611-01");
    expect(first.textContent).toContain("Main factory");
    expect(first.textContent).toContain("7 of 10 · Making");
    expect(first.textContent).toContain("1,000");
    expect(first.textContent).toContain("Now due 26 Nov · 6 days late");
    expect(first.textContent).toContain("Final inspection");
    expect(first.textContent).toContain("QC manager · 26 Nov");
    expect(within(first).getByRole("img", { name: "5 of 10 stages done, 1 skipped" })).toBeTruthy();
    // Planned and received.
    expect(rows[3].textContent).toContain("600");
    expect(rows[3].textContent).toContain("300");
    expect(screen.getByText("3 in production, 2 need attention")).toBeTruthy();
  });

  it("filters by late, waiting for the owner and closed, with counts on the chips", async () => {
    serveBoth();
    renderAt("/production/next/orders", owner());
    await screen.findByRole("table");
    expect(screen.getByRole("button", { name: "In production · 3" }).getAttribute("aria-pressed")).toBe("true");

    fireEvent.click(screen.getByRole("button", { name: "Late · 1" }));
    let table = screen.getByRole("table");
    expect(within(table).getAllByRole("row")).toHaveLength(2);
    expect(table.textContent).toContain("Oversized hoodie");

    fireEvent.click(screen.getByRole("button", { name: "Waiting for owner · 1" }));
    table = screen.getByRole("table");
    expect(table.textContent).toContain("Zip hoodie");
    expect(table.textContent).toContain("Approve the sample");
    expect(table.textContent).toContain("Owner · waiting");

    fireEvent.click(screen.getByRole("button", { name: "Closed · 1" }));
    table = screen.getByRole("table");
    expect(table.textContent).toContain("Wide-leg sweatpants");
    expect(table.textContent).toContain("Settled and closed");
    expect(table.textContent).toContain("Finished on time");
  });

  it("offers New order to the owner only", async () => {
    serveBoth();
    renderAt("/production/next/orders", owner());
    expect((await screen.findByRole("link", { name: "New order" })).getAttribute("href")).toBe("/production/next/orders/new");
    cleanup();
    renderAt("/production/next/orders", qc());
    await screen.findByRole("table");
    expect(screen.queryByRole("link", { name: "New order" })).toBeNull();
  });

  it("is cards, not a table, on a phone", async () => {
    narrowScreen(true);
    serveBoth();
    renderAt("/production/next/orders", qc());
    await screen.findByRole("link", { name: "Oversized hoodie · Off-white" });
    expect(screen.queryByRole("table")).toBeNull();
    expect(document.querySelectorAll("article.prod-card")).toHaveLength(3);
  });

  it("says so when there is nothing, and when it cannot load", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ orders: [] }), { status: 200 })));
    renderAt("/production/next/orders", owner());
    expect(await screen.findByText(/No orders in production/)).toBeTruthy();
    cleanup();
    mockApi({ "GET /api/prod/orders": () => new Response(JSON.stringify({ detail: "The database is down." }), { status: 503 }) });
    renderAt("/production/next/orders", owner());
    expect((await screen.findByRole("alert")).textContent).toBe("The database is down.");
    await waitFor(() => expect(screen.getByRole("button", { name: "Try again" })).toBeTruthy());
  });
});

