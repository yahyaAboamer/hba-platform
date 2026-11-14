// @vitest-environment jsdom
import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { Session } from "../../../../lib/api";
import type { Incoming, IncomingArrival, IncomingDelivery } from "../types";
import {
  counts,
  makeArrival,
  makeIncoming,
  makeIncomingDelivery,
  makeTaskList,
  mockApi,
  narrowScreen,
  owner,
  qc,
  renderAt,
  reply,
} from "./fixtures";

const ADDRESS = "/production/next/incoming";

const BLACK = { id: 1, code: "PO-2610-01", style_name: "Oversized hoodie", colour: "Black" };
const OFFWHITE = { id: 2, code: "PO-2610-02", style_name: "Oversized hoodie", colour: "Off-white" };
const GREY = { id: 4, code: "PO-2611-01", style_name: "Wide-leg sweatpants", colour: "Grey" };

const readOnly = (): Session => {
  const reader = qc();
  reader.permissions = ["production.view"];
  return reader;
};

/** The mockup's sample, as the server would send it: two arrivals that can be recorded, one that cannot. */
const arrivals = (): IncomingArrival[] => [
  makeArrival({
    key: "order:1:fix", kind: "fix", order: BLACK, basis: null, due: "2030-11-17",
    expected: counts({ S: 5, M: 8, L: 9, XL: 5, XXL: 3 }), to_come: counts({ S: 5, M: 8, L: 9, XL: 5, XXL: 3 }),
    stage: { key: "warehouse", label: "Warehouse receipt", position: 9 }, status_words: "repaired pieces", can_record: true,
  }),
  makeArrival({
    key: "order:2:finished", order: OFFWHITE, basis: "cut", due: "2030-11-26", late_days: 6,
    expected: counts({ S: 148, M: 296, L: 295, XL: 177, XXL: 69 }),
    shipped: counts({ S: 148, M: 152 }),
    to_come: counts({ M: 144, L: 295, XL: 177, XXL: 69 }),
    stage: { key: "warehouse", label: "Warehouse receipt", position: 9 }, status_words: "arriving as pieces finish", can_record: true,
  }),
  makeArrival({
    key: "order:4:finished", order: GREY, due: "2030-12-05",
    expected: counts({ S: 120, M: 240, L: 240, XL: 140, XXL: 60 }), to_come: counts({ S: 120, M: 240, L: 240, XL: 140, XXL: 60 }),
    status_words: "being cut, final numbers after cutting", can_record: false,
  }),
];

const deliveries = (): IncomingDelivery[] => [
  makeIncomingDelivery({
    id: 31, order: OFFWHITE, number: 1, shipped_on: "2030-11-12", counted_on: null, shipped: { S: 148, M: 152 },
    shipped_total: 300, counted: {}, counted_total: null, state: "waiting_for_count",
  }),
  makeIncomingDelivery({
    id: 22, order: BLACK, number: 2, shipped_on: "2030-11-11", counted_on: "2030-11-12", shipped: { S: 60, M: 140, L: 136, XL: 80, XXL: 30 },
    shipped_total: 446, counted: { S: 60, M: 139, L: 136, XL: 80, XXL: 30 }, counted_total: 445, state: "mismatch", difference: -1,
    missing: 1, extra: 0, sizes_differ: [{ size: "M", shipped: 140, counted: 139, difference: -1 }],
  }),
  makeIncomingDelivery({ id: 21, order: BLACK, number: 1, shipped_on: "2030-11-09", shipped_total: 480, counted_total: 480 }),
];

function serve(data: Incoming = makeIncoming(arrivals(), deliveries())) {
  return mockApi({ "GET /api/prod/incoming": data, "GET /api/prod/tasks": makeTaskList([]) });
}

const rowOf = (title: string): HTMLElement => screen.getByRole("link", { name: title }).closest("li")!;
const hrefOf = (element: HTMLElement) => element.getAttribute("href");

beforeEach(() => narrowScreen(false));
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("The Incoming screen", () => {
  it("says how much is still to leave the factory and what waits for Khazenly, with the four figures", async () => {
    serve();
    renderAt(ADDRESS, owner());
    expect(await screen.findByRole("heading", { level: 1, name: "Incoming" })).toBeTruthy();
    // 30 fix + 685 of the Off-white + 800 of the sweatpants; 300 shipped and waiting.
    expect(screen.getByText("1,515 pieces still to leave the factory · 300 shipped and waiting for Khazenly's count")).toBeTruthy();

    const figure = (label: string) => screen.getByText(label).closest("div")!;
    expect(figure("Arriving in November").textContent).toBe("Arriving in November" + "715");
    expect(figure("Arriving in December").textContent).toBe("Arriving in December" + "800");
    expect(figure("Waiting for Khazenly's count").textContent).toBe("Waiting for Khazenly's count" + "300");
    expect(figure("Counts that do not match").textContent).toBe("Counts that do not match" + "1 piece");
    // Only a figure with something owed gets a tone, and its words say the same.
    expect(within(figure("Waiting for Khazenly's count")).getByText("300").className).toContain("prod-warn");
    expect(within(figure("Counts that do not match")).getByText("1 piece").className).toContain("prod-late");
    expect(within(figure("Arriving in November")).getByText("715").className).toBe("");
  });

  it("shows nothing in a tone when nothing is owed", async () => {
    serve(makeIncoming(arrivals().slice(1, 2), [makeIncomingDelivery()]));
    renderAt(ADDRESS, owner());
    await screen.findByRole("heading", { level: 1, name: "Incoming" });
    const waiting = screen.getByText("Waiting for Khazenly's count").closest("div")!;
    expect(within(waiting).getByText("0").className).toBe("");
    const mismatch = screen.getByText("Counts that do not match").closest("div")!;
    expect(within(mismatch).getByText("None").className).toBe("");
  });

  it("lists the arrivals nearest first, each with its sizes, order line, date and Record delivery", async () => {
    serve();
    renderAt(ADDRESS, owner());
    await screen.findByRole("heading", { level: 1, name: "Incoming" });
    expect(screen.getByRole("heading", { level: 2, name: "Arriving next" })).toBeTruthy();

    const fix = rowOf("Oversized hoodie · Black · 30 fix pieces");
    expect(fix.textContent).toContain("S 5 · M 8 · L 9 · XL 5 · XXL 3");
    expect(fix.textContent).toContain("PO-2610-01 · Main factory · repaired pieces");
    expect(fix.textContent).toContain("17 Nov");
    // Fix pieces name their kind, so the order opens the right form even with finished pieces still to come.
    expect(hrefOf(within(fix).getByRole("link", { name: /^Record delivery/ }))).toBe("/production/next/orders/1?open=delivery:fix");

    const offWhite = rowOf("Oversized hoodie · Off-white · 685 of 985 still to come");
    expect(offWhite.textContent).toContain("M 144 · L 295 · XL 177 · XXL 69 · as cut · 300 already shipped");
    expect(offWhite.textContent).toContain("PO-2610-02 · Main factory · arriving as pieces finish");
    expect(offWhite.textContent).toContain("26 Nov · 6 days late");
    expect(within(offWhite).getByText("26 Nov · 6 days late").className).toContain("prod-late");
    expect(hrefOf(within(offWhite).getByRole("link", { name: /^Record delivery/ }))).toBe("/production/next/orders/2?open=delivery");

    // Still being cut: numbers are the plan, and the order's form would not take a delivery yet.
    const sweatpants = rowOf("Wide-leg sweatpants · Grey · 800 planned");
    expect(sweatpants.textContent).toContain("S 120 · M 240 · L 240 · XL 140 · XXL 60");
    expect(sweatpants.textContent).toContain("PO-2611-01 · Main factory · being cut, final numbers after cutting");
    expect(sweatpants.textContent).toContain("5 Dec");
    expect(within(sweatpants).queryByRole("link", { name: /Record delivery/ })).toBeNull();

    const titles = screen
      .getAllByRole("link")
      .map((link) => link.textContent ?? "")
      .filter((text) => /still to come$|planned$|fix pieces$/.test(text));
    expect(titles).toEqual([
      "Oversized hoodie · Black · 30 fix pieces",
      "Oversized hoodie · Off-white · 685 of 985 still to come",
      "Wide-leg sweatpants · Grey · 800 planned",
    ]);
  });

  it("links each title to its order", async () => {
    serve();
    renderAt(ADDRESS, readOnly());
    await screen.findByRole("heading", { level: 1, name: "Incoming" });
    expect(hrefOf(screen.getByRole("link", { name: "Wide-leg sweatpants · Grey · 800 planned" }))).toBe("/production/next/orders/4");
    expect(hrefOf(screen.getByRole("link", { name: "Oversized hoodie · Black · delivery 2" }))).toBe("/production/next/orders/1");
  });

  it("words a plain arrival with nothing shipped by what the order is counted from", async () => {
    serve(makeIncoming([makeArrival({ basis: "passed", expected: counts({ S: 70 }), to_come: counts({ S: 70 }) })], []));
    renderAt(ADDRESS, owner());
    expect(await screen.findByRole("link", { name: "Oversized hoodie · Black · 70 still to come" })).toBeTruthy();
  });

  it("lists every delivery with its counts, a pill in words and one button", async () => {
    serve();
    renderAt(ADDRESS, owner());
    await screen.findByRole("heading", { level: 1, name: "Incoming" });
    expect(screen.getByRole("heading", { level: 2, name: "Deliveries" })).toBeTruthy();

    const waiting = rowOf("Oversized hoodie · Off-white · delivery 1");
    expect(waiting.textContent).toContain("12 Nov · factory shipped 300 · Khazenly's count not entered yet");
    expect(within(waiting).getByText("Waiting for count").className).toContain("prod-pill--wait");
    expect(hrefOf(within(waiting).getByRole("link", { name: /^Enter Khazenly's count/ }))).toBe("/production/next/orders/2?open=delivery:31");

    const short = rowOf("Oversized hoodie · Black · delivery 2");
    expect(short.textContent).toContain("11 Nov · factory shipped 446 · Khazenly counted 445 · size M is 1 short");
    expect(within(short).getByText("1 piece missing").className).toContain("prod-pill--late");
    expect(hrefOf(within(short).getByRole("link", { name: /^Add reason/ }))).toBe("/production/next/orders/1?open=delivery-reason:22");

    const match = rowOf("Oversized hoodie · Black · delivery 1");
    expect(match.textContent).toContain("9 Nov · factory shipped 480 · Khazenly counted 480");
    expect(within(match).getByText("Counts match").className).toContain("prod-pill--ok");
    expect(within(match).getAllByRole("link")).toHaveLength(1); // the title only: nothing left to do
  });

  it("says the difference in words for pieces over, pieces both ways, an explained count and a size not counted", async () => {
    serve(
      makeIncoming([], [
        makeIncomingDelivery({
          id: 1, number: 1, state: "mismatch", counted_total: 482, difference: 2, extra: 2,
          sizes_differ: [{ size: "S", shipped: 200, counted: 202, difference: 2 }],
        }),
        makeIncomingDelivery({
          id: 2, number: 2, state: "mismatch", difference: 0, missing: 1, extra: 1,
          sizes_differ: [
            { size: "S", shipped: 200, counted: 199, difference: -1 },
            { size: "M", shipped: 280, counted: 281, difference: 1 },
          ],
        }),
        makeIncomingDelivery({
          id: 3, number: 3, state: "explained", difference: -1, missing: 1, reason: "One piece not found at Khazenly",
          sizes_differ: [{ size: "M", shipped: 280, counted: 279, difference: -1 }],
        }),
        makeIncomingDelivery({
          id: 4, number: 4, kind: "fix", state: "waiting_for_count", shipped: { S: 3, XS: 5 }, shipped_total: 8,
          counted: { S: 3 }, counted_total: 3,
        }),
      ]),
    );
    renderAt(ADDRESS, owner());
    await screen.findByRole("heading", { level: 1, name: "Incoming" });

    const over = rowOf("Oversized hoodie · Black · delivery 1");
    expect(over.textContent).toContain("size S is 2 more than shipped");
    expect(within(over).getByText("2 more than shipped")).toBeTruthy();

    const both = rowOf("Oversized hoodie · Black · delivery 2");
    expect(both.textContent).toContain("size S is 1 short, size M is 1 more than shipped");
    expect(within(both).getByText("1 piece missing, 1 more than shipped")).toBeTruthy();

    const explained = rowOf("Oversized hoodie · Black · delivery 3");
    expect(within(explained).getByText("Explained")).toBeTruthy();
    expect(explained.textContent).toContain("Reason given: One piece not found at Khazenly");
    expect(within(explained).getAllByRole("link")).toHaveLength(1); // nothing left to do

    const part = rowOf("Oversized hoodie · Black · delivery 4 · fix pieces");
    expect(part.textContent).toContain("Khazenly counted 3 · size XS not counted yet");
    expect(within(part).getByText("Waiting for count")).toBeTruthy();
    expect(within(part).getByRole("link", { name: /^Enter Khazenly's count/ })).toBeTruthy();
  });

  it("gives somebody who can only read no button at all, and the QC manager and the owner theirs", async () => {
    serve();
    const { unmount } = renderAt(ADDRESS, readOnly());
    await screen.findByRole("heading", { level: 1, name: "Incoming" });
    expect(screen.queryByRole("link", { name: /^Record delivery/ })).toBeNull();
    expect(screen.queryByRole("link", { name: /^Enter Khazenly's count/ })).toBeNull();
    expect(screen.queryByRole("link", { name: /^Add reason/ })).toBeNull();
    // The pills and the sizes are still there to read.
    expect(screen.getByText("Waiting for count")).toBeTruthy();
    expect(screen.getByText("1 piece missing")).toBeTruthy();
    unmount();

    for (const session of [qc(), owner()]) {
      serve();
      const view = renderAt(ADDRESS, session);
      await screen.findByRole("heading", { level: 1, name: "Incoming" });
      expect(screen.getAllByRole("link", { name: /^Record delivery/ })).toHaveLength(2);
      expect(screen.getAllByRole("link", { name: /^Enter Khazenly's count/ })).toHaveLength(1);
      expect(screen.getAllByRole("link", { name: /^Add reason/ })).toHaveLength(1);
      view.unmount();
    }
  });

  it("says so in words when nothing is on its way and no delivery has been made", async () => {
    serve(makeIncoming([], []));
    renderAt(ADDRESS, owner());
    expect(await screen.findByText("Nothing is on its way.")).toBeTruthy();
    expect(screen.getByText("No deliveries yet.")).toBeTruthy();
    expect(screen.getByText("0 pieces still to leave the factory · 0 shipped and waiting for Khazenly's count")).toBeTruthy();
  });

  it("says when it could not load, and tries again", async () => {
    let answers = 0;
    mockApi({
      "GET /api/prod/incoming": () => (answers++ === 0 ? reply(500, { detail: "The server is busy." }) : makeIncoming(arrivals(), deliveries())),
      "GET /api/prod/tasks": makeTaskList([]),
    });
    renderAt(ADDRESS, owner());
    expect(await screen.findByRole("alert")).toBeTruthy();
    expect(screen.queryByRole("heading", { level: 2, name: "Arriving next" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByRole("heading", { level: 2, name: "Arriving next" })).toBeTruthy();
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("is a tab after Tasks, and the current one", async () => {
    serve();
    renderAt(ADDRESS, owner());
    await screen.findByRole("heading", { level: 1, name: "Incoming" });
    const nav = screen.getByRole("navigation", { name: "Production sections" });
    const links = within(nav).getAllByRole("link");
    const names = links.map((link) => link.textContent?.replace(/\s.*/, ""));
    expect(names.indexOf("Incoming")).toBe(names.indexOf("Tasks") + 1);
    expect(hrefOf(within(nav).getByRole("link", { name: "Incoming" }))).toBe("/production/next/incoming");
    expect(within(nav).getByRole("link", { name: "Incoming" }).getAttribute("aria-current")).toBe("page");
    expect(within(nav).getByRole("link", { name: "Tasks" }).getAttribute("aria-current")).toBeNull();
  });

  it("stacks each row on a phone and keeps every button", async () => {
    narrowScreen(true);
    serve();
    renderAt(ADDRESS, owner());
    await screen.findByRole("heading", { level: 1, name: "Incoming" });
    const rows = screen.getAllByRole("listitem").filter((item) => item.className.includes("prod-task"));
    expect(rows).toHaveLength(6);
    for (const row of rows) expect(row.className).toContain("prod-task--narrow");
    expect(screen.getAllByRole("link", { name: /^Record delivery/ })).toHaveLength(2);
    expect(within(rowOf("Oversized hoodie · Off-white · 685 of 985 still to come")).getByText("26 Nov · 6 days late")).toBeTruthy();
    await waitFor(() => expect(screen.getByText("Waiting for count")).toBeTruthy());
  });
});
