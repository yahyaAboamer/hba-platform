// @vitest-environment jsdom
import { cleanup, fireEvent, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { Session } from "../../../../lib/api";
import { headerLine, monthName, quantityLine } from "../overviewLogic";
import type { OrderRow, Overview, OverviewDecision, OverviewProblem } from "../types";
import { counts, makeArrival, makeRow, mockApi, narrowScreen, owner, qc, renderAt, reply, TODAY } from "./fixtures";

const ADDRESS = "/production/overview";

const readOnly = (): Session => {
  const reader = qc();
  reader.permissions = ["production.view"];
  return reader;
};

const BLACK = { id: 1, code: "PO-2610-01", style_name: "Oversized hoodie", colour: "Black" };
const OFFWHITE = { id: 2, code: "PO-2610-02", style_name: "Oversized hoodie", colour: "Off-white" };
const OLIVE = { id: 5, code: "PO-2611-05", style_name: "Zip hoodie", colour: "Olive" };

const decisions = (): OverviewDecision[] => [
  { key: "order:5:sample", title: "Approve the sample", kind: "generated", order: OLIVE, due: "2030-11-10", since: "2030-11-10", open: "sample", overdue_days: 3 },
  { key: "order:1:settle", title: "Settle with the factory", kind: "generated", order: BLACK, due: "2030-11-17", since: null, open: "settle", overdue_days: 0 },
  { key: "task:9", title: "Call the printer", kind: "manual", id: 9, order: null, due: null, since: null, open: null, overdue_days: 0 },
];

const problems = (): OverviewProblem[] => [
  { kind: "late_order", title: "Oversized hoodie · Off-white is 6 days late", detail: "Factory moved 20 Nov to 26 Nov · waiting in the print queue", link: { to: "order", id: 2 } },
  { kind: "late_material", title: "Zips for the sweatpants are 2 days late", detail: "Trims supplier · At Cutting", link: { to: "tasks" } },
  { kind: "count_mismatch", title: "1 piece missing between factory and Khazenly", detail: "Oversized hoodie · Black · no reason given yet", link: { to: "order", id: 1, open: "delivery-reason:31" } },
  { kind: "cost_over", title: "Oversized hoodie · Black costs EGP 9 more per piece than planned", detail: "EGP 309 against EGP 300 · fabric", link: { to: "order", id: 1 } },
];

const orders = (): OrderRow[] => [
  makeRow({
    id: 1, style_name: "Oversized hoodie", colour: "Black", code: "PO-2610-01",
    stage: { key: "warehouse", label: "Warehouse receipt", position: 9 },
    steps: ["done", "skipped", "done", "done", "done", "done", "done", "done", "done", "todo"],
    planned_total: 1000, cut_total: 1000, shipped_total: 925, received_total: 925,
    delivery_date: "2030-11-17", lateness_days: 6, finished_on: "2030-11-23",
    next_action: { stage: "warehouse", what: "30 fix pieces", who: "factory", by: "2030-11-17", since: null },
  }),
  makeRow({
    id: 2, style_name: "Oversized hoodie", colour: "Off-white", code: "PO-2610-02",
    cut_total: 985, shipped_total: 300, delivery_date: "2030-11-26", lateness_days: 6,
    next_action: { stage: "making", what: "Final inspection", who: "qc", by: "2030-11-26", since: null },
    flags: { late: true, waiting_for_owner: false, count_mismatch: false, fix_pieces_due: false },
  }),
  makeRow({
    id: 5, style_name: "Zip hoodie", colour: "Olive", code: "PO-2611-05",
    stage: { key: "sample", label: "Sample", position: 2 },
    steps: ["done", "done", "todo", "todo", "todo", "todo", "todo", "todo", "todo", "todo"],
    planned_total: 500, cut_total: null, delivery_date: "2030-12-20", lateness_days: 0,
    next_action: { stage: "sample", what: "Approve the sample", who: "owner", by: "2030-11-10", since: "2030-11-10" },
  }),
];

const arriving = () => [
  makeArrival({ key: "order:1:fix", kind: "fix", order: BLACK, basis: null, due: "2030-11-17", expected: counts({ M: 30 }), to_come: counts({ M: 30 }) }),
  makeArrival({ key: "order:2:finished", order: OFFWHITE, due: "2030-11-26", late_days: 6, expected: counts({ M: 685 }), to_come: counts({ M: 685 }) }),
];

/** The answer as the server sends it to the owner; `forOthers` takes the money out as the server does. */
function overview(over: Partial<Overview> = {}, forOthers = false): Overview {
  const answer: Overview = {
    today: TODAY,
    summary: { open_orders: 5, planned_pieces: 3900 },
    figures: {
      decisions: 2,
      late_orders: 2,
      open_orders: 5,
      arriving_this_month: { month: "2030-11", pieces: 715 },
      owed_piastres: 14315000,
    },
    decisions: decisions().slice(0, 2),
    problems: problems(),
    orders: orders(),
    arriving: arriving(),
    owed: [
      { supplier: { id: "SUP-2", name: "Fabric supplier A" }, owed_piastres: 13200000, detail: "Rest of the fleece purchase" },
      { supplier: { id: "SUP-3", name: "Trims supplier" }, owed_piastres: 840000, detail: null },
    ],
    ...over,
  };
  if (forOthers) {
    delete answer.owed;
    delete answer.figures.owed_piastres;
    answer.problems = answer.problems.filter((problem) => problem.kind !== "cost_over");
  }
  return answer;
}

const serve = (answer: Overview) => mockApi({ "GET /api/prod/overview": answer });

const hrefOf = (element: HTMLElement): string | null => element.getAttribute("href");

const figureOf = (label: string): HTMLElement => {
  const term = screen.getByText(label, { selector: "dt" });
  return term.parentElement as HTMLElement;
};

const card = (name: string): Promise<HTMLElement> => screen.findByRole("region", { name });

beforeEach(() => narrowScreen(false));
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("The header and the figures", () => {
  it("says the day, the orders and the pieces, and gives the owner four figures", async () => {
    serve(overview());
    renderAt(ADDRESS, owner());
    expect(await screen.findByRole("heading", { level: 1, name: "Production" })).toBeTruthy();
    expect(screen.getByText("Wednesday 13 Nov · 5 orders in production, 3,900 pieces planned")).toBeTruthy();

    const decisionsFigure = figureOf("Waiting for your decision");
    expect(decisionsFigure.textContent).toContain("2");
    expect(decisionsFigure.querySelector("dd")?.className).toBe("prod-warn");
    const lateFigure = figureOf("Orders running late");
    expect(lateFigure.querySelector("dd")?.textContent).toBe("2 of 5");
    expect(lateFigure.querySelector("dd")?.className).toBe("prod-late");
    expect(figureOf("Arriving in November").querySelector("dd")?.textContent).toBe("715 pieces");
    expect(figureOf("You owe suppliers").querySelector("dd")?.textContent).toBe("EGP 143,150.00");
    expect(document.querySelectorAll(".prod-facts > div")).toHaveLength(4);
  });

  it("leaves the tone off a figure that is zero", async () => {
    serve(overview({ figures: { decisions: 0, late_orders: 0, open_orders: 5, arriving_this_month: { month: "2030-11", pieces: 0 }, owed_piastres: 0 }, decisions: [] }));
    renderAt(ADDRESS, owner());
    await screen.findByRole("heading", { level: 1, name: "Production" });
    expect(figureOf("Waiting for your decision").querySelector("dd")?.className).toBe("");
    expect(figureOf("Orders running late").querySelector("dd")?.textContent).toBe("0 of 5");
    expect(figureOf("Orders running late").querySelector("dd")?.className).toBe("");
    expect(figureOf("Arriving in November").querySelector("dd")?.textContent).toBe("0 pieces");
  });

  it("gives the QC manager three figures and not a pound of money anywhere", async () => {
    serve(overview({}, true));
    renderAt(ADDRESS, qc());
    await screen.findByRole("heading", { level: 1, name: "Production" });
    expect(document.querySelectorAll(".prod-facts > div")).toHaveLength(3);
    expect(document.querySelector(".prod-facts--three")).toBeTruthy();
    expect(screen.queryByText("You owe suppliers")).toBeNull();
    expect(screen.queryByText("Waiting for your decision")).toBeNull();
    expect(figureOf("Waiting for the owner").querySelector("dd")?.textContent).toBe("2");
    expect(document.body.textContent).not.toMatch(/EGP/);
  });

  it("draws no money when the answer has none, even for an owner's session", async () => {
    serve(overview({}, true));
    renderAt(ADDRESS, owner());
    await screen.findByRole("heading", { level: 1, name: "Production" });
    expect(screen.queryByText("You owe suppliers")).toBeNull();
    expect(screen.queryByRole("region", { name: "What you owe" })).toBeNull();
    expect(document.body.textContent).not.toMatch(/EGP/);
    expect(document.querySelectorAll(".prod-facts > div")).toHaveLength(3);
  });

  it("names the month the server names, from its label or from YYYY-MM", async () => {
    expect(monthName({ month: "2030-12" })).toBe("December");
    expect(monthName({ month: "2030-11", label: "November" })).toBe("November");
    expect(monthName({ month: "November" })).toBe("November");
    expect(headerLine(overview({ summary: { open_orders: 1, planned_pieces: 1 } }))).toBe("Wednesday 13 Nov · 1 order in production, 1 piece planned");
  });
});

describe("Waiting for your decision", () => {
  it("lists the owner's decisions with the order and how long, and a button per kind", async () => {
    serve(overview({ decisions: decisions() }));
    renderAt(ADDRESS, owner());
    const box = await card("Waiting for your decision");
    // "waiting 3 days" counts from the server's today (13 Nov) to the day it started waiting (10 Nov).
    expect(within(box).getByText("Zip hoodie · Olive · waiting 3 days")).toBeTruthy();
    expect(within(box).getByText("Oversized hoodie · Black")).toBeTruthy();
    expect(within(box).getByText("Added by hand · no order")).toBeTruthy();

    const review = within(box).getByRole("link", { name: "Review sample: Approve the sample" });
    expect(review.textContent).toBe("Review sample");
    expect(hrefOf(review)).toBe("/production/orders/5?open=sample");
    const settle = within(box).getByRole("link", { name: "Settle: Settle with the factory" });
    expect(hrefOf(settle)).toBe("/production/orders/1?open=settle");
    const tasks = within(box).getByRole("link", { name: "Open tasks: Call the printer" });
    expect(hrefOf(tasks)).toBe("/production/tasks");
  });

  it("is headed for the owner, and gives the QC manager the same rows with no buttons", async () => {
    serve(overview({ decisions: decisions() }, true));
    renderAt(ADDRESS, qc());
    const box = await screen.findByRole("region", { name: "Waiting for the owner" });
    expect(screen.queryByRole("region", { name: "Waiting for your decision" })).toBeNull();
    expect(within(box).getByText("Approve the sample")).toBeTruthy();
    expect(within(box).queryAllByRole("link")).toHaveLength(0);
    expect(within(box).queryAllByRole("button")).toHaveLength(0);
  });

  it("gives somebody who can only read no buttons either", async () => {
    serve(overview({ decisions: decisions() }, true));
    renderAt(ADDRESS, readOnly());
    const box = await screen.findByRole("region", { name: "Waiting for the owner" });
    expect(within(box).queryAllByRole("link")).toHaveLength(0);
  });

  it("says plainly when nothing waits", async () => {
    serve(overview({ decisions: [], figures: { ...overview().figures, decisions: 0 } }));
    renderAt(ADDRESS, owner());
    expect(await screen.findByText("Nothing is waiting for you.")).toBeTruthy();
    cleanup();
    serve(overview({ decisions: [] }, true));
    renderAt(ADDRESS, qc());
    expect(await screen.findByText("Nothing is waiting for the owner.")).toBeTruthy();
  });
});

describe("Problems right now", () => {
  it("shows each problem's title and detail, and an Open link to the right place", async () => {
    serve(overview());
    renderAt(ADDRESS, owner());
    const box = await screen.findByRole("region", { name: "Problems right now" });
    expect(within(box).getByText("Factory moved 20 Nov to 26 Nov · waiting in the print queue")).toBeTruthy();
    const late = within(box).getByRole("link", { name: "Open: Oversized hoodie · Off-white is 6 days late" });
    expect(late.textContent).toBe("Open");
    expect(hrefOf(late)).toBe("/production/orders/2");
    expect(hrefOf(within(box).getByRole("link", { name: "Open: Zips for the sweatpants are 2 days late" }))).toBe("/production/tasks");
    expect(hrefOf(within(box).getByRole("link", { name: "Open: 1 piece missing between factory and Khazenly" }))).toBe(
      "/production/orders/1?open=delivery-reason:31",
    );
    expect(within(box).getByText("EGP 309 against EGP 300 · fabric")).toBeTruthy();
  });

  it("also sends a problem to Incoming", async () => {
    serve(overview({ problems: [{ kind: "count_mismatch", title: "Counts differ", detail: "x", link: { to: "incoming" } }] }));
    renderAt(ADDRESS, owner());
    const link = await screen.findByRole("link", { name: "Open: Counts differ" });
    expect(hrefOf(link)).toBe("/production/incoming");
  });

  it("shows no cost problem to the QC manager, and says plainly when there is none", async () => {
    serve(overview({}, true));
    renderAt(ADDRESS, qc());
    const box = await screen.findByRole("region", { name: "Problems right now" });
    expect(within(box).queryByText(/costs EGP/)).toBeNull();
    expect(within(box).getAllByRole("link")).toHaveLength(3);
    cleanup();
    serve(overview({ problems: [] }));
    renderAt(ADDRESS, owner());
    expect(await screen.findByText("No problems right now.")).toBeTruthy();
  });
});

describe("Every order, and what happens next", () => {
  it("shows each order's name, stage, pieces, step bar, next action, date and lateness", async () => {
    serve(overview());
    renderAt(ADDRESS, owner());
    const heading = await screen.findByRole("heading", { level: 2, name: "Every order, and what happens next" });
    const list = heading.parentElement as HTMLElement;
    const rows = within(list).getAllByRole("listitem");
    expect(rows).toHaveLength(3);

    const first = rows[0];
    const name = within(first).getByRole("link", { name: "Oversized hoodie · Black" });
    expect(hrefOf(name)).toBe("/production/orders/1");
    expect(within(first).getByText("9 of 10 · Warehouse receipt · 925 of 1,000 counted")).toBeTruthy();
    expect(within(first).getByRole("img", { name: "8 of 10 stages done, 1 skipped" })).toBeTruthy();
    expect(within(first).getByText("Next: 30 fix pieces · Factory")).toBeTruthy();
    const late = within(first).getByText("17 Nov · finished 6 days late");
    expect(late.className).toBe("prod-late");

    expect(within(rows[1]).getByText("7 of 10 · Making · 300 of 985 shipped")).toBeTruthy();
    expect(within(rows[1]).getByText("Next: final inspection · QC manager")).toBeTruthy();
    expect(within(rows[1]).getByText("26 Nov · 6 days late").className).toBe("prod-late");

    const owners = within(rows[2]).getByText("Next: approve the sample · Owner");
    expect(owners.className).toBe("prod-warn");
    expect(within(rows[2]).getByText("20 Dec · on time").className).toBe("");
  });

  it("names the pieces by how far the order has got", () => {
    const row = makeRow({ id: 9, style_name: "x" });
    expect(quantityLine({ ...row, cut_total: null, planned_total: 800, shipped_total: 0, received_total: null })).toBe("800 planned");
    expect(quantityLine({ ...row, cut_total: 972, shipped_total: 0, received_total: null })).toBe("972 cut");
    expect(quantityLine({ ...row, cut_total: 985, shipped_total: 300, received_total: null })).toBe("300 of 985 shipped");
    expect(quantityLine({ ...row, cut_total: 1000, shipped_total: 925, received_total: 925 })).toBe("925 of 1,000 counted");
  });

  it("says plainly when there are no orders, and gives the owner the way to make one", async () => {
    serve(overview({ orders: [], summary: { open_orders: 0, planned_pieces: 0 } }));
    renderAt(ADDRESS, owner());
    expect(await screen.findByText("No orders in production.")).toBeTruthy();
    expect(screen.getAllByRole("link", { name: "New order" })).toHaveLength(1);
    cleanup();
    serve(overview({ orders: [], summary: { open_orders: 0, planned_pieces: 0 } }, true));
    renderAt(ADDRESS, qc());
    expect(await screen.findByText("No orders in production.")).toBeTruthy();
    expect(screen.queryByRole("link", { name: "New order" })).toBeNull();
  });
});

describe("Arriving next and What you owe", () => {
  it("lists what arrives, with the late one as 'by <date>' in the late colour", async () => {
    serve(overview());
    renderAt(ADDRESS, owner());
    const box = await screen.findByRole("region", { name: "Arriving next" });
    const fix = within(box).getByRole("link", { name: "30 fix pieces · Oversized hoodie · Black" });
    expect(hrefOf(fix)).toBe("/production/orders/1");
    expect(within(box).getByText("17 Nov").className).toBe("");
    expect(within(box).getByRole("link", { name: "685 pieces · Oversized hoodie · Off-white" })).toBeTruthy();
    expect(within(box).getByText("by 26 Nov").className).toBe("prod-late");
  });

  it("lists what the owner owes, largest first as the server sent it, with a link to each supplier", async () => {
    serve(overview());
    renderAt(ADDRESS, owner());
    const box = await screen.findByRole("region", { name: "What you owe" });
    const names = within(box).getAllByRole("link").map((link) => link.textContent);
    expect(names).toEqual(["Fabric supplier A", "Trims supplier"]);
    expect(hrefOf(within(box).getByRole("link", { name: "Fabric supplier A" }))).toBe("/production/suppliers/SUP-2");
    expect(within(box).getByText("Rest of the fleece purchase")).toBeTruthy();
    expect(within(box).getByText("EGP 132,000.00")).toBeTruthy();
    expect(within(box).getByText("EGP 8,400.00")).toBeTruthy();
  });

  it("gives the QC manager Arriving next alone, across the page", async () => {
    serve(overview({}, true));
    renderAt(ADDRESS, qc());
    const box = await screen.findByRole("region", { name: "Arriving next" });
    expect(screen.queryByRole("region", { name: "What you owe" })).toBeNull();
    expect(box.parentElement?.className).toContain("prod-halves--one");
  });

  it("says plainly when nothing is on its way or owed", async () => {
    serve(overview({ arriving: [], owed: [] }));
    renderAt(ADDRESS, owner());
    expect(await screen.findByText("Nothing is on its way.")).toBeTruthy();
    expect(screen.getByText("You owe no supplier anything.")).toBeTruthy();
  });
});

describe("New order", () => {
  it("is the owner's button, and nobody else's", async () => {
    serve(overview());
    renderAt(ADDRESS, owner());
    const button = await screen.findByRole("link", { name: "New order" });
    expect(hrefOf(button)).toBe("/production/orders/new");
    cleanup();
    serve(overview({}, true));
    renderAt(ADDRESS, qc());
    await screen.findByRole("heading", { level: 1, name: "Production" });
    expect(screen.queryByRole("link", { name: "New order" })).toBeNull();
  });
});

describe("Loading, errors and the phone", () => {
  it("says it is loading, then shows the page", async () => {
    let release: (answer: Overview) => void = () => undefined;
    mockApi({ "GET /api/prod/overview": () => new Promise<Overview>((resolve) => (release = resolve)) });
    renderAt(ADDRESS, owner());
    expect(await screen.findByRole("status")).toBeTruthy();
    expect(screen.getByText("Loading the overview…")).toBeTruthy();
    release(overview());
    expect(await screen.findByRole("region", { name: "Problems right now" })).toBeTruthy();
  });

  it("shows a failure and reads again on Try again", async () => {
    let fail = true;
    const calls = mockApi({
      "GET /api/prod/overview": () => (fail ? reply(500, { detail: "The overview is broken." }) : overview()),
    });
    renderAt(ADDRESS, owner());
    expect((await screen.findByRole("alert")).textContent).toContain("The overview is broken.");
    fail = false;
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByRole("region", { name: "Problems right now" })).toBeTruthy();
    expect(screen.queryByRole("alert")).toBeNull();
    expect(calls.filter((call) => call.path === "/api/prod/overview")).toHaveLength(2);
  });

  it("stacks each row on a phone and keeps every button and link", async () => {
    narrowScreen(true);
    serve(overview({ decisions: decisions() }));
    renderAt(ADDRESS, owner());
    await screen.findByRole("region", { name: "Problems right now" });
    expect(document.querySelectorAll(".prod-task:not(.prod-task--narrow)")).toHaveLength(0);
    expect(document.querySelectorAll(".prod-task--narrow").length).toBeGreaterThan(8);
    expect(screen.getByRole("link", { name: "Review sample: Approve the sample" })).toBeTruthy();
    expect(screen.getByRole("link", { name: "Open: Zips for the sweatpants are 2 days late" })).toBeTruthy();
  });
});

describe("The Overview address", () => {
  it("is where /production goes", async () => {
    serve(overview());
    renderAt("/production", owner());
    expect(await screen.findByRole("region", { name: "Problems right now" })).toBeTruthy();
  });
});
