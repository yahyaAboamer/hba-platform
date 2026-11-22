// @vitest-environment jsdom
import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { fabricLinesProblem } from "../FabricLines";
import { countOf, fabricBody, fabricProblem, blankFabric, kgOf, kgWords, moveWords, signedKg } from "../fabricLogic";
import type { FabricDetail, FabricMove, FabricRow, OrderView } from "../types";
import { makeOrder, makeRow, mockApi, narrowScreen, owner, qc, renderAt } from "./fixtures";
import type { Call } from "./fixtures";

function fabric(over: Partial<FabricRow> & { id: number; name: string }): FabricRow {
  return {
    fabric_type: "Cotton fleece 320 gsm",
    colour: "Black",
    colour_code: null,
    supplier: { id: "SUP-2", name: "Fabric supplier A" },
    active: true,
    in_stock_kg: "40.000",
    bought_kg: "100.000",
    used_kg: "60.000",
    orders: 1,
    ...over,
  };
}

const rows = (): FabricRow[] => [
  fabric({ id: 1, name: "Black fleece", price_per_kg_piastres: 18000 }),
  fabric({ id: 2, name: "White jersey", colour: "White", fabric_type: "Single jersey", in_stock_kg: "0.000", price_per_kg_piastres: null }),
  fabric({ id: 3, name: "Old rib", active: false, in_stock_kg: "2.500" }),
];

function move(over: Partial<FabricMove> & { id: number; kind: FabricMove["kind"]; kg: string }): FabricMove {
  return { created_at: "2026-11-20T10:00:00Z", by: "Owner", note: null, purchase: null, order: null, returned: false, ...over };
}

const detail = (): FabricDetail => ({
  fabric: { ...fabric({ id: 1, name: "Black fleece", price_per_kg_piastres: 18000 }), note: null },
  moves: [
    move({ id: 4, kind: "use", kg: "-25.000", order: { id: 3, code: "PO-2611-01" } }),
    move({ id: 3, kind: "count", kg: "-2.000", note: "Waste after cutting" }),
    move({ id: 1, kind: "purchase", kg: "100.000", purchase: { id: 9, item: "Black fleece rolls", supplier: { id: "SUP-2", name: "Fabric supplier A" } } }),
  ],
});

const forStaff = (row: FabricRow): FabricRow => {
  const copy = { ...row };
  delete copy.price_per_kg_piastres;
  return copy;
};

beforeEach(() => narrowScreen(false));
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("Fabric words and checks", () => {
  it("writes kilos without trailing zeros and reads typed kilos strictly", () => {
    expect(kgWords("12.500")).toBe("12.5 kg");
    expect(kgWords("1250.000")).toBe("1,250 kg");
    expect(kgWords(0.125)).toBe("0.125 kg");
    expect(signedKg("-3.000")).toBe("−3 kg");
    expect(signedKg("12.500")).toBe("+12.5 kg");
    expect(kgOf("12,5")).toBe(12.5);
    expect(kgOf("0")).toBeNull();
    expect(kgOf("1.2345")).toBeNull();
    expect(kgOf("abc")).toBeNull();
    expect(countOf("0")).toBe(0);
    expect(countOf("7.25")).toBe(7.25);
  });

  it("says each kind of move in words", () => {
    expect(moveWords(detail().moves[2])).toBe("Bought from Fabric supplier A: Black fleece rolls");
    expect(moveWords(move({ id: 5, kind: "use", kg: "-1.000", order: { id: 3, code: "PO-1" }, returned: true }))).toBe("Taken by PO-1 (given back since)");
    expect(moveWords(move({ id: 6, kind: "count", kg: "1.000" }))).toBe("Storage counted");
  });

  it("needs a name, and kilos that read when adding with some already in storage", () => {
    expect(fabricProblem(blankFabric(), true)).toBe("Give the fabric a name.");
    expect(fabricProblem({ ...blankFabric(), name: "Rib", inStorage: "lots" }, true)).not.toBeNull();
    expect(fabricBody({ ...blankFabric(), name: " Rib ", inStorage: "4.5", colour: " " }, true)).toEqual({
      name: "Rib", fabric_type: null, colour: null, colour_code: null, note: null, in_storage_kg: 4.5,
    });
    expect(fabricBody({ ...blankFabric(), name: "Rib", inStorage: "4.5" }, false)).not.toHaveProperty("in_storage_kg");
  });

  it("refuses an order's fabric lines that are blank, doubled or more than storage holds", () => {
    const choices = [{ id: 1, name: "Black fleece", colour: "Black", in_stock_kg: "40.000" }];
    expect(fabricLinesProblem([{ fabricId: "", kg: "5" }], choices)).toMatch(/Choose a fabric/);
    expect(fabricLinesProblem([{ fabricId: "1", kg: "5" }, { fabricId: "1", kg: "2" }], choices)).toMatch(/two lines/);
    expect(fabricLinesProblem([{ fabricId: "1", kg: "41" }], choices)).toBe("Only 40 kg of Black fleece is in storage.");
    expect(fabricLinesProblem([{ fabricId: "1", kg: "40" }], choices)).toBeNull();
  });
});

describe("The Fabric list", () => {
  it("lists the fabrics in use with their kilos and, for the owner, the price a kg", async () => {
    mockApi({ "GET /api/prod/fabrics": { fabrics: rows() } });
    renderAt("/production/fabric", owner());
    const table = await screen.findByRole("table");
    const lines = within(table).getAllByRole("row").slice(1);
    expect(lines).toHaveLength(2);
    expect(within(lines[0]).getByRole("link", { name: "Black fleece" }).getAttribute("href")).toBe("/production/fabric/1");
    expect(lines[0].textContent).toContain("40 kg");
    expect(lines[0].textContent).toContain("EGP 180.00 a kg");
    expect(lines[1].textContent).toContain("Not bought yet");
    expect(screen.getByText("2 fabrics · 40 kg in storage")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "No longer used · 1" }));
    expect(within(screen.getByRole("table")).getByRole("link", { name: "Old rib" })).toBeTruthy();
  });

  it("never shows the QC manager a price", async () => {
    mockApi({ "GET /api/prod/fabrics": { fabrics: rows().map(forStaff) } });
    renderAt("/production/fabric", qc());
    const table = await screen.findByRole("table");
    expect(table.textContent).not.toContain("EGP");
    expect(within(table).queryByRole("columnheader", { name: "Price" })).toBeNull();
  });

  it("adds a fabric with the kilos already in storage, then opens it", async () => {
    const calls = mockApi({
      "GET /api/prod/fabrics": { fabrics: rows() },
      "POST /api/prod/fabrics": { fabric: { ...fabric({ id: 7, name: "Navy rib" }), note: null } },
      "GET /api/prod/fabrics/7": { fabric: { ...fabric({ id: 7, name: "Navy rib" }), note: null }, moves: [] },
    });
    renderAt("/production/fabric", qc());
    fireEvent.click(await screen.findByRole("button", { name: "Add a fabric" }));
    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "Navy rib" } });
    fireEvent.change(screen.getByLabelText("Already in storage, kg"), { target: { value: "12.5" } });
    fireEvent.click(screen.getByRole("button", { name: "Add fabric" }));
    expect(await screen.findByRole("heading", { level: 1, name: "Navy rib" })).toBeTruthy();
    expect(calls.find((call) => call.method === "POST")!.body).toMatchObject({ name: "Navy rib", in_storage_kg: 12.5 });
  });
});

describe("One fabric", () => {
  it("shows its kilos, its price for the owner, and every kilo in and out", async () => {
    mockApi({ "GET /api/prod/fabrics/1": detail() });
    renderAt("/production/fabric/1", owner());
    expect(await screen.findByRole("heading", { level: 1, name: "Black fleece" })).toBeTruthy();
    expect(screen.getByText("Price a kg").nextElementSibling?.textContent).toBe("EGP 180.00");
    const history = screen.getByRole("region", { name: "Every kilo in and out" });
    const lines = within(history).getAllByRole("row").slice(1);
    expect(lines[0].textContent).toContain("Taken by PO-2611-01");
    expect(within(lines[0]).getByRole("link", { name: "PO-2611-01" }).getAttribute("href")).toBe("/production/orders/3");
    expect(lines[0].textContent).toContain("−25 kg");
    expect(lines[1].textContent).toContain("Waste after cutting");
    expect(lines[2].textContent).toContain("+100 kg");
  });

  it("counts storage with a reason, and refuses one without", async () => {
    const after = { ...detail(), fabric: { ...detail().fabric, in_stock_kg: "38.000" } };
    const calls = mockApi({ "GET /api/prod/fabrics/1": detail(), "POST /api/prod/fabrics/1/count": after });
    renderAt("/production/fabric/1", qc());
    fireEvent.click(await screen.findByRole("button", { name: "Count storage" }));
    fireEvent.change(screen.getByLabelText("Kilos in storage now"), { target: { value: "38" } });
    fireEvent.click(screen.getByRole("button", { name: "Save count" }));
    expect(await screen.findByText(/Say why storage is being corrected/)).toBeTruthy();
    fireEvent.change(screen.getByLabelText("Why"), { target: { value: "Recounted the rolls" } });
    fireEvent.click(screen.getByRole("button", { name: "Save count" }));
    expect(await screen.findByText("Count saved.")).toBeTruthy();
    expect(calls.find((call) => call.method === "POST")!.body).toEqual({ kg_in_storage: 38, note: "Recounted the rolls" });
    expect(screen.getByText("In storage").nextElementSibling?.textContent).toBe("38 kg");
  });
});

describe("Fabric on an order", () => {
  const ADDRESS = "/production/orders/3";
  const withUses = (extra: Partial<OrderView> = {}, money = false) =>
    makeOrder("cutting", { money, extra: { fabric_uses: [{ move_id: 4, fabric: { id: 1, name: "Black fleece", colour: "Black" }, kg: "25.000" }], ...extra } });
  function serve(order: OrderView, extra: Record<string, unknown> = {}) {
    return mockApi({
      "GET /api/prod/orders/3": { order },
      "GET /api/prod/orders/3/history": { events: [] },
      "GET /api/prod/orders/3/files": { files: [] },
      "GET /api/prod/fabrics": { fabrics: rows() },
      ...extra,
    });
  }
  const card = () => screen.getByRole("heading", { name: "Fabric from storage", level: 2 }).closest("section")!;
  const writes = (calls: Call[]) => calls.filter((call) => call.method !== "GET");

  it("lists what the order took, and takes more from a fabric that has some", async () => {
    const calls = serve(withUses(), { "POST /api/prod/orders/3/fabric": { order: withUses() } });
    renderAt(ADDRESS, qc());
    await screen.findByRole("heading", { name: "Fabric from storage", level: 2 });
    expect(card().textContent).toContain("25 kg");
    fireEvent.click(within(card()).getByRole("button", { name: "Take fabric" }));
    const select = (await within(card()).findByLabelText("Fabric")) as HTMLSelectElement;
    // A fabric with nothing in storage, and one no longer used, are not offered.
    expect(Array.from(select.options).map((option) => option.textContent)).toEqual(["Choose a fabric…", "Black fleece · Black · 40 kg in storage"]);
    fireEvent.change(select, { target: { value: "1" } });
    fireEvent.change(within(card()).getByLabelText("Kilos"), { target: { value: "5.5" } });
    fireEvent.click(within(card()).getByRole("button", { name: "Take from storage" }));
    expect(await screen.findByText("Took 5.5 kg of Black fleece from storage.")).toBeTruthy();
    expect(writes(calls)[0]).toMatchObject({ method: "POST", path: "/api/prod/orders/3/fabric", body: { fabric_id: 1, kg: 5.5 } });
  });

  it("gives fabric back after asking", async () => {
    const calls = serve(withUses(), { "DELETE /api/prod/orders/3/fabric/4": { order: makeOrder("cutting") } });
    renderAt(ADDRESS, qc());
    await screen.findByRole("heading", { name: "Fabric from storage", level: 2 });
    fireEvent.click(within(card()).getByRole("button", { name: "Give back 25 kg of Black fleece" }));
    fireEvent.click(within(card()).getByRole("button", { name: "Give back" }));
    expect(await screen.findByText("Gave back 25 kg of Black fleece to storage.")).toBeTruthy();
    expect(writes(calls)[0]).toMatchObject({ method: "DELETE", path: "/api/prod/orders/3/fabric/4" });
  });

  it("says the factory buys the fabric, and offers nothing to take", async () => {
    serve(makeOrder("cutting", { extra: { fabric_bought_by: "factory", fabric_uses: [] } }));
    renderAt(ADDRESS, owner());
    await screen.findByRole("heading", { level: 1 });
    expect(screen.queryByRole("heading", { name: "Fabric from storage", level: 2 })).toBeNull();
  });

  it("offers the owner the fabric cost from storage as the actual fabric cost", async () => {
    const order = withUses({ fabric_cost: { total_piastres: 450000, per_piece_piastres: 15000, pieces: 30, basis: "cut" } }, true);
    const calls = serve(order, { "PATCH /api/prod/orders/3": { order } });
    renderAt(ADDRESS, owner());
    await screen.findByRole("heading", { name: "Cost per piece", level: 2 });
    expect(screen.getByText("From fabric storage: EGP 150.00 per piece")).toBeTruthy();
    expect(screen.getByText(/EGP 4,500.00 for the fabric this order took, over 30 cut pieces/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: /from fabric storage/ }));
    await waitFor(() => expect(writes(calls)).toHaveLength(1));
    expect(writes(calls)[0]).toMatchObject({ method: "PATCH", body: { actual_fabric_piastres: 15000 } });
  });
});

describe("Fabric on the New order form", () => {
  const choices = {
    suppliers: [{ id: "SUP-1", name: "Main factory", category: "Manufacturer" }],
    products: [{ id: "P1", title: "Oversized hoodie", status: "active", image_url: null }],
    sizes: ["XS", "S", "M", "L", "XL", "XXL"],
    stage_days: { sample: 7, materials: 7, fabric_check: 2, pattern_check: 3, cutting: 2, making: 17, final_inspection: 1, warehouse: 3, settle: 7 },
    fabrics: [{ id: 1, name: "Black fleece", colour: "Black", in_stock_kg: "40.000" }],
  };

  it("sends the fabric lines with the order, and refuses more than storage holds before sending", async () => {
    const calls = mockApi({ "GET /api/prod/choices": choices, "POST /api/prod/orders": { order: makeOrder("plan") }, "GET /api/prod/orders/3": { order: makeOrder("plan") } });
    renderAt("/production/orders/new", owner());
    await screen.findByLabelText("Style, from the product list");
    fireEvent.click(screen.getByRole("combobox", { name: "Style, from the product list" }));
    fireEvent.click(within(screen.getByRole("listbox", { name: "Products" })).getByRole("option", { name: /^Oversized hoodie/ }));
    fireEvent.change(screen.getByLabelText("Colour"), { target: { value: "Black" } });
    fireEvent.change(screen.getByLabelText("Factory"), { target: { value: "SUP-1" } });
    fireEvent.change(within(screen.getByRole("group", { name: "Pieces per size" })).getByLabelText("M"), { target: { value: "100" } });
    fireEvent.change(screen.getByLabelText("Target date"), { target: { value: "2030-11-03" } });
    fireEvent.click(screen.getByRole("button", { name: "Take fabric from storage" }));
    fireEvent.change(screen.getByLabelText("Fabric, line 1"), { target: { value: "1" } });
    fireEvent.change(screen.getByLabelText("Kilos, line 1"), { target: { value: "45" } });
    fireEvent.click(screen.getByRole("button", { name: "Create order" }));
    expect(await screen.findByText("Only 40 kg of Black fleece is in storage.")).toBeTruthy();
    expect(calls.filter((call) => call.method === "POST")).toHaveLength(0);

    fireEvent.change(screen.getByLabelText("Kilos, line 1"), { target: { value: "30" } });
    fireEvent.click(screen.getByRole("button", { name: "Create order" }));
    await waitFor(() => expect(calls.filter((call) => call.method === "POST")).toHaveLength(1));
    expect(calls.find((call) => call.method === "POST")!.body).toMatchObject({ fabric: [{ fabric_id: 1, kg: 30 }] });
  });
});

describe("The Overview's decisions", () => {
  it("shows five at a time with the pager", async () => {
    const decisions = Array.from({ length: 7 }, (_, index) => ({
      key: `task:${index}`, title: `Decision ${index + 1}`, kind: "manual" as const, id: index, order: null, due: null, since: null, open: null, overdue_days: 0,
    }));
    mockApi({
      "GET /api/prod/overview": {
        today: "2030-11-13",
        summary: { open_orders: 1, planned_pieces: 10 },
        figures: { decisions: 7, late_orders: 0, open_orders: 1, arriving_this_month: { month: "2030-11", pieces: 0 }, owed_piastres: 0 },
        decisions,
        problems: [],
        orders: [makeRow({ id: 1, style_name: "Boxy tee" })],
        arriving: [],
        owed: [],
      },
    });
    renderAt("/production/overview", owner());
    const card = await screen.findByRole("region", { name: "Waiting for your decision" });
    expect(within(card).getAllByRole("listitem")).toHaveLength(5);
    const pager = within(card).getByRole("navigation", { name: "Pages" });
    expect(within(pager).getByText("1–5 of 7")).toBeTruthy();
    fireEvent.click(within(pager).getByRole("button", { name: "Next page" }));
    expect(within(card).getAllByRole("listitem").map((item) => item.querySelector("b")?.textContent)).toEqual(["Decision 6", "Decision 7"]);
  });
});
