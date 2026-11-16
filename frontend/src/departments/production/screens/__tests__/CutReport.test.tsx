// @vitest-environment jsdom
/**
 * The QC manager's side of the factory's cut report (batch 6b): the report waits
 * on the order's Cutting stage, and the cut form opens already filled with it
 * and says who reported it and when. Without a report nothing changes.
 */
import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { OrderView } from "../types";
import { makeOrder, mockApi, narrowScreen, qc, renderAt } from "./fixtures";
import type { Call } from "./fixtures";

const ADDRESS = "/production/orders/3";
const REPORT = { sizes: { S: 8, M: 19 }, note: "Short on fabric for S", reported_on: "2030-11-16" } as const;

function serve(order: OrderView) {
  return mockApi({
    "GET /api/prod/orders/3": { order },
    "GET /api/prod/orders/3/history": { events: [] },
    "GET /api/prod/orders/3/files": { files: [] },
    "PUT /api/prod/orders/3/cut": () => ({ order: makeOrder("final_inspection") }),
  });
}

const writes = (calls: Call[]) => calls.filter((call) => call.method !== "GET");

beforeEach(() => narrowScreen(false));
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("a cut the factory reported", () => {
  it("waits on the Cutting stage, and the button says it is the factory's cut to confirm", async () => {
    serve(makeOrder("cutting", { extra: { cut_report: REPORT } }));
    renderAt(ADDRESS, qc());
    await screen.findByRole("heading", { level: 1, name: "Oversized hoodie · Black" });

    const stages = screen.getByRole("region", { name: "Next action" }).ownerDocument.getElementById("prod-stages")!.closest("section")!;
    expect(within(stages).getByText(/Factory reported 27 cut on 16 Nov, waiting to be confirmed/)).toBeTruthy();
    expect(screen.getAllByRole("button", { name: "Confirm the factory's cut" })).toHaveLength(2);
    expect(screen.queryByRole("button", { name: "Record cut quantities" })).toBeNull();
  });

  it("opens the cut form filled with the reported sizes, saying who reported them and when", async () => {
    const calls = serve(makeOrder("cutting", { extra: { cut_report: REPORT } }));
    renderAt(ADDRESS, qc());
    await screen.findByRole("heading", { level: 1, name: "Oversized hoodie · Black" });

    fireEvent.click(screen.getAllByRole("button", { name: "Confirm the factory's cut" })[0]);
    const form = screen.getByRole("heading", { name: "Confirm the factory's cut", level: 2 }).closest("section")!;
    expect(within(form).getByText(/Reported by the factory on 16 Nov/)).toBeTruthy();
    expect(within(form).getByText(/The factory's note: Short on fabric for S/)).toBeTruthy();
    const cut = within(within(form).getByRole("group", { name: "Pieces cut" }));
    expect((cut.getByLabelText("S") as HTMLInputElement).value).toBe("8");
    expect((cut.getByLabelText("M") as HTMLInputElement).value).toBe("19");
    // Planned 30, reported 27: the shortfall is asked about as ever, and what is saved is what is on screen.
    expect(within(form).getByText("Cut 27 of 30 planned: 3 pieces fewer")).toBeTruthy();

    // The QC manager corrects one size and gives the reasons; what is saved is what the form holds.
    fireEvent.change(cut.getByLabelText("M"), { target: { value: "20" } });
    fireEvent.change(within(form).getByLabelText("Reason 1"), { target: { value: "Fabric defects" } });
    fireEvent.change(within(form).getByLabelText("Pieces for reason 1"), { target: { value: "2" } });
    fireEvent.click(within(form).getByRole("button", { name: "Save cut quantities" }));
    await waitFor(() => expect(writes(calls)).toHaveLength(1));
    expect(writes(calls)[0].body).toMatchObject({ sizes: { S: 8, M: 20 }, reasons: [{ reason: "Fabric defects", quantity: 2 }] });
  });

  it("is the plain cut form, from the plan, when no report waits", async () => {
    serve(makeOrder("cutting"));
    renderAt(ADDRESS, qc());
    await screen.findByRole("heading", { level: 1, name: "Oversized hoodie · Black" });

    expect(screen.queryByText(/waiting to be confirmed/)).toBeNull();
    fireEvent.click(screen.getAllByRole("button", { name: "Record cut quantities" })[0]);
    const form = screen.getByRole("heading", { name: "Record cut quantities", level: 2 }).closest("section")!;
    expect(within(form).queryByText(/Reported by the factory/)).toBeNull();
    const cut = within(within(form).getByRole("group", { name: "Pieces cut" }));
    expect((cut.getByLabelText("S") as HTMLInputElement).value).toBe("10");
    expect((cut.getByLabelText("M") as HTMLInputElement).value).toBe("20");
  });

  it("is not drawn once cutting is recorded, when the server sends the report as null", async () => {
    serve(makeOrder("final_inspection", { extra: { cut_report: null } }));
    renderAt(ADDRESS, qc());
    await screen.findByRole("heading", { level: 1, name: "Oversized hoodie · Black" });
    expect(screen.queryByText(/Factory reported/)).toBeNull();
  });
});
