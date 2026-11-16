// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { Session } from "../../../../lib/api";
import { productionNextRoutes } from "../routes";
import type { AccountLine, SupplierView } from "../types";
import { mockApi, narrowScreen, owner, qc, renderAt, reply } from "./fixtures";
import type { Call } from "./fixtures";
import { SECTIONS, factoryAccount, makeLine, makePurchase, makeSupplierList, makeSupplierPage } from "./supplierFixtures";

const ADDRESS = "/production/next/suppliers/fac";

/** A manager: may edit a supplier's details, holds no money. */
const manager = (): Session => {
  const session = qc();
  session.permissions = ["production.view", "production.edit", "production.suppliers"];
  return session;
};
/** Somebody who can only read. */
const reader = (): Session => {
  const session = qc();
  session.permissions = ["production.view"];
  return session;
};

const writes = (calls: Call[]) => calls.filter((call) => call.method !== "GET");
const type = (label: string, value: string) => fireEvent.change(screen.getByLabelText(label), { target: { value } });
const click = (name: string | RegExp) => fireEvent.click(screen.getByRole("button", { name }));
const panelOf = (name: string | RegExp): HTMLElement => screen.getByRole("heading", { name, level: 2 }).closest("section")!;
const cardOf = (name: string): HTMLElement => screen.getByRole("heading", { name, level: 2 }).closest("section")!;
const rowOf = (text: string): HTMLElement => screen.getByText(text).closest("tr")!;

/** The supplier's page as the server keeps it: `state.page` is what the next read answers. */
function serve(page: SupplierView, money: boolean, extra: Record<string, unknown> = {}) {
  const state = { page };
  const calls = mockApi({
    "GET /api/prod/suppliers/fac": () => ({ supplier: state.page }),
    "GET /api/prod/suppliers": makeSupplierList([], money, SECTIONS),
    "GET /api/prod/orders": { orders: [] },
    ...extra,
  });
  return { calls, state };
}

beforeEach(() => {
  narrowScreen(false);
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(new Date("2030-11-13T10:00:00Z"));
});
afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("A supplier's page, for the owner", () => {
  it("shows the four figures, the account, the purchases, the orders and the details", async () => {
    serve(makeSupplierPage(), true);
    renderAt(ADDRESS, owner());
    expect(await screen.findByRole("heading", { level: 1, name: "Main factory" })).toBeTruthy();
    expect(screen.getByText("Manufacturers · 1 order open · 2 purchases not received")).toBeTruthy();
    expect(screen.getByRole("link", { name: "← All suppliers" }).getAttribute("href")).toBe("/production/next/suppliers");

    // Four figures: what is owed, what is held, what was paid this year, and how late the supplier usually is.
    const facts = document.querySelector(".prod-facts")!;
    expect(within(facts as HTMLElement).getAllByRole("term").map((term) => term.textContent)).toEqual([
      "You owe now",
      "Held until pieces are fixed",
      "Paid in 2030",
      "Usual lateness",
    ]);
    expect(facts.textContent).toContain("EGP 13,399.00");
    expect(facts.textContent).toContain("EGP 3,450.00");
    expect(facts.textContent).toContain("EGP 30,000.00");
    expect(facts.textContent).toContain("5 days");
    expect(screen.getByRole("button", { name: "Record a payment" })).toBeTruthy();

    // Orders and details.
    const orders = cardOf("Orders and ratings");
    expect(within(orders).getAllByRole("link", { name: "Oversized hoodie · Black" }).map((link) => link.getAttribute("href"))).toEqual([
      "/production/next/orders/2",
      "/production/next/orders/1",
    ]);
    expect(orders.textContent).toContain("PO-2611-02 · Factory · 9 of 10 · Warehouse receipt");
    expect(orders.textContent).toContain("PO-2611-01 · Factory · closed 11 Nov");
    const details = cardOf("Details");
    expect(details.textContent).toContain("Karim");
    expect(within(details).getByRole("link", { name: "0100 111 2222" }).getAttribute("href")).toBe("tel:01001112222");
    expect(details.textContent).toContain("Manufacturers");
    // Not a manager: no edit.
    expect(screen.getByRole("button", { name: "Edit details" })).toBeTruthy();
  });

  it("draws the account newest first, with what is owed after each line, in words", async () => {
    serve(makeSupplierPage(), true);
    renderAt(ADDRESS, owner());
    await screen.findByRole("heading", { level: 1, name: "Main factory" });
    const account = cardOf("Account");
    const body = within(account).getAllByRole("row").slice(1);
    expect(body).toHaveLength(6);

    // The order not yet settled comes first, and says so in words.
    expect(body[0].textContent).toContain("Work on PO-2611-02 so far, not settled");
    expect(body[0].textContent).toContain("Worked out now. It becomes a line of its own when the order is settled.");
    expect(body[0].textContent).toContain("So far");

    // A payment: its method and kind in its words, its note, what is owed after it, and the direction in words.
    const payment = body[1];
    expect(payment.textContent).toContain("Weekly payment · InstaPay");
    expect(payment.textContent).toContain("Week 46");
    expect(payment.textContent).toContain("EGP 2,750.00");
    expect(payment.textContent).toContain("− EGP 30,000.00");
    expect(payment.textContent).toContain("takes off what you owe");
    expect(within(payment).getByRole("link", { name: /^View receipt/ }).getAttribute("href")).toBe("/api/prod/entries/6/receipt");
    expect(payment.querySelector("img")?.getAttribute("src")).toBe("/api/prod/entries/6/receipt");

    // Work adds to what is owed.
    expect(body[4].textContent).toContain("+ EGP 10,994.00");
    expect(body[4].textContent).toContain("adds to what you owe");
    // The opening balance, last.
    expect(body[5].textContent).toContain("Balance brought forward");
    expect(body[5].textContent).toContain("EGP 42,000.00");
  });

  it("strikes a reversed line through, and gives the reason on both lines", async () => {
    serve(makeSupplierPage(), true);
    renderAt(ADDRESS, owner());
    await screen.findByRole("heading", { level: 1, name: "Main factory" });
    const reversed = rowOf("Adjustment");
    expect(within(reversed).getByText("Adjustment").closest(".prod-struck")).toBeTruthy();
    expect(reversed.textContent).toContain("(reversed)");
    expect(reversed.textContent).toContain("Reversed: Counted twice");
    const reversal = rowOf("Reversal · Adjustment");
    expect(reversal.textContent).toContain("Reason: Counted twice");
    expect(within(reversal).getByText("Reversal · Adjustment").closest(".prod-struck")).toBeNull();
  });

  it("offers Reverse only where the server allows it, and the balance button only until one stands", async () => {
    serve(makeSupplierPage(), true);
    renderAt(ADDRESS, owner());
    await screen.findByRole("heading", { level: 1, name: "Main factory" });
    const account = cardOf("Account");
    // The payment and the balance brought forward; not work, not a reversal, not a line already reversed.
    expect(within(account).getAllByRole("button", { name: /^Reverse/ })).toHaveLength(2);
    expect(within(rowOf("Weekly payment · InstaPay")).getByRole("button", { name: /^Reverse/ })).toBeTruthy();
    expect(within(rowOf("Work on PO-2611-01")).queryByRole("button", { name: /^Reverse/ })).toBeNull();
    expect(within(rowOf("Reversal · Adjustment")).queryByRole("button", { name: /^Reverse/ })).toBeNull();
    expect(within(rowOf("Adjustment")).queryByRole("button", { name: /^Reverse/ })).toBeNull();
    expect(within(account).queryByRole("button", { name: "Balance brought forward" })).toBeNull();
    expect(within(account).getByRole("button", { name: "Add a correction" })).toBeTruthy();
  });

  it("shows a purchase with its price, total and deposit, and a voided one struck through with its reason", async () => {
    serve(makeSupplierPage(), true);
    renderAt(ADDRESS, owner());
    await screen.findByRole("heading", { level: 1, name: "Main factory" });
    const purchases = cardOf("Purchases");
    const fleece = within(purchases).getByText("Heavy fleece, black").closest("tr")!;
    expect(fleece.textContent).toContain("Fabric · Pick up from the mill");
    expect(fleece.textContent).toContain("1,075 kg");
    expect(fleece.textContent).toContain("PO-2611-02");
    expect(fleece.textContent).toContain("Bought 9 Nov · expected 12 Nov, 1 day late · not received yet");
    expect(fleece.textContent).toContain("EGP 172,000.00");
    expect(fleece.textContent).toContain("EGP 160.00 per kilogram");
    expect(fleece.textContent).toContain("Deposit paid EGP 40,000.00");
    expect(within(fleece).getByRole("link", { name: /PO-2611-02/ }).getAttribute("href")).toBe("/production/next/orders/2");

    const voided = within(purchases).getByText("Wrong thread").closest("tr")!;
    expect(within(voided).getByText("Wrong thread").closest(".prod-struck")).toBeTruthy();
    expect(voided.textContent).toContain("Voided: Wrong supplier");
    // A voided purchase can be changed no more.
    expect(within(voided).queryByRole("button")).toBeNull();
    expect(within(fleece).getByRole("button", { name: /^Void/ })).toBeTruthy();
  });

  it("stacks the account and the purchases on a phone", async () => {
    narrowScreen(true);
    serve(makeSupplierPage(), true);
    renderAt(ADDRESS, owner());
    await screen.findByRole("heading", { level: 1, name: "Main factory" });
    expect(screen.queryByRole("table")).toBeNull();
    const account = cardOf("Account");
    const lines = account.querySelectorAll(".prod-line");
    expect(lines).toHaveLength(6);
    expect(lines[1].textContent).toContain("You owe after this line: EGP 2,750.00");
    expect(lines[1].textContent).toContain("takes off what you owe");
    expect(cardOf("Purchases").querySelectorAll(".prod-line")).toHaveLength(3);
  });

  it("says when the supplier cannot be loaded, and tries again", async () => {
    let fail = true;
    mockApi({ "GET /api/prod/suppliers/fac": () => (fail ? reply(404, { detail: "There is no such supplier." }) : { supplier: makeSupplierPage() }) });
    renderAt(ADDRESS, owner());
    expect((await screen.findByRole("alert")).textContent).toBe("There is no such supplier.");
    fail = false;
    click("Try again");
    expect(await screen.findByRole("heading", { level: 1, name: "Main factory" })).toBeTruthy();
  });
});

describe("A supplier's page, for somebody without the owner permission", () => {
  it("shows no money and no money control anywhere, not even an empty column or a zero", async () => {
    const { calls } = serve(makeSupplierPage({}, false), false);
    renderAt(ADDRESS, qc());
    await screen.findByRole("heading", { level: 1, name: "Main factory" });

    expect(document.body.textContent).not.toMatch(/EGP|You owe|Overpaid|Nothing owed|Held until|Paid in|owe/);
    // The one figure that is not money: how late the supplier usually is.
    const facts = document.querySelector(".prod-facts")!;
    expect(within(facts as HTMLElement).getAllByRole("term").map((term) => term.textContent)).toEqual(["Usual lateness"]);
    expect(screen.queryByRole("heading", { name: "Account" })).toBeNull();
    for (const name of [/^Record a payment/, /^Record a purchase/, /^Void/, /^Reverse/, /Balance brought forward/, /Add a correction/, /receipt/i]) {
      expect(screen.queryByRole("button", { name })).toBeNull();
    }
    // The purchases: item, quantity, order, dates; no Total column.
    const purchases = cardOf("Purchases");
    expect(within(purchases).queryByRole("columnheader", { name: "Total" })).toBeNull();
    expect(within(purchases).getAllByRole("columnheader").map((cell) => cell.textContent)).toEqual(["Item", "Quantity", "Order", "Dates"]);
    const fleece = within(purchases).getByText("Heavy fleece, black").closest("tr")!;
    expect(fleece.textContent).toContain("1,075 kg");
    expect(fleece.textContent).toContain("expected 12 Nov");
    // A voided purchase is struck through, without a reason: the reason is the owner's.
    expect(within(purchases).getByText("Wrong thread").closest("tr")!.textContent).toContain("Voided");
    expect(within(purchases).getByText("Wrong thread").closest("tr")!.textContent).not.toContain("Wrong supplier");
    // What the QC manager does is there; editing the supplier is not.
    expect(within(fleece).getByRole("button", { name: /^Mark received/ })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Edit details" })).toBeNull();
    expect(writes(calls)).toEqual([]);
  });

  it("offers a manager the supplier's details to edit, and still no money", async () => {
    serve(makeSupplierPage({}, false), false);
    renderAt(ADDRESS, manager());
    await screen.findByRole("heading", { level: 1, name: "Main factory" });
    expect(screen.getByRole("button", { name: "Edit details" })).toBeTruthy();
    expect(document.body.textContent).not.toMatch(/EGP/);
  });

  it("offers somebody who can only read nothing to press", async () => {
    serve(makeSupplierPage({}, false), false);
    renderAt(ADDRESS, reader());
    await screen.findByRole("heading", { level: 1, name: "Main factory" });
    expect(screen.queryByRole("button")).toBeNull();
  });
});

describe("Record a payment", () => {
  const open = async () => {
    renderAt(ADDRESS, owner());
    await screen.findByRole("heading", { level: 1, name: "Main factory" });
    // A real click puts focus on the button first; the panel gives it back there when it saves.
    screen.getByRole("button", { name: "Record a payment" }).focus();
    click("Record a payment");
    return panelOf("Record a payment to Main factory");
  };

  it("says what the balance will be after it: what is still owed, nothing, or an overpayment", async () => {
    serve(makeSupplierPage(), true);
    const panel = await open();
    expect(panel.textContent).toContain("You owe EGP 13,399.00 now.");
    expect(within(panel).getByText("Give the amount to see what you will owe after it.")).toBeTruthy();

    type("Amount, EGP", "1,000");
    expect(within(panel).getByText("After this payment you will owe EGP 12,399.00.")).toBeTruthy();
    type("Amount, EGP", "13,399");
    expect(within(panel).getByText("After this payment you will owe nothing.")).toBeTruthy();
    type("Amount, EGP", "20,000");
    expect(within(panel).getByText("After this payment Main factory will be overpaid by EGP 6,601.00, which comes off what you owe them next.")).toBeTruthy();
    type("Amount, EGP", "30,000.50");
    expect(within(panel).getByText(/overpaid by EGP 16,601\.50/)).toBeTruthy();
  });

  it("checks the amount and the date before sending, and does not send", async () => {
    const { calls } = serve(makeSupplierPage(), true);
    const panel = await open();
    fireEvent.click(within(panel).getByRole("button", { name: "Save payment" }));
    expect((await within(panel).findByRole("alert")).textContent).toBe("Give the amount.");
    type("Amount, EGP", "0");
    fireEvent.click(within(panel).getByRole("button", { name: "Save payment" }));
    expect((await within(panel).findByRole("alert")).textContent).toBe("The amount must be more than 0.");
    type("Amount, EGP", "100");
    type("Date", "2030-11-14");
    fireEvent.click(within(panel).getByRole("button", { name: "Save payment" }));
    expect((await within(panel).findByRole("alert")).textContent).toBe("The payment date can't be in the future.");
    expect(writes(calls)).toEqual([]);
  });

  it("saves the payment, then adds the receipt photo, and draws the page the server answers with", async () => {
    const after = makeSupplierPage({ owed_piastres: 1239900, paid_piastres: 3100000 });
    const { calls } = serve(makeSupplierPage(), true, {
      "POST /api/prod/suppliers/fac/payments": () => reply(201, { supplier: after, entry_id: 12 }),
      "POST /api/prod/entries/12/receipt": () => reply(201, { supplier: after }),
    });
    const panel = await open();
    type("Amount, EGP", "1,000");
    type("Paid by", "cash");
    type("What it is", "final");
    type("Note, optional", "  Week 47 ");
    const file = new File(["x"], "receipt.png", { type: "image/png" });
    fireEvent.change(screen.getByLabelText("Receipt photo, optional"), { target: { files: [file] } });
    expect(within(panel).getByText(/receipt\.png/)).toBeTruthy();

    fireEvent.click(within(panel).getByRole("button", { name: "Save payment" }));
    await waitFor(() => expect(screen.getByRole("status").textContent).toBe("Payment recorded: EGP 1,000.00 to Main factory."));
    expect(writes(calls).map((call) => [call.method, call.path, call.body])).toEqual([
      ["POST", "/api/prod/suppliers/fac/payments", { amount_piastres: 100000, paid_on: "2030-11-13", method: "cash", kind: "final", note: "Week 47" }],
      ["POST", "/api/prod/entries/12/receipt", undefined],
    ]);
    // The page is the server's: what is owed moved, and the panel has gone.
    expect(document.querySelector(".prod-facts")!.textContent).toContain("EGP 12,399.00");
    expect(screen.queryByRole("heading", { name: "Record a payment to Main factory" })).toBeNull();
    // Focus is back on the button that opened the panel.
    expect(document.activeElement).toBe(screen.getByRole("button", { name: "Record a payment" }));
  });

  it("does not call a saved payment failed when only its receipt could not be added", async () => {
    const after = makeSupplierPage({ owed_piastres: 1239900 });
    const { calls } = serve(makeSupplierPage(), true, {
      "POST /api/prod/suppliers/fac/payments": () => reply(201, { supplier: after, entry_id: 12 }),
      "POST /api/prod/entries/12/receipt": () => reply(503, { detail: "The receipt couldn't be saved. Try again." }),
    });
    const panel = await open();
    type("Amount, EGP", "1,000");
    fireEvent.change(screen.getByLabelText("Receipt photo, optional"), { target: { files: [new File(["x"], "r.png", { type: "image/png" })] } });
    fireEvent.click(within(panel).getByRole("button", { name: "Save payment" }));
    await waitFor(() => expect(screen.getByRole("status").textContent).toContain("Payment recorded, but the receipt photo could not be added."));
    expect(screen.getByRole("status").textContent).toContain("The receipt couldn't be saved. Try again. Add it from the account.");
    // The payment was sent once, so there is no second one to be made by pressing Save again.
    expect(writes(calls).filter((call) => call.path.endsWith("/payments"))).toHaveLength(1);
    expect(document.querySelector(".prod-facts")!.textContent).toContain("EGP 12,399.00");
  });

  it("shows the server's refusal as it is and keeps what was typed", async () => {
    serve(makeSupplierPage(), true, { "POST /api/prod/suppliers/fac/payments": () => reply(422, { detail: "The amount is too large. Check the number." }) });
    const panel = await open();
    type("Amount, EGP", "5,000");
    fireEvent.click(within(panel).getByRole("button", { name: "Save payment" }));
    expect((await within(panel).findByRole("alert")).textContent).toBe("The amount is too large. Check the number.");
    expect((screen.getByLabelText("Amount, EGP") as HTMLInputElement).value).toBe("5,000");
  });
});

describe("The balance brought forward and a correction", () => {
  it("records the balance once, as an amount and who owes whom, with what it makes you owe", async () => {
    const page = makeSupplierPage({ has_opening: false, account: [], owed_piastres: 0 });
    const { calls } = serve(page, true, { "POST /api/prod/suppliers/fac/opening": () => reply(201, { supplier: makeSupplierPage(), entry_id: 1 }) });
    renderAt(ADDRESS, owner());
    await screen.findByRole("heading", { level: 1, name: "Main factory" });
    expect(screen.getByText("Nothing on the account yet.")).toBeTruthy();

    click("Balance brought forward");
    const panel = panelOf("Balance brought forward");
    type("Amount, EGP", "42,000");
    expect(within(panel).getByText("After this you will owe EGP 42,000.00.")).toBeTruthy();
    type("Who owes whom", "less");
    expect(within(panel).getByText("After this you will have overpaid by EGP 42,000.00.")).toBeTruthy();
    type("Who owes whom", "more");
    type("Date", "2030-10-06");
    type("Note, optional", "From the notebook");
    fireEvent.click(within(panel).getByRole("button", { name: "Save the balance" }));
    await waitFor(() => expect(screen.getByRole("status").textContent).toBe("Balance brought forward recorded."));
    expect(writes(calls).map((call) => [call.method, call.path, call.body])).toEqual([
      ["POST", "/api/prod/suppliers/fac/opening", { amount_piastres: 4200000, happened_on: "2030-10-06", note: "From the notebook" }],
    ]);
  });

  it("will not record a correction without saying why, and sends the direction as a sign", async () => {
    const { calls } = serve(makeSupplierPage(), true, { "POST /api/prod/suppliers/fac/adjustments": () => reply(201, { supplier: makeSupplierPage(), entry_id: 13 }) });
    renderAt(ADDRESS, owner());
    await screen.findByRole("heading", { level: 1, name: "Main factory" });
    click("Add a correction");
    const panel = panelOf("Add a correction");
    type("Amount, EGP", "100");
    type("Effect on the account", "less");
    fireEvent.click(within(panel).getByRole("button", { name: "Save the correction" }));
    expect((await within(panel).findByRole("alert")).textContent).toBe("Say why: the note is kept with the line.");
    expect(writes(calls)).toEqual([]);

    type("Why, required", "Counted twice");
    fireEvent.click(within(panel).getByRole("button", { name: "Save the correction" }));
    await waitFor(() => expect(screen.getByRole("status").textContent).toBe("Correction recorded."));
    expect(writes(calls).map((call) => [call.method, call.path, call.body])).toEqual([
      ["POST", "/api/prod/suppliers/fac/adjustments", { amount_piastres: -10000, happened_on: "2030-11-13", note: "Counted twice" }],
    ]);
  });
});

describe("Reversing a line and voiding a purchase", () => {
  it("will not reverse a line without a reason, and sends it with one", async () => {
    const { calls } = serve(makeSupplierPage(), true, { "POST /api/prod/entries/6/reverse": () => reply(200, { supplier: makeSupplierPage({ owed_piastres: 4339900 }), entry_id: 14 }) });
    renderAt(ADDRESS, owner());
    await screen.findByRole("heading", { level: 1, name: "Main factory" });
    fireEvent.click(within(rowOf("Weekly payment · InstaPay")).getByRole("button", { name: /^Reverse/ }));
    const panel = panelOf("Reverse: Weekly payment · InstaPay");

    fireEvent.click(within(panel).getByRole("button", { name: "Reverse this line" }));
    expect((await within(panel).findByRole("alert")).textContent).toBe("Say why you are reversing it.");
    type("Why, required", "   ");
    fireEvent.click(within(panel).getByRole("button", { name: "Reverse this line" }));
    expect((await within(panel).findByRole("alert")).textContent).toBe("Say why you are reversing it.");
    expect(writes(calls)).toEqual([]);

    type("Why, required", " Paid twice ");
    fireEvent.click(within(panel).getByRole("button", { name: "Reverse this line" }));
    await waitFor(() => expect(screen.getByRole("status").textContent).toBe("Line reversed."));
    expect(writes(calls).map((call) => [call.method, call.path, call.body])).toEqual([["POST", "/api/prod/entries/6/reverse", { reason: "Paid twice" }]]);
    expect(document.querySelector(".prod-facts")!.textContent).toContain("EGP 43,399.00");
  });

  it("keeps the line when the person says keep it", async () => {
    const { calls } = serve(makeSupplierPage(), true);
    renderAt(ADDRESS, owner());
    await screen.findByRole("heading", { level: 1, name: "Main factory" });
    fireEvent.click(within(rowOf("Weekly payment · InstaPay")).getByRole("button", { name: /^Reverse/ }));
    click("Keep it");
    expect(screen.queryByRole("heading", { name: /^Reverse:/ })).toBeNull();
    expect(writes(calls)).toEqual([]);
  });

  it("will not void a purchase without a reason, and then shows it struck through with the reason", async () => {
    const voidedPage = makeSupplierPage({
      purchases: [
        makePurchase({ id: 3, item: "Wrong thread", voided: true, void_reason: "Wrong supplier" }),
        makePurchase({ id: 2, item: "Zips", voided: true, void_reason: "Ordered twice", expected_on: "2030-11-19" }),
        makePurchase({ id: 1 }),
      ],
    });
    const { calls } = serve(makeSupplierPage(), true, { "POST /api/prod/purchases/2/void": () => reply(200, { supplier: voidedPage }) });
    renderAt(ADDRESS, owner());
    await screen.findByRole("heading", { level: 1, name: "Main factory" });
    fireEvent.click(screen.getByRole("button", { name: "Void: Zips" }));
    const panel = panelOf("Void the Zips purchase");

    fireEvent.click(within(panel).getByRole("button", { name: "Void this purchase" }));
    expect((await within(panel).findByRole("alert")).textContent).toBe("Say why you are voiding it.");
    expect(writes(calls)).toEqual([]);

    type("Why, required", "Ordered twice");
    fireEvent.click(within(panel).getByRole("button", { name: "Void this purchase" }));
    await waitFor(() => expect(screen.getByRole("status").textContent).toBe("Purchase voided: Zips."));
    expect(writes(calls).map((call) => [call.method, call.path, call.body])).toEqual([["POST", "/api/prod/purchases/2/void", { reason: "Ordered twice" }]]);
    const zips = within(cardOf("Purchases")).getByText("Zips").closest("tr")!;
    expect(within(zips).getByText("Zips").closest(".prod-struck")).toBeTruthy();
    expect(zips.textContent).toContain("Voided: Ordered twice");
    expect(within(zips).queryByRole("button")).toBeNull();
  });
});

describe("Marking a purchase received", () => {
  const received = (): SupplierView =>
    makeSupplierPage(
      {
        purchases: [
          makePurchase({ id: 3, item: "Wrong thread", voided: true }, false),
          makePurchase({ id: 2, item: "Zips", expected_on: "2030-11-19" }, false),
          makePurchase({ id: 1, received_on: "2030-11-13" }, false),
        ],
        open_purchases: 1,
      },
      false,
    );

  it("lets the QC manager mark it received today, with no money in the answer", async () => {
    const { calls } = serve(makeSupplierPage({}, false), false, { "PATCH /api/prod/purchases/1": () => ({ supplier: received() }) });
    renderAt(ADDRESS, qc());
    await screen.findByRole("heading", { level: 1, name: "Main factory" });
    const fleece = within(cardOf("Purchases")).getByText("Heavy fleece, black").closest("tr")!;
    fireEvent.click(within(fleece).getByRole("button", { name: /^Mark received/ }));
    const panel = panelOf("Mark Heavy fleece, black received");
    expect(panel.textContent).toContain("Expected 12 Nov. Say the day it really arrived.");
    expect((screen.getByLabelText("Arrived on") as HTMLInputElement).value).toBe("2030-11-13");

    fireEvent.click(within(panel).getByRole("button", { name: "Mark received" }));
    await waitFor(() => expect(screen.getByRole("status").textContent).toBe("Heavy fleece, black marked as received."));
    // Only the date is sent: nothing of money, and nothing else of the purchase.
    expect(writes(calls).map((call) => [call.method, call.path, call.body])).toEqual([["PATCH", "/api/prod/purchases/1", { received_on: "2030-11-13" }]]);
    const row = within(cardOf("Purchases")).getByText("Heavy fleece, black").closest("tr")!;
    expect(row.textContent).toContain("received 13 Nov");
    expect(within(row).queryByRole("button", { name: /^Mark received/ })).toBeNull();
    expect(within(row).getByRole("button", { name: /^Change arrival date/ })).toBeTruthy();
    expect(document.body.textContent).not.toMatch(/EGP/);
  });

  it("refuses a day in the future before sending", async () => {
    const { calls } = serve(makeSupplierPage({}, false), false);
    renderAt(ADDRESS, qc());
    await screen.findByRole("heading", { level: 1, name: "Main factory" });
    const fleece = within(cardOf("Purchases")).getByText("Heavy fleece, black").closest("tr")!;
    fireEvent.click(within(fleece).getByRole("button", { name: /^Mark received/ }));
    type("Arrived on", "2030-11-14");
    fireEvent.click(screen.getByRole("button", { name: "Mark received" }));
    expect((await screen.findByRole("alert")).textContent).toBe("The date it arrived can't be in the future.");
    expect(writes(calls)).toEqual([]);
  });

  it("changes the expected date, or clears it", async () => {
    const { calls } = serve(makeSupplierPage({}, false), false, { "PATCH /api/prod/purchases/1": () => ({ supplier: makeSupplierPage({}, false) }) });
    renderAt(ADDRESS, qc());
    await screen.findByRole("heading", { level: 1, name: "Main factory" });
    const fleece = () => within(cardOf("Purchases")).getByText("Heavy fleece, black").closest("tr")!;
    fireEvent.click(within(fleece()).getByRole("button", { name: /^Change expected date/ }));
    type("Expected on", "2030-11-20");
    fireEvent.click(screen.getByRole("button", { name: "Save the date" }));
    await waitFor(() => expect(screen.getByRole("status").textContent).toBe("Heavy fleece, black is now expected 20 Nov."));

    fireEvent.click(within(fleece()).getByRole("button", { name: /^Change expected date/ }));
    type("Expected on", "");
    fireEvent.click(screen.getByRole("button", { name: "Save the date" }));
    await waitFor(() => expect(screen.getByRole("status").textContent).toBe("Heavy fleece, black no longer has an expected date."));
    expect(writes(calls).map((call) => call.body)).toEqual([{ expected_on: "2030-11-20" }, { expected_on: null }]);
  });

  it("shows the server's refusal when a purchase was voided meanwhile", async () => {
    serve(makeSupplierPage({}, false), false, { "PATCH /api/prod/purchases/1": () => reply(409, { detail: "This purchase was voided. Nothing on it can change now." }) });
    renderAt(ADDRESS, qc());
    await screen.findByRole("heading", { level: 1, name: "Main factory" });
    fireEvent.click(within(within(cardOf("Purchases")).getByText("Heavy fleece, black").closest("tr")!).getByRole("button", { name: /^Mark received/ }));
    fireEvent.click(screen.getByRole("button", { name: "Mark received" }));
    expect((await screen.findByRole("alert")).textContent).toBe("This purchase was voided. Nothing on it can change now.");
  });

  it("can take an arrival back", async () => {
    const page = makeSupplierPage({ purchases: [makePurchase({ id: 1, received_on: "2030-11-12" }, false)] }, false);
    const { calls } = serve(page, false, { "PATCH /api/prod/purchases/1": () => ({ supplier: makeSupplierPage({}, false) }) });
    renderAt(ADDRESS, qc());
    await screen.findByRole("heading", { level: 1, name: "Main factory" });
    fireEvent.click(screen.getByRole("button", { name: /^Change arrival date/ }));
    expect((screen.getByLabelText("Arrived on") as HTMLInputElement).value).toBe("2030-11-12");
    click("Not arrived after all");
    await waitFor(() => expect(screen.getByRole("status").textContent).toBe("Heavy fleece, black is marked as not received yet."));
    expect(writes(calls).map((call) => call.body)).toEqual([{ received_on: null }]);
  });
});

describe("A form opened from a task (`?open=purchase:<id>`)", () => {
  function renderWith(address: string, session: Session) {
    function Where() {
      const location = useLocation();
      return <output data-testid="where">{location.pathname + location.search}</output>;
    }
    render(
      <MemoryRouter initialEntries={[address]}>
        <Routes>
          <Route path="/production">{productionNextRoutes(session)}</Route>
        </Routes>
        <Where />
      </MemoryRouter>,
    );
  }
  const where = () => screen.getByTestId("where").textContent;
  const panel = () => document.querySelector(".prod-panel");

  it("opens that purchase's Mark received once the supplier has loaded, and clears the address", async () => {
    serve(makeSupplierPage({}, false), false);
    renderWith(`${ADDRESS}?open=purchase:1`, qc());
    expect(await screen.findByRole("heading", { level: 2, name: "Mark Heavy fleece, black received" })).toBeTruthy();
    expect(where()).toBe(ADDRESS);
    // The panel has focus, as when a button opened it.
    await waitFor(() => expect(document.activeElement?.textContent).toBe("Mark Heavy fleece, black received"));
  });

  it("opens it once: closing it does not bring it back, and an ordinary visit opens nothing", async () => {
    serve(makeSupplierPage({}, false), false);
    renderWith(`${ADDRESS}?open=purchase:1`, qc());
    await screen.findByRole("heading", { level: 2, name: "Mark Heavy fleece, black received" });
    click("Close");
    expect(panel()).toBeNull();
    await new Promise((resolve) => setTimeout(resolve, 20));
    expect(panel()).toBeNull();
    cleanup();

    serve(makeSupplierPage({}, false), false);
    renderWith(ADDRESS, qc());
    await screen.findByRole("heading", { level: 1, name: "Main factory" });
    expect(panel()).toBeNull();
  });

  it("opens nothing for somebody who may not mark it, a voided or received purchase, or an unknown one, but still clears the address", async () => {
    serve(makeSupplierPage({}, false), false);
    renderWith(`${ADDRESS}?open=purchase:1`, reader());
    await screen.findByRole("heading", { level: 1, name: "Main factory" });
    expect(panel()).toBeNull();
    expect(where()).toBe(ADDRESS);
    cleanup();

    for (const open of ["purchase:3", "purchase:99", "nonsense"]) {
      serve(makeSupplierPage({}, false), false);
      renderWith(`${ADDRESS}?open=${open}`, qc());
      await screen.findByRole("heading", { level: 1, name: "Main factory" });
      expect(panel()).toBeNull();
      expect(where()).toBe(ADDRESS);
      cleanup();
    }
  });

  it("works for the owner too, with money drawn for the owner only", async () => {
    serve(makeSupplierPage(), true);
    renderWith(`${ADDRESS}?open=purchase:2`, owner());
    expect(await screen.findByRole("heading", { level: 2, name: "Mark Zips received" })).toBeTruthy();
  });
});

describe("A payment's receipt photo", () => {
  const withoutReceipt = (): AccountLine[] =>
    factoryAccount().map((line) => (line.id === 6 ? { ...line, receipt: null } : line));

  it("adds one to a payment that has none, and then it can be viewed", async () => {
    const after = makeSupplierPage();
    const { calls } = serve(makeSupplierPage({ account: withoutReceipt() }), true, { "POST /api/prod/entries/6/receipt": () => reply(201, { supplier: after }) });
    renderAt(ADDRESS, owner());
    await screen.findByRole("heading", { level: 1, name: "Main factory" });
    const payment = rowOf("Weekly payment · InstaPay");
    expect(within(payment).queryByRole("link", { name: /^View receipt/ })).toBeNull();

    fireEvent.click(within(payment).getByRole("button", { name: /^Add receipt/ }));
    fireEvent.change(screen.getByLabelText("Choose a receipt photo or PDF"), { target: { files: [new File(["x"], "r.png", { type: "image/png" })] } });
    await waitFor(() => expect(screen.getByRole("status").textContent).toBe("Receipt added."));
    expect(writes(calls).map((call) => [call.method, call.path])).toEqual([["POST", "/api/prod/entries/6/receipt"]]);
    expect(within(rowOf("Weekly payment · InstaPay")).getByRole("link", { name: /^View receipt/ })).toBeTruthy();
    // Focus goes to the page, where the notice is read.
    expect(document.activeElement).toBe(screen.getByRole("heading", { level: 1, name: "Main factory" }));
  });

  it("replaces one, and refuses a file that is too large before sending", async () => {
    const { calls } = serve(makeSupplierPage(), true, { "POST /api/prod/entries/6/receipt": () => reply(201, { supplier: makeSupplierPage() }) });
    renderAt(ADDRESS, owner());
    await screen.findByRole("heading", { level: 1, name: "Main factory" });
    fireEvent.click(within(rowOf("Weekly payment · InstaPay")).getByRole("button", { name: /^Replace receipt/ }));
    const big = new File(["x"], "big.png", { type: "image/png" });
    Object.defineProperty(big, "size", { value: 21 * 1024 * 1024 });
    fireEvent.change(screen.getByLabelText("Choose a receipt photo or PDF"), { target: { files: [big] } });
    expect((await screen.findByRole("alert")).textContent).toBe("Files must be 20 MB or smaller.");
    expect(writes(calls)).toEqual([]);

    fireEvent.click(within(rowOf("Weekly payment · InstaPay")).getByRole("button", { name: /^Replace receipt/ }));
    fireEvent.change(screen.getByLabelText("Choose a receipt photo or PDF"), { target: { files: [new File(["x"], "ok.png", { type: "image/png" })] } });
    await waitFor(() => expect(screen.getByRole("status").textContent).toBe("Receipt replaced."));
  });

  it("removes one only after asking", async () => {
    const after = makeSupplierPage({ account: withoutReceipt() });
    const { calls } = serve(makeSupplierPage(), true, { "DELETE /api/prod/entries/6/receipt": () => ({ supplier: after }) });
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(false);
    renderAt(ADDRESS, owner());
    await screen.findByRole("heading", { level: 1, name: "Main factory" });

    fireEvent.click(within(rowOf("Weekly payment · InstaPay")).getByRole("button", { name: /^Remove receipt/ }));
    expect(confirm).toHaveBeenCalledWith("Remove the receipt photo from this payment?");
    expect(writes(calls)).toEqual([]);

    confirm.mockReturnValue(true);
    fireEvent.click(within(rowOf("Weekly payment · InstaPay")).getByRole("button", { name: /^Remove receipt/ }));
    await waitFor(() => expect(screen.getByRole("status").textContent).toBe("Receipt removed."));
    expect(writes(calls).map((call) => [call.method, call.path])).toEqual([["DELETE", "/api/prod/entries/6/receipt"]]);
    expect(within(rowOf("Weekly payment · InstaPay")).queryByRole("link", { name: /^View receipt/ })).toBeNull();
    expect(within(rowOf("Weekly payment · InstaPay")).getByRole("button", { name: /^Add receipt/ })).toBeTruthy();
  });

  it("shows the server's refusal", async () => {
    serve(makeSupplierPage(), true, { "DELETE /api/prod/entries/6/receipt": () => reply(404, { detail: "That payment has no receipt." }) });
    vi.spyOn(window, "confirm").mockReturnValue(true);
    renderAt(ADDRESS, owner());
    await screen.findByRole("heading", { level: 1, name: "Main factory" });
    fireEvent.click(within(rowOf("Weekly payment · InstaPay")).getByRole("button", { name: /^Remove receipt/ }));
    expect((await screen.findByRole("alert")).textContent).toBe("That payment has no receipt.");
  });

  it("offers no receipt on a line that is not a payment, nor one that was reversed", async () => {
    const account = [
      makeLine({ id: 9, what: "Weekly payment · cash", amount_piastres: -100, reversed: true, reversed_by_id: 10 }),
      makeLine({ id: 10, what: "Reversal · Weekly payment · cash", amount_piastres: 100, reversal: true, reverses_id: 9, note: "Paid twice" }),
      makeLine({ id: 11, kind: "adjustment", what: "Adjustment", amount_piastres: 100, note: "x" }),
    ];
    serve(makeSupplierPage({ account }), true);
    renderAt(ADDRESS, owner());
    await screen.findByRole("heading", { level: 1, name: "Main factory" });
    expect(within(cardOf("Account")).queryByRole("button", { name: /receipt/i })).toBeNull();
  });
});

describe("Editing the supplier's details", () => {
  it("saves them with the sections, and can make the supplier inactive", async () => {
    const after = makeSupplierPage({ active: false, city: "Giza", sections: [{ id: 7, name: "Fabric" }] }, false);
    const { calls } = serve(makeSupplierPage({}, false), false, { "PATCH /api/prod/suppliers/fac": () => ({ supplier: after }) });
    renderAt(ADDRESS, manager());
    await screen.findByRole("heading", { level: 1, name: "Main factory" });
    click("Edit details");
    const panel = panelOf("Edit Main factory");
    await within(panel).findByRole("checkbox", { name: "Manufacturers" });
    expect((within(panel).getByRole("checkbox", { name: "Manufacturers" }) as HTMLInputElement).checked).toBe(true);
    expect((screen.getByLabelText("Name") as HTMLInputElement).value).toBe("Main factory");

    type("City, optional", "Giza");
    fireEvent.click(within(panel).getByRole("checkbox", { name: "Manufacturers" }));
    fireEvent.click(within(panel).getByRole("checkbox", { name: "Fabric" }));
    fireEvent.click(within(panel).getByRole("checkbox", { name: /^Active/ }));
    fireEvent.click(within(panel).getByRole("button", { name: "Save changes" }));

    await waitFor(() => expect(screen.getByRole("status").textContent).toBe("Main factory saved."));
    expect(writes(calls).map((call) => [call.method, call.path, call.body])).toEqual([
      [
        "PATCH",
        "/api/prod/suppliers/fac",
        { name: "Main factory", contact_person: "Karim", phone: "0100 111 2222", whatsapp: null, city: "Giza", notes: "Pays by InstaPay", section_ids: [7], active: false },
      ],
    ]);
    expect(screen.getByText(/· Inactive/)).toBeTruthy();
  });

  it("does not offer a purchase from a supplier that is not active", async () => {
    serve(makeSupplierPage({ active: false }), true);
    renderAt(ADDRESS, owner());
    await screen.findByRole("heading", { level: 1, name: "Main factory" });
    expect(within(cardOf("Purchases")).queryByRole("button", { name: "Record a purchase" })).toBeNull();
  });
});

describe("Record a purchase, from a supplier's page", () => {
  it("is for this supplier, so it does not ask for one, and reads the new page the server answers with", async () => {
    const after = makeSupplierPage({ open_purchases: 3 });
    const { calls } = serve(makeSupplierPage(), true, { "POST /api/prod/suppliers/fac/purchases": () => reply(201, { supplier: after, purchase_id: 4 }) });
    renderAt(ADDRESS, owner());
    await screen.findByRole("heading", { level: 1, name: "Main factory" });
    fireEvent.click(within(cardOf("Purchases")).getByRole("button", { name: "Record a purchase" }));
    const panel = panelOf("Record a purchase from Main factory");
    expect(within(panel).queryByLabelText("Supplier")).toBeNull();
    type("What was bought", "Labels");
    type("Quantity", "500");
    type("Measured in", "piece");
    type("Price per piece, EGP", "2.50");
    expect(within(panel).getByText(/^Total EGP 1,250\.00\./)).toBeTruthy();
    fireEvent.click(within(panel).getByRole("button", { name: "Save purchase" }));
    await waitFor(() => expect(screen.getByRole("status").textContent).toBe("Purchase recorded: Labels from Main factory."));
    expect(writes(calls)[0].body).toMatchObject({ item: "Labels", quantity: "500", unit: "piece", unit_price_piastres: 250 });
    expect(screen.getByText("Manufacturers · 1 order open · 3 purchases not received")).toBeTruthy();
  });
});

describe("Voiding a purchase that has a deposit asks what became of the deposit", () => {
  // Built as recommended on 15 November 2026, awaiting the owner's confirmation.
  const fleece = (): HTMLElement => {
    fireEvent.click(screen.getByRole("button", { name: "Void: Heavy fleece, black" }));
    return panelOf("Void the Heavy fleece, black purchase");
  };

  it("shows the question with neither answer chosen, and will not send until one is", async () => {
    const { calls } = serve(makeSupplierPage(), true);
    renderAt(ADDRESS, owner());
    await screen.findByRole("heading", { level: 1, name: "Main factory" });
    const panel = fleece();
    expect(within(panel).getByText("What became of the EGP 40,000.00 deposit?")).toBeTruthy();
    const returned = within(panel).getByRole("radio", { name: "The supplier returned the deposit" }) as HTMLInputElement;
    const kept = within(panel).getByRole("radio", { name: "The supplier keeps the deposit as credit" }) as HTMLInputElement;
    expect(returned.checked).toBe(false);
    expect(kept.checked).toBe(false);
    expect(within(panel).getByText("Choose one to see what the account will show.")).toBeTruthy();

    type("Why, required", "Wrong supplier");
    fireEvent.click(within(panel).getByRole("button", { name: "Void this purchase" }));
    expect((await within(panel).findByRole("alert")).textContent).toBe("Say whether the supplier returned the deposit.");
    expect(writes(calls)).toEqual([]);
  });

  it("says what the account will show after each answer, and sends the answer", async () => {
    const { calls } = serve(makeSupplierPage(), true, { "POST /api/prod/purchases/1/void": () => reply(200, { supplier: makeSupplierPage() }) });
    renderAt(ADDRESS, owner());
    await screen.findByRole("heading", { level: 1, name: "Main factory" });
    const panel = fleece();
    fireEvent.click(within(panel).getByRole("radio", { name: "The supplier returned the deposit" }));
    expect(within(panel).getByText("The purchase and the deposit are both reversed, so the account shows neither of them any more.")).toBeTruthy();
    fireEvent.click(within(panel).getByRole("radio", { name: "The supplier keeps the deposit as credit" }));
    expect(panel.textContent).toContain("Only the purchase is reversed. The EGP 40,000.00 deposit stays on the account as credit with Main factory");
    expect(panel.textContent).toContain("Overpaid");

    type("Why, required", " Wrong supplier ");
    fireEvent.click(within(panel).getByRole("button", { name: "Void this purchase" }));
    await waitFor(() => expect(screen.getByRole("status").textContent).toBe("Purchase voided: Heavy fleece, black."));
    expect(writes(calls).map((call) => [call.method, call.path, call.body])).toEqual([
      ["POST", "/api/prod/purchases/1/void", { reason: "Wrong supplier", deposit_returned: false }],
    ]);
  });

  it("sends true when the supplier returned it", async () => {
    const { calls } = serve(makeSupplierPage(), true, { "POST /api/prod/purchases/1/void": () => reply(200, { supplier: makeSupplierPage() }) });
    renderAt(ADDRESS, owner());
    await screen.findByRole("heading", { level: 1, name: "Main factory" });
    const panel = fleece();
    fireEvent.click(within(panel).getByRole("radio", { name: "The supplier returned the deposit" }));
    type("Why, required", "Typo");
    fireEvent.click(within(panel).getByRole("button", { name: "Void this purchase" }));
    await waitFor(() => expect(writes(calls)).toHaveLength(1));
    expect(writes(calls)[0].body).toEqual({ reason: "Typo", deposit_returned: true });
  });

  it("asks nothing when there is no deposit, and sends no answer", async () => {
    const { calls } = serve(makeSupplierPage(), true, { "POST /api/prod/purchases/2/void": () => reply(200, { supplier: makeSupplierPage() }) });
    renderAt(ADDRESS, owner());
    await screen.findByRole("heading", { level: 1, name: "Main factory" });
    fireEvent.click(screen.getByRole("button", { name: "Void: Zips" }));
    const panel = panelOf("Void the Zips purchase");
    expect(within(panel).queryByRole("radio")).toBeNull();
    expect(panel.textContent).not.toContain("deposit");
    type("Why, required", "Ordered twice");
    fireEvent.click(within(panel).getByRole("button", { name: "Void this purchase" }));
    await waitFor(() => expect(writes(calls)).toHaveLength(1));
    expect(writes(calls)[0].body).toEqual({ reason: "Ordered twice" });
  });

  it("shows a voided purchase whose deposit was kept as credit", async () => {
    const page = makeSupplierPage({
      purchases: [makePurchase({ id: 1, voided: true, voided_at: "2030-11-12T09:00:00Z", void_reason: "Wrong supplier", deposit_piastres: 4000000, deposit_kept: true })],
    });
    serve(page, true);
    renderAt(ADDRESS, owner());
    await screen.findByRole("heading", { level: 1, name: "Main factory" });
    const row = within(cardOf("Purchases")).getByText("Heavy fleece, black").closest("tr")!;
    expect(row.textContent).toContain("Deposit kept as credit EGP 40,000.00");
    expect(row.textContent).not.toContain("Deposit paid");
  });
});

describe("Saving twice by accident", () => {
  it("sends one payment however many times Save is pressed while it is in flight, and shows the server's refusal as it comes", async () => {
    let answer: (value: Response) => void = () => {};
    const slow = new Promise<Response>((resolve) => (answer = resolve));
    const { calls } = serve(makeSupplierPage(), true, { "POST /api/prod/suppliers/fac/payments": () => slow });
    renderAt(ADDRESS, owner());
    await screen.findByRole("heading", { level: 1, name: "Main factory" });
    click("Record a payment");
    const panel = panelOf("Record a payment to Main factory");
    type("Amount, EGP", "1,000");
    const save = within(panel).getByRole("button", { name: "Save payment" }) as HTMLButtonElement;
    fireEvent.click(save);
    fireEvent.click(save);
    fireEvent.submit(save.closest("form")!);
    await waitFor(() => expect((within(panel).getByRole("button", { name: "Saving…" }) as HTMLButtonElement).disabled).toBe(true));
    expect(writes(calls)).toHaveLength(1);

    const twice = "This looks like the same payment recorded twice. Wait a minute if it really is a second one.";
    answer(reply(409, { detail: twice }));
    expect((await within(panel).findByRole("alert")).textContent).toBe(twice);
    // Refused: the form is back, and nothing more was sent.
    expect((within(panel).getByRole("button", { name: "Save payment" }) as HTMLButtonElement).disabled).toBe(false);
    expect(writes(calls)).toHaveLength(1);
  });
});

describe("Dates a money entry cannot have", () => {
  it("stops a payment dated more than a year back before sending it", async () => {
    const { calls } = serve(makeSupplierPage(), true);
    renderAt(ADDRESS, owner());
    await screen.findByRole("heading", { level: 1, name: "Main factory" });
    click("Record a payment");
    const panel = panelOf("Record a payment to Main factory");
    type("Amount, EGP", "100");
    expect((screen.getByLabelText("Date") as HTMLInputElement).min).toBe("2029-11-12");
    type("Date", "2029-11-11");
    fireEvent.click(within(panel).getByRole("button", { name: "Save payment" }));
    expect((await within(panel).findByRole("alert")).textContent).toBe("The payment date can't be more than a year ago. Check the date.");
    expect(writes(calls)).toEqual([]);
  });

  it("will not mark a purchase received before the day it was bought", async () => {
    const { calls } = serve(makeSupplierPage(), true);
    renderAt(ADDRESS, owner());
    await screen.findByRole("heading", { level: 1, name: "Main factory" });
    fireEvent.click(screen.getByRole("button", { name: "Mark received: Zips" }));
    const panel = panelOf("Mark Zips received");
    expect((screen.getByLabelText("Arrived on") as HTMLInputElement).min).toBe("2030-11-09");
    type("Arrived on", "2030-11-08");
    fireEvent.click(within(panel).getByRole("button", { name: "Mark received" }));
    expect((await within(panel).findByRole("alert")).textContent).toMatch(/^The date it arrived can't be before the day it was bought, /);
    expect(writes(calls)).toEqual([]);
  });
});
