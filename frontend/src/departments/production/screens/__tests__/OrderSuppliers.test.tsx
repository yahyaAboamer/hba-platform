// @vitest-environment jsdom
import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { FromPurchases, OrderView } from "../types";
import { makeOrder, mockApi, narrowScreen, owner, qc, renderAt, reply } from "./fixtures";
import type { Call } from "./fixtures";

const ADDRESS = "/production/orders/3";

const FLEECE = { id: 1, item: "Heavy fleece, black", supplier: { id: "fac", name: "Main factory" }, total_piastres: 17_200_000 };
const ZIPS = { id: 2, item: "Zips", supplier: { id: "fac", name: "Main factory" }, total_piastres: 300_000 };

/** `cost.from_purchases` as the server sends it: fabric and accessories bought, printing and packaging not. */
function fromPurchases(over: Partial<FromPurchases> = {}): FromPurchases {
  return {
    pieces: 972,
    basis: "cut",
    parts: [
      { part: "fabric", label: "Fabric", purchases: [FLEECE], total_piastres: 17_200_000, per_piece_piastres: 17_695 },
      { part: "printing", label: "Printing", purchases: [], total_piastres: 0, per_piece_piastres: null },
      { part: "accessories", label: "Accessories", purchases: [ZIPS], total_piastres: 300_000, per_piece_piastres: 309 },
      { part: "packaging", label: "Special packaging", purchases: [], total_piastres: 0, per_piece_piastres: null },
    ],
    other: { purchases: [], total_piastres: 0 },
    ...over,
  };
}

function ownersOrder(over: Partial<OrderView> = {}, bought: FromPurchases | null = fromPurchases()): OrderView {
  const order = makeOrder("cutting", { money: true, extra: over });
  if (order.cost && bought) order.cost.from_purchases = bought;
  return order;
}

const writes = (calls: Call[]) => calls.filter((call) => call.method !== "GET");
const costCard = (): HTMLElement => screen.getByRole("heading", { name: "Cost per piece" }).closest("section")!;
const rowOf = (part: string): HTMLElement => within(costCard()).getByText(part, { selector: "td" }).closest("tr")!;

function serve(order: OrderView, extra: Record<string, unknown> = {}) {
  return mockApi({
    "GET /api/prod/orders/3": { order },
    "GET /api/prod/orders/3/history": { events: [] },
    "GET /api/prod/orders/3/files": { files: [] },
    ...extra,
  });
}

beforeEach(() => narrowScreen(false));
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("The cost card: from purchases", () => {
  it("shows, per part, what the purchases say it costs per piece, and nothing for a part with none", async () => {
    serve(ownersOrder());
    renderAt(ADDRESS, owner());
    await screen.findByRole("heading", { level: 1, name: "Oversized hoodie · Black" });

    const fabric = rowOf("Fabric");
    expect(within(fabric).getByText("From purchases: EGP 176.95 per piece")).toBeTruthy();
    expect(fabric.textContent).toContain("Heavy fleece, black (Main factory) · EGP 172,000.00 over 972 cut pieces");
    expect(within(rowOf("Accessories")).getByText("From purchases: EGP 3.09 per piece")).toBeTruthy();
    for (const part of ["Printing", "Special packaging", "Manufacturing"]) {
      expect(rowOf(part).textContent).not.toContain("From purchases");
      expect(within(rowOf(part)).queryByRole("button", { name: /^Use this/ })).toBeNull();
    }
  });

  it("says over how many pieces: those planned until cutting is done", async () => {
    serve(ownersOrder({}, fromPurchases({ basis: "planned", pieces: 1000 })));
    renderAt(ADDRESS, owner());
    await screen.findByRole("heading", { level: 1, name: "Oversized hoodie · Black" });
    expect(rowOf("Fabric").textContent).toContain("over 1,000 planned pieces");
  });

  it("sets that part's actual cost with Use this, through the order's own edit, and says so", async () => {
    const after = ownersOrder();
    after.cost!.parts[0].actual_piastres = 17_695;
    const calls = serve(ownersOrder(), { "PATCH /api/prod/orders/3": () => ({ order: after }) });
    renderAt(ADDRESS, owner());
    await screen.findByRole("heading", { level: 1, name: "Oversized hoodie · Black" });

    fireEvent.click(within(rowOf("Fabric")).getByRole("button", { name: /^Use this/ }));
    await waitFor(() => expect(screen.getByRole("status").textContent).toBe("Fabric actual cost set to EGP 176.95 per piece."));
    // Only that part is sent, and as piastres.
    expect(writes(calls).map((call) => [call.method, call.path, call.body])).toEqual([["PATCH", "/api/prod/orders/3", { actual_fabric_piastres: 17_695 }]]);
    // The figure is in, so the button has gone and the row says why; focus is on the card, not lost.
    expect(within(rowOf("Fabric")).queryByRole("button", { name: /^Use this/ })).toBeNull();
    expect(rowOf("Fabric").textContent).toContain("This is already the actual cost.");
    expect(document.activeElement).toBe(screen.getByRole("heading", { name: "Cost per piece" }));
    // The other part still offers its own.
    expect(within(rowOf("Accessories")).getByRole("button", { name: /^Use this/ })).toBeTruthy();
  });

  it("sets accessories on its own key", async () => {
    const calls = serve(ownersOrder(), { "PATCH /api/prod/orders/3": () => ({ order: ownersOrder() }) });
    renderAt(ADDRESS, owner());
    await screen.findByRole("heading", { level: 1, name: "Oversized hoodie · Black" });
    fireEvent.click(within(rowOf("Accessories")).getByRole("button", { name: /^Use this/ }));
    await waitFor(() => expect(writes(calls)).toHaveLength(1));
    expect(writes(calls)[0].body).toEqual({ actual_accessories_piastres: 309 });
  });

  it("shows the server's refusal in the card", async () => {
    serve(ownersOrder(), { "PATCH /api/prod/orders/3": () => reply(409, { detail: "A cancelled or closed order can't be changed." }) });
    renderAt(ADDRESS, owner());
    await screen.findByRole("heading", { level: 1, name: "Oversized hoodie · Black" });
    fireEvent.click(within(rowOf("Fabric")).getByRole("button", { name: /^Use this/ }));
    expect((await within(costCard()).findByRole("alert")).textContent).toBe("A cancelled or closed order can't be changed.");
  });

  it("offers Use this only while the order is open", async () => {
    serve(ownersOrder({ status: "closed" }));
    renderAt(ADDRESS, owner());
    await screen.findByRole("heading", { level: 1, name: "Oversized hoodie · Black" });
    expect(within(rowOf("Fabric")).getByText("From purchases: EGP 176.95 per piece")).toBeTruthy();
    expect(within(costCard()).queryByRole("button", { name: /^Use this/ })).toBeNull();
  });

  it("says what other purchases for the order are not counted in a part", async () => {
    serve(ownersOrder({}, fromPurchases({ other: { purchases: [{ id: 9, item: "Courier bags", supplier: { id: "fac", name: "Main factory" }, total_piastres: 12_500 }], total_piastres: 12_500 } })));
    renderAt(ADDRESS, owner());
    await screen.findByRole("heading", { level: 1, name: "Oversized hoodie · Black" });
    expect(costCard().textContent).toContain("Other purchases for this order, not counted in a part: EGP 125.00 (Courier bags).");
  });

  it("draws nothing of it when the order carries no purchases figure, and nothing at all for the QC manager", async () => {
    serve(ownersOrder({}, null));
    renderAt(ADDRESS, owner());
    await screen.findByRole("heading", { level: 1, name: "Oversized hoodie · Black" });
    expect(costCard().textContent).not.toContain("From purchases");
    cleanup();

    serve(makeOrder("cutting"));
    renderAt(ADDRESS, qc());
    await screen.findByRole("heading", { level: 1, name: "Oversized hoodie · Black" });
    expect(document.body.textContent).not.toMatch(/From purchases|Use this|EGP/);
  });
});

describe("The factory's name on the order page", () => {
  it("links to the supplier's page", async () => {
    serve(makeOrder("cutting"));
    renderAt(ADDRESS, qc());
    await screen.findByRole("heading", { level: 1, name: "Oversized hoodie · Black" });
    const link = screen.getByRole("link", { name: "Main factory" });
    expect(link.getAttribute("href")).toBe("/production/suppliers/SUP-1");
    expect(link.closest(".page__subtitle")!.textContent).toContain("PO-2611-01 · Main factory · fabric bought by HBA · printed at the factory");
  });

  it("links the print house too, when the order is printed outside", async () => {
    serve(makeOrder("cutting", { extra: { printing: "outside", print_supplier: { id: "prt", name: "Print house A" } } }));
    renderAt(ADDRESS, qc());
    await screen.findByRole("heading", { level: 1, name: "Oversized hoodie · Black" });
    expect(screen.getByRole("link", { name: "Print house A" }).getAttribute("href")).toBe("/production/suppliers/prt");
  });
});

describe("Use this, when the part is in what the factory is owed", () => {
  const stay = () => within(costCard()).getByRole("button", { name: "Keep it as it is" });

  it("asks first, inline, for fabric the factory bought, and sends nothing until the owner agrees", async () => {
    const after = ownersOrder({ fabric_bought_by: "factory" });
    const calls = serve(ownersOrder({ fabric_bought_by: "factory" }), { "PATCH /api/prod/orders/3": () => ({ order: after }) });
    const confirm = vi.spyOn(window, "confirm");
    renderAt(ADDRESS, owner());
    await screen.findByRole("heading", { level: 1, name: "Oversized hoodie · Black" });

    fireEvent.click(within(rowOf("Fabric")).getByRole("button", { name: /^Use this/ }));
    expect(writes(calls)).toEqual([]);
    expect(confirm).not.toHaveBeenCalled(); // inline, not window.confirm
    const group = within(costCard()).getByRole("group", { name: "Use the purchases' figure for Fabric" });
    expect(group.textContent).toContain("This changes what the factory is owed for this order.");
    expect(group.textContent).toContain("EGP 176.95 per piece");

    // Keeping it as it is writes nothing and brings the button back.
    fireEvent.click(stay());
    expect(writes(calls)).toEqual([]);
    expect(within(rowOf("Fabric")).getByRole("button", { name: /^Use this/ })).toBeTruthy();

    fireEvent.click(within(rowOf("Fabric")).getByRole("button", { name: /^Use this/ }));
    fireEvent.click(within(costCard()).getByRole("button", { name: "Yes, use it" }));
    await waitFor(() => expect(writes(calls)).toHaveLength(1));
    expect(writes(calls)[0].body).toEqual({ actual_fabric_piastres: 17_695 });
  });

  it("says so for printing when the factory prints, and acts at once when an outside house prints", async () => {
    const printed = fromPurchases({
      parts: fromPurchases().parts.map((part) =>
        part.part === "printing" ? { ...part, purchases: [{ ...ZIPS, id: 5, item: "Screens" }], total_piastres: 97_200, per_piece_piastres: 100 } : part,
      ),
    });
    const calls = serve(ownersOrder({ printing: "factory" }, printed), { "PATCH /api/prod/orders/3": () => ({ order: ownersOrder({}, printed) }) });
    renderAt(ADDRESS, owner());
    await screen.findByRole("heading", { level: 1, name: "Oversized hoodie · Black" });
    fireEvent.click(within(rowOf("Printing")).getByRole("button", { name: /^Use this/ }));
    expect(within(costCard()).getByRole("group").textContent).toContain("This changes what the factory is owed for this order.");
    expect(writes(calls)).toEqual([]);
    cleanup();

    serve(ownersOrder({ printing: "outside" }, printed), { "PATCH /api/prod/orders/3": () => ({ order: ownersOrder({}, printed) }) });
    renderAt(ADDRESS, owner());
    await screen.findByRole("heading", { level: 1, name: "Oversized hoodie · Black" });
    fireEvent.click(within(rowOf("Printing")).getByRole("button", { name: /^Use this/ }));
    await waitFor(() => expect(screen.getByRole("status").textContent).toContain("Printing actual cost set to EGP 1.00 per piece."));
    expect(within(costCard()).queryByRole("group")).toBeNull();
  });

  it("acts at once for fabric HBA bought and for accessories, which never touch the factory's pay", async () => {
    const calls = serve(ownersOrder({ fabric_bought_by: "hba" }), { "PATCH /api/prod/orders/3": () => ({ order: ownersOrder() }) });
    renderAt(ADDRESS, owner());
    await screen.findByRole("heading", { level: 1, name: "Oversized hoodie · Black" });
    expect(within(costCard()).queryByRole("group")).toBeNull();
    fireEvent.click(within(rowOf("Accessories")).getByRole("button", { name: /^Use this/ }));
    await waitFor(() => expect(writes(calls)).toHaveLength(1));
    expect(writes(calls)[0].body).toEqual({ actual_accessories_piastres: 309 });
  });
});
