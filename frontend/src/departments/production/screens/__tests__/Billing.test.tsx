// @vitest-environment jsdom
import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { NO_FABRIC, billDetail, billMatches, billingQuery, fabricBody, fabricProblem, offersStorage, quantityLine, quantityWords } from "../billingLogic";
import type { Bill, BillingList, FabricRow } from "../types";
import { mockApi, narrowScreen, owner, qc, renderAt, reply } from "./fixtures";
import type { Call } from "./fixtures";

const ADDRESS = "/production/billing";

const bill = (over: Partial<Bill> & { id: number }): Bill => ({
  supplier: { id: "SUP-4", name: "Delta Fabrics" },
  item: "Heavy fleece, black",
  quantity: "12.500",
  unit: "kg",
  unit_price_piastres: 8500,
  total_piastres: 106250,
  part: "fabric",
  bought_on: "2030-11-12",
  expected_on: null,
  received_on: null,
  order: null,
  note: null,
  voided: false,
  void_reason: null,
  fabric: null,
  photos: [],
  created_by: "Yahya",
  ...over,
});

const bills = (): Bill[] => [
  bill({ id: 3, order: { id: 1, code: "PO-2611-01" }, fabric: { id: 5, name: "Black fleece" }, photos: [{ id: 30, mime_type: "image/jpeg", url: "/api/prod/bill-photos/30" }, { id: 31, mime_type: "application/pdf", url: "/api/prod/bill-photos/31" }] }),
  bill({ id: 2, supplier: { id: "SUP-2", name: "Print House" }, item: "Screen print, front", quantity: "300.000", unit: "piece", unit_price_piastres: 1500, total_piastres: 450000, part: "printing", note: "Rush job" }),
  bill({ id: 1, item: "Wrong roll", total_piastres: 50000, voided: true, void_reason: "Bought twice by mistake", photos: [{ id: 10, mime_type: "image/png", url: "/api/prod/bill-photos/10" }] }),
];

const SUPPLIERS = [
  { id: "SUP-4", name: "Delta Fabrics" },
  { id: "SUP-2", name: "Print House" },
];

const list = (rows: Bill[]): BillingList => ({
  bills: rows,
  total_piastres: rows.filter((one) => !one.voided).reduce((sum, one) => sum + one.total_piastres, 0),
  by_part: { fabric: 106250, printing: 450000, accessories: 0, packaging: 0, other: 0 },
  suppliers: SUPPLIERS,
});

const fabricRow = (over: Partial<FabricRow> & { id: number; name: string }): FabricRow => ({
  fabric_type: null,
  colour: null,
  colour_code: null,
  supplier: null,
  active: true,
  in_stock_kg: "10.000",
  bought_kg: "10.000",
  used_kg: "0.000",
  orders: 0,
  ...over,
});

function serve(extra: Record<string, unknown> = {}, rows: Bill[] = bills()) {
  return mockApi({
    "GET /api/prod/billing": () => list(rows),
    "GET /api/prod/suppliers": { sections: [], unsectioned: 0, suppliers: [{ id: "SUP-4", name: "Delta Fabrics", active: true }, { id: "SUP-9", name: "Old mill", active: false }] },
    "GET /api/prod/orders": { orders: [] },
    "GET /api/prod/fabrics": { fabrics: [fabricRow({ id: 5, name: "Black fleece", colour: "Black", in_stock_kg: "12.500" }), fabricRow({ id: 6, name: "Retired", active: false })] },
    ...extra,
  });
}

const reads = (calls: Call[]) => calls.filter((call) => call.method === "GET" && call.path === "/api/prod/billing").map((call) => call.url);
const rowOf = (text: string) => screen.getByText(text).closest("tr, li") as HTMLElement;

beforeEach(() => narrowScreen(false));
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("The Billing logic", () => {
  it("writes the address, leaving out what is not set", () => {
    expect(billingQuery({ from: "", to: "" }, "", "")).toBe("");
    expect(billingQuery({ from: "2030-11-01", to: "2030-11-30" }, "SUP-4", "fabric")).toBe("from=2030-11-01&to=2030-11-30&supplier=SUP-4&part=fabric");
  });

  it("reads quantities and prices in plain words", () => {
    expect(quantityWords("12.500")).toBe("12.5");
    expect(quantityWords("300.000")).toBe("300");
    expect(quantityLine(bill({ id: 1 }))).toBe("12.5 kg at EGP 85.00");
    expect(billDetail(bill({ id: 1, order: { id: 1, code: "PO-1" }, fabric: { id: 2, name: "Fleece" } }))).toBe("order PO-1 · into storage: Fleece");
  });

  it("searches item, supplier, order code, note and fabric name", () => {
    const one = bill({ id: 1, order: { id: 1, code: "PO-2611-01" }, note: "Rush", fabric: { id: 2, name: "Black fleece" } });
    for (const text of ["heavy", "delta", "po-2611", "rush", "black fleece", "DELTA rush"]) expect(billMatches(one, text)).toBe(true);
    expect(billMatches(one, "zipper")).toBe(false);
  });

  it("offers storage only for fabric by the kilo, and sends the choice only then", () => {
    expect(offersStorage("fabric", "kg")).toBe(true);
    expect(offersStorage("fabric", "m")).toBe(false);
    expect(offersStorage("printing", "kg")).toBe(false);
    expect(fabricBody("fabric", "kg", { ...NO_FABRIC, pick: "5" })).toEqual({ fabric_id: 5 });
    expect(fabricBody("fabric", "kg", { pick: "new", name: " Cotton ", colour: "" })).toEqual({ new_fabric: { name: "Cotton" } });
    expect(fabricBody("fabric", "kg", { pick: "new", name: "Cotton", colour: "Navy" })).toEqual({ new_fabric: { name: "Cotton", colour: "Navy" } });
    expect(fabricBody("fabric", "m", { ...NO_FABRIC, pick: "5" })).toEqual({});
    expect(fabricBody("fabric", "kg", NO_FABRIC)).toEqual({});
    expect(fabricProblem("fabric", "kg", { pick: "new", name: " ", colour: "" })).toMatch(/name/);
    expect(fabricProblem("fabric", "m", { pick: "new", name: "", colour: "" })).toBeNull();
  });
});

describe("The Billing screen", () => {
  it("tells somebody without the owner's permission, and asks nothing", async () => {
    const calls = serve();
    renderAt(ADDRESS, qc());
    expect(await screen.findByText("Billing is for the owner only.")).toBeTruthy();
    expect(reads(calls)).toHaveLength(0);
  });

  it("lists every bill with the server's totals; a voided one is struck through with its reason and no receipt controls", async () => {
    const calls = serve();
    renderAt(ADDRESS, owner());
    await screen.findByRole("heading", { level: 1, name: "Billing" });
    expect(await screen.findByText(/2 bills · EGP 5,562.50/)).toBeTruthy();
    expect(reads(calls)).toEqual(["/api/prod/billing"]);

    const totals = screen.getByLabelText(/Totals/);
    expect(within(totals).getByText("EGP 5,562.50")).toBeTruthy();
    expect(within(totals).getByText("EGP 1,062.50")).toBeTruthy();
    expect(within(totals).getByText("EGP 4,500.00")).toBeTruthy();

    const first = rowOf("Heavy fleece, black");
    expect(within(first).getByRole("link", { name: "Delta Fabrics" }).getAttribute("href")).toBe("/production/suppliers/SUP-4");
    expect(within(first).getByText("12.5 kg at EGP 85.00")).toBeTruthy();
    expect(within(first).getByText(/order PO-2611-01 · into storage: Black fleece/)).toBeTruthy();
    expect(first.querySelector("img")?.getAttribute("src")).toBe("/api/prod/bill-photos/30");
    expect(within(first).getByText("PDF").closest("a")?.getAttribute("href")).toBe("/api/prod/bill-photos/31");
    expect(within(first).getByText(/Add receipt/)).toBeTruthy();

    const voided = rowOf("Wrong roll");
    expect(voided.querySelector("s")).toBeTruthy();
    expect(within(voided).getByText(/Voided: Bought twice by mistake/)).toBeTruthy();
    expect(within(voided).queryByText(/Add receipt/)).toBeNull();
    expect(within(voided).queryByRole("button", { name: /Remove/ })).toBeNull();
  });

  it("sends the dates, supplier and part as the query, and the chips show counts", async () => {
    const calls = serve();
    renderAt(ADDRESS, owner());
    await screen.findByText("Heavy fleece, black");
    expect(screen.getByRole("button", { name: "All · 3" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Printing · 1" })).toBeTruthy();

    fireEvent.change(screen.getByLabelText("From"), { target: { value: "2030-11-01" } });
    fireEvent.change(screen.getByLabelText("To"), { target: { value: "2030-11-30" } });
    fireEvent.change(screen.getByLabelText("Supplier"), { target: { value: "SUP-4" } });
    fireEvent.click(screen.getByRole("button", { name: /^Fabric/ }));
    await waitFor(() => expect(reads(calls).at(-1)).toBe("/api/prod/billing?from=2030-11-01&to=2030-11-30&supplier=SUP-4&part=fabric"));
  });

  it("searches what is loaded", async () => {
    serve();
    renderAt(ADDRESS, owner());
    await screen.findByText("Heavy fleece, black");
    fireEvent.change(screen.getByRole("searchbox", { name: "Search the bills" }), { target: { value: "rush" } });
    expect(screen.queryByText("Heavy fleece, black")).toBeNull();
    expect(screen.getByText("Screen print, front")).toBeTruthy();
    fireEvent.change(screen.getByRole("searchbox", { name: "Search the bills" }), { target: { value: "zzz" } });
    expect(screen.getByText("No bill matches.")).toBeTruthy();
  });

  it("shows cards on a phone", async () => {
    narrowScreen(true);
    serve();
    renderAt(ADDRESS, owner());
    await screen.findByText("Heavy fleece, black");
    expect(document.querySelector("table")).toBeNull();
    expect(document.querySelectorAll("li.prod-card")).toHaveLength(3);
  });

  it("pages after 25 bills", async () => {
    const many = Array.from({ length: 30 }, (_, index) => bill({ id: 100 + index, item: `Roll ${index + 1}` }));
    serve({}, many);
    renderAt(ADDRESS, owner());
    await screen.findByText("Roll 1");
    expect(screen.queryByText("Roll 30")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: /next/i }));
    expect(await screen.findByText("Roll 30")).toBeTruthy();
  });
});

describe("Receipts", () => {
  it("adds a receipt to the bill's own address and reads the list again", async () => {
    const calls = serve({ "POST /api/prod/purchases/2/photos": () => reply(201, { photo: { id: 40, mime_type: "image/jpeg", url: "/api/prod/bill-photos/40" } }) });
    renderAt(ADDRESS, owner());
    await screen.findByText("Screen print, front");
    const before = reads(calls).length;
    const input = within(rowOf("Screen print, front")).getByLabelText(/Add receipt/) as HTMLInputElement;
    fireEvent.change(input, { target: { files: [new File(["x"], "bill.jpg", { type: "image/jpeg" })] } });
    expect(await screen.findByText("Receipt added to Screen print, front.")).toBeTruthy();
    expect(calls.some((call) => call.method === "POST" && call.path === "/api/prod/purchases/2/photos")).toBe(true);
    await waitFor(() => expect(reads(calls).length).toBeGreaterThan(before));
  });

  it("asks before removing, and keeps it when told to", async () => {
    const calls = serve({ "DELETE /api/prod/bill-photos/30": { deleted: 30 } });
    renderAt(ADDRESS, owner());
    await screen.findByText("Heavy fleece, black");
    const row = () => rowOf("Heavy fleece, black");
    fireEvent.click(within(row()).getByRole("button", { name: /Remove receipt 1 of/ }));
    expect(calls.some((call) => call.method === "DELETE")).toBe(false);
    fireEvent.click(within(row()).getByRole("button", { name: "Keep" }));
    expect(within(row()).queryByRole("button", { name: "Remove" })).toBeNull();

    fireEvent.click(within(row()).getByRole("button", { name: /Remove receipt 1 of/ }));
    fireEvent.click(within(row()).getByRole("button", { name: "Remove" }));
    expect(await screen.findByText(/Receipt 1 removed from/)).toBeTruthy();
    expect(calls.filter((call) => call.method === "DELETE").map((call) => call.path)).toEqual(["/api/prod/bill-photos/30"]);
  });
});

describe("Adding a bill", () => {
  async function openPanel() {
    renderAt(ADDRESS, owner());
    await screen.findByText("Heavy fleece, black");
    fireEvent.click(screen.getByRole("button", { name: "Add a bill" }));
    await screen.findByRole("heading", { name: "Record a purchase" });
  }

  const chooser = () => screen.getAllByLabelText("Supplier").find((node) => node.closest(".prod-panel")) as HTMLSelectElement;

  function fill(item = "Heavy fleece, grey") {
    fireEvent.change(chooser(), { target: { value: "SUP-4" } });
    fireEvent.change(screen.getByLabelText("What was bought"), { target: { value: item } });
    fireEvent.change(screen.getByLabelText("Quantity"), { target: { value: "10" } });
    fireEvent.change(screen.getByLabelText(/Price per/), { target: { value: "85" } });
  }

  it("records the purchase on the supplier's account, then offers the receipt and reads the list again", async () => {
    const calls = serve({ "POST /api/prod/suppliers/SUP-4/purchases": () => reply(201, { supplier: {}, purchase_id: 9 }) });
    await openPanel();
    expect(Array.from(chooser().options).map((option) => option.textContent)).toEqual(["Choose a supplier", "Delta Fabrics"]);
    fill();
    const before = reads(calls).length;
    fireEvent.click(screen.getByRole("button", { name: "Save purchase" }));
    expect(await screen.findByText(/Purchase recorded: Heavy fleece, grey from Delta Fabrics/)).toBeTruthy();
    const post = calls.find((call) => call.method === "POST" && call.path === "/api/prod/suppliers/SUP-4/purchases");
    expect(post?.body).toMatchObject({ item: "Heavy fleece, grey", quantity: "10", unit: "kg", unit_price_piastres: 8500, part: "fabric" });
    expect(screen.getByText(/Add the receipt photo/)).toBeTruthy();
    await waitFor(() => expect(reads(calls).length).toBeGreaterThan(before));
  });

  it("offers fabric storage only for fabric by the kilo, and sends nothing when not chosen", async () => {
    const calls = serve({ "POST /api/prod/suppliers/SUP-4/purchases": () => reply(201, { supplier: {}, purchase_id: 9 }) });
    await openPanel();
    expect(await screen.findByLabelText("Put into fabric storage")).toBeTruthy();
    const options = Array.from((screen.getByLabelText("Put into fabric storage") as HTMLSelectElement).options).map((option) => option.textContent);
    expect(options).toEqual(["Not into storage", "Black fleece · Black · 12.5 kg in storage", "A new fabric"]);

    fireEvent.change(screen.getByLabelText("Measured in"), { target: { value: "m" } });
    expect(screen.queryByLabelText("Put into fabric storage")).toBeNull();
    fireEvent.change(screen.getByLabelText("Measured in"), { target: { value: "kg" } });
    fireEvent.change(screen.getByLabelText("Which part of the cost it is"), { target: { value: "printing" } });
    expect(screen.queryByLabelText("Put into fabric storage")).toBeNull();
    fireEvent.change(screen.getByLabelText("Which part of the cost it is"), { target: { value: "fabric" } });

    fill();
    fireEvent.click(screen.getByRole("button", { name: "Save purchase" }));
    await screen.findByText(/Purchase recorded/);
    const body = calls.find((call) => call.method === "POST" && call.path === "/api/prod/suppliers/SUP-4/purchases")?.body as Record<string, unknown>;
    expect(body).not.toHaveProperty("fabric_id");
    expect(body).not.toHaveProperty("new_fabric");
  });

  it("sends fabric_id for a fabric in storage", async () => {
    const calls = serve({ "POST /api/prod/suppliers/SUP-4/purchases": () => reply(201, { supplier: {}, purchase_id: 9 }) });
    await openPanel();
    fill();
    await screen.findByText(/Black fleece · Black/);
    fireEvent.change(screen.getByLabelText("Put into fabric storage"), { target: { value: "5" } });
    fireEvent.click(screen.getByRole("button", { name: "Save purchase" }));
    await screen.findByText(/Purchase recorded/);
    const body = calls.find((call) => call.method === "POST" && call.path === "/api/prod/suppliers/SUP-4/purchases")?.body;
    expect(body).toMatchObject({ fabric_id: 5 });
    expect(body).not.toHaveProperty("new_fabric");
  });

  it("sends new_fabric for a new one, and wants its name", async () => {
    const calls = serve({ "POST /api/prod/suppliers/SUP-4/purchases": () => reply(201, { supplier: {}, purchase_id: 9 }) });
    await openPanel();
    fill();
    await screen.findByText(/Black fleece · Black/);
    fireEvent.change(screen.getByLabelText("Put into fabric storage"), { target: { value: "new" } });
    fireEvent.click(screen.getByRole("button", { name: "Save purchase" }));
    expect(await screen.findByText(/Give the new fabric a name/)).toBeTruthy();
    expect(calls.some((call) => call.method === "POST")).toBe(false);

    fireEvent.change(screen.getByLabelText("New fabric name"), { target: { value: "Navy rib" } });
    fireEvent.change(screen.getByLabelText("Colour, optional"), { target: { value: "Navy" } });
    fireEvent.click(screen.getByRole("button", { name: "Save purchase" }));
    await screen.findByText(/Purchase recorded/);
    const body = calls.find((call) => call.method === "POST" && call.path === "/api/prod/suppliers/SUP-4/purchases")?.body;
    expect(body).toMatchObject({ new_fabric: { name: "Navy rib", colour: "Navy" } });
    expect(body).not.toHaveProperty("fabric_id");
  });

  it("shows the server's refusal in the form", async () => {
    serve({ "POST /api/prod/suppliers/SUP-4/purchases": () => reply(422, { detail: "Only fabric bought by the kilo can go into storage." }) });
    await openPanel();
    fill();
    fireEvent.click(screen.getByRole("button", { name: "Save purchase" }));
    expect(await screen.findByText("Only fabric bought by the kilo can go into storage.")).toBeTruthy();
  });
});
