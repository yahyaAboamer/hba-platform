// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useLocation, useNavigate } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { formatEgp } from "../../../../lib/money";
import { cancelSentence } from "../logic";
import { productionRoutes } from "../routes";
import type { Delivery, OrderView } from "../types";
import { makeOrder, mockApi, narrowScreen, owner, qc, renderAt, reply } from "./fixtures";
import type { Call } from "./fixtures";

const ADDRESS = "/production/orders/3";

/** The routes every order page reads besides the order itself. */
function serve(order: OrderView, extra: Record<string, unknown> = {}) {
  return mockApi({
    "GET /api/prod/orders/3": { order },
    "GET /api/prod/orders/3/history": { events: [{ id: 1, at: "2030-09-28T08:00:00Z", who: "Nour", action: "production.order_created", summary: "Created PO-2611-01" }] },
    "GET /api/prod/orders/3/files": { files: [] },
    ...extra,
  });
}

const type = (label: string, value: string) => fireEvent.change(screen.getByLabelText(label), { target: { value } });
const writes = (calls: Call[]) => calls.filter((call) => call.method !== "GET");

beforeEach(() => narrowScreen(false));
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("One order, by who is looking", () => {
  it("shows the owner the cost, what is owed and the owner's controls", async () => {
    serve(makeOrder("final_inspection", { money: true }));
    renderAt(ADDRESS, owner());
    expect(await screen.findByRole("heading", { level: 1, name: "Oversized hoodie · Black" })).toBeTruthy();

    expect(screen.getByRole("heading", { name: "Cost per piece" })).toBeTruthy();
    expect(screen.getByRole("heading", { name: "Owed to the factory for this order" })).toBeTruthy();
    expect(screen.getAllByText("EGP 3,450.00").length).toBeGreaterThan(0);
    expect(screen.getByRole("button", { name: "Edit actual cost" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Edit the order" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Cancel this order" })).toBeTruthy();
  });

  it("shows the QC manager no money at all, and none of the owner's controls", async () => {
    serve(makeOrder("final_inspection"));
    renderAt(ADDRESS, qc());
    await screen.findByRole("heading", { level: 1, name: "Oversized hoodie · Black" });

    expect(screen.queryByRole("heading", { name: "Cost per piece" })).toBeNull();
    expect(screen.queryByRole("heading", { name: /Owed to the factory/ })).toBeNull();
    expect(document.body.textContent).not.toMatch(/EGP/);
    for (const name of ["Edit actual cost", "Edit the order", "Cancel this order", "Settle with the factory", "Review the sample"]) {
      expect(screen.queryByRole("button", { name })).toBeNull();
    }
    // What the QC manager does stays.
    expect(screen.getByRole("button", { name: "Record the inspection" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Change date" })).toBeTruthy();
  });

  it("offers nothing to somebody who can only read", async () => {
    serve(makeOrder("final_inspection"));
    const reader = qc();
    reader.permissions = ["production.view"];
    renderAt(ADDRESS, reader);
    await screen.findByRole("heading", { level: 1, name: "Oversized hoodie · Black" });
    expect(screen.queryByRole("button", { name: "Record the inspection" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Change date" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Add a photo" })).toBeNull();
  });

  it("shows the stages, the pieces by size, the date history and the order's history", async () => {
    serve(makeOrder("final_inspection"));
    renderAt(ADDRESS, qc());
    await screen.findByRole("heading", { level: 1, name: "Oversized hoodie · Black" });
    expect(screen.getByText("8 of 10 · Final inspection")).toBeTruthy();
    expect(screen.getByText("Next: finish the final inspection")).toBeTruthy();
    expect(screen.getByText("Skipped: Repeat run, nothing changed")).toBeTruthy();
    const sizes = screen.getByRole("heading", { name: "Pieces by size" }).closest("section")!;
    expect(within(sizes).getAllByRole("row")).toHaveLength(4);
    expect(screen.getByText("Target when planned")).toBeTruthy();
    expect(await screen.findByText("Created PO-2611-01")).toBeTruthy();
  });
});

describe("Cutting", () => {
  it("refuses until the reasons add up to the shortfall, then sends them", async () => {
    const calls = serve(makeOrder("cutting"), {
      "PUT /api/prod/orders/3/cut": () => ({ order: makeOrder("final_inspection") }),
    });
    renderAt(ADDRESS, qc());
    await screen.findByRole("heading", { level: 1, name: "Oversized hoodie · Black" });

    fireEvent.click(screen.getAllByRole("button", { name: "Record cut quantities" })[0]);
    const form = screen.getByRole("heading", { name: "Record cut quantities", level: 2 }).closest("section")!;
    const cut = within(within(form).getByRole("group", { name: "Pieces cut" }));
    expect((cut.getByLabelText("S") as HTMLInputElement).value).toBe("10");

    // Three short in size S: reasons appear and must add up to 3.
    fireEvent.change(cut.getByLabelText("S"), { target: { value: "7" } });
    expect(screen.getByText("Cut 27 of 30 planned: 3 pieces fewer")).toBeTruthy();
    expect(screen.getByText("Reasons add up to 0 of 3")).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "Save cut quantities" }));
    expect((await screen.findByRole("alert")).textContent).toBe(
      "3 pieces fewer were cut than planned; the reasons account for 0. Make them add up to 3.",
    );
    expect(writes(calls)).toHaveLength(0);

    type("Reason 1", "Fabric defects");
    type("Pieces for reason 1", "2");
    expect(screen.getByText("Reasons add up to 2 of 3")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Save cut quantities" }));
    expect((await screen.findByRole("alert")).textContent).toMatch(/account for 2/);
    expect(writes(calls)).toHaveLength(0);

    type("Pieces for reason 1", "3");
    fireEvent.click(screen.getByRole("button", { name: "Save cut quantities" }));
    await waitFor(() => expect(writes(calls)).toHaveLength(1));
    const sent = writes(calls)[0];
    expect(sent.method).toBe("PUT");
    expect(sent.path).toBe("/api/prod/orders/3/cut");
    expect(sent.body).toMatchObject({
      sizes: { S: 7, M: 20 },
      reasons: [{ reason: "Fabric defects", quantity: 3 }],
      promised_date: "2030-11-03",
    });
    expect(await screen.findByText("Cut quantities recorded.")).toBeTruthy();
    expect(screen.queryByRole("heading", { name: "Record cut quantities", level: 2 })).toBeNull();
  });

  it("shows the server's own words when it still refuses", async () => {
    serve(makeOrder("cutting"), {
      "PUT /api/prod/orders/3/cut": () => reply(422, { detail: "Finish Pattern check first." }),
    });
    renderAt(ADDRESS, qc());
    await screen.findByRole("heading", { level: 1, name: "Oversized hoodie · Black" });
    fireEvent.click(screen.getAllByRole("button", { name: "Record cut quantities" })[0]);
    fireEvent.click(screen.getByRole("button", { name: "Save cut quantities" }));
    expect((await screen.findByRole("alert")).textContent).toBe("Finish Pattern check first.");
  });
});

describe("Final inspection", () => {
  const sizes = [{ cut: 10 }, { cut: 20 }];

  it("refuses to complete until every size adds up, and the reasons too", async () => {
    const calls = serve(makeOrder("final_inspection", { sizes }), {
      "PUT /api/prod/orders/3/inspection": () => ({ order: makeOrder("warehouse", { sizes: [{ cut: 10, passed: 8, to_fix: 1, rejected: 1 }, { cut: 20, passed: 20, to_fix: 0, rejected: 0 }] }) }),
    });
    renderAt(ADDRESS, qc());
    await screen.findByRole("heading", { level: 1, name: "Oversized hoodie · Black" });
    fireEvent.click(screen.getByRole("button", { name: "Record the inspection" }));

    type("S passed", "8");
    type("S to fix", "1");
    type("M passed", "20");
    expect(screen.getByText("1 left")).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "Complete the inspection" }));
    expect((await screen.findByRole("alert")).textContent).toBe(
      "Size S: 9 inspected of 10 cut. Passed, to fix and rejected must add up to the cut for every size.",
    );
    expect(writes(calls)).toHaveLength(0);

    type("S rejected", "1");
    expect(screen.getAllByText("All counted")).toHaveLength(2);
    fireEvent.click(screen.getByRole("button", { name: "Complete the inspection" }));
    expect((await screen.findByRole("alert")).textContent).toBe("1 rejected, and the reasons account for 0. Make them add up.");

    type("Rejected reason 1", "Stain");
    type("Pieces for rejected reason 1", "1");
    fireEvent.click(screen.getByRole("button", { name: "Complete the inspection" }));
    expect((await screen.findByRole("alert")).textContent).toBe("1 to fix, and the reasons account for 0. Make them add up.");
    expect(writes(calls)).toHaveLength(0);

    type("Fix reason 1", "Loose stitching");
    type("Pieces for fix reason 1", "1");
    fireEvent.click(screen.getByRole("button", { name: "Complete the inspection" }));
    await waitFor(() => expect(writes(calls)).toHaveLength(1));
    expect(writes(calls)[0].body).toMatchObject({
      complete: true,
      sizes: { S: { passed: 8, to_fix: 1, rejected: 1 }, M: { passed: 20, to_fix: 0, rejected: 0 } },
      reasons: [
        { kind: "rejected", reason: "Stain", quantity: 1 },
        { kind: "to_fix", reason: "Loose stitching", quantity: 1 },
      ],
    });
    expect(await screen.findByText("Final inspection completed.")).toBeTruthy();
  });

  it("saves counts in batches without completing, but never above the cut", async () => {
    const calls = serve(makeOrder("final_inspection", { sizes }), {
      "PUT /api/prod/orders/3/inspection": () => ({ order: makeOrder("final_inspection", { sizes }) }),
    });
    renderAt(ADDRESS, qc());
    await screen.findByRole("heading", { level: 1, name: "Oversized hoodie · Black" });
    fireEvent.click(screen.getByRole("button", { name: "Record the inspection" }));

    type("S passed", "11");
    fireEvent.click(screen.getByRole("button", { name: "Save counts for now" }));
    expect((await screen.findByRole("alert")).textContent).toBe("Size S: 11 inspected, more than the 10 cut.");
    expect(writes(calls)).toHaveLength(0);

    type("S passed", "6");
    fireEvent.click(screen.getByRole("button", { name: "Save counts for now" }));
    await waitFor(() => expect(writes(calls)).toHaveLength(1));
    expect(writes(calls)[0].body).toMatchObject({ complete: false });
    expect(await screen.findByText("Inspection counts saved.")).toBeTruthy();
  });
});

describe("Deliveries", () => {
  const passed = [{ cut: 10, passed: 10 }, { cut: 20, passed: 20 }];

  async function openDelivery(calls = serve(makeOrder("warehouse", { sizes: passed }))) {
    renderAt(ADDRESS, qc());
    await screen.findByRole("heading", { level: 1, name: "Oversized hoodie · Black" });
    fireEvent.click(screen.getAllByRole("button", { name: "Record a delivery" })[0]);
    return calls;
  }

  it("never ships more than has passed", async () => {
    const calls = await openDelivery();
    const shipped = within(screen.getByRole("group", { name: "Shipped from the factory, counted by the QC manager" }));
    fireEvent.change(shipped.getByLabelText("S"), { target: { value: "11" } });
    fireEvent.change(shipped.getByLabelText("M"), { target: { value: "20" } });
    fireEvent.click(screen.getByRole("button", { name: "Save delivery" }));
    expect((await screen.findByRole("alert")).textContent).toMatch(/31 finished pieces shipped, more than the 30/);
    expect(writes(calls)).toHaveLength(0);
  });

  it("flags a count that does not match, asks why, and sends the reason with the counts", async () => {
    const shippedDelivery: Delivery = {
      id: 11, number: 1, kind: "finished", shipped_on: "2030-10-01", counted_on: "2030-10-01", mismatch_reason: "One piece lost in transit",
      sizes: [{ size: "S", shipped: 10, counted: 10 }, { size: "M", shipped: 20, counted: 19 }],
      shipped_total: 30, counted_total: 29, waiting_for_count: false, mismatch: true, needs_reason: false,
    };
    const calls = serve(makeOrder("warehouse", { sizes: passed }), {
      "POST /api/prod/orders/3/deliveries": () => ({ order: makeOrder("warehouse", { sizes: passed, deliveries: [shippedDelivery] }), delivery_id: 11 }),
    });
    await openDelivery(calls);

    const shipped = within(screen.getByRole("group", { name: "Shipped from the factory, counted by the QC manager" }));
    const counted = within(screen.getByRole("group", { name: "Counted by Khazenly, copied from their dashboard" }));
    fireEvent.change(shipped.getByLabelText("S"), { target: { value: "10" } });
    fireEvent.change(shipped.getByLabelText("M"), { target: { value: "20" } });
    const day = (screen.getByLabelText("Date it left the factory") as HTMLInputElement).value;
    fireEvent.change(screen.getByLabelText(/Date Khazenly counted it/), { target: { value: day } });
    fireEvent.change(counted.getByLabelText("S"), { target: { value: "10" } });
    expect(screen.queryByLabelText("Why the counts differ")).toBeNull();
    fireEvent.change(counted.getByLabelText("M"), { target: { value: "19" } });

    const flag = screen.getByText(/Size M: shipped 20, Khazenly counted 19\./).closest("[role=status]")!;
    expect(flag.textContent).toContain("1 piece missing.");
    expect(flag.textContent).toContain("the order cannot close until it has one");
    type("Why the counts differ", "One piece lost in transit");

    fireEvent.click(screen.getByRole("button", { name: "Save delivery" }));
    await waitFor(() => expect(writes(calls)).toHaveLength(1));
    expect(writes(calls)[0].body).toMatchObject({
      kind: "finished",
      shipped: { S: 10, M: 20 },
      counted_on: day,
      counted: { S: 10, M: 19 },
      mismatch_reason: "One piece lost in transit",
    });
    expect(await screen.findByText("Delivery saved.")).toBeTruthy();
    expect(screen.getByText("Counts differ, explained")).toBeTruthy();
  });

  it("can be saved without the reason, and then says the order cannot close without it", async () => {
    const calls = await openDelivery(
      serve(makeOrder("warehouse", { sizes: passed }), {
        "POST /api/prod/orders/3/deliveries": () => ({ order: makeOrder("warehouse", { sizes: passed }) }),
      }),
    );
    const shipped = within(screen.getByRole("group", { name: "Shipped from the factory, counted by the QC manager" }));
    const counted = within(screen.getByRole("group", { name: "Counted by Khazenly, copied from their dashboard" }));
    fireEvent.change(shipped.getByLabelText("S"), { target: { value: "10" } });
    fireEvent.change(shipped.getByLabelText("M"), { target: { value: "20" } });
    const day = (screen.getByLabelText("Date it left the factory") as HTMLInputElement).value;
    fireEvent.change(screen.getByLabelText(/Date Khazenly counted it/), { target: { value: day } });
    fireEvent.change(counted.getByLabelText("S"), { target: { value: "9" } });
    fireEvent.change(counted.getByLabelText("M"), { target: { value: "20" } });
    fireEvent.click(screen.getByRole("button", { name: "Save delivery" }));
    await waitFor(() => expect(writes(calls)).toHaveLength(1));
    expect(writes(calls)[0].body).toMatchObject({ mismatch_reason: null });
    expect((await screen.findByText(/still needs a reason before the order can close/)).textContent).toContain("Delivery saved.");
  });

  it("asks for Khazenly's count on a delivery that was only shipped", async () => {
    const waiting: Delivery = {
      id: 12, number: 1, kind: "finished", shipped_on: "2030-10-01", counted_on: null, mismatch_reason: null,
      sizes: [{ size: "S", shipped: 10, counted: null }, { size: "M", shipped: 20, counted: null }],
      shipped_total: 30, counted_total: null, waiting_for_count: true, mismatch: false, needs_reason: false,
    };
    const order = makeOrder("warehouse", { sizes: passed, deliveries: [waiting] });
    order.next_action = { stage: "warehouse", what: "Enter Khazenly's count", who: "qc", by: null, since: null };
    serve(order);
    renderAt(ADDRESS, qc());
    await screen.findByRole("heading", { level: 1, name: "Oversized hoodie · Black" });
    expect(screen.getByText("Waiting for count")).toBeTruthy();
    fireEvent.click(screen.getAllByRole("button", { name: "Enter Khazenly's count" })[0]);
    const counted = within(screen.getByRole("group", { name: "Counted by Khazenly, copied from their dashboard" }));
    expect((counted.getByLabelText("S") as HTMLInputElement).value).toBe("");
    expect((within(screen.getByRole("group", { name: "Shipped from the factory, counted by the QC manager" })).getByLabelText("M") as HTMLInputElement).value).toBe("20");
  });
});

describe("The owner's decisions", () => {
  it("asks the owner for a reason before cancelling, and sends it", async () => {
    const calls = serve(makeOrder("final_inspection", { money: true }), {
      "POST /api/prod/orders/3/cancel": () => ({ order: makeOrder("final_inspection", { money: true, extra: { status: "cancelled", next_action: null } }) }),
    });
    renderAt(ADDRESS, owner());
    await screen.findByRole("heading", { level: 1, name: "Oversized hoodie · Black" });
    fireEvent.click(screen.getByRole("button", { name: "Cancel this order" }));
    fireEvent.click(screen.getByRole("button", { name: "Cancel the order" }));
    expect((await screen.findByRole("alert")).textContent).toBe("Say why it is being cancelled.");
    type("Why", "Fabric never came");
    fireEvent.click(screen.getByRole("button", { name: "Cancel the order" }));
    await waitFor(() => expect(writes(calls)).toHaveLength(1));
    expect(writes(calls)[0].body).toEqual({ reason: "Fabric never came" });
    expect(await screen.findByText("This order was cancelled.")).toBeTruthy();
  });

  it("types the actual cost in pounds and sends piastres, empty parts as null", async () => {
    const calls = serve(makeOrder("final_inspection", { money: true }), {
      "PATCH /api/prod/orders/3": () => ({ order: makeOrder("final_inspection", { money: true }) }),
    });
    renderAt(ADDRESS, owner());
    await screen.findByRole("heading", { level: 1, name: "Oversized hoodie · Black" });
    fireEvent.click(screen.getByRole("button", { name: "Edit actual cost" }));
    expect((screen.getByLabelText("Fabric") as HTMLInputElement).value).toBe("172");
    type("Accessories", "14.50");
    fireEvent.click(screen.getByRole("button", { name: "Save the actual cost" }));
    await waitFor(() => expect(writes(calls)).toHaveLength(1));
    expect(writes(calls)[0].body).toEqual({
      actual_fabric_piastres: 17200,
      actual_manufacturing_piastres: null,
      actual_printing_piastres: null,
      actual_accessories_piastres: 1450,
      actual_packaging_piastres: null,
    });
  });
});

const PHOTO = { id: 5, name: "front.png", stage: null, mime_type: "image/png", size_bytes: 10, created_at: null, uploaded_by: "Nour", url: "/api/prod/files/5" };

describe("Files follow the order's status", () => {
  it("offers adding and removing a photo while the order is open", async () => {
    serve(makeOrder("cutting"), { "GET /api/prod/orders/3/files": { files: [PHOTO] } });
    renderAt(ADDRESS, qc());
    await screen.findByRole("heading", { level: 1, name: "Oversized hoodie · Black" });
    expect(screen.getByRole("button", { name: "Add a photo" })).toBeTruthy();
    expect(await screen.findByRole("button", { name: /^Remove\s*front\.png$/ })).toBeTruthy();
  });

  it.each(["cancelled", "closed"] as const)("offers neither on a %s order, which keeps its files as they are", async (status) => {
    serve(makeOrder("settle", { extra: { status, stage: null, next_action: null } }), { "GET /api/prod/orders/3/files": { files: [PHOTO] } });
    renderAt(ADDRESS, owner());
    await screen.findByRole("heading", { level: 1, name: "Oversized hoodie · Black" });
    expect(await screen.findByAltText("front.png")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Add a photo" })).toBeNull();
    expect(screen.queryByRole("button", { name: /^Remove/ })).toBeNull();
  });
});

describe("Where focus goes after a panel saves", () => {
  const cutOrder = () => serve(makeOrder("cutting"), { "PUT /api/prod/orders/3/cut": () => ({ order: makeOrder("final_inspection") }) });

  it("returns to the control that opened it, when that is still there", async () => {
    cutOrder();
    renderAt(ADDRESS, qc());
    await screen.findByRole("heading", { level: 1, name: "Oversized hoodie · Black" });
    const opener = screen.getAllByRole("button", { name: "Record cut quantities" })[0];
    opener.focus();
    fireEvent.click(opener);
    fireEvent.click(screen.getByRole("button", { name: "Save cut quantities" }));
    expect(await screen.findByText("Cut quantities recorded.")).toBeTruthy();
    await waitFor(() => expect(document.activeElement).toBe(opener));
    expect(opener.isConnected).toBe(true);
  });

  it("goes to the next-action button when the control that opened it has gone", async () => {
    cutOrder();
    renderAt(ADDRESS, qc());
    await screen.findByRole("heading", { level: 1, name: "Oversized hoodie · Black" });
    const sizesButton = screen.getAllByRole("button", { name: "Record cut quantities" })[1];
    sizesButton.focus();
    fireEvent.click(sizesButton);
    fireEvent.click(screen.getByRole("button", { name: "Save cut quantities" }));
    expect(await screen.findByText("Cut quantities recorded.")).toBeTruthy();
    // Cutting is done, so the pieces card no longer offers that button; the bar offers the next step.
    await waitFor(() => expect(document.activeElement).toBe(screen.getByRole("button", { name: "Record the inspection" })));
    expect(sizesButton.isConnected).toBe(false);
  });

  it("goes to the page heading when there is no button left, such as after cancelling", async () => {
    serve(makeOrder("final_inspection", { money: true }), {
      "POST /api/prod/orders/3/cancel": () => ({ order: makeOrder("final_inspection", { money: true, extra: { status: "cancelled", next_action: null, stage: null } }) }),
    });
    renderAt(ADDRESS, owner());
    await screen.findByRole("heading", { level: 1, name: "Oversized hoodie · Black" });
    const opener = screen.getByRole("button", { name: "Cancel this order" });
    opener.focus();
    fireEvent.click(opener);
    type("Why", "Fabric never came");
    fireEvent.click(screen.getByRole("button", { name: "Cancel the order" }));
    expect(await screen.findByText("This order was cancelled.")).toBeTruthy();
    await waitFor(() => expect(document.activeElement).toBe(screen.getByRole("heading", { level: 1, name: "Oversized hoodie · Black" })));
  });
});

describe("The inspection form", () => {
  const sizes = [{ cut: 10 }, { cut: 20 }];

  it("only saves when Enter is pressed in a count box, even when the numbers add up", async () => {
    const calls = serve(makeOrder("final_inspection", { sizes }), {
      "PUT /api/prod/orders/3/inspection": () => ({ order: makeOrder("final_inspection", { sizes }) }),
    });
    renderAt(ADDRESS, qc());
    await screen.findByRole("heading", { level: 1, name: "Oversized hoodie · Black" });
    fireEvent.click(screen.getByRole("button", { name: "Record the inspection" }));

    type("S passed", "8");
    type("S to fix", "1");
    type("S rejected", "1");
    type("M passed", "20");
    type("Rejected reason 1", "Stain");
    type("Pieces for rejected reason 1", "1");
    type("Fix reason 1", "Loose stitching");
    type("Pieces for fix reason 1", "1");

    // Enter in a box submits the form. Everything adds up, and still it must not complete.
    fireEvent.submit(screen.getByLabelText("S passed").closest("form")!);
    await waitFor(() => expect(writes(calls)).toHaveLength(1));
    expect(writes(calls)[0].body).toMatchObject({ complete: false });
    expect(writes(calls)[0].body).not.toHaveProperty("done_on");
    expect(await screen.findByText("Inspection counts saved.")).toBeTruthy();
  });

  it("makes the form's own submit the save, and completing a separate button", async () => {
    serve(makeOrder("final_inspection", { sizes }));
    renderAt(ADDRESS, qc());
    await screen.findByRole("heading", { level: 1, name: "Oversized hoodie · Black" });
    fireEvent.click(screen.getByRole("button", { name: "Record the inspection" }));
    expect((screen.getByRole("button", { name: "Save counts for now" }) as HTMLButtonElement).type).toBe("submit");
    expect((screen.getByRole("button", { name: "Complete the inspection" }) as HTMLButtonElement).type).toBe("button");
  });
});

describe("Editing the order", () => {
  const choices = {
    suppliers: [{ id: "SUP-2", name: "Print house A", category: "Printing houses" }],
    products: [{ id: "P1", title: "Oversized hoodie" }],
    sizes: ["XS", "S", "M", "L", "XL", "XXL"],
    stage_days: {},
  };

  it("keeps a factory that is no longer active in the list, and says so", async () => {
    serve(makeOrder("cutting", { money: true }), { "GET /api/prod/choices": choices });
    renderAt(ADDRESS, owner());
    await screen.findByRole("heading", { level: 1, name: "Oversized hoodie · Black" });
    fireEvent.click(screen.getByRole("button", { name: "Edit the order" }));
    const factory = (await screen.findByRole("combobox", { name: "Factory" })) as HTMLSelectElement;
    expect(factory.value).toBe("SUP-1");
    expect(within(factory).getByRole("option", { name: "Main factory (no longer active)" })).toBeTruthy();
    expect(within(factory).getByRole("option", { name: /Print house A/ })).toBeTruthy();
  });

  it("keeps an inactive print house in its list too, and sends it back unchanged", async () => {
    const calls = serve(
      makeOrder("cutting", { money: true, extra: { printing: "outside", print_supplier: { id: "SUP-9", name: "Old print house" } } }),
      { "GET /api/prod/choices": choices, "PATCH /api/prod/orders/3": () => ({ order: makeOrder("cutting", { money: true }) }) },
    );
    renderAt(ADDRESS, owner());
    await screen.findByRole("heading", { level: 1, name: "Oversized hoodie · Black" });
    fireEvent.click(screen.getByRole("button", { name: "Edit the order" }));
    const printer = (await screen.findByRole("combobox", { name: "Print house" })) as HTMLSelectElement;
    expect(printer.value).toBe("SUP-9");
    expect(within(printer).getByRole("option", { name: "Old print house (no longer active)" })).toBeTruthy();
    type("Colour", "Red");
    fireEvent.click(screen.getByRole("button", { name: "Save changes" }));
    await waitFor(() => expect(writes(calls)).toHaveLength(1));
    expect(writes(calls)[0].body).toMatchObject({ factory_id: "SUP-1", printing: "outside", print_supplier_id: "SUP-9", colour: "Red" });
  });

  it("lets who buys the fabric and printing change before cutting", async () => {
    serve(makeOrder("cutting", { money: true }), { "GET /api/prod/choices": choices });
    renderAt(ADDRESS, owner());
    await screen.findByRole("heading", { level: 1, name: "Oversized hoodie · Black" });
    fireEvent.click(screen.getByRole("button", { name: "Edit the order" }));
    expect(((await screen.findByRole("combobox", { name: "Who buys the fabric" })) as HTMLSelectElement).disabled).toBe(false);
    expect((screen.getByRole("combobox", { name: "Printing" }) as HTMLSelectElement).disabled).toBe(false);
    expect(screen.queryByText(/cannot change after cutting/)).toBeNull();
  });

  it("shows who buys the fabric and printing read-only, with the reason, once cutting is done", async () => {
    const calls = serve(makeOrder("final_inspection", { money: true }), {
      "GET /api/prod/choices": choices,
      "PATCH /api/prod/orders/3": () => ({ order: makeOrder("final_inspection", { money: true }) }),
    });
    renderAt(ADDRESS, owner());
    await screen.findByRole("heading", { level: 1, name: "Oversized hoodie · Black" });
    fireEvent.click(screen.getByRole("button", { name: "Edit the order" }));
    const buyer = (await screen.findByRole("combobox", { name: "Who buys the fabric" })) as HTMLSelectElement;
    const printing = screen.getByRole("combobox", { name: "Printing" }) as HTMLSelectElement;
    expect(buyer.disabled).toBe(true);
    expect(printing.disabled).toBe(true);
    expect(buyer.value).toBe("hba");
    expect(printing.value).toBe("factory");
    expect(screen.getByText("Who buys the fabric cannot change after cutting. Reopen cutting first.")).toBeTruthy();
    expect(screen.getByText("Printing cannot change after cutting. Reopen cutting first.")).toBeTruthy();
    expect(buyer.getAttribute("aria-describedby")).toBeTruthy();

    // Saving still sends the unchanged values, which the server accepts.
    type("Colour", "Red");
    fireEvent.click(screen.getByRole("button", { name: "Save changes" }));
    await waitFor(() => expect(writes(calls)).toHaveLength(1));
    expect(writes(calls)[0].body).toMatchObject({ fabric_bought_by: "hba", printing: "factory", print_supplier_id: null });
  });
});

describe("Slow and out-of-order answers", () => {
  const event = (id: number, summary: string) => ({ id, at: "2030-09-28T08:00:00Z", who: "Nour", action: "production.order_x", summary });

  it("keeps the newer history when an earlier read answers late", async () => {
    let release: (answer: unknown) => void = () => undefined;
    let reads = 0;
    serve(makeOrder("cutting"), {
      "GET /api/prod/orders/3/history": () => {
        reads += 1;
        if (reads === 1) return new Promise((resolve) => (release = resolve));
        return { events: [event(2, "Newer entry")] };
      },
      "PUT /api/prod/orders/3/cut": () => ({ order: makeOrder("final_inspection") }),
    });
    renderAt(ADDRESS, qc());
    await screen.findByRole("heading", { level: 1, name: "Oversized hoodie · Black" });
    fireEvent.click(screen.getAllByRole("button", { name: "Record cut quantities" })[0]);
    fireEvent.click(screen.getByRole("button", { name: "Save cut quantities" }));
    expect(await screen.findByText("Newer entry")).toBeTruthy();

    await act(async () => {
      release({ events: [event(1, "Older entry")] });
      await new Promise((resolve) => setTimeout(resolve, 20));
    });
    expect(screen.queryByText("Older entry")).toBeNull();
    expect(screen.getByText("Newer entry")).toBeTruthy();
  });

  it("clears the history's error once a later read works", async () => {
    let reads = 0;
    serve(makeOrder("cutting"), {
      "GET /api/prod/orders/3/history": () => (++reads === 1 ? reply(500, { detail: "The history is not available just now." }) : { events: [event(3, "Back again")] }),
      "PUT /api/prod/orders/3/cut": () => ({ order: makeOrder("final_inspection") }),
    });
    renderAt(ADDRESS, qc());
    expect(await screen.findByText("The history is not available just now.")).toBeTruthy();
    fireEvent.click(screen.getAllByRole("button", { name: "Record cut quantities" })[0]);
    fireEvent.click(screen.getByRole("button", { name: "Save cut quantities" }));
    expect(await screen.findByText("Back again")).toBeTruthy();
    expect(screen.queryByText("The history is not available just now.")).toBeNull();
  });

  it("does not let a slow answer for the order left behind replace the one on the page", async () => {
    let release: (answer: unknown) => void = () => undefined;
    mockApi({
      "GET /api/prod/orders/3": () => new Promise((resolve) => (release = resolve)),
      "GET /api/prod/orders/4": { order: makeOrder("cutting", { extra: { id: 4, style_name: "Boxy tee" } }) },
      "GET /api/prod/orders/4/history": { events: [] },
      "GET /api/prod/orders/4/files": { files: [] },
    });
    function Jump() {
      const navigate = useNavigate();
      return <button type="button" onClick={() => navigate("/production/orders/4")}>Go to the other order</button>;
    }
    render(
      <MemoryRouter initialEntries={[ADDRESS]}>
        <Jump />
        <Routes>
          <Route path="/production">{productionRoutes(qc())}</Route>
        </Routes>
      </MemoryRouter>,
    );
    fireEvent.click(screen.getByRole("button", { name: "Go to the other order" }));
    expect(await screen.findByRole("heading", { level: 1, name: "Boxy tee · Black" })).toBeTruthy();

    await act(async () => {
      release({ order: makeOrder("cutting", { extra: { id: 3, style_name: "Late hoodie" } }) });
      await new Promise((resolve) => setTimeout(resolve, 20));
    });
    expect(screen.queryByRole("heading", { level: 1, name: "Late hoodie · Black" })).toBeNull();
    expect(screen.getByRole("heading", { level: 1, name: "Boxy tee · Black" })).toBeTruthy();
  });
});

describe("A form opened from a task (`?open=`)", () => {
  /** The order page at an address, with the address on show so a test can see it cleared. */
  function renderWith(address: string, session = qc()) {
    function Where() {
      const location = useLocation();
      return <output data-testid="where">{location.pathname + location.search}</output>;
    }
    render(
      <MemoryRouter initialEntries={[address]}>
        <Routes>
          <Route path="/production">{productionRoutes(session)}</Route>
        </Routes>
        <Where />
      </MemoryRouter>,
    );
  }
  const where = () => screen.getByTestId("where").textContent;
  const panel = () => document.querySelector(".prod-panel");

  it("opens that form once the order has loaded, and clears the address", async () => {
    serve(makeOrder("cutting"));
    renderWith(`${ADDRESS}?open=cut`);
    expect(await screen.findByRole("heading", { level: 2, name: "Record cut quantities" })).toBeTruthy();
    expect(where()).toBe(ADDRESS);
    // The panel has focus, as when a button opened it.
    await waitFor(() => expect(document.activeElement?.textContent).toBe("Record cut quantities"));
  });

  it("opens a stage's own form, the fabric check's and a delivery's", async () => {
    serve(makeOrder("making"));
    renderWith(`${ADDRESS}?open=stage:making`);
    expect(await screen.findByRole("heading", { level: 2, name: /Mark making finished|Making/ })).toBeTruthy();
    expect(where()).toBe(ADDRESS);
    cleanup();

    serve(makeOrder("fabric_check"));
    renderWith(`${ADDRESS}?open=stage:fabric_check`);
    expect(await screen.findByRole("group", { name: "Result" })).toBeTruthy();
    cleanup();

    const delivery: Delivery = {
      id: 11, number: 2, kind: "finished", shipped_on: "2030-10-01", counted_on: "2030-10-01", mismatch_reason: null,
      sizes: [{ size: "S", shipped: 10, counted: 10 }, { size: "M", shipped: 20, counted: 19 }],
      shipped_total: 30, counted_total: 29, waiting_for_count: false, mismatch: true, needs_reason: true,
    };
    serve(makeOrder("warehouse", { sizes: [{ cut: 10, passed: 10 }, { cut: 20, passed: 20 }], deliveries: [delivery] }));
    renderWith(`${ADDRESS}?open=delivery-reason:11`);
    expect(await screen.findByRole("heading", { level: 2, name: "Delivery 2" })).toBeTruthy();
    expect(screen.getByLabelText("Why the counts differ")).toBeTruthy();
    expect(where()).toBe(ADDRESS);
  });

  it("opens the owner's forms for the owner", async () => {
    serve(makeOrder("settle", { money: true }));
    renderWith(`${ADDRESS}?open=settle`, owner());
    expect(await screen.findByRole("heading", { level: 2, name: /Settle/ })).toBeTruthy();
  });

  it("opens nothing for a form this person may not use, but still clears the address", async () => {
    serve(makeOrder("settle"));
    renderWith(`${ADDRESS}?open=settle`);
    await screen.findByRole("heading", { level: 1, name: "Oversized hoodie · Black" });
    expect(panel()).toBeNull();
    expect(where()).toBe(ADDRESS);
    cleanup();

    serve(makeOrder("cutting"));
    const reader = qc();
    reader.permissions = ["production.view"];
    renderWith(`${ADDRESS}?open=cut`, reader);
    await screen.findByRole("heading", { level: 1, name: "Oversized hoodie · Black" });
    expect(panel()).toBeNull();
    expect(where()).toBe(ADDRESS);
  });

  it("opens nothing for work the order has moved past, or a value it does not know", async () => {
    serve(makeOrder("final_inspection"));
    renderWith(`${ADDRESS}?open=cut`);
    await screen.findByRole("heading", { level: 1, name: "Oversized hoodie · Black" });
    expect(panel()).toBeNull();
    cleanup();

    serve(makeOrder("cutting"));
    renderWith(`${ADDRESS}?open=nonsense`);
    await screen.findByRole("heading", { level: 1, name: "Oversized hoodie · Black" });
    expect(panel()).toBeNull();
    expect(where()).toBe(ADDRESS);
  });

  it("opens it once: closing it does not bring it back, and an ordinary visit opens nothing", async () => {
    serve(makeOrder("cutting"));
    renderWith(`${ADDRESS}?open=cut`);
    await screen.findByRole("heading", { level: 2, name: "Record cut quantities" });
    fireEvent.click(screen.getByRole("button", { name: "Close" }));
    expect(panel()).toBeNull();
    await new Promise((resolve) => setTimeout(resolve, 20));
    expect(panel()).toBeNull();
    cleanup();

    serve(makeOrder("cutting"));
    renderWith(ADDRESS);
    await screen.findByRole("heading", { level: 1, name: "Oversized hoodie · Black" });
    expect(panel()).toBeNull();
  });
});

describe("Cancelling after cutting says what goes on the factory's account", () => {
  // Built as recommended on 15 November 2026, awaiting the owner's confirmation.
  it("tells the owner the factory keeps what it earned, once cutting is done", async () => {
    serve(makeOrder("final_inspection", { money: true }));
    renderAt(ADDRESS, owner());
    await screen.findByRole("heading", { level: 1, name: "Oversized hoodie · Black" });
    fireEvent.click(screen.getByRole("button", { name: "Cancel this order" }));
    expect(screen.getByText("The factory keeps EGP 3,450.00 for the work already done; it goes on their account.")).toBeTruthy();
  });

  it("says the other two cases in words too", async () => {
    const owed = makeOrder("final_inspection", { money: true });
    expect(cancelSentence(owed, formatEgp)).toBe("The factory keeps EGP 3,450.00 for the work already done; it goes on their account.");
    expect(cancelSentence({ ...owed, settlement: { ...owed.settlement!, payable_piastres: 0 } }, formatEgp)).toBe(
      "Nothing is owed to the factory for the work already done, so nothing goes on their account.",
    );
    expect(cancelSentence({ ...owed, settlement: { ...owed.settlement!, payable_piastres: -17140000 } }, formatEgp)).toBe(
      "The rejected pieces came to more than the work done, so the factory owes HBA EGP 171,400.00; it goes on their account.",
    );
  });

  it("says nothing before cutting is done", async () => {
    serve(makeOrder("cutting", { money: true }));
    renderAt(ADDRESS, owner());
    await screen.findByRole("heading", { level: 1, name: "Oversized hoodie · Black" });
    fireEvent.click(screen.getByRole("button", { name: "Cancel this order" }));
    expect(screen.getByRole("heading", { name: "Cancel this order", level: 2 })).toBeTruthy();
    expect(document.body.textContent).not.toMatch(/goes on their account|nothing goes on their account/);
  });

  it("never says it to somebody who has no settlement to read", () => {
    const seen = makeOrder("final_inspection");
    expect(seen.settlement).toBeUndefined();
    expect(cancelSentence(seen, formatEgp)).toBeNull();
  });

  it("calls the frozen figure of a cancelled order what it is, not a settlement", async () => {
    const frozen = makeOrder("final_inspection", { money: true, extra: { status: "cancelled", next_action: null, stage: null } });
    frozen.settlement = { ...frozen.settlement!, settled: true, settled_at: "2030-11-13T10:00:00Z" };
    serve(frozen);
    renderAt(ADDRESS, owner());
    await screen.findByRole("heading", { level: 1, name: "Oversized hoodie · Black" });
    expect(screen.getByText("Owed to the factory when the order was cancelled, on their account")).toBeTruthy();
    expect(screen.queryByText("Settled with the factory")).toBeNull();
  });
});

describe("The factory is read-only once cutting is done", () => {
  const choices = {
    suppliers: [{ id: "SUP-2", name: "Print house A", category: "Printing houses" }],
    products: [{ id: "P1", title: "Oversized hoodie" }],
    sizes: ["XS", "S", "M", "L", "XL", "XXL"],
    stage_days: {},
  };

  it("lets the factory change before cutting", async () => {
    serve(makeOrder("cutting", { money: true }), { "GET /api/prod/choices": choices });
    renderAt(ADDRESS, owner());
    await screen.findByRole("heading", { level: 1, name: "Oversized hoodie · Black" });
    fireEvent.click(screen.getByRole("button", { name: "Edit the order" }));
    expect(((await screen.findByRole("combobox", { name: "Factory" })) as HTMLSelectElement).disabled).toBe(false);
    expect(screen.queryByText("The factory cannot change after cutting. Reopen cutting first.")).toBeNull();
  });

  it("shows it with the reason once cutting is done, and still sends it back unchanged", async () => {
    const calls = serve(makeOrder("final_inspection", { money: true }), {
      "GET /api/prod/choices": choices,
      "PATCH /api/prod/orders/3": () => ({ order: makeOrder("final_inspection", { money: true }) }),
    });
    renderAt(ADDRESS, owner());
    await screen.findByRole("heading", { level: 1, name: "Oversized hoodie · Black" });
    fireEvent.click(screen.getByRole("button", { name: "Edit the order" }));
    const factory = (await screen.findByRole("combobox", { name: "Factory" })) as HTMLSelectElement;
    expect(factory.disabled).toBe(true);
    expect(factory.value).toBe("SUP-1");
    expect(factory.getAttribute("aria-describedby")).toBeTruthy();
    expect(screen.getByText("The factory cannot change after cutting. Reopen cutting first.")).toBeTruthy();
    type("Colour", "Red");
    fireEvent.click(screen.getByRole("button", { name: "Save changes" }));
    await waitFor(() => expect(writes(calls)).toHaveLength(1));
    expect(writes(calls)[0].body).toMatchObject({ factory_id: "SUP-1", colour: "Red" });
  });
});
