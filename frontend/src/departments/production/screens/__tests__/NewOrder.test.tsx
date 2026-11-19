// @vitest-environment jsdom
import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { makeOrder, mockApi, narrowScreen, owner, qc, renderAt } from "./fixtures";

const choices = {
  suppliers: [
    { id: "SUP-1", name: "Main factory", category: "Manufacturer" },
    { id: "SUP-2", name: "Print house A", category: "Printing" },
  ],
  products: [
    { id: "P1", title: "Oversized hoodie", status: "active", image_url: "https://cdn.example/hoodie.jpg" },
    { id: "P2", title: "Zip hoodie", status: "draft", image_url: null },
    { id: "P3", title: "Wide-leg sweatpants", status: "active", image_url: null },
  ],
  sizes: ["XS", "S", "M", "L", "XL", "XXL"],
  stage_days: { sample: 7, materials: 7, fabric_check: 2, pattern_check: 3, cutting: 2, making: 17, final_inspection: 1, warehouse: 3, settle: 7 },
};

const type = (label: string | RegExp, value: string) => fireEvent.change(screen.getByLabelText(label), { target: { value } });
const sizes = () => within(screen.getByRole("group", { name: "Pieces per size" }));
const dateOf = (label: string) => (screen.getByLabelText(label) as HTMLInputElement).value;
const styleBox = () => screen.getByRole("combobox", { name: "Style, from the product list" }) as HTMLInputElement;
/** Open the style list and press a line of it. */
function pickStyle(name: string | RegExp) {
  fireEvent.click(styleBox());
  fireEvent.click(within(screen.getByRole("listbox", { name: "Products" })).getByRole("option", { name }));
}

async function fill() {
  await screen.findByLabelText("Style, from the product list");
  pickStyle(/^Oversized hoodie/);
  type("Colour", "Black");
  type("Factory", "SUP-1");
  for (const [size, count] of Object.entries({ S: "150", M: "300", L: "300", XL: "180", XXL: "70" })) {
    fireEvent.change(sizes().getByLabelText(size), { target: { value: count } });
  }
  type("Target date", "2030-11-03");
  for (const [part, amount] of Object.entries({ Fabric: "165", Manufacturing: "85", Printing: "30", Accessories: "12", Packaging: "8" })) {
    type(`${part}, target cost`, amount);
  }
}

beforeEach(() => narrowScreen(false));
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("New production order", () => {
  it("totals the pieces and the cost as they are typed", async () => {
    mockApi({ "GET /api/prod/choices": choices });
    renderAt("/production/orders/new", owner());
    await fill();
    expect(screen.getByText("Total 1,000 pieces")).toBeTruthy();
    expect(screen.getByText("Total EGP 300.00 per piece · EGP 300,000.00 for the order")).toBeTruthy();
  });

  it("fills each stage's expected date backwards from the target date, and again when it moves", async () => {
    mockApi({ "GET /api/prod/choices": choices });
    renderAt("/production/orders/new", owner());
    await fill();
    await waitFor(() => expect(dateOf("At the warehouse")).toBe("2030-11-03"));
    expect(dateOf("Final inspection")).toBe("2030-10-31");
    expect(dateOf("Making finished")).toBe("2030-10-30");
    expect(dateOf("Cutting")).toBe("2030-10-13");
    expect(dateOf("Pattern check")).toBe("2030-10-11");
    expect(dateOf("Fabric check")).toBe("2030-10-08");
    expect(dateOf("Materials arrive")).toBe("2030-10-06");
    expect(dateOf("Sample approved")).toBe("2030-09-29");

    // Edited by hand: it stays when the target date moves; the rest follow.
    fireEvent.change(screen.getByLabelText("Cutting"), { target: { value: "2030-10-20" } });
    type("Target date", "2030-11-10");
    await waitFor(() => expect(dateOf("At the warehouse")).toBe("2030-11-10"));
    expect(dateOf("Making finished")).toBe("2030-11-06");
    expect(dateOf("Cutting")).toBe("2030-10-20");

    // A repeat run skips the sample.
    fireEvent.click(screen.getByLabelText(/Repeat run with nothing changed/));
    const sample = screen.getByLabelText("Sample approved") as HTMLInputElement;
    expect(sample.value).toBe("Skipped");
    expect(sample.disabled).toBe(true);
  });

  it("refuses what the server would refuse, before sending", async () => {
    const calls = mockApi({ "GET /api/prod/choices": choices });
    renderAt("/production/orders/new", owner());
    await screen.findByLabelText("Style, from the product list");
    fireEvent.click(screen.getByRole("button", { name: "Create order" }));
    expect((await screen.findByRole("alert")).textContent).toBe("Choose the style, or type a new name.");
    pickStyle(/^A new style, not on Shopify yet/);
    type("Style name", "Boxy tee");
    type("Colour", "Black");
    type("Factory", "SUP-1");
    fireEvent.click(screen.getByRole("button", { name: "Create order" }));
    expect((await screen.findByRole("alert")).textContent).toBe("Plan at least one piece.");
    expect(calls.filter((call) => call.method === "POST")).toHaveLength(0);
    // Outside printing needs a print house.
    fireEvent.change(screen.getByLabelText("Printing", { selector: "select" }), { target: { value: "outside" } });
    fireEvent.change(sizes().getByLabelText("S"), { target: { value: "5" } });
    fireEvent.click(screen.getByRole("button", { name: "Create order" }));
    expect((await screen.findByRole("alert")).textContent).toBe("Choose the print house.");
  });

  it("creates the order with the dates, then opens it", async () => {
    const calls = mockApi({
      "GET /api/prod/choices": choices,
      "POST /api/prod/orders": () => ({ order: makeOrder("plan", { money: true, extra: { id: 9 } }) }),
      "GET /api/prod/orders/9": { order: makeOrder("materials", { money: true, extra: { id: 9, style_name: "Oversized hoodie" } }) },
      "GET /api/prod/orders/9/history": { events: [] },
      "GET /api/prod/orders/9/files": { files: [] },
    });
    renderAt("/production/orders/new", owner());
    await fill();
    fireEvent.click(screen.getByLabelText(/Repeat run with nothing changed/));
    await waitFor(() => expect(dateOf("Materials arrive")).toBe("2030-10-06"));
    fireEvent.click(screen.getByRole("button", { name: "Create order" }));

    expect(await screen.findByRole("heading", { level: 1, name: /Oversized hoodie/ })).toBeTruthy();
    const posted = calls.find((call) => call.method === "POST")!;
    expect(posted.path).toBe("/api/prod/orders");
    expect(posted.body).toMatchObject({
      style_name: "Oversized hoodie",
      shopify_product_id: "P1",
      colour: "Black",
      factory_id: "SUP-1",
      fabric_bought_by: "hba",
      printing: "factory",
      print_supplier_id: null,
      repeat_run: true,
      target_date: "2030-11-03",
      planned: { S: 150, M: 300, L: 300, XL: 180, XXL: 70 },
      target_fabric_piastres: 16500,
      target_manufacturing_piastres: 8500,
      target_printing_piastres: 3000,
      target_accessories_piastres: 1200,
      target_packaging_piastres: 800,
    });
    const dates = (posted.body as { expected_dates: Record<string, string> }).expected_dates;
    expect(dates).toMatchObject({ materials: "2030-10-06", cutting: "2030-10-13", making: "2030-10-30", warehouse: "2030-11-03" });
    expect(dates).not.toHaveProperty("sample");
  });

  it("is for owners only", async () => {
    const calls = mockApi({ "GET /api/prod/choices": choices });
    renderAt("/production/orders/new", qc());
    expect(await screen.findByText("Only owners make production orders.")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Create order" })).toBeNull();
    // The screen reads nothing of its own; the layout's tab row reads only the overdue task count.
    expect(calls.filter((call) => call.path !== "/api/prod/tasks")).toHaveLength(0);
  });
});

describe("The style picker", () => {
  const list = () => within(screen.getByRole("listbox", { name: "Products" }));
  const titles = () => list().getAllByRole("option").map((option) => option.textContent);

  async function openNew() {
    mockApi({ "GET /api/prod/choices": choices });
    renderAt("/production/orders/new", owner());
    await screen.findByRole("combobox", { name: "Style, from the product list" });
  }

  it("narrows the list as the name is typed, anywhere in it and in any case, keeping the new style last", async () => {
    await openNew();
    const box = styleBox();
    expect(box.getAttribute("aria-expanded")).toBe("false");
    fireEvent.click(box);
    expect(box.getAttribute("aria-expanded")).toBe("true");
    expect(titles()).toEqual(["Oversized hoodie", "Zip hoodieDraft", "Wide-leg sweatpants", "A new style, not on Shopify yet"]);
    fireEvent.change(box, { target: { value: "HOOD" } });
    expect(titles()).toEqual(["Oversized hoodie", "Zip hoodieDraft", "A new style, not on Shopify yet"]);
    fireEvent.change(box, { target: { value: "leg sw" } });
    expect(titles()).toEqual(["Wide-leg sweatpants", "A new style, not on Shopify yet"]);
    fireEvent.change(box, { target: { value: "nothing like it" } });
    expect(titles()).toEqual(["A new style, not on Shopify yet"]);
    expect(screen.getByText("No product matches “nothing like it”.")).toBeTruthy();
  });

  it("shows each product's picture, a blank tile without one, and Draft on a draft", async () => {
    await openNew();
    fireEvent.click(styleBox());
    const hoodie = list().getByRole("option", { name: /^Oversized hoodie/ });
    const picture = hoodie.querySelector("img")!;
    expect(picture.getAttribute("src")).toBe("https://cdn.example/hoodie.jpg");
    expect(picture.getAttribute("loading")).toBe("lazy");
    const zip = list().getByRole("option", { name: /^Zip hoodie/ });
    expect(zip.querySelector("img")).toBeNull();
    expect(zip.querySelector(".prod-style__thumb--none")).toBeTruthy();
    expect(within(zip).getByText("Draft")).toBeTruthy();
    expect(within(hoodie).queryByText("Draft")).toBeNull();
  });

  it("picks with a click, then shows the chosen product and its picture when closed", async () => {
    await openNew();
    fireEvent.click(styleBox());
    fireEvent.click(list().getByRole("option", { name: /^Zip hoodie/ }));
    expect(styleBox().getAttribute("aria-expanded")).toBe("false");
    expect(styleBox().value).toBe("Zip hoodie");
    expect(screen.queryByLabelText("Style name")).toBeNull();
    pickStyle(/^Oversized hoodie/);
    expect(styleBox().value).toBe("Oversized hoodie");
    expect(styleBox().closest(".prod-style__box")!.querySelector("img")!.getAttribute("src")).toBe("https://cdn.example/hoodie.jpg");
  });

  it("moves with the arrows, picks with Enter and closes with Escape", async () => {
    await openNew();
    const box = styleBox();
    fireEvent.keyDown(box, { key: "ArrowDown" });
    expect(box.getAttribute("aria-expanded")).toBe("true");
    fireEvent.keyDown(box, { key: "ArrowDown" });
    const active = box.getAttribute("aria-activedescendant")!;
    expect(document.getElementById(active)!.textContent).toBe("Zip hoodieDraft");
    expect(document.getElementById(active)!.getAttribute("aria-selected")).toBe("true");
    fireEvent.keyDown(box, { key: "Enter" });
    expect(box.value).toBe("Zip hoodie");
    expect(box.getAttribute("aria-expanded")).toBe("false");
    fireEvent.keyDown(box, { key: "ArrowDown" });
    fireEvent.keyDown(box, { key: "Escape" });
    expect(box.getAttribute("aria-expanded")).toBe("false");
    expect(box.value).toBe("Zip hoodie");
  });

  it("still offers a new style, with its own name box", async () => {
    await openNew();
    pickStyle(/^A new style, not on Shopify yet/);
    expect(styleBox().value).toBe("A new style, not on Shopify yet");
    type("Style name", "Boxy tee");
    expect((screen.getByLabelText("Style name") as HTMLInputElement).value).toBe("Boxy tee");
  });
});
