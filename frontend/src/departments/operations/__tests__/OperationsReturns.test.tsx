// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { OperationsKhazenly } from "../OperationsKhazenly";
import { DEFAULT_FOLDS, OperationsReturns, matches, sortRefunds } from "../OperationsReturns";
import type { Refund, ReturnsTab } from "../OperationsReturns";

const reply = (status: number, body: unknown) =>
  Promise.resolve({
    ok: status < 400,
    status,
    headers: { get: () => "application/json" },
    json: () => Promise.resolve(body),
    text: () => Promise.resolve(JSON.stringify(body)),
  } as unknown as Response);

const minutesAgo = (minutes: number) => new Date(Date.now() - minutes * 60_000).toISOString();

function refund(extra: Partial<Refund>): Refund {
  return {
    id: 1,
    khazenly_number: "KH-HBA-08997921",
    kind: "return",
    merchant_order: "#31876-RE",
    order_number: "#31876",
    customer_name: "Khaled Magdy",
    customer_phone: "01060910507",
    amount: "395.00",
    method: "instapay",
    refund_to: "01060910507",
    step: "Return Completed",
    step_at: minutesAgo(90),
    timeline: [
      { step: "Return Completed", at: minutesAgo(90), note: "shipment Delivered" },
      { step: "New Return", at: minutesAgo(3000), note: null },
    ],
    received_at: minutesAgo(90),
    checked_at: minutesAgo(5),
    check_error: null,
    paid_on: null,
    paid_by: null,
    paid_early: false,
    proof_url: null,
    created_at: minutesAgo(3000),
    group: "ready",
    attention: [],
    tracking_url: "https://track.khazenly.com/?referenceNumber=KH-HBA-08997921&lang=en",
    ...extra,
  };
}

function tab(refunds: Refund[], extra: Partial<ReturnsTab> = {}): ReturnsTab {
  return {
    refunds,
    totals: {
      owed_now: "395.00",
      owed_count: 1,
      owed_missing_amount: 0,
      refunded_this_month: "1070.00",
      refunded_count: 2,
      month: "2026-11",
    },
    tracking: { checked_at: minutesAgo(5), every_minutes: 30, khazenly_down: false },
    paid_shown: 100,
    methods: [
      { value: "instapay", label: "InstaPay" },
      { value: "vodafone_cash", label: "Vodafone Cash" },
      { value: "bank_transfer", label: "Bank transfer" },
      { value: "other", label: "Other" },
    ],
    ...extra,
  };
}

const READY = refund({});
const ON_THE_WAY = refund({
  id: 2,
  khazenly_number: "KH-HBA-09000276",
  customer_name: "Jana Mohamed",
  step: "Ready for Pickup",
  received_at: null,
  group: "on_the_way",
  amount: null,
  refund_to: null,
  method: null,
  attention: ["details_missing"],
});
const STUCK = refund({
  id: 3,
  khazenly_number: "KH-HBA-09000241",
  step: "Return Picked Up",
  received_at: null,
  group: "attention",
  attention: ["stuck"],
});
const PAID = refund({ id: 4, khazenly_number: "KH-HBA-09000213", group: "paid", paid_on: "2026-11-09", paid_by: "Mona" });

/** Open a group that starts folded, by its header. */
function openGroup(title: string) {
  fireEvent.click(screen.getByRole("button", { name: new RegExp(`^${title} ·`) }));
}

let fetchMock: ReturnType<typeof vi.fn>;
beforeEach(() => {
  window.localStorage.clear();
  fetchMock = vi.fn();
  vi.stubGlobal("fetch", fetchMock);
  vi.stubGlobal(
    "matchMedia",
    vi.fn(() => ({ matches: false, addEventListener: () => undefined, removeEventListener: () => undefined })),
  );
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

function respond(body: ReturnsTab, write?: (path: string, init: RequestInit) => Promise<Response>) {
  fetchMock.mockImplementation((path: string, init?: RequestInit) => {
    if (init?.method && init.method !== "GET" && write) return write(path, init);
    return reply(200, body);
  });
}

describe("Operations → Returns (ADR 0079)", () => {
  it("groups refunds by the next act, with what is owed and refunded", async () => {
    respond(tab([READY, ON_THE_WAY, STUCK, PAID]));
    render(<OperationsReturns canEdit={false} />);

    expect(await screen.findByRole("heading", { name: "Ready to refund · 1" })).toBeTruthy();
    expect(screen.getAllByText("EGP 395.00").length).toBeGreaterThan(0);
    expect(fetchMock.mock.calls[0][0]).toBe("/api/order-ops/returns");
    expect(screen.getByText("Refunded in November")).toBeTruthy();
    expect(screen.getByText("EGP 1,070.00")).toBeTruthy();
    expect(screen.getByRole("heading", { name: "Ready to refund · 1" })).toBeTruthy();
    expect(screen.getByRole("heading", { name: "On the way back · 1" })).toBeTruthy();
    expect(screen.getByRole("heading", { name: "Needs attention · 1" })).toBeTruthy();
    expect(screen.getByRole("heading", { name: "Paid · 1" })).toBeTruthy();
    expect(screen.getByText("No movement for 3 days")).toBeTruthy();
    openGroup("Paid");
    expect(screen.getByText("Paid 9 Nov")).toBeTruthy();
    expect(screen.getByText(/Khazenly checked 5 minutes ago · every 30 minutes/)).toBeTruthy();
  });

  it("offers a viewer nothing to change", async () => {
    respond(tab([READY, PAID]));
    render(<OperationsReturns canEdit={false} />);
    await screen.findByText("KH-HBA-08997921");

    expect(screen.queryByRole("heading", { name: "Add a refund" })).toBeNull();
    fireEvent.click(screen.getByText("KH-HBA-08997921"));
    // The timeline opens; no form does.
    expect(await screen.findByText("Open on Khazenly")).toBeTruthy();
    expect(screen.queryByRole("button", { name: /as paid/ })).toBeNull();
    expect(screen.queryByRole("button", { name: "Save details" })).toBeNull();
    openGroup("Paid");
    fireEvent.click(screen.getByText("KH-HBA-09000213"));
    expect(screen.queryByRole("button", { name: "Undo paid" })).toBeNull();
  });

  it("adds a refund and says which pasted numbers were not added", async () => {
    let sent: Record<string, unknown> | null = null;
    respond(tab([]), (_path, init) => {
      sent = JSON.parse(String(init.body));
      return reply(200, {
        added: [READY],
        refused: [{ number: "KH-HBA-00000001", reason: "Khazenly has no order with this number." }],
      });
    });
    render(<OperationsReturns canEdit />);

    const numbers = await screen.findByLabelText(/Khazenly number/);
    fireEvent.change(numbers, { target: { value: "KH-HBA-08997921\nKH-HBA-00000001" } });
    // Two numbers: the details wait for each one.
    expect(screen.queryByLabelText(/Amount to refund/)).toBeNull();
    fireEvent.click(screen.getByLabelText("Exchange"));
    fireEvent.click(screen.getByRole("button", { name: "Add 2 refunds" }));

    expect(await screen.findByText("Added 1 refund.")).toBeTruthy();
    expect(screen.getByText(/Khazenly has no order with this number/)).toBeTruthy();
    expect(sent).toEqual({ numbers: ["KH-HBA-08997921\nKH-HBA-00000001"], kind: "exchange" });
    // What was not added stays in the box to fix.
    expect((screen.getByLabelText(/Khazenly number/) as HTMLTextAreaElement).value).toBe("KH-HBA-00000001");
  });

  it("marks a received refund paid, saying it sends nothing", async () => {
    let sent: { path: string; body: Record<string, unknown> } | null = null;
    respond(tab([READY]), (path, init) => {
      sent = { path, body: JSON.parse(String(init.body)) };
      return reply(200, { refund: { ...READY, group: "paid", paid_on: "2026-11-10" }, totals: tab([]).totals });
    });
    render(<OperationsReturns canEdit />);

    fireEvent.click(await screen.findByText("KH-HBA-08997921"));
    expect(screen.getByText("This records the refund you sent. It sends nothing.")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Record EGP 395.00 as paid" }));

    await waitFor(() => expect(sent).not.toBeNull());
    expect(sent!.path).toBe("/api/order-ops/returns/1/paid");
    expect(sent!.body).toMatchObject({ amount: "395.00", method: "instapay", refund_to: "01060910507" });
  });

  it("shows the server's refusal in its words", async () => {
    respond(tab([READY]), () => reply(422, { detail: "The day it was sent can't be in the future." }));
    render(<OperationsReturns canEdit />);
    fireEvent.click(await screen.findByText("KH-HBA-08997921"));
    fireEvent.click(screen.getByRole("button", { name: "Record EGP 395.00 as paid" }));
    expect(await screen.findByText("The day it was sent can't be in the future.")).toBeTruthy();
  });

  it("undoes paid only with a reason", async () => {
    let sent: Record<string, unknown> | null = null;
    respond(tab([PAID]), (_path, init) => {
      sent = JSON.parse(String(init.body));
      return reply(200, { refund: READY, totals: tab([]).totals });
    });
    render(<OperationsReturns canEdit />);
    await screen.findByRole("heading", { name: "Paid · 1" });
    openGroup("Paid");
    fireEvent.click(screen.getByText("KH-HBA-09000213"));
    fireEvent.click(screen.getByRole("button", { name: "Undo paid" }));

    const confirm = screen.getAllByRole("button", { name: "Undo paid" }).at(-1) as HTMLButtonElement;
    expect(confirm.disabled).toBe(true);
    fireEvent.change(screen.getByLabelText(/Why is it no longer paid/), { target: { value: "Sent to the wrong number" } });
    fireEvent.click(confirm);
    await waitFor(() => expect(sent).toEqual({ reason: "Sent to the wrong number" }));
  });

  it("says plainly when Khazenly isn't answering", async () => {
    respond(tab([STUCK], { tracking: { checked_at: minutesAgo(5), every_minutes: 30, khazenly_down: true } }));
    render(<OperationsReturns canEdit={false} />);
    const banner = await screen.findByRole("alert");
    expect(within(banner).getByText(/Khazenly's tracking isn't answering/)).toBeTruthy();
  });

  it("invites the first refund when there are none", async () => {
    respond(tab([], { totals: { ...tab([]).totals, owed_now: "0.00", owed_count: 0 } }));
    render(<OperationsReturns canEdit />);
    expect(await screen.findByText("Nothing to refund right now.")).toBeTruthy();
    expect(screen.getByRole("heading", { name: "Add a refund" })).toBeTruthy();
  });
});

describe("Finding a refund", () => {
  it("matches the name, the phone however it is written, the Shopify order and the Khazenly number", () => {
    expect(matches(READY, "khaled")).toBe(true);
    expect(matches(READY, "  KHALED magdy ")).toBe(true);
    expect(matches(READY, "01060910507")).toBe(true);
    expect(matches(READY, "+20 106 091 0507")).toBe(true);
    expect(matches(READY, "0106091")).toBe(true);
    expect(matches(READY, "#31876")).toBe(true);
    expect(matches(READY, "31876")).toBe(true);
    expect(matches(READY, "kh-hba-0899")).toBe(true);
    expect(matches(READY, "08997921")).toBe(true);
    expect(matches(READY, "Jana")).toBe(false);
    expect(matches(READY, "01")).toBe(false);
    expect(matches(READY, "99999")).toBe(false);
  });

  it("filters every group, says how many match, and hides the groups with none", async () => {
    respond(tab([READY, ON_THE_WAY, STUCK, PAID]));
    render(<OperationsReturns canEdit={false} />);
    const search = await screen.findByRole("searchbox", { name: "Search refunds" });

    fireEvent.change(search, { target: { value: "jana" } });
    expect(screen.getByText("1 refund matches.")).toBeTruthy();
    expect(screen.getByRole("heading", { name: "On the way back · 1 of 1" })).toBeTruthy();
    expect(screen.queryByRole("heading", { name: /Ready to refund/ })).toBeNull();
    expect(screen.queryByText("KH-HBA-08997921")).toBeNull();

    fireEvent.change(search, { target: { value: "nobody at all" } });
    expect(screen.getByText(/No refund matches “nobody at all”/)).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "Clear the search" }));
    expect(screen.getByRole("heading", { name: "Ready to refund · 1" })).toBeTruthy();
  });
});

describe("Sorting refunds", () => {
  const rows = [
    refund({ id: 1, khazenly_number: "KH-HBA-09000182", customer_name: "Omar", amount: "749.00", step_at: "2026-11-08T10:00:00Z", created_at: "2026-11-01T10:00:00Z" }),
    refund({ id: 2, khazenly_number: "KH-HBA-08903136", customer_name: "abdelrahman", amount: null, step_at: "2026-11-10T10:00:00Z", created_at: "2026-11-03T10:00:00Z" }),
    refund({ id: 3, khazenly_number: "KH-HBA-09000376", customer_name: "Mona", amount: "1402.00", step_at: "2026-11-09T10:00:00Z", created_at: "2026-11-02T10:00:00Z" }),
  ];
  const order = (sorted: Refund[]) => sorted.map((row) => row.id);

  it("sorts every column both ways, with what is missing always last", () => {
    expect(order(sortRefunds(rows, { key: "added", dir: "desc" }))).toEqual([2, 3, 1]);
    expect(order(sortRefunds(rows, { key: "khazenly", dir: "asc" }))).toEqual([2, 1, 3]);
    expect(order(sortRefunds(rows, { key: "customer", dir: "asc" }))).toEqual([2, 3, 1]);
    expect(order(sortRefunds(rows, { key: "amount", dir: "desc" }))).toEqual([3, 1, 2]);
    expect(order(sortRefunds(rows, { key: "amount", dir: "asc" }))).toEqual([1, 3, 2]);
    expect(order(sortRefunds(rows, { key: "status", dir: "desc" }))).toEqual([2, 3, 1]);
  });

  it("sorts from a column head, and again the other way on a second press", async () => {
    respond(tab(rows.map((row) => ({ ...row, group: "ready" as const }))));
    render(<OperationsReturns canEdit={false} />);
    const amount = await screen.findByRole("button", { name: "Sort by Amount" });
    const numbers = () =>
      Array.from(document.querySelectorAll(".ops-rt__kh")).map((node) => node.textContent);

    fireEvent.click(amount);
    expect(numbers()).toEqual(["KH-HBA-09000376", "KH-HBA-09000182", "KH-HBA-08903136"]);
    const now = screen.getByRole("button", { name: "Sort by Amount, now descending" });
    expect(now.getAttribute("aria-pressed")).toBe("true");
    fireEvent.click(now);
    expect(numbers()).toEqual(["KH-HBA-09000182", "KH-HBA-09000376", "KH-HBA-08903136"]);

    // The phone's menu says the same sort in words, and sets it too.
    const menu = screen.getByLabelText("Sort by") as HTMLSelectElement;
    expect(menu.value).toBe("amount:asc");
    fireEvent.change(menu, { target: { value: "customer:asc" } });
    expect(numbers()[0]).toBe("KH-HBA-08903136");
  });
});

describe("Operations → Khazenly for a viewer (ADR 0079)", () => {
  it("shows the history and nothing to build", async () => {
    fetchMock.mockImplementation(() =>
      reply(200, {
        freshness: {
          source: "shopify",
          label: "Shopify",
          state: "fresh",
          updated_at: minutesAgo(2),
          checked_at: minutesAgo(2),
          error: null,
          row_count: 40,
        },
        runs: [],
      }),
    );
    render(<OperationsKhazenly canBuild={false} />);
    expect(await screen.findByRole("heading", { name: "History" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Build the file" })).toBeNull();
  });
});

describe("Folding the groups", () => {
  it("opens the groups that ask for something, folds the rest, and remembers", async () => {
    respond(tab([READY, ON_THE_WAY, STUCK, PAID]));
    render(<OperationsReturns canEdit={false} />);
    await screen.findByText("KH-HBA-08997921");

    expect(DEFAULT_FOLDS).toEqual({ ready: true, attention: true, on_the_way: false, paid: false });
    expect(screen.getByText("KH-HBA-09000241")).toBeTruthy();
    expect(screen.queryByText("KH-HBA-09000276")).toBeNull();
    expect(screen.queryByText("KH-HBA-09000213")).toBeNull();

    const onTheWay = screen.getByRole("button", { name: /^On the way back ·/ });
    expect(onTheWay.getAttribute("aria-expanded")).toBe("false");
    fireEvent.click(onTheWay);
    expect(onTheWay.getAttribute("aria-expanded")).toBe("true");
    expect(screen.getByText("KH-HBA-09000276")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: /^Ready to refund ·/ }));
    expect(screen.queryByText("KH-HBA-08997921")).toBeNull();

    expect(JSON.parse(window.localStorage.getItem("hba.ops.returns.open")!)).toMatchObject({
      ready: false,
      on_the_way: true,
    });
  });

  it("opens every group a search found something in", async () => {
    respond(tab([READY, PAID]));
    render(<OperationsReturns canEdit={false} />);
    await screen.findByText("KH-HBA-08997921");
    fireEvent.change(screen.getByLabelText("Search refunds"), { target: { value: "09000213" } });
    expect(screen.getByText("KH-HBA-09000213")).toBeTruthy();
  });
});

describe("Paying before the return is back (ADR 0080)", () => {
  it("asks to confirm a payment made early, and says so to the server", async () => {
    let sent: { path: string; body: Record<string, unknown> } | null = null;
    respond(tab([STUCK]), (path, init) => {
      sent = { path, body: JSON.parse(String(init.body)) };
      return reply(200, { refund: { ...STUCK, group: "paid" } });
    });
    render(<OperationsReturns canEdit />);
    fireEvent.click(await screen.findByText("KH-HBA-09000241"));
    fireEvent.click(screen.getByRole("button", { name: "Paid it already? Record it" }));

    expect(screen.getByRole("heading", { name: "Mark as paid early" })).toBeTruthy();
    const record = screen.getByRole("button", { name: "Record EGP 395.00 as paid early" }) as HTMLButtonElement;
    expect(record.disabled).toBe(true);
    fireEvent.click(screen.getByLabelText(/I paid it before Khazenly said the return was back/));
    expect(record.disabled).toBe(false);
    fireEvent.click(record);

    await waitFor(() => expect(sent).not.toBeNull());
    expect(sent!.path).toBe("/api/order-ops/returns/3/paid");
    expect(sent!.body).toMatchObject({ early: true, amount: "395.00" });
  });

  it("sends the optional photo after recording the payment", async () => {
    const paths: string[] = [];
    respond(tab([READY]), (path) => {
      paths.push(path);
      return reply(200, { refund: { ...READY, group: "paid" } });
    });
    render(<OperationsReturns canEdit />);
    fireEvent.click(await screen.findByText("KH-HBA-08997921"));
    const photo = new File([new Uint8Array([0x89, 0x50])], "proof.png", { type: "image/png" });
    fireEvent.change(screen.getByLabelText(/Photo of the payment/), { target: { files: [photo] } });
    fireEvent.click(screen.getByRole("button", { name: "Record EGP 395.00 as paid" }));

    await waitFor(() => expect(paths).toEqual(["/api/order-ops/returns/1/paid", "/api/order-ops/returns/1/proof"]));
  });

  it("shows a refund paid early with its Khazenly step and its photo, to a viewer too", async () => {
    const early = refund({
      ...STUCK,
      group: "paid",
      attention: [],
      paid_on: "2026-11-09",
      paid_by: "Mona",
      paid_early: true,
      proof_url: "/api/order-ops/returns/3/proof?v=abc",
    });
    respond(tab([early]));
    render(<OperationsReturns canEdit={false} />);
    await screen.findByRole("heading", { name: "Paid · 1" });
    openGroup("Paid");

    expect(screen.getByText("Paid before it was back")).toBeTruthy();
    expect(screen.getByText("Khazenly: Return Picked Up")).toBeTruthy();
    fireEvent.click(screen.getByText("KH-HBA-09000241"));
    const image = screen.getByRole("img", { name: "Payment photo for KH-HBA-09000241" }) as HTMLImageElement;
    expect(image.getAttribute("src")).toBe("/api/order-ops/returns/3/proof?v=abc");
    expect(screen.queryByRole("button", { name: "Remove photo" })).toBeNull();
  });
});
