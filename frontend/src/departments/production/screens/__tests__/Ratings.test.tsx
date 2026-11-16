// @vitest-environment jsdom
import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { Session } from "../../../../lib/api";
import type { OrderRatings, OrderView, RatingTarget } from "../types";
import { makeOrder, mockApi, narrowScreen, owner, qc, renderAt, reply } from "./fixtures";
import type { Call } from "./fixtures";
import { factoryRow, makeSupplierList, makeSupplierPage, makeSupplierRow, moneyKeysIn } from "./supplierFixtures";
import { averageWords, latenessWords, ratingLine, starsWords, usualFigure, usualWords } from "../supplierLogic";

const ORDER = "/production/orders/3";
const writes = (calls: Call[]) => calls.filter((call) => call.method !== "GET");

/** Somebody who can only read. */
const reader = (): Session => {
  const session = qc();
  session.permissions = ["production.view"];
  return session;
};

const closedOrder = (status: "closed" | "cancelled" = "closed"): OrderView =>
  makeOrder("settle", { extra: { status, stage: null, next_action: null } });

const target = (over: Partial<RatingTarget> & { id: string; name: string }): RatingTarget => {
  const { id, name, ...rest } = over;
  return { supplier: { id, name }, role: "factory", lateness_days: null, suggested_timing: null, rating: null, ...rest };
};

const FACTORY = target({ id: "fac", name: "Main factory", lateness_days: 6, suggested_timing: 2 });
const PRINT = target({ id: "prt", name: "Print house A", role: "print" });
const TRIMS = target({ id: "trm", name: "Trims supplier", role: "materials", lateness_days: 0, suggested_timing: 5 });
const RATED = { quality: 4, timing: 3, dealing: 5, note: "Fixed the stitching problem quickly.", updated_at: "2030-11-13T10:00:00Z" };

const ratingsOf = (suppliers: RatingTarget[], ratable = true): OrderRatings => ({ ratable, suppliers });

function serveOrder(order: OrderView, ratings: OrderRatings | (() => OrderRatings), extra: Record<string, unknown> = {}) {
  return mockApi({
    "GET /api/prod/orders/3": { order },
    "GET /api/prod/orders/3/history": { events: [] },
    "GET /api/prod/orders/3/files": { files: [] },
    "GET /api/prod/orders/3/ratings": typeof ratings === "function" ? ratings : () => ratings,
    ...extra,
  });
}

const formOf = (name: string): HTMLElement => screen.getByRole("form", { name: `Rating for ${name}` });
const groupOf = (form: HTMLElement, label: string): HTMLElement => within(form).getByRole("radiogroup", { name: label });
const checked = (group: HTMLElement): string | null => {
  const picked = within(group).queryAllByRole("radio").find((radio) => (radio as HTMLInputElement).checked);
  return picked ? (picked.closest("label")!.querySelector(".prod-star__n")?.textContent ?? null) : null;
};
const pick = (form: HTMLElement, label: string, stars: number) =>
  fireEvent.click(within(groupOf(form, label)).getByRole("radio", { name: `${stars} of 5` }));

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

describe("The words of ratings and the record", () => {
  it("says averages with one decimal and an order's own stars as whole numbers", () => {
    expect(averageWords({ quality: 4, timing: 2.5, dealing: 4.5 })).toBe("Quality 4.0 ★ · Timing 2.5 ★ · Dealing 4.5 ★");
    expect(starsWords({ quality: 4, timing: 3, dealing: 5 })).toBe("Quality 4 ★ · Timing 3 ★ · Dealing 5 ★");
  });

  it("says the usual lateness on the list, with and without ratings", () => {
    expect(ratingLine({ ratings: { quality: 4, timing: 2.5, dealing: 4.5, count: 2 }, usual_lateness_days: 5 })).toBe(
      "Quality 4.0 ★ · Timing 2.5 ★ · Dealing 4.5 ★ · usually 5 days late",
    );
    expect(ratingLine({ ratings: null, usual_lateness_days: null })).toBe("Not rated yet");
    expect(ratingLine({ ratings: null, usual_lateness_days: 0 })).toBe("Not rated yet · usually on time");
    expect(usualWords(1)).toBe("usually 1 day late");
    expect(usualWords(0)).toBe("usually on time");
    expect(usualWords(null)).toBeNull();
  });

  it("says the figure and an order's lateness in words", () => {
    expect(usualFigure(5)).toEqual({ text: "5 days", late: true });
    expect(usualFigure(0)).toEqual({ text: "On time", late: false });
    expect(usualFigure(null)).toEqual({ text: "Not known yet", late: false });
    expect(latenessWords(2)).toEqual({ text: "2 days late", late: true });
    expect(latenessWords(0)).toEqual({ text: "on time", late: false });
    expect(latenessWords(null)).toBeNull();
  });
});

describe("The supplier list's ratings line", () => {
  const serve = (money: boolean) =>
    mockApi({
      "GET /api/prod/suppliers": makeSupplierList(
        [
          factoryRow(money),
          makeSupplierRow({ id: "trm", name: "Trims supplier", ratings: { quality: 4, timing: 3, dealing: 3.5, count: 1 }, usual_lateness_days: 0 }, money),
          makeSupplierRow({ id: "pkg", name: "Packaging supplier" }, money),
        ],
        money,
      ),
      "GET /api/prod/orders": { orders: [] },
    });

  it.each([
    ["the owner", owner, true],
    ["the QC manager", qc, false],
  ])("shows %s the averages, the usual lateness and Not rated yet", async (_who, session, money) => {
    serve(money);
    renderAt("/production/suppliers", session());
    await screen.findByRole("link", { name: "Main factory" });
    const row = (name: string) => screen.getByRole("link", { name }).closest("li")!;
    expect(row("Main factory").textContent).toContain("Quality 4.0 ★ · Timing 2.5 ★ · Dealing 4.5 ★ · usually 5 days late");
    expect(row("Trims supplier").textContent).toContain("Quality 4.0 ★ · Timing 3.0 ★ · Dealing 3.5 ★ · usually on time");
    expect(row("Packaging supplier").textContent).toContain("Not rated yet");
    expect(row("Packaging supplier").textContent).not.toContain("usually");
  });
});

describe("The supplier page's usual lateness and Orders and ratings card", () => {
  const serve = (money: boolean, over = {}) =>
    mockApi({
      "GET /api/prod/suppliers/fac": { supplier: makeSupplierPage(over, money) },
      "GET /api/prod/suppliers": makeSupplierList([], money),
      "GET /api/prod/orders": { orders: [] },
    });
  const card = () => screen.getByRole("heading", { name: "Orders and ratings", level: 2 }).closest("section")!;

  it("shows the owner each order's lateness and rejects, the stars and note, and a way to rate the unrated", async () => {
    serve(true);
    renderAt("/production/suppliers/fac", owner());
    await screen.findByRole("heading", { level: 1, name: "Main factory" });
    const orders = card();
    const rows = within(orders).getAllByRole("listitem");
    expect(rows).toHaveLength(3);

    // Open: lateness so far, and nothing to rate yet.
    expect(rows[0].textContent).toContain("PO-2611-02 · Factory · 9 of 10 · Warehouse receipt · 6 days late");
    expect(rows[0].textContent).toContain("Rate it when the order is settled");
    expect(within(rows[0]).queryByRole("link", { name: /^Rate it/ })).toBeNull();

    // Closed and not rated: the owner is taken to the order's rating panel.
    expect(rows[1].textContent).toContain("PO-2611-01 · Factory · closed 11 Nov · 2 days late · 1.2% rejected");
    const rate = within(rows[1]).getByRole("link", { name: /^Rate it/ });
    expect(rate.getAttribute("href")).toBe("/production/orders/1?open=rate");

    // Closed and rated: the stars and the note in quotes, no button.
    expect(rows[2].textContent).toContain("PO-2610-04 · Factory · closed 30 Oct · on time · 2.1% rejected");
    expect(rows[2].textContent).toContain("“Fixed the stitching problem quickly.”");
    expect(rows[2].textContent).toContain("Quality 4 ★ · Timing 5 ★ · Dealing 3 ★");
    expect(within(rows[2]).queryByRole("link", { name: /^Rate it/ })).toBeNull();
  });

  it("shows the owner the fourth figure beside the money ones", async () => {
    serve(true);
    renderAt("/production/suppliers/fac", owner());
    await screen.findByRole("heading", { level: 1, name: "Main factory" });
    const facts = document.querySelector(".prod-facts") as HTMLElement;
    const figure = within(facts).getByText("Usual lateness").nextElementSibling!;
    expect(figure.textContent).toBe("5 days");
    expect(figure.className).toContain("prod-late");
  });

  it("shows the QC manager the figure and the card, with nothing to click and no money", async () => {
    const answered = makeSupplierPage({}, false);
    serve(false);
    renderAt("/production/suppliers/fac", qc());
    await screen.findByRole("heading", { level: 1, name: "Main factory" });
    const facts = document.querySelector(".prod-facts") as HTMLElement;
    expect(within(facts).getAllByRole("term").map((term) => term.textContent)).toEqual(["Usual lateness"]);
    expect(facts.textContent).toContain("5 days");
    const orders = card();
    expect(orders.textContent).toContain("1.2% rejected");
    expect(orders.textContent).toContain("Quality 4 ★ · Timing 5 ★ · Dealing 3 ★");
    // A closed order that nobody has rated yet says so; it is not a button for this person.
    expect(orders.textContent).toContain("Not rated yet");
    expect(within(orders).queryByRole("link", { name: /^Rate it/ })).toBeNull();
    expect(within(orders).queryByRole("button")).toBeNull();
    expect(moneyKeysIn(answered)).toEqual([]);
  });

  it("says a supplier is on time, or that it is not known yet", async () => {
    serve(false, { usual_lateness_days: 0 });
    renderAt("/production/suppliers/fac", reader());
    await screen.findByRole("heading", { level: 1, name: "Main factory" });
    expect(document.querySelector(".prod-facts")!.textContent).toContain("On time");
    cleanup();
    serve(false, { usual_lateness_days: null });
    renderAt("/production/suppliers/fac", reader());
    await screen.findByRole("heading", { level: 1, name: "Main factory" });
    expect(document.querySelector(".prod-facts")!.textContent).toContain("Not known yet");
  });

  it("names the supplier's role on an order it sold materials for", async () => {
    serve(false, {
      orders: [
        { id: 7, code: "PO-2611-07", style_name: "Zip hoodie", colour: "Olive", status: "closed", role: "materials", stage: null, lateness_days: 3, closed_on: "2030-11-01", rating: null },
      ],
    });
    renderAt("/production/suppliers/fac", reader());
    await screen.findByRole("heading", { level: 1, name: "Main factory" });
    expect(card().textContent).toContain("PO-2611-07 · Materials · closed 1 Nov · 3 days late");
    expect(card().textContent).not.toContain("rejected");
  });
});

describe("The Ratings card on a closed order", () => {
  it("shows anybody who can see the order each supplier's stars and note, or Not rated yet, and no button", async () => {
    serveOrder(closedOrder(), ratingsOf([{ ...FACTORY, rating: RATED }, PRINT]));
    renderAt(ORDER, reader());
    await screen.findByRole("heading", { level: 1, name: "Oversized hoodie · Black" });
    const card = (await screen.findByRole("heading", { name: "Ratings", level: 2 })).closest("section")!;
    await waitFor(() => expect(card.textContent).toContain("Main factory"));
    const rows = within(card).getAllByRole("listitem");
    expect(rows[0].textContent).toContain("Quality 4 ★ · Timing 3 ★ · Dealing 5 ★");
    expect(rows[0].textContent).toContain("“Fixed the stitching problem quickly.”");
    expect(rows[1].textContent).toContain("Print house A");
    expect(rows[1].textContent).toContain("Not rated yet");
    expect(within(card).queryByRole("button")).toBeNull();
    expect(within(rows[0]).getByRole("link", { name: "Main factory" }).getAttribute("href")).toBe("/production/suppliers/fac");
  });

  it("is not on an open or a cancelled order", async () => {
    const calls = serveOrder(makeOrder("cutting"), ratingsOf([]));
    renderAt(ORDER, owner());
    await screen.findByRole("heading", { level: 1, name: "Oversized hoodie · Black" });
    expect(screen.queryByRole("heading", { name: "Ratings" })).toBeNull();
    expect(calls.some((call) => call.path.endsWith("/ratings"))).toBe(false);
    cleanup();
    const again = serveOrder(closedOrder("cancelled"), ratingsOf([], false));
    renderAt(ORDER, owner());
    await screen.findByRole("heading", { level: 1, name: "Oversized hoodie · Black" });
    expect(screen.queryByRole("heading", { name: "Ratings" })).toBeNull();
    expect(screen.queryByRole("button", { name: /Rate the suppliers|Change ratings/ })).toBeNull();
    expect(writes(again)).toEqual([]);
  });

  it("offers the owner Rate the suppliers while nobody is rated, and Change ratings once one is", async () => {
    serveOrder(closedOrder(), ratingsOf([FACTORY]));
    renderAt(ORDER, owner());
    expect(await screen.findByRole("button", { name: "Rate the suppliers" })).toBeTruthy();
    cleanup();
    serveOrder(closedOrder(), ratingsOf([{ ...FACTORY, rating: RATED }]));
    renderAt(ORDER, owner());
    expect(await screen.findByRole("button", { name: "Change ratings" })).toBeTruthy();
  });
});

describe("Rating the suppliers of a closed order", () => {
  /** A server that keeps what was put, so the next read answers it. */
  function keep(base: RatingTarget[]) {
    const state = { suppliers: base.map((one) => ({ ...one })) };
    const calls = serveOrder(closedOrder(), () => ratingsOf(state.suppliers), {
      "PUT /api/prod/orders/3/ratings/fac": (body: unknown) => {
        const { quality, timing, dealing, note } = body as { quality: number; timing: number; dealing: number; note: string | null };
        state.suppliers[0] = { ...state.suppliers[0], rating: { quality, timing, dealing, note, updated_at: "2030-11-13T10:00:00Z" } };
        return {};
      },
    });
    return { state, calls };
  }

  it("opens from the card with one block per supplier, timing filled in from the lateness", async () => {
    keep([FACTORY, PRINT, TRIMS]);
    renderAt(ORDER, owner());
    fireEvent.click(await screen.findByRole("button", { name: "Rate the suppliers" }));
    const panel = screen.getByRole("heading", { name: "Rate the suppliers", level: 2 }).closest("section")!;
    expect(panel.textContent).toContain("Each supplier is saved on its own.");
    const factory = await waitFor(() => formOf("Main factory"));
    expect(factory.textContent).toContain("Factory · 6 days late");
    expect(formOf("Trims supplier").textContent).toContain("Materials · on time");
    expect(formOf("Print house A").textContent).toContain("Printing");

    // Timing is filled in from the real lateness; the other two start empty; a print house with no figure has none.
    expect(checked(groupOf(factory, "Timing"))).toBe("2");
    expect(checked(groupOf(factory, "Quality"))).toBeNull();
    expect(checked(groupOf(formOf("Trims supplier"), "Timing"))).toBe("5");
    expect(checked(groupOf(formOf("Print house A"), "Timing"))).toBeNull();

    // Five real radio buttons per group, each named by its stars, and not by colour: a number is drawn too.
    const stars = within(groupOf(factory, "Quality")).getAllByRole("radio");
    expect(stars.map((radio) => radio.getAttribute("type"))).toEqual(["radio", "radio", "radio", "radio", "radio"]);
    expect(within(groupOf(factory, "Quality")).getAllByRole("radio", { name: /of 5$/ })).toHaveLength(5);
    expect(groupOf(factory, "Quality").textContent).toContain("5");
  });

  it("saves one supplier at a time, with the stars, the timing it was given and the note, and keeps the panel open", async () => {
    const { calls } = keep([FACTORY, PRINT]);
    renderAt(ORDER, owner());
    fireEvent.click(await screen.findByRole("button", { name: "Rate the suppliers" }));
    const factory = await waitFor(() => formOf("Main factory"));
    pick(factory, "Quality", 4);
    pick(factory, "Dealing", 5);
    fireEvent.change(within(factory).getByLabelText("Note (optional)"), { target: { value: "  Good, but the date moved.  " } });
    fireEvent.click(within(factory).getByRole("button", { name: "Save: Main factory" }));

    await waitFor(() => expect(writes(calls)).toHaveLength(1));
    expect(writes(calls)[0]).toMatchObject({
      method: "PUT",
      path: "/api/prod/orders/3/ratings/fac",
      body: { quality: 4, timing: 2, dealing: 5, note: "Good, but the date moved." },
    });
    expect(await within(factory).findByText("Saved.")).toBeTruthy();
    expect(screen.getByText("Main factory rated.")).toBeTruthy();
    // The panel stays for the others, and the card behind it follows.
    expect(screen.getByRole("heading", { name: "Rate the suppliers", level: 2 })).toBeTruthy();
    const card = screen.getByRole("heading", { name: "Ratings", level: 2 }).closest("section")!;
    await waitFor(() => expect(card.textContent).toContain("Quality 4 ★ · Timing 2 ★ · Dealing 5 ★"));
    expect(screen.getByRole("button", { name: "Change ratings" })).toBeTruthy();
  });

  it("asks for all three stars before sending anything", async () => {
    const { calls } = keep([FACTORY]);
    renderAt(ORDER, owner());
    fireEvent.click(await screen.findByRole("button", { name: "Rate the suppliers" }));
    const factory = await waitFor(() => formOf("Main factory"));
    pick(factory, "Quality", 3);
    fireEvent.click(within(factory).getByRole("button", { name: "Save: Main factory" }));
    expect((await within(factory).findByRole("alert")).textContent).toBe("Choose a star for quality, timing and dealing.");
    expect(writes(calls)).toEqual([]);
  });

  it("shows the server's refusal, in its own words", async () => {
    serveOrder(closedOrder(), ratingsOf([FACTORY]), {
      "PUT /api/prod/orders/3/ratings/fac": () => reply(409, { detail: "Only a settled order can be rated." }),
    });
    renderAt(ORDER, owner());
    fireEvent.click(await screen.findByRole("button", { name: "Rate the suppliers" }));
    const factory = await waitFor(() => formOf("Main factory"));
    pick(factory, "Quality", 3);
    pick(factory, "Dealing", 3);
    fireEvent.click(within(factory).getByRole("button", { name: "Save: Main factory" }));
    expect((await within(factory).findByRole("alert")).textContent).toBe("Only a settled order can be rated.");
  });

  it("changes a rating already given: the stars come back as they were, and the new ones are sent", async () => {
    const { calls } = keep([{ ...FACTORY, rating: RATED }]);
    renderAt(ORDER, owner());
    fireEvent.click(await screen.findByRole("button", { name: "Change ratings" }));
    const factory = await waitFor(() => formOf("Main factory"));
    expect(checked(groupOf(factory, "Quality"))).toBe("4");
    expect(checked(groupOf(factory, "Timing"))).toBe("3");
    expect((within(factory).getByLabelText("Note (optional)") as HTMLTextAreaElement).value).toBe("Fixed the stitching problem quickly.");
    pick(factory, "Timing", 4);
    fireEvent.click(within(factory).getByRole("button", { name: "Save: Main factory" }));
    await waitFor(() => expect(writes(calls)).toHaveLength(1));
    expect(writes(calls)[0].body).toMatchObject({ quality: 4, timing: 4, dealing: 5, note: "Fixed the stitching problem quickly." });
  });

  it("opens from `?open=rate`, which a supplier's page sends the owner to, and not for anybody else", async () => {
    keep([FACTORY]);
    renderAt(`${ORDER}?open=rate`, owner());
    expect(await screen.findByRole("heading", { name: "Rate the suppliers", level: 2 })).toBeTruthy();
    cleanup();
    serveOrder(closedOrder(), ratingsOf([FACTORY]));
    renderAt(`${ORDER}?open=rate`, qc());
    await screen.findByRole("heading", { level: 1, name: "Oversized hoodie · Black" });
    expect(screen.queryByRole("heading", { name: "Rate the suppliers", level: 2 })).toBeNull();
    expect(screen.queryByRole("button", { name: /Rate the suppliers|Change ratings/ })).toBeNull();
  });
});

describe("Settling an order offers the ratings, and they can be skipped", () => {
  function settleServer(suppliers: RatingTarget[]) {
    const settled = closedOrder();
    return serveOrder(makeOrder("settle", { money: true }), ratingsOf(suppliers), {
      "POST /api/prod/orders/3/settle": () => ({ order: settled }),
    });
  }

  async function settle() {
    renderAt(`${ORDER}?open=settle`, owner());
    const panel = (await screen.findByRole("heading", { level: 2, name: /Settle/ })).closest("section")!;
    fireEvent.click(within(panel).getByRole("button", { name: "Settle and close this order" }));
  }

  it("opens the Rate the suppliers panel right after settling, with Skip for now", async () => {
    const calls = settleServer([FACTORY, TRIMS]);
    await settle();
    const panel = (await screen.findByRole("heading", { level: 2, name: "Rate the suppliers" })).closest("section")!;
    expect(panel.textContent).toContain("The order is settled.");
    await waitFor(() => formOf("Main factory"));
    expect(checked(groupOf(formOf("Main factory"), "Timing"))).toBe("2");
    expect(screen.getByRole("status").textContent).toBe("Settled and closed.");
    expect(calls.filter((call) => call.method === "POST")).toHaveLength(1);

    fireEvent.click(within(panel).getByRole("button", { name: "Skip for now" }));
    expect(screen.queryByRole("heading", { level: 2, name: "Rate the suppliers" })).toBeNull();
    // Nothing was written, and the card can bring it back.
    expect(writes(calls).map((call) => call.method)).toEqual(["POST"]);
    expect(screen.getByRole("button", { name: "Rate the suppliers" })).toBeTruthy();
  });

  it("does not open it on a plain visit to a closed order", async () => {
    serveOrder(closedOrder(), ratingsOf([FACTORY]));
    renderAt(ORDER, owner());
    await screen.findByRole("button", { name: "Rate the suppliers" });
    expect(screen.queryByRole("heading", { level: 2, name: "Rate the suppliers" })).toBeNull();
  });
});
