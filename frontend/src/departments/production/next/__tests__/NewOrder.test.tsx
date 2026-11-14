// @vitest-environment jsdom
import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { makeOrder, mockApi, narrowScreen, owner, qc, renderAt } from "./fixtures";

const choices = {
  suppliers: [
    { id: "SUP-1", name: "Main factory", category: "Manufacturer" },
    { id: "SUP-2", name: "Print house A", category: "Printing" },
  ],
  products: [{ id: "P1", title: "Oversized hoodie" }],
  sizes: ["XS", "S", "M", "L", "XL", "XXL"],
  stage_days: { sample: 7, materials: 7, fabric_check: 2, pattern_check: 3, cutting: 2, making: 17, final_inspection: 1, warehouse: 3, settle: 7 },
};

const type = (label: string | RegExp, value: string) => fireEvent.change(screen.getByLabelText(label), { target: { value } });
const sizes = () => within(screen.getByRole("group", { name: "Pieces per size" }));
const dateOf = (label: string) => (screen.getByLabelText(label) as HTMLInputElement).value;

async function fill() {
  await screen.findByLabelText("Style, from the product list");
  type("Style, from the product list", "P1");
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
    renderAt("/production/next/orders/new", owner());
    await fill();
    expect(screen.getByText("Total 1,000 pieces")).toBeTruthy();
    expect(screen.getByText("Total EGP 300.00 per piece · EGP 300,000.00 for the order")).toBeTruthy();
  });

  it("fills each stage's expected date backwards from the target date, and again when it moves", async () => {
    mockApi({ "GET /api/prod/choices": choices });
    renderAt("/production/next/orders/new", owner());
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
    renderAt("/production/next/orders/new", owner());
    await screen.findByLabelText("Style, from the product list");
    fireEvent.click(screen.getByRole("button", { name: "Create order" }));
    expect((await screen.findByRole("alert")).textContent).toBe("Choose the style, or type a new name.");
    type("Style, from the product list", "__new");
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
    renderAt("/production/next/orders/new", owner());
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
    renderAt("/production/next/orders/new", qc());
    expect(await screen.findByText("Only owners make production orders.")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Create order" })).toBeNull();
    // The screen reads nothing of its own; the layout's tab row reads only the overdue task count.
    expect(calls.filter((call) => call.path !== "/api/prod/tasks")).toHaveLength(0);
  });
});
