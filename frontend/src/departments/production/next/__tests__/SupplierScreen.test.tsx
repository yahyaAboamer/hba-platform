// @vitest-environment jsdom
import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { Session } from "../../../../lib/api";
import type { Section, SupplierRow } from "../types";
import { makeRow, mockApi, narrowScreen, owner, qc, renderAt, reply } from "./fixtures";
import type { Call } from "./fixtures";
import { SECTIONS, factoryRow, makeSupplierList, makeSupplierRow, moneyKeysIn } from "./supplierFixtures";

const ADDRESS = "/production/next/suppliers";

const rows = (money = true): SupplierRow[] => [
  factoryRow(money),
  makeSupplierRow({ id: "fab", name: "Fabric supplier A", sections: [{ id: 7, name: "Fabric" }], open_purchases: 1, owed_piastres: -60000 }, money),
  makeSupplierRow({ id: "prt", name: "Print house A" }, money),
  makeSupplierRow({ id: "old", name: "Closed mill", active: false, sections: [{ id: 7, name: "Fabric" }] }, money),
];

/** A manager: reads, and manages suppliers and sections, but holds no money. */
const manager = (): Session => {
  const session = qc();
  session.permissions = ["production.view", "production.edit", "production.suppliers"];
  return session;
};

const writes = (calls: Call[]) => calls.filter((call) => call.method !== "GET");
const type = (label: string, value: string) => fireEvent.change(screen.getByLabelText(label), { target: { value } });
const panelOf = (name: string): HTMLElement => screen.getByRole("heading", { name, level: 2 }).closest("section")!;
const click = (name: string | RegExp) => fireEvent.click(screen.getByRole("button", { name }));

/** The list as the server keeps it, so a section written changes the next read. */
function serve(money = true, extra: Record<string, unknown> = {}) {
  const state = { sections: SECTIONS.map((section) => ({ ...section })), rows: rows(money) };
  const calls = mockApi({
    "GET /api/prod/suppliers": () => makeSupplierList(state.rows, money, state.sections),
    "GET /api/prod/orders": { orders: [makeRow({ id: 2, style_name: "Oversized hoodie", planned_total: 1000, cut_total: null })] },
    ...extra,
  });
  return { calls, state };
}

const sectionsAnswer = (sections: Section[], extra: object = {}) => ({ sections, ...extra });

beforeEach(() => {
  narrowScreen(false);
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(new Date("2030-11-13T10:00:00Z"));
});
afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe("The supplier list, by who is looking", () => {
  it("shows the owner what is owed, in words, and the controls", async () => {
    serve();
    renderAt(ADDRESS, owner());
    expect(await screen.findByRole("heading", { level: 1, name: "Suppliers" })).toBeTruthy();

    expect(screen.getByText("3 suppliers · you owe EGP 2,750.00 in total")).toBeTruthy();
    const list = screen.getByRole("list", { name: "Suppliers" });
    const factory = within(list).getByText("Main factory").closest("li")!;
    expect(factory.textContent).toContain("Manufacturers · 1 order open · 2 purchases not received");
    expect(factory.textContent).toContain("You owe EGP 2,750.00");
    expect(within(list).getByText("Fabric supplier A").closest("li")!.textContent).toContain("Overpaid EGP 600.00");
    expect(within(list).getByText("Print house A").closest("li")!.textContent).toContain("Nothing owed");
    expect(within(list).getByText("Print house A").closest("li")!.textContent).toContain("No section · nothing open");
    expect(within(list).getByRole("link", { name: "Main factory" }).getAttribute("href")).toBe("/production/next/suppliers/fac");

    expect(screen.getByRole("button", { name: "Record a purchase" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Add supplier" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "+ Add section" })).toBeTruthy();
  });

  it("shows the QC manager no money and no money control: not a figure, not an empty column, not a zero", async () => {
    const { calls } = serve(false);
    renderAt(ADDRESS, qc());
    await screen.findByText("Main factory");

    expect(screen.getByText("3 suppliers")).toBeTruthy();
    expect(document.body.textContent).not.toMatch(/EGP|You owe|Overpaid|Nothing owed|owe/);
    expect(screen.queryByRole("button", { name: "Record a purchase" })).toBeNull();
    // Nor the managers' controls.
    expect(screen.queryByRole("button", { name: "Add supplier" })).toBeNull();
    expect(screen.queryByRole("button", { name: "+ Add section" })).toBeNull();
    // What is there: names, sections, what is open.
    expect(screen.getByText("Manufacturers · 1 order open · 2 purchases not received")).toBeTruthy();
    expect(writes(calls)).toEqual([]);
  });

  it("gives a manager the supplier controls but still no money", async () => {
    serve(false);
    renderAt(ADDRESS, manager());
    await screen.findByText("Main factory");
    expect(screen.getByRole("button", { name: "Add supplier" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "+ Add section" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Record a purchase" })).toBeNull();
    expect(document.body.textContent).not.toMatch(/EGP|You owe|Overpaid/);
  });

  it("holds inactive suppliers behind a tick, marked in words", async () => {
    serve();
    renderAt(ADDRESS, owner());
    await screen.findByText("Main factory");
    expect(screen.queryByText("Closed mill")).toBeNull();
    fireEvent.click(screen.getByRole("checkbox", { name: "Show inactive" }));
    const mill = screen.getByText("Closed mill").closest("li")!;
    expect(within(mill).getByText("Inactive")).toBeTruthy();
    // The chips count what is shown.
    expect(screen.getByRole("button", { name: "All · 4" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Fabric · 2" })).toBeTruthy();
  });

  it("filters by section chip, with counts, and says when a section is empty", async () => {
    serve();
    renderAt(ADDRESS, owner());
    await screen.findByText("Main factory");
    expect(screen.getByRole("button", { name: "All · 3" }).getAttribute("aria-pressed")).toBe("true");
    expect(screen.getByRole("button", { name: "Manufacturers · 1" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Packaging · 0" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "No section · 1" })).toBeTruthy();

    click("Fabric · 1");
    expect(screen.queryByText("Main factory")).toBeNull();
    expect(screen.getByText("Fabric supplier A")).toBeTruthy();
    click("Packaging · 0");
    expect(screen.getByText("No suppliers in this section.")).toBeTruthy();
  });

  it("stacks the rows on a phone", async () => {
    narrowScreen(true);
    serve();
    renderAt(ADDRESS, owner());
    await screen.findByText("Main factory");
    expect(document.querySelectorAll(".prod-task--narrow").length).toBe(3);
  });

  it("says why the list did not load, and tries again", async () => {
    let fail = true;
    mockApi({ "GET /api/prod/suppliers": () => (fail ? reply(500, { detail: "The suppliers are away." }) : makeSupplierList(rows())) });
    renderAt(ADDRESS, owner());
    expect((await screen.findByRole("alert")).textContent).toBe("The suppliers are away.");
    fail = false;
    click("Try again");
    expect(await screen.findByText("Main factory")).toBeTruthy();
  });
});

describe("Sections", () => {
  it("adds one by name, and shows its chip", async () => {
    const { calls, state } = serve(true, {
      "POST /api/prod/sections": (body: { name: string }) => {
        state.sections.push({ id: 9, name: body.name, position: 4, supplier_count: 0 });
        return reply(201, sectionsAnswer(state.sections, { section_id: 9 }));
      },
    });
    renderAt(ADDRESS, owner());
    await screen.findByText("Main factory");

    click("+ Add section");
    expect(document.activeElement).toBe(screen.getByLabelText("Name of the new section"));
    // A blank name is refused before it is sent.
    click("Add section");
    expect((await screen.findByRole("alert")).textContent).toBe("Give the section a name.");
    expect(writes(calls)).toEqual([]);

    type("Name of the new section", "Trims");
    click("Add section");
    expect(await screen.findByRole("button", { name: "Trims · 0" })).toBeTruthy();
    expect(writes(calls).map((call) => [call.method, call.path, call.body])).toEqual([["POST", "/api/prod/sections", { name: "Trims" }]]);
    expect(screen.getByRole("status").textContent).toBe("Added the Trims section.");
    // The name box has gone, and focus is back on the chip that opened it.
    expect(screen.queryByLabelText("Name of the new section")).toBeNull();
    expect(document.activeElement).toBe(screen.getByRole("button", { name: "+ Add section" }));
  });

  it("renames one and reads the rows again, since they carry its name", async () => {
    const { calls, state } = serve(true, {
      "PATCH /api/prod/sections/7": (body: { name: string }) => {
        state.sections[1].name = body.name;
        state.rows = state.rows.map((row) => ({ ...row, sections: row.sections.map((section) => (section.id === 7 ? { ...section, name: body.name } : section)) }));
        return sectionsAnswer(state.sections);
      },
    });
    renderAt(ADDRESS, owner());
    await screen.findByText("Main factory");

    click("Fabric · 1");
    click(/^Rename\s*Fabric$/);
    expect((screen.getByLabelText("New name for Fabric") as HTMLInputElement).value).toBe("Fabric");
    type("New name for Fabric", "Cloth");
    click("Save name");
    expect(await screen.findByRole("button", { name: "Cloth · 1" })).toBeTruthy();
    expect(writes(calls).map((call) => [call.method, call.path, call.body])).toEqual([["PATCH", "/api/prod/sections/7", { name: "Cloth" }]]);
    expect(screen.getByText("Cloth · 1 purchase not received")).toBeTruthy();
  });

  it("offers Remove only on an empty section, asks first, and drops the chip", async () => {
    const { calls, state } = serve(true, {
      "DELETE /api/prod/sections/8": () => {
        state.sections = state.sections.filter((section) => section.id !== 8);
        return sectionsAnswer(state.sections, { deleted: 8 });
      },
    });
    renderAt(ADDRESS, owner());
    await screen.findByText("Main factory");

    // A section with suppliers in it cannot be removed, and says why.
    click("Manufacturers · 1");
    expect(screen.queryByRole("button", { name: /^Remove\s*Manufacturers$/ })).toBeNull();
    expect(screen.getByText(/can be removed once no supplier is in it \(1 is, counting inactive ones\)/)).toBeTruthy();

    click("Packaging · 0");
    click(/^Remove\s*Packaging$/);
    expect(screen.getByText("Remove the Packaging section?")).toBeTruthy();
    // The safe answer has focus.
    expect(document.activeElement).toBe(screen.getByRole("button", { name: "Keep it" }));
    expect(writes(calls)).toEqual([]);
    click("Remove section");
    await waitFor(() => expect(screen.queryByRole("button", { name: "Packaging · 0" })).toBeNull());
    expect(writes(calls).map((call) => [call.method, call.path])).toEqual([["DELETE", "/api/prod/sections/8"]]);
    expect(screen.getByRole("status").textContent).toBe("Removed the Packaging section.");
    // The removed section was the one chosen: the list is back to all.
    expect(screen.getByRole("button", { name: "All · 3" }).getAttribute("aria-pressed")).toBe("true");
  });

  it("shows the server's refusal when it will not remove a section", async () => {
    serve(true, { "DELETE /api/prod/sections/8": () => reply(422, { detail: "1 supplier is still in Packaging. Move them to another section first." }) });
    renderAt(ADDRESS, owner());
    await screen.findByText("Main factory");
    click("Packaging · 0");
    click(/^Remove\s*Packaging$/);
    click("Remove section");
    expect((await screen.findByRole("alert")).textContent).toBe("1 supplier is still in Packaging. Move them to another section first.");
    // It is still there.
    expect(screen.getByRole("button", { name: "Packaging · 0" })).toBeTruthy();
  });

  it("keeps the section when the person says keep it", async () => {
    const { calls } = serve();
    renderAt(ADDRESS, owner());
    await screen.findByText("Main factory");
    click("Packaging · 0");
    click(/^Remove\s*Packaging$/);
    click("Keep it");
    expect(screen.queryByText("Remove the Packaging section?")).toBeNull();
    expect(writes(calls)).toEqual([]);
    expect(document.activeElement).toBe(screen.getByRole("button", { name: /^Remove\s*Packaging$/ }));
  });
});

describe("Add supplier", () => {
  it("adds one with its sections, then reads the list again", async () => {
    const { calls, state } = serve(true, {
      "POST /api/prod/suppliers": (body: { name: string }) => {
        state.rows.push(makeSupplierRow({ id: "new", name: body.name, sections: [{ id: 7, name: "Fabric" }] }));
        return reply(201, { supplier: { ...state.rows.at(-1), purchases: [], orders: [] } });
      },
    });
    renderAt(ADDRESS, owner());
    await screen.findByText("Main factory");

    click("Add supplier");
    const panel = panelOf("Add supplier");
    // A name is needed.
    fireEvent.click(within(panel).getByRole("button", { name: "Add supplier" }));
    expect((await screen.findByRole("alert")).textContent).toBe("Give the supplier's name.");

    type("Name", "Trims supplier");
    type("City, optional", "Giza");
    fireEvent.click(within(panel).getByRole("checkbox", { name: "Fabric" }));
    fireEvent.click(within(panel).getByRole("button", { name: "Add supplier" }));

    expect(await screen.findByText("Trims supplier")).toBeTruthy();
    expect(writes(calls).map((call) => [call.method, call.path, call.body])).toEqual([
      [
        "POST",
        "/api/prod/suppliers",
        { name: "Trims supplier", contact_person: null, phone: null, whatsapp: null, city: "Giza", notes: null, section_ids: [7] },
      ],
    ]);
    expect(screen.getByRole("status").textContent).toBe("Added Trims supplier.");
    // Focus is back on the button that opened the panel.
    await waitFor(() => expect(document.activeElement).toBe(screen.getByRole("button", { name: "Add supplier" })));
  });

  it("shows the server's words when it refuses", async () => {
    serve(true, { "POST /api/prod/suppliers": () => reply(422, { detail: "There is already a supplier called Trims supplier." }) });
    renderAt(ADDRESS, owner());
    await screen.findByText("Main factory");
    click("Add supplier");
    type("Name", "Trims supplier");
    fireEvent.click(within(panelOf("Add supplier")).getByRole("button", { name: "Add supplier" }));
    expect((await screen.findByRole("alert")).textContent).toBe("There is already a supplier called Trims supplier.");
    // The panel stays open, with what was typed.
    expect((screen.getByLabelText("Name") as HTMLInputElement).value).toBe("Trims supplier");
  });
});

describe("Record a purchase, from the list", () => {
  it("works the total as the person types, and sends pounds as piastres, with no total", async () => {
    const { calls } = serve(true, { "POST /api/prod/suppliers/fac/purchases": () => reply(201, { supplier: {}, purchase_id: 9 }) });
    renderAt(ADDRESS, owner());
    await screen.findByText("Main factory");

    click("Record a purchase");
    const panel = panelOf("Record a purchase");
    // Only active suppliers are offered.
    const options = within(within(panel).getByLabelText("Supplier")).getAllByRole("option").map((option) => option.textContent);
    expect(options).toEqual(["Choose a supplier", "Main factory", "Fabric supplier A", "Print house A"]);

    expect(within(panel).getByText("Give the quantity and the price to see the total.")).toBeTruthy();
    type("Supplier", "fac");
    type("What was bought", "Heavy fleece, black");
    type("Quantity", "1,075");
    expect(screen.getByLabelText("Price per kilogram, EGP")).toBeTruthy();
    type("Price per kilogram, EGP", "160");
    expect(within(panel).getByText(/^Total EGP 172,000\.00\. All of it goes on this supplier's balance/)).toBeTruthy();

    // The label follows the unit.
    type("Measured in", "m");
    expect(screen.getByLabelText("Price per metre, EGP")).toBeTruthy();
    type("Measured in", "kg");

    type("Deposit paid now, EGP, optional", "40,000");
    expect(within(panel).getByText(/After the deposit, EGP 132,000\.00 of it is still owed/)).toBeTruthy();

    // An order picked: what this purchase adds to its cost per piece.
    await waitFor(() => expect(within(panel).getByRole("option", { name: "Oversized hoodie · Black · PO-2611-02" })).toBeTruthy());
    type("For which order, optional", "2");
    expect(within(panel).getByText("For PO-2611-02 that adds EGP 172.00 per piece to its fabric cost, over 1,000 planned pieces.")).toBeTruthy();

    fireEvent.click(within(panel).getByRole("button", { name: "Save purchase" }));
    await waitFor(() => expect(screen.getByRole("status").textContent).toBe("Purchase recorded: Heavy fleece, black from Main factory."));
    expect(writes(calls).map((call) => [call.method, call.path, call.body])).toEqual([
      [
        "POST",
        "/api/prod/suppliers/fac/purchases",
        {
          item: "Heavy fleece, black",
          quantity: "1075",
          unit: "kg",
          unit_price_piastres: 16000,
          part: "fabric",
          order_id: 2,
          bought_on: "2030-11-13",
          expected_on: null,
          note: null,
          deposit_piastres: 4000000,
          deposit_method: "bank_transfer",
        },
      ],
    ]);
  });

  it("rounds the total half up and refuses a deposit above it, before sending", async () => {
    const { calls } = serve();
    renderAt(ADDRESS, owner());
    await screen.findByText("Main factory");
    click("Record a purchase");
    const panel = panelOf("Record a purchase");
    type("Supplier", "fac");
    type("What was bought", "Buttons");
    // 1.005 at EGP 1.00 is 100.5 piastres: EGP 1.01.
    type("Quantity", "1.005");
    type("Price per kilogram, EGP", "1");
    expect(within(panel).getByText(/^Total EGP 1\.01\./)).toBeTruthy();

    type("Deposit paid now, EGP, optional", "1.02");
    fireEvent.click(within(panel).getByRole("button", { name: "Save purchase" }));
    expect((await within(panel).findByRole("alert")).textContent).toBe("The deposit can't be more than the total.");
    expect(writes(calls)).toEqual([]);
  });

  it("says before sending what is missing", async () => {
    const { calls } = serve();
    renderAt(ADDRESS, owner());
    await screen.findByText("Main factory");
    click("Record a purchase");
    const panel = panelOf("Record a purchase");
    fireEvent.click(within(panel).getByRole("button", { name: "Save purchase" }));
    expect((await within(panel).findByRole("alert")).textContent).toBe("Choose the supplier.");
    type("Supplier", "fac");
    fireEvent.click(within(panel).getByRole("button", { name: "Save purchase" }));
    expect((await within(panel).findByRole("alert")).textContent).toBe("Say what was bought.");
    expect(writes(calls)).toEqual([]);
  });

  it("shows the server's refusal as it is", async () => {
    serve(true, { "POST /api/prod/suppliers/fac/purchases": () => reply(422, { detail: "Pick an order that is still in production." }) });
    renderAt(ADDRESS, owner());
    await screen.findByText("Main factory");
    click("Record a purchase");
    const panel = panelOf("Record a purchase");
    type("Supplier", "fac");
    type("What was bought", "Zips");
    type("Quantity", "10");
    type("Price per kilogram, EGP", "3");
    fireEvent.click(within(panel).getByRole("button", { name: "Save purchase" }));
    expect((await within(panel).findByRole("alert")).textContent).toBe("Pick an order that is still in production.");
  });
});

describe("What reaches the page", () => {
  it("carries no money key for the QC manager", () => {
    // The fixture is what the server sends somebody without the owner permission.
    expect(moneyKeysIn(makeSupplierList(rows(false), false))).toEqual([]);
    expect(moneyKeysIn(makeSupplierList(rows(true), true))).not.toEqual([]);
  });
});
