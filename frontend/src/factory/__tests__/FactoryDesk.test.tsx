// @vitest-environment jsdom
import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { mockApi, reply } from "../../departments/production/next/__tests__/fixtures";
import type { Call } from "../../departments/production/next/__tests__/fixtures";
import type { FactoryOrder } from "../types";
import { makeOrder, makeRow, renderDesk, reportedOrder } from "./fixtures";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const writes = (calls: Call[]) => calls.filter((call) => call.method !== "GET");
const type = (label: string, value: string) => fireEvent.change(screen.getByLabelText(label), { target: { value } });
const click = (name: string | RegExp) => fireEvent.click(screen.getByRole("button", { name }));
const cardOf = (name: string): HTMLElement => screen.getByRole("heading", { name, level: 2 }).closest("section")!;

/** `GET /orders/2` answers whatever `state.order` is now, so a write can change what the next read says. */
function serveOrder(order: FactoryOrder, extra: Record<string, unknown> = {}) {
  const state = { order };
  const calls = mockApi({
    "GET /api/factory/orders/2": () => ({ order: state.order }),
    ...extra,
  });
  return { calls, state };
}

describe("Your orders", () => {
  it("lists the factory's own orders as links, with what stands on each and no money", async () => {
    mockApi({
      "GET /api/factory/orders": {
        orders: [
          makeRow({ id: 2, style_name: "Wide-leg sweatpants" }),
          makeRow({
            id: 3,
            style_name: "Oversized hoodie",
            colour: "Off-white",
            planned_total: 1000,
            cut: { reported_total: null, confirmed_total: 985 },
            status_words: "being made",
            delivery_date: "2030-11-26",
            moved: true,
            moved_from: "2026-11-20",
          }),
          makeRow({ id: 4, style_name: "Boxy tee", colour: "Black", planned_total: 600, status_words: "fabric not yet with you", delivery_date: "2030-12-16" }),
        ],
      },
    });
    renderDesk("/factory");

    expect(await screen.findByRole("heading", { level: 1, name: "Your orders" })).toBeTruthy();
    expect(screen.getByText("3 orders with HBA")).toBeTruthy();
    const rows = screen.getAllByRole("link").filter((link) => link.getAttribute("href")?.startsWith("/factory/orders/"));
    expect(rows.map((row) => row.getAttribute("href"))).toEqual(["/factory/orders/2", "/factory/orders/3", "/factory/orders/4"]);
    expect(rows[0].textContent).toContain("Wide-leg sweatpants · Grey");
    expect(rows[0].textContent).toContain("PO-2611-02 · 800 planned · tell us how many you cut");
    expect(rows[0].textContent).toContain("Deliver by 5 Dec");
    expect(rows[1].textContent).toContain("PO-2611-03 · 985 cut · being made");
    expect(rows[1].textContent).toContain("Deliver by 26 Nov · moved from 20 Nov");
    expect(screen.getByText("Only your own orders appear here. No prices, costs or payments are shown.")).toBeTruthy();
    expect(document.body.textContent).not.toMatch(/EGP|piastres/i);
  });

  it("says a reported cut is reported until HBA confirms it", async () => {
    mockApi({
      "GET /api/factory/orders": { orders: [makeRow({ id: 2, style_name: "Wide-leg sweatpants", cut: { reported_total: 792, confirmed_total: null } })] },
    });
    renderDesk("/factory");
    expect(await screen.findByText(/792 reported cut/)).toBeTruthy();
    expect(screen.getByText("1 order with HBA")).toBeTruthy();
  });

  it("says so when there are none", async () => {
    mockApi({ "GET /api/factory/orders": { orders: [] } });
    renderDesk("/factory");
    expect(await screen.findByText("No open orders with HBA")).toBeTruthy();
  });

  it("shows a refusal and offers to try again", async () => {
    let calls = 0;
    mockApi({
      "GET /api/factory/orders": () => (++calls === 1 ? reply(500, { detail: "The orders could not be read." }) : { orders: [] }),
    });
    renderDesk("/factory");
    expect((await screen.findByRole("alert")).textContent).toBe("The orders could not be read.");
    click("Try again");
    expect(await screen.findByText("No open orders with HBA")).toBeTruthy();
  });

  it("names who is signed in and offers a way out", async () => {
    mockApi({ "GET /api/factory/orders": { orders: [] } });
    renderDesk("/factory");
    await screen.findByText("No open orders with HBA");
    expect(screen.getByText("HBA · Production")).toBeTruthy();
    expect(screen.getByText("Main factory")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Sign out" })).toBeTruthy();
  });
});

describe("One order", () => {
  it("shows the sizes, the report form with its total on the button, and the date", async () => {
    serveOrder(makeOrder());
    renderDesk("/factory/orders/2");

    expect(await screen.findByRole("heading", { level: 1, name: "Wide-leg sweatpants · Grey" })).toBeTruthy();
    expect(screen.getByText("PO-2611-02 · printing: none · deliver by 5 Dec")).toBeTruthy();
    expect(screen.getByRole("link", { name: "← Your orders" }).getAttribute("href")).toBe("/factory");

    const sizes = within(cardOf("Sizes"));
    expect(sizes.getAllByRole("columnheader").map((head) => head.textContent)).toEqual(["Size", "Planned", "You reported cut", "Confirmed cut"]);
    const body = sizes.getAllByRole("row").slice(1);
    expect(body.map((row) => row.textContent)).toEqual(["S120——", "M240——", "L240——"]);

    expect(screen.getByText("HBA's QC manager checks and confirms these before they count.")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Send pieces cut" })).toBeTruthy();
    type("S", "118");
    type("M", "240");
    type("L", "236");
    expect(screen.getByRole("button", { name: "Send 594 pieces cut" })).toBeTruthy();
    expect(document.body.textContent).not.toMatch(/EGP|piastres/i);
  });

  it("refuses nothing cut, and what is not a whole number, before it sends anything", async () => {
    const { calls } = serveOrder(makeOrder());
    renderDesk("/factory/orders/2");
    await screen.findByRole("heading", { level: 1, name: "Wide-leg sweatpants · Grey" });

    click("Send pieces cut");
    expect((await screen.findByRole("alert")).textContent).toBe("Give the number cut for at least one size.");

    type("S", "12a");
    click(/^Send/);
    expect((await screen.findByRole("alert")).textContent).toMatch(/whole numbers only/);

    type("S", "100001");
    click(/^Send/);
    expect((await screen.findByRole("alert")).textContent).toMatch(/at most 100,000/);
    expect(writes(calls)).toHaveLength(0);
  });

  it("sends the report, then shows it waiting with the flag and a way to correct it", async () => {
    const { calls, state } = serveOrder(makeOrder(), {
      "PUT /api/factory/orders/2/cut-report": () => {
        state.order = reportedOrder();
        return { ok: true };
      },
    });
    renderDesk("/factory/orders/2");
    await screen.findByRole("heading", { level: 1, name: "Wide-leg sweatpants · Grey" });

    type("S", "118");
    type("M", "240");
    type("L", "236");
    type("Note (optional)", "  Short on fabric for S and L ");
    click("Send 594 pieces cut");

    await waitFor(() => expect(writes(calls)).toHaveLength(1));
    expect(writes(calls)[0]).toMatchObject({
      method: "PUT",
      path: "/api/factory/orders/2/cut-report",
      body: { sizes: { S: 118, M: 240, L: 236 }, note: "Short on fabric for S and L" },
    });

    expect(await screen.findByText(/You reported 594 pieces cut on 16 Nov\. Waiting for HBA's QC manager to confirm\./)).toBeTruthy();
    expect(screen.getByText(/Your note: Short on fabric for S and L/)).toBeTruthy();
    expect(screen.getByText(/Sent\. HBA's QC manager will check and confirm it\./)).toBeTruthy();
    // The form is gone; what was sent is in the table, and the correction is one press away.
    expect(screen.queryByRole("heading", { name: "Report how many you cut" })).toBeNull();
    const body = within(cardOf("Sizes")).getAllByRole("row").slice(1);
    expect(body.map((row) => row.textContent)).toEqual(["S120118—", "M240240—", "L240236—"]);
    expect(screen.getByRole("button", { name: "Correct what I sent" })).toBeTruthy();
  });

  it("corrects what was sent, starting from the numbers sent, and can be cancelled", async () => {
    const { calls, state } = serveOrder(reportedOrder(), {
      "PUT /api/factory/orders/2/cut-report": () => {
        state.order = reportedOrder({ report: { reported_on: "2030-11-16", note: null } });
        return { ok: true };
      },
    });
    renderDesk("/factory/orders/2");
    await screen.findByText(/You reported 594 pieces cut/);

    click("Correct what I sent");
    expect((screen.getByLabelText("S") as HTMLInputElement).value).toBe("118");
    expect((screen.getByLabelText("L") as HTMLInputElement).value).toBe("236");
    expect((screen.getByLabelText("Note (optional)") as HTMLInputElement).value).toBe("Short on fabric for S and L");

    click("Cancel");
    expect(screen.queryByRole("heading", { name: "Report how many you cut" })).toBeNull();

    click("Correct what I sent");
    type("S", "120");
    type("Note (optional)", "");
    click("Send 596 pieces cut");
    await waitFor(() => expect(writes(calls)).toHaveLength(1));
    expect(writes(calls)[0].body).toEqual({ sizes: { S: 120, M: 240, L: 236 }, note: null });
    expect(await screen.findByText("Your correction was sent.")).toBeTruthy();
  });

  it("shows the server's own words when it refuses the report", async () => {
    serveOrder(makeOrder(), {
      "PUT /api/factory/orders/2/cut-report": () => reply(422, { detail: "Cutting is already recorded." }),
    });
    renderDesk("/factory/orders/2");
    await screen.findByRole("heading", { level: 1, name: "Wide-leg sweatpants · Grey" });
    type("S", "5");
    click("Send 5 pieces cut");
    expect((await screen.findByRole("alert")).textContent).toBe("Cutting is already recorded.");
    // What was typed is still there.
    expect((screen.getByLabelText("S") as HTMLInputElement).value).toBe("5");
  });

  it("offers no form once HBA has confirmed the cut, and says what was confirmed", async () => {
    serveOrder(
      reportedOrder({
        cut: { reported_total: 594, confirmed_total: 590 },
        sizes: [
          { size: "S", planned: 120, reported: 118, confirmed: 116 },
          { size: "M", planned: 240, reported: 240, confirmed: 240 },
          { size: "L", planned: 240, reported: 236, confirmed: 234 },
        ],
        report: null,
        can_report_cut: false,
      }),
    );
    renderDesk("/factory/orders/2");
    expect(await screen.findByText("HBA confirmed 590 pieces cut.")).toBeTruthy();
    expect(screen.queryByRole("heading", { name: "Report how many you cut" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Correct what I sent" })).toBeNull();
    expect(within(cardOf("Sizes")).getAllByRole("row")[1].textContent).toBe("S120118116");
  });

  it("moves the delivery date with a reason, and reads the history again", async () => {
    const { calls, state } = serveOrder(makeOrder(), {
      "POST /api/factory/orders/2/delivery-date": () => {
        state.order = makeOrder({
          delivery_date: "2030-12-12",
          moved: true,
          dates: [
            { on: "2030-11-16", date: "2030-12-12", by: "You", reason: "Waiting in the print queue" },
            { on: "2030-11-02", date: "2030-12-05", by: "HBA", reason: "Planned" },
          ],
        });
        return { ok: true };
      },
    });
    renderDesk("/factory/orders/2");
    await screen.findByRole("heading", { level: 1, name: "Wide-leg sweatpants · Grey" });

    const card = within(cardOf("Delivery date"));
    expect(card.getByText("Now 5 Dec. If it will change, tell us the new date and why.")).toBeTruthy();
    expect(card.getAllByRole("columnheader").map((head) => head.textContent)).toEqual(["When", "Date", "Moved by", "Why"]);
    expect(card.getAllByRole("row")[1].textContent).toBe("2 Nov5 DecHBAPlanned");

    // A date, then the reason: each is asked for.
    click("Move the date");
    expect((await screen.findByRole("alert")).textContent).toBe("Give the new date.");
    type("New date", "2030-12-05");
    click("Move the date");
    expect((await screen.findByRole("alert")).textContent).toBe("That is already the delivery date.");
    type("New date", "2030-12-12");
    click("Move the date");
    expect((await screen.findByRole("alert")).textContent).toBe("Say why the date will change.");
    expect(writes(calls)).toHaveLength(0);

    type("Why", "Waiting in the print queue");
    click("Move the date");
    await waitFor(() => expect(writes(calls)).toHaveLength(1));
    expect(writes(calls)[0]).toMatchObject({
      method: "POST",
      path: "/api/factory/orders/2/delivery-date",
      body: { date: "2030-12-12", reason: "Waiting in the print queue" },
    });
    expect(await screen.findByText("The delivery date was moved.")).toBeTruthy();
    expect(screen.getByText("PO-2611-02 · printing: none · deliver by 12 Dec")).toBeTruthy();
    const history = within(cardOf("Delivery date")).getAllByRole("row").slice(1);
    expect(history.map((row) => row.textContent)).toEqual(["16 Nov12 DecYouWaiting in the print queue", "2 Nov5 DecHBAPlanned"]);
    // The boxes are empty for the next time.
    expect((screen.getByLabelText("Why") as HTMLInputElement).value).toBe("");
  });

  it("shows the server's own words when it refuses the new date", async () => {
    serveOrder(makeOrder(), {
      "POST /api/factory/orders/2/delivery-date": () => reply(422, { detail: "The order is already finished." }),
    });
    renderDesk("/factory/orders/2");
    await screen.findByRole("heading", { level: 1, name: "Wide-leg sweatpants · Grey" });
    type("New date", "2030-12-12");
    type("Why", "Print queue");
    click("Move the date");
    expect((await screen.findByRole("alert")).textContent).toBe("The order is already finished.");
  });

  it("keeps the history but offers no move when the date can no longer be moved", async () => {
    serveOrder(makeOrder({ can_move_date: false, can_report_cut: false }));
    renderDesk("/factory/orders/2");
    await screen.findByRole("heading", { level: 1, name: "Wide-leg sweatpants · Grey" });
    expect(screen.queryByRole("button", { name: "Move the date" })).toBeNull();
    expect(screen.queryByLabelText("New date")).toBeNull();
    expect(within(cardOf("Delivery date")).getAllByRole("row")).toHaveLength(2);
  });

  it("says why an order that is not this factory's, or was cancelled, cannot be opened", async () => {
    mockApi({ "GET /api/factory/orders/9": () => reply(403, { detail: "This order is not available to you." }) });
    renderDesk("/factory/orders/9");
    expect((await screen.findByRole("alert")).textContent).toBe("This order is not available to you.");
    expect(screen.getByRole("link", { name: "← Your orders" }).getAttribute("href")).toBe("/factory");
    expect(screen.queryByRole("heading", { name: "Sizes" })).toBeNull();
  });

  it("sends an address that is not a factory screen to the list", async () => {
    mockApi({ "GET /api/factory/orders": { orders: [] } });
    renderDesk("/production/next/orders");
    expect(await screen.findByRole("heading", { level: 1, name: "Your orders" })).toBeTruthy();
  });
});
