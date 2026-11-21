// @vitest-environment jsdom
import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { cogsBody, cogsProblem, cogsText, missingWords, poundsText, sizesWords } from "../libraryLogic";
import { COST_LABELS, blankCost } from "../logic";
import type { LibraryItem, LibraryRow } from "../types";
import { mockApi, narrowScreen, owner, qc, renderAt } from "./fixtures";

const FILLED = { details: true, cogs: true, design: true, size_chart: true };

function row(over: Partial<LibraryRow> & { id: string; title: string }): LibraryRow {
  return {
    status: "active",
    image_url: null,
    sizes: ["S", "M", "L"],
    skus: [],
    colour_code: null,
    fabric_type: null,
    filled: { details: false, cogs: false, design: false, size_chart: false },
    orders: 0,
    ...over,
  };
}

const rows = (): LibraryRow[] => [
  row({ id: "101", title: "HBA Club Hoodie Black", image_url: "https://cdn.shopify.com/s/files/black.png", skus: ["HCH-BLK-S", "HCH-BLK-M"], filled: FILLED, orders: 2, fabric_type: "Cotton fleece" }),
  row({ id: "102", title: "HBA Club Hoodie Army Green", status: "draft", filled: { ...FILLED, cogs: false, size_chart: false } }),
  row({ id: "103", title: "Old logo tee", status: "archived", sizes: ["One size"] }),
];

function item(over: Partial<LibraryItem> = {}): LibraryItem {
  return {
    id: "101",
    title: "HBA Club Hoodie Black",
    handle: "hba-club-hoodie-black",
    status: "active",
    image_url: "https://cdn.shopify.com/s/files/black.png",
    synced_at: "2026-11-21T09:00:00Z",
    variants: [
      { id: "v1", title: "S", sku: "HCH-BLK-S" },
      { id: "v2", title: "M", sku: null },
    ],
    details: { colour_code: "#1d1d1f", fabric_type: "Cotton fleece 320 gsm", decoration_type: "DTF print", decoration_width_cm: "12.5", notes: null },
    cogs: {
      fabric_piastres: 16500,
      manufacturing_piastres: 8500,
      printing_piastres: null,
      accessories_piastres: 1250,
      packaging_piastres: null,
      total_piastres: 26250,
    },
    files: {
      design: [{ id: 7, name: "club-logo.ai", mime_type: "application/octet-stream", size_bytes: 10, created_at: null, uploaded_by: "Nour", url: "/api/prod/library-files/7" }],
      size_chart: [],
      pattern: [],
    },
    orders: [{ id: 3, code: "PO-2611-01", colour: "Black", status: "cancelled", planned_total: 10, target_date: "2027-01-20" }],
    updated_at: "2026-11-21T10:00:00Z",
    updated_by: "Yahya",
    ...over,
  };
}

/** What a reader without the owner's permission gets: no COGS at all. */
function forStaff(answer: LibraryItem): LibraryItem {
  const copy = { ...answer };
  delete copy.cogs;
  return copy;
}

beforeEach(() => narrowScreen(false));
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("The Library's words", () => {
  it("writes piastres as pounds to type, and reads them back with blanks as not set", () => {
    expect(poundsText(16500)).toBe("165");
    expect(poundsText(1250)).toBe("12.50");
    expect(poundsText(5)).toBe("0.05");
    expect(poundsText(null)).toBe("");
    const text = cogsText(item().cogs);
    expect(text).toEqual({ fabric: "165", manufacturing: "85", printing: "", accessories: "12.50", packaging: "" });
    expect(cogsBody(text)).toEqual({
      cogs_fabric_piastres: 16500,
      cogs_manufacturing_piastres: 8500,
      cogs_printing_piastres: null,
      cogs_accessories_piastres: 1250,
      cogs_packaging_piastres: null,
    });
    expect(cogsBody({ ...blankCost(), printing: "0" }).cogs_printing_piastres).toBe(0);
  });

  it("refuses a part that is not an amount, naming it", () => {
    expect(cogsProblem({ ...blankCost(), fabric: "abc" }, COST_LABELS)).toBe("Check fabric: an amount in pounds, like 85 or 85.50.");
    expect(cogsProblem({ ...blankCost(), fabric: "-3" }, COST_LABELS)).not.toBeNull();
    expect(cogsProblem({ ...blankCost(), fabric: "1,250.50" }, COST_LABELS)).toBeNull();
  });

  it("says what is missing, and leaves the COGS out for somebody who may not see it", () => {
    const draft = rows()[1];
    expect(missingWords(draft, true)).toBe("COGS, size chart");
    expect(missingWords(draft, false)).toBe("size chart");
    expect(missingWords(rows()[0], true)).toBeNull();
    expect(sizesWords(["XS", "S", "M"])).toBe("3 sizes · XS to M");
    expect(sizesWords(["One size"])).toBe("1 size · One size");
    expect(sizesWords([])).toBe("No sizes");
  });
});

describe("The Library list", () => {
  it("lists every product, drafts and archived ones too, with what is still missing", async () => {
    mockApi({ "GET /api/prod/library": { products: rows() } });
    renderAt("/production/library", owner());
    const table = await screen.findByRole("table");
    const lines = within(table).getAllByRole("row").slice(1);
    expect(lines).toHaveLength(3);
    expect(within(lines[0]).getByRole("link", { name: "HBA Club Hoodie Black" }).getAttribute("href")).toBe("/production/library/101");
    expect(lines[0].textContent).toContain("All added");
    expect(lines[0].textContent).toContain("2 orders");
    expect(lines[1].textContent).toContain("Draft");
    expect(lines[1].textContent).toContain("Missing: COGS, size chart");
    expect(lines[2].textContent).toContain("Archived");
    expect(lines[2].textContent).toContain("1 size · One size");
    expect(lines[2].textContent).toContain("None yet");
    expect(lines[0].querySelector("img.prod-photo")?.getAttribute("src")).toBe("https://cdn.shopify.com/s/files/black.png?width=96");

    fireEvent.click(screen.getByRole("button", { name: "Draft · 1" }));
    expect(within(screen.getByRole("table")).getAllByRole("row")).toHaveLength(2);
    fireEvent.click(screen.getByRole("button", { name: "All · 3" }));

    fireEvent.change(screen.getByRole("searchbox", { name: "Search the library" }), { target: { value: "hch-blk-m" } });
    expect(within(screen.getByRole("table")).getAllByRole("link").map((link) => link.textContent)).toEqual(["HBA Club Hoodie Black"]);
    fireEvent.change(screen.getByRole("searchbox", { name: "Search the library" }), { target: { value: "nothing" } });
    expect(screen.getByText("No product matches.")).toBeTruthy();
  });

  it("does not tell the QC manager about the COGS", async () => {
    mockApi({ "GET /api/prod/library": { products: rows() } });
    renderAt("/production/library", qc());
    const table = await screen.findByRole("table");
    expect(table.textContent).toContain("Missing: size chart");
    expect(table.textContent).not.toContain("COGS");
  });
});

describe("A Library product, for the owner", () => {
  it("shows the details, the COGS a piece, the files, Shopify's sizes and the orders made of it", async () => {
    mockApi({ "GET /api/prod/library/101": { product: item() } });
    renderAt("/production/library/101", owner());
    expect(await screen.findByRole("heading", { level: 1, name: "HBA Club Hoodie Black" })).toBeTruthy();
    const details = screen.getByRole("region", { name: "Details" });
    expect(details.textContent).toContain("#1d1d1f");
    expect(details.textContent).toContain("DTF print · 12.5 cm wide");
    const cogs = screen.getByRole("region", { name: "COGS a piece" });
    expect(cogs.textContent).toContain("EGP 165.00");
    expect(cogs.textContent).toContain("Not set");
    expect(cogs.textContent).toContain("EGP 262.50");
    const files = screen.getByRole("region", { name: "Files" });
    expect(within(files).getByRole("link", { name: "club-logo.ai" }).getAttribute("href")).toBe("/api/prod/library-files/7");
    const shopify = screen.getByRole("region", { name: "From Shopify" });
    expect(shopify.textContent).toContain("HCH-BLK-S");
    const orders = screen.getByRole("region", { name: "Production orders" });
    expect(within(orders).getByRole("link", { name: "PO-2611-01 · Black" }).getAttribute("href")).toBe("/production/orders/3");
    expect(orders.textContent).toContain("Cancelled");
    expect(screen.getByRole("link", { name: "New order" }).getAttribute("href")).toBe("/production/orders/new?product=101");
  });

  it("saves the details, every field, blanks as null", async () => {
    const calls = mockApi({
      "GET /api/prod/library/101": { product: item() },
      "PATCH /api/prod/library/101": { product: item({ details: { ...item().details, fabric_type: "French terry" } }) },
    });
    renderAt("/production/library/101", owner());
    fireEvent.click(await screen.findByRole("button", { name: "Edit details" }));
    fireEvent.change(screen.getByLabelText("Fabric"), { target: { value: "French terry" } });
    fireEvent.change(screen.getByLabelText("Colour code"), { target: { value: "  " } });
    fireEvent.click(screen.getByRole("button", { name: "Save details" }));
    expect(await screen.findByText("Details saved.")).toBeTruthy();
    const patch = calls.find((call) => call.method === "PATCH")!;
    expect(patch.body).toEqual({ colour_code: null, fabric_type: "French terry", decoration_type: "DTF print", decoration_width_cm: 12.5, notes: null });
    expect(screen.getByRole("region", { name: "Details" }).textContent).toContain("French terry");
  });

  it("refuses a width that is not a number before sending", async () => {
    const calls = mockApi({ "GET /api/prod/library/101": { product: item() } });
    renderAt("/production/library/101", owner());
    fireEvent.click(await screen.findByRole("button", { name: "Edit details" }));
    fireEvent.change(screen.getByLabelText("Design width, cm"), { target: { value: "wide" } });
    fireEvent.click(screen.getByRole("button", { name: "Save details" }));
    expect(await screen.findByText(/Check the width/)).toBeTruthy();
    expect(calls.filter((call) => call.method === "PATCH")).toHaveLength(0);
  });

  it("saves the COGS in piastres, a blank part as not set", async () => {
    const calls = mockApi({
      "GET /api/prod/library/101": { product: item() },
      "PATCH /api/prod/library/101": { product: item() },
    });
    renderAt("/production/library/101", owner());
    fireEvent.click(await screen.findByRole("button", { name: "Edit COGS" }));
    expect((screen.getByLabelText("Fabric") as HTMLInputElement).value).toBe("165");
    fireEvent.change(screen.getByLabelText("Printing"), { target: { value: "30" } });
    fireEvent.change(screen.getByLabelText("Accessories"), { target: { value: "" } });
    expect(screen.getByText("Total EGP 280.00 a piece")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Save COGS" }));
    expect(await screen.findByText("COGS saved.")).toBeTruthy();
    expect(calls.find((call) => call.method === "PATCH")!.body).toEqual({
      cogs_fabric_piastres: 16500,
      cogs_manufacturing_piastres: 8500,
      cogs_printing_piastres: 3000,
      cogs_accessories_piastres: null,
      cogs_packaging_piastres: null,
    });
  });

  it("shows the server's words when it refuses", async () => {
    mockApi({
      "GET /api/prod/library/101": { product: item() },
      "PATCH /api/prod/library/101": () => new Response(JSON.stringify({ detail: "The fabric is too long." }), { status: 422, headers: { "Content-Type": "application/json" } }),
    });
    renderAt("/production/library/101", owner());
    fireEvent.click(await screen.findByRole("button", { name: "Edit details" }));
    fireEvent.click(screen.getByRole("button", { name: "Save details" }));
    expect(await screen.findByText("The fabric is too long.")).toBeTruthy();
  });
});

describe("A Library product, for the QC manager", () => {
  it("has no COGS and no Edit details, but adds and removes files", async () => {
    const after = item({
      files: { ...item().files, size_chart: [{ id: 9, name: "chart.pdf", mime_type: "application/pdf", size_bytes: 5, created_at: null, uploaded_by: "QC", url: "/api/prod/library-files/9" }] },
    });
    let current = forStaff(item());
    const calls = mockApi({
      "GET /api/prod/library/101": () => ({ product: current }),
      "POST /api/prod/library/101/files": () => {
        current = forStaff(after);
        return { file: after.files.size_chart[0] };
      },
      "DELETE /api/prod/library-files/7": () => {
        current = forStaff({ ...after, files: { ...after.files, design: [] } });
        return { deleted: 7 };
      },
    });
    renderAt("/production/library/101", qc());
    await screen.findByRole("heading", { level: 1, name: "HBA Club Hoodie Black" });
    expect(screen.queryByRole("region", { name: "COGS a piece" })).toBeNull();
    expect(document.body.textContent).not.toContain("EGP");
    expect(screen.queryByRole("button", { name: "Edit details" })).toBeNull();
    expect(screen.queryByRole("link", { name: "New order" })).toBeNull();

    const chart = screen.getByLabelText("Add a size chart") as HTMLInputElement;
    expect(chart.getAttribute("accept")).toContain("application/pdf");
    expect((screen.getByLabelText("Add a design file") as HTMLInputElement).getAttribute("accept")).toBeNull();
    fireEvent.change(chart, { target: { files: [new File(["x"], "chart.pdf")] } });
    expect(await screen.findByText("Size chart added: chart.pdf.")).toBeTruthy();
    const sent = vi.mocked(fetch).mock.calls.find(([url, init]) => String(url) === "/api/prod/library/101/files" && init?.method === "POST")!;
    expect((sent[1]!.body as FormData).get("kind")).toBe("size_chart");
    await waitFor(() => expect(screen.getByRole("link", { name: "chart.pdf" })).toBeTruthy());

    fireEvent.click(screen.getByRole("button", { name: "Remove club-logo.ai" }));
    fireEvent.click(screen.getByRole("button", { name: "Remove" }));
    expect(await screen.findByText("Removed: club-logo.ai.")).toBeTruthy();
    expect(calls.some((call) => call.method === "DELETE" && call.path === "/api/prod/library-files/7")).toBe(true);
    expect(screen.queryByRole("link", { name: "club-logo.ai" })).toBeNull();
  });
});

describe("A new order from the Library", () => {
  const choices = {
    suppliers: [{ id: "SUP-1", name: "Main factory", category: "Manufacturer" }],
    products: [
      { id: "101", title: "HBA Club Hoodie Black", status: "active", image_url: null },
      { id: "102", title: "HBA Club Hoodie Army Green", status: "draft", image_url: null },
    ],
    sizes: ["XS", "S", "M", "L", "XL", "XXL"],
    stage_days: { sample: 7, materials: 7, fabric_check: 2, pattern_check: 3, cutting: 2, making: 17, final_inspection: 1, warehouse: 3, settle: 7 },
  };

  it("starts with the product picked and its target cost filled from the COGS", async () => {
    mockApi({ "GET /api/prod/choices": choices, "GET /api/prod/library/101": { product: item() } });
    renderAt("/production/orders/new?product=101", owner());
    const style = (await screen.findByRole("combobox", { name: "Style, from the product list" })) as HTMLInputElement;
    await waitFor(() => expect(style.value).toBe("HBA Club Hoodie Black"));
    await waitFor(() => expect((screen.getByLabelText("Fabric, target cost") as HTMLInputElement).value).toBe("165"));
    expect((screen.getByLabelText("Accessories, target cost") as HTMLInputElement).value).toBe("12.50");
    expect((screen.getByLabelText("Printing, target cost") as HTMLInputElement).value).toBe("");
    expect(screen.getByText(/filled from this product's COGS in the Library/)).toBeTruthy();
  });

  it("leaves a target cost alone that somebody has started typing, and a product with no COGS", async () => {
    mockApi({ "GET /api/prod/choices": choices, "GET /api/prod/library/102": { product: item({ id: "102", cogs: { fabric_piastres: null, manufacturing_piastres: null, printing_piastres: null, accessories_piastres: null, packaging_piastres: null, total_piastres: null } }) } });
    renderAt("/production/orders/new?product=102", owner());
    const style = (await screen.findByRole("combobox", { name: "Style, from the product list" })) as HTMLInputElement;
    await waitFor(() => expect(style.value).toBe("HBA Club Hoodie Army Green"));
    await waitFor(() => expect(vi.mocked(fetch).mock.calls.some(([url]) => String(url) === "/api/prod/library/102")).toBe(true));
    expect((screen.getByLabelText("Fabric, target cost") as HTMLInputElement).value).toBe("");
    expect(screen.queryByText(/filled from this product's COGS/)).toBeNull();
  });
});
