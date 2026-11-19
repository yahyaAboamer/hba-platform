// @vitest-environment jsdom
import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { cogsWords, decorationWords, hexOf, productBody, productProblem } from "../productLogic";
import type { OrderView, ProdFile, ProductDetails } from "../types";
import { emptyProduct, makeOrder, mockApi, narrowScreen, owner, qc, renderAt } from "./fixtures";
import type { Call } from "./fixtures";

const ADDRESS = "/production/orders/3";

const file = (id: number, name: string, kind: ProdFile["kind"]): ProdFile => ({
  id,
  name,
  stage: null,
  kind,
  mime_type: name.endsWith(".pdf") ? "application/pdf" : "application/octet-stream",
  size_bytes: 1000,
  created_at: "2030-10-01T08:00:00Z",
  uploaded_by: "Nour",
  url: `/api/prod/files/${id}`,
});

const full = (): ProductDetails => ({
  colour_code: "#2F3A2F",
  fabric_type: "Cotton fleece 320 gsm",
  decoration_type: "DTF print",
  decoration_width_cm: "12.5",
  suppliers: [
    { id: "SUP-1", name: "Nour Factory", roles: ["Factory"] },
    { id: "SUP-4", name: "Delta Fabrics", roles: ["Fabric"] },
    { id: "SUP-7", name: "Print House", roles: ["Printing", "Accessories"] },
  ],
  pattern_files: [file(11, "hoodie-v2.dxf", "pattern")],
  size_charts: [file(12, "sizes.pdf", "size_chart")],
});

function withProduct(product: ProductDetails, money = false, stage: Parameters<typeof makeOrder>[0] = "cutting"): OrderView {
  const order = makeOrder(stage, { money, extra: { product } });
  if (money && order.cost) order.cost.cogs = { per_piece_piastres: 18500, pieces: 480, pieces_basis: "passed", total_piastres: 8880000 };
  return order;
}

function serve(order: OrderView, extra: Record<string, unknown> = {}) {
  return mockApi({
    "GET /api/prod/orders/3": { order },
    "GET /api/prod/orders/3/history": { events: [] },
    "GET /api/prod/orders/3/files": { files: [] },
    ...extra,
  });
}

const card = () => screen.getByRole("heading", { name: "Product", level: 2 }).closest("section")!;
const detail = (term: string) => within(card()).getByText(term, { selector: "dt" }).nextElementSibling as HTMLElement;
const writes = (calls: Call[]) => calls.filter((call) => call.method !== "GET");

beforeEach(() => narrowScreen(false));
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("The Product card", () => {
  it("shows every detail, the suppliers with their roles and the files, first in the side column", async () => {
    serve(withProduct(full()));
    renderAt(ADDRESS, qc());
    await screen.findByRole("heading", { level: 1, name: "Oversized hoodie · Black" });
    const stack = card().parentElement!;
    expect(stack.firstElementChild).toBe(card());

    expect(detail("Colour").textContent).toBe("Black · #2F3A2F");
    expect((detail("Colour").querySelector(".prod-swatch") as HTMLElement).style.background).toBeTruthy();
    expect(detail("Fabric").textContent).toBe("Cotton fleece 320 gsm");
    expect(detail("Print or embroidery").textContent).toBe("DTF print · 12.5 cm wide");

    const suppliers = detail("Suppliers");
    expect(within(suppliers).getByRole("link", { name: "Delta Fabrics" }).getAttribute("href")).toBe("/production/suppliers/SUP-4");
    expect(suppliers.textContent).toContain("Print House · Printing, Accessories");
    expect(suppliers.textContent).toContain("Nour Factory · Factory");

    const pattern = within(detail("Pattern files")).getByRole("link", { name: "hoodie-v2.dxf" });
    expect(pattern.getAttribute("href")).toBe("/api/prod/files/11");
    expect(pattern.getAttribute("target")).toBe("_blank");
    expect(within(detail("Size charts")).getByRole("link", { name: "sizes.pdf" })).toBeTruthy();
  });

  it("says Not set for what is empty, and has no swatch for a code that is not a hex colour", async () => {
    serve(withProduct({ ...emptyProduct(), colour_code: "Pantone 19-0303", suppliers: [] }));
    renderAt(ADDRESS, { ...qc(), permissions: ["production.view"] });
    await screen.findByRole("heading", { level: 1, name: "Oversized hoodie · Black" });
    expect(detail("Colour").textContent).toBe("Black · Pantone 19-0303");
    expect(detail("Colour").querySelector(".prod-swatch")).toBeNull();
    for (const term of ["Fabric", "Print or embroidery", "Suppliers", "Pattern files", "Size charts"]) {
      expect(detail(term).textContent).toBe("Not set");
    }
    // Somebody who can only read gets no buttons.
    expect(within(card()).queryAllByRole("button")).toHaveLength(0);
  });

  it("shows the COGS to the owner only", async () => {
    serve(withProduct(full(), true));
    renderAt(ADDRESS, owner());
    await screen.findByRole("heading", { level: 1, name: "Oversized hoodie · Black" });
    expect(detail("COGS").textContent).toBe("EGP 185.00 a piece · EGP 88,800.00 for 480 passed pieces");
    cleanup();

    serve(withProduct(full()));
    renderAt(ADDRESS, qc());
    await screen.findByRole("heading", { level: 1, name: "Oversized hoodie · Black" });
    expect(within(card()).queryByText("COGS")).toBeNull();
    expect(within(card()).queryByText(/EGP/)).toBeNull();
    // The QC manager adds files but does not edit the details.
    expect(within(card()).queryByRole("button", { name: "Edit details" })).toBeNull();
    expect(within(card()).getByRole("button", { name: "Add a pattern file" })).toBeTruthy();
  });

  it("uploads a pattern file with its kind, then shows the order the server answers", async () => {
    const after = withProduct({ ...full(), pattern_files: [file(13, "hoodie-v3.plt", "pattern"), ...full().pattern_files] });
    const calls = serve(withProduct(full()), { "POST /api/prod/orders/3/files": { file: file(13, "hoodie-v3.plt", "pattern") } });
    renderAt(ADDRESS, qc());
    await screen.findByRole("heading", { level: 1, name: "Oversized hoodie · Black" });
    // The next read of the order carries the new file.
    serve(after, { "POST /api/prod/orders/3/files": { file: file(13, "hoodie-v3.plt", "pattern") } });
    const picker = within(card()).getByLabelText("Add a pattern file") as HTMLInputElement;
    // A pattern can be any file; a size chart is a photo or a PDF.
    expect(picker.getAttribute("accept")).toBeNull();
    expect((within(card()).getByLabelText("Add a size chart") as HTMLInputElement).getAttribute("accept")).toContain("application/pdf");
    fireEvent.change(picker, { target: { files: [new File(["x"], "hoodie-v3.plt")] } });

    expect(await screen.findByText("Pattern file added: hoodie-v3.plt.")).toBeTruthy();
    await waitFor(() => expect(within(detail("Pattern files")).getByRole("link", { name: "hoodie-v3.plt" })).toBeTruthy());
    const fetched = vi.mocked(fetch).mock.calls.find(([url, init]) => String(url) === "/api/prod/orders/3/files" && init?.method === "POST")!;
    const form = fetched[1]!.body as FormData;
    expect(form.get("kind")).toBe("pattern");
    expect((form.get("file") as File).name).toBe("hoodie-v3.plt");
    expect(calls.length).toBeGreaterThan(0);
  });

  it("offers no upload on an order that is not open", async () => {
    serve(withProduct(full(), false, "cutting"));
    const order = withProduct(full());
    order.status = "closed";
    serve(order);
    renderAt(ADDRESS, owner());
    await screen.findByRole("heading", { level: 1, name: "Oversized hoodie · Black" });
    expect(within(card()).queryAllByRole("button")).toHaveLength(0);
  });
});

describe("Edit product details", () => {
  it("starts with what the product has and sends the four fields, blank as null", async () => {
    const calls = serve(withProduct(full(), true), {
      "PATCH /api/prod/orders/3": () => ({ order: withProduct({ ...full(), fabric_type: null, decoration_width_cm: "8.0" }, true) }),
    });
    renderAt(ADDRESS, owner());
    await screen.findByRole("heading", { level: 1, name: "Oversized hoodie · Black" });
    const edit = within(card()).getByRole("button", { name: "Edit details" });
    edit.focus();
    fireEvent.click(edit);
    const panel = screen.getByRole("heading", { name: "Edit product details", level: 2 }).closest("section")!;
    expect((within(panel).getByLabelText("Colour code") as HTMLInputElement).value).toBe("#2F3A2F");
    expect((within(panel).getByLabelText("Print or embroidery width, cm") as HTMLInputElement).value).toBe("12.5");

    fireEvent.change(within(panel).getByLabelText("Print or embroidery width, cm"), { target: { value: "12.55" } });
    fireEvent.click(within(panel).getByRole("button", { name: "Save details" }));
    expect((await within(panel).findByRole("alert")).textContent).toBe("Check the width: a number of cm above 0, like 12 or 12.5.");
    expect(writes(calls)).toHaveLength(0);

    fireEvent.change(within(panel).getByLabelText("Print or embroidery width, cm"), { target: { value: "8" } });
    fireEvent.change(within(panel).getByLabelText("Fabric type"), { target: { value: "  " } });
    fireEvent.click(within(panel).getByRole("button", { name: "Save details" }));
    expect(await screen.findByText("Product details saved.")).toBeTruthy();
    expect(writes(calls)).toEqual([
      expect.objectContaining({
        method: "PATCH",
        path: "/api/prod/orders/3",
        body: { colour_code: "#2F3A2F", fabric_type: null, decoration_type: "DTF print", decoration_width_cm: 8 },
      }),
    ]);
    expect(detail("Fabric").textContent).toBe("Not set");
    expect(detail("Print or embroidery").textContent).toBe("DTF print · 8.0 cm wide");
    await waitFor(() => expect(document.activeElement).toBe(within(card()).getByRole("button", { name: "Edit details" })));
  });

  it("keeps a style that is no longer in the product list chosen, in Edit the order", async () => {
    const order = makeOrder("cutting", { money: true, extra: { shopify_product_id: "P9", style_name: "Old hoodie" } });
    serve(order, {
      "GET /api/prod/choices": {
        suppliers: [{ id: "SUP-1", name: "Main factory", category: null }],
        products: [{ id: "P1", title: "Oversized hoodie", status: "active", image_url: null }],
        sizes: ["S", "M"],
        stage_days: {},
      },
    });
    renderAt(ADDRESS, owner());
    await screen.findByRole("heading", { level: 1, name: "Old hoodie · Black" });
    fireEvent.click(screen.getByRole("button", { name: "Edit the order" }));
    const box = (await screen.findByRole("combobox", { name: "Style, from the product list" })) as HTMLInputElement;
    expect(box.value).toBe("Old hoodie");
    fireEvent.click(box);
    const options = within(screen.getByRole("listbox", { name: "Products" })).getAllByRole("option").map((option) => option.textContent);
    expect(options).toEqual(["Oversized hoodie", "Old hoodie (chosen)", "A new style, not on Shopify yet"]);
    // Escape closes the list, not the panel.
    fireEvent.keyDown(box, { key: "Escape" });
    expect(screen.getByRole("heading", { name: "Edit the order", level: 2 })).toBeTruthy();
  });
});

describe("The product's words", () => {
  it("takes only a #rrggbb code as a swatch", () => {
    expect(hexOf("#2f3a2f")).toBe("#2f3a2f");
    expect(hexOf("Pantone 19-0303")).toBeNull();
    expect(hexOf("#fff")).toBeNull();
    expect(hexOf(null)).toBeNull();
  });

  it("joins the print type and its width", () => {
    expect(decorationWords({ decoration_type: "Puff embroidery", decoration_width_cm: null })).toBe("Puff embroidery");
    expect(decorationWords({ decoration_type: null, decoration_width_cm: "4.0" })).toBe("4.0 cm wide");
    expect(decorationWords({ decoration_type: null, decoration_width_cm: null })).toBeNull();
  });

  it("says the COGS on the server's basis", () => {
    expect(cogsWords({ per_piece_piastres: 18500, pieces: 1, pieces_basis: "planned", total_piastres: 18500 })).toBe(
      "EGP 185.00 a piece · EGP 185.00 for 1 planned piece",
    );
  });

  it("checks the width and sends blank as null", () => {
    const draft = { colourCode: " ", fabricType: "Fleece", decorationType: "", width: "" };
    expect(productProblem(draft)).toBeNull();
    expect(productBody(draft)).toEqual({ colour_code: null, fabric_type: "Fleece", decoration_type: null, decoration_width_cm: null });
    expect(productProblem({ ...draft, width: "0" })).not.toBeNull();
    expect(productProblem({ ...draft, width: "1000" })).not.toBeNull();
    expect(productProblem({ ...draft, width: "999.9" })).toBeNull();
    expect(productBody({ ...draft, width: "12,5" }).decoration_width_cm).toBe(12.5);
  });
});
