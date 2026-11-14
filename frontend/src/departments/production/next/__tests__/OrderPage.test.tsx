// @vitest-environment jsdom
import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { Delivery, OrderView } from "../types";
import { makeOrder, mockApi, narrowScreen, owner, qc, renderAt, reply } from "./fixtures";
import type { Call } from "./fixtures";

const ADDRESS = "/production/next/orders/3";

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
