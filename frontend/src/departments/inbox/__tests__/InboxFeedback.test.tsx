// @vitest-environment jsdom
/**
 * Inbox → Feedback (ADR 0083, decision 6): the sheet of every answer to the
 * delivery question. Every name, number, order and comment here is made up.
 */
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, useLocation } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { InboxFeedback } from "../InboxFeedback";

const reply = (status: number, body: unknown) =>
  Promise.resolve({
    ok: status < 400,
    status,
    headers: { get: () => "application/json" },
    json: () => Promise.resolve(body),
    text: () => Promise.resolve(JSON.stringify(body)),
  } as unknown as Response);

/** The default start: today in Cairo and the 29 days before it. */
function thirtyDaysBack(): string {
  const [year, month, day] = new Intl.DateTimeFormat("en-CA", { timeZone: "Africa/Cairo" })
    .format(new Date())
    .split("-")
    .map(Number);
  return new Date(Date.UTC(year, month - 1, day - 29)).toISOString().slice(0, 10);
}

const row = (id: number, extra: object = {}) => ({
  id,
  order_id: `id-${7000 + id}`,
  order_name: `#${7000 + id}`,
  delivered_at: "2026-11-06T10:00:00+00:00",
  sent_at: "2026-11-08T10:00:00+00:00",
  asked_at: "2026-11-08T10:00:00+00:00",
  customer_name: "Habiba Tarek",
  phone: "201005550103",
  products: ["Cotton shirt"],
  courier: "Bosta",
  state: "sent",
  state_label: "Sent",
  skip_reason: null,
  last_error: null,
  step: "done",
  rating: "loved",
  rated_at: "2026-11-08T11:00:00+00:00",
  reason: "quality",
  comment: null,
  comment_at: null,
  reorder: null,
  needs_follow_up: false,
  resolved_at: null,
  resolved_by: null,
  resolved_by_name: null,
  solved: null,
  solved_at: null,
  reopened_count: 0,
  code: null,
  code_sent_at: null,
  code_expires_at: null,
  code_used_at: null,
  code_order_name: null,
  ...extra,
});

const SUMMARY = {
  asked: 6,
  not_reached: 0,
  answered: 5,
  loved: 1,
  okay: 1,
  unhappy: 3,
  needs_follow_up: 2,
  solved: 1,
  codes_sent: 1,
  codes_used: 1,
};

const OPTIONS = {
  couriers: ["Aramex", "Bosta", "Mylerz"],
  ratings: [
    { id: "loved", title: "Loved it" },
    { id: "okay", title: "It was okay" },
    { id: "unhappy", title: "Not happy" },
  ],
  reasons: {
    loved: [
      { id: "quality", title: "Quality" },
      { id: "other", title: "Something else" },
    ],
    okay: [{ id: "price", title: "Price" }],
    unhappy: [
      { id: "size_fit", title: "Size / fit" },
      { id: "delivery", title: "Delivery" },
    ],
  },
  states: [
    { id: "needs_follow_up", title: "Needs follow-up" },
    { id: "resolved", title: "Resolved" },
    { id: "reopened", title: "Reopened" },
  ],
};

const ROWS = [
  row(1, {
    rating: "unhappy",
    reason: "delivery",
    comment: "It came two days late and the box was damaged",
    needs_follow_up: true,
    reopened_count: 1,
    products: ["Cotton shirt", "Linen trousers"],
  }),
  row(2, {
    customer_name: null,
    phone: "201005550188",
    rating: "unhappy",
    reason: "size_fit",
    resolved_at: "2026-11-09T10:00:00+00:00",
    resolved_by_name: "Mariam",
    solved: true,
    reorder: "very_likely",
    code: "THANKS-4F7K",
    code_sent_at: "2026-11-10T10:00:00+00:00",
    code_used_at: "2026-11-12T10:00:00+00:00",
    code_order_name: "#7100",
  }),
  row(3, { rating: null, reason: null, rated_at: null, code: "THANKS-9ZZZ", code_sent_at: "2026-11-10T10:00:00+00:00" }),
  row(4, { state: "no_whatsapp", rating: null, reason: null, rated_at: null, sent_at: null, asked_at: null }),
  row(5, { state: "failed", last_error: "Meta said no", rating: null, reason: null, rated_at: null }),
  row(6, { state: "would_send", rating: null, reason: null, rated_at: null }),
];

type Served = {
  page?: (url: string) => [number, unknown];
  /** The feature's switch, as the sheet itself reports it. On unless a test says otherwise. */
  enabled?: boolean;
  download?: () => Promise<Response>;
};

let calls: string[] = [];
const feedbackCalls = () => calls.filter((url) => /^\/api\/inbox\/feedback\?/.test(url));
const lastFeedbackCall = () => feedbackCalls()[feedbackCalls().length - 1];
const query = (url: string) => new URL(url, "http://x").searchParams;

function serve(served: Served = {}) {
  calls = [];
  vi.stubGlobal(
    "fetch",
    vi.fn((url: string) => {
      calls.push(url);
      if (url.startsWith("/api/inbox/feedback/download")) {
        return served.download?.() ?? reply(200, {});
      }
      if (url.startsWith("/api/inbox/feedback")) {
        const [status, body] = served.page?.(url) ?? [
          200,
          { rows: ROWS, next_offset: null, summary: SUMMARY, options: OPTIONS },
        ];
        const found = body as object;
        return reply(status, "rows" in found ? { enabled: served.enabled ?? true, ...found } : found);
      }
      return reply(404, { detail: "Not here" });
    }),
  );
}

function Where() {
  const location = useLocation();
  return <output data-testid="where">{location.search}</output>;
}

function show(address = "/inbox/feedback") {
  return render(
    <MemoryRouter initialEntries={[address]}>
      <InboxFeedback />
      <Where />
    </MemoryRouter>,
  );
}

const where = () => screen.getByTestId("where").textContent ?? "";

function narrowScreen(narrow: boolean) {
  vi.stubGlobal(
    "matchMedia",
    vi.fn(() => ({ matches: narrow, addEventListener: () => undefined, removeEventListener: () => undefined })),
  );
}

beforeEach(() => narrowScreen(false));
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("the Feedback sheet", () => {
  it("asks for the last 30 days, and shows a row for each asked order", async () => {
    serve();
    show();

    const table = await screen.findByRole("table");
    expect(query(lastFeedbackCall()).get("since")).toBe(thirtyDaysBack());
    expect(query(lastFeedbackCall()).get("until")).toBeNull();

    const headings = within(table).getAllByRole("columnheader").map((cell) => cell.textContent);
    expect(headings).toEqual([
      "Asked", "Customer", "Order", "Products", "Courier", "Answer", "Reason", "Comment", "Follow-up", "Code",
    ]);

    const rows = within(table).getAllByRole("row").slice(1);
    expect(rows).toHaveLength(6);

    // Unhappy, reopened, still waiting on a person.
    const first = rows[0];
    expect(within(first).getByText("Habiba Tarek")).toBeTruthy();
    expect(within(first).getByText("+20 100 555 0103")).toBeTruthy();
    expect(within(first).getByText("#7001")).toBeTruthy();
    expect(within(first).getByText("Cotton shirt, Linen trousers")).toBeTruthy();
    expect(within(first).getByText("Not happy")).toBeTruthy();
    expect(within(first).getByText("Delivery")).toBeTruthy();
    expect(within(first).getByText("Needs follow-up")).toBeTruthy();
    expect(within(first).getByText("Reopened 1×")).toBeTruthy();
    expect(within(first).getByText("8 Nov, 12:00")).toBeTruthy();

    // Resolved, solved, would order again, code used on an order.
    const second = rows[1];
    expect(within(second).getByText("No name")).toBeTruthy();
    expect(within(second).getByText("Size / fit")).toBeTruthy();
    expect(within(second).getByText("Resolved by Mariam on 9 Nov")).toBeTruthy();
    expect(within(second).getByText("Solved: yes")).toBeTruthy();
    expect(within(second).getByText("Order again: Very likely")).toBeTruthy();
    expect(within(second).getByText("THANKS-4F7K")).toBeTruthy();
    expect(within(second).getByText("Used on #7100")).toBeTruthy();

    // No answer, and a code that is out but not used.
    const third = rows[2];
    expect(within(third).getByText("No answer yet")).toBeTruthy();
    expect(within(third).getByText("Not used")).toBeTruthy();

    // A question that did not go as it should have says so, quietly.
    expect(within(rows[3]).getByText("Not on WhatsApp")).toBeTruthy();
    expect(within(rows[3]).getByText("—", { selector: ".num" })).toBeTruthy();
    expect(within(rows[4]).getByText("Could not be sent: Meta said no")).toBeTruthy();
    expect(within(rows[5]).getByText("Would send: sending is off")).toBeTruthy();
  });

  it("has a link to the feedback setup in its head, beside Download", async () => {
    serve();
    show();

    await screen.findByRole("table");
    const link = screen.getByRole("link", { name: "Feedback setup" });
    expect(link.getAttribute("href")).toBe("/inbox/feedback/setup");
  });

  it("puts the numbers for these filters above the sheet", async () => {
    serve();
    show();
    const summary = await screen.findByRole("group", { name: "Summary of these answers" });

    for (const [label, value] of [
      ["Asked", "6"], ["Answered", "5"], ["Loved it", "1"], ["It was okay", "1"], ["Not happy", "3"],
      ["Needs follow-up", "2"], ["Solved", "1"], ["Codes sent", "1"], ["Codes used", "1"],
    ]) {
      const tile = within(summary).getByText(label).parentElement as HTMLElement;
      expect(within(tile).getByText(value)).toBeTruthy();
    }
    // Nothing unreached: nothing said about it.
    expect(within(summary).queryByText(/could not be reached/)).toBeNull();
  });

  it("says how many questions could not be reached, beside Asked and only when some could not", async () => {
    serve({
      page: () => [200, { rows: ROWS, next_offset: null, summary: { ...SUMMARY, not_reached: 3 }, options: OPTIONS }],
    });
    show();
    const summary = await screen.findByRole("group", { name: "Summary of these answers" });

    const asked = within(summary).getByText("Asked").parentElement as HTMLElement;
    expect(within(asked).getByText("3 could not be reached")).toBeTruthy();
    // A quiet line on the card, not a card of its own.
    expect(within(summary).getAllByText(/could not be reached/)).toHaveLength(1);
  });

  it("narrows to an answer or to the follow-ups from a tap on a number, and back off again", async () => {
    serve();
    show();
    const summary = await screen.findByRole("group", { name: "Summary of these answers" });

    fireEvent.click(within(summary).getByRole("button", { name: /Not happy/ }));
    await waitFor(() => expect(query(lastFeedbackCall()).get("rating")).toBe("unhappy"));
    expect(where()).toContain("rating=unhappy");
    expect(within(summary).getByRole("button", { name: /Not happy/ }).getAttribute("aria-pressed")).toBe("true");

    fireEvent.click(within(summary).getByRole("button", { name: /Needs follow-up/ }));
    await waitFor(() => expect(query(lastFeedbackCall()).get("state")).toBe("needs_follow_up"));

    fireEvent.click(within(summary).getByRole("button", { name: /Not happy/ }));
    await waitFor(() => expect(query(lastFeedbackCall()).get("rating")).toBeNull());
    // Asked, answered, solved and the codes are only read.
    expect(within(summary).queryByRole("button", { name: /Asked/ })).toBeNull();
  });

  it("asks again with each filter, and keeps each in the address", async () => {
    serve();
    show();
    await screen.findByRole("table");

    fireEvent.change(screen.getByLabelText("From"), { target: { value: "2026-10-01" } });
    await waitFor(() => expect(query(lastFeedbackCall()).get("since")).toBe("2026-10-01"));
    fireEvent.change(screen.getByLabelText("To"), { target: { value: "2026-10-31" } });
    await waitFor(() => expect(query(lastFeedbackCall()).get("until")).toBe("2026-10-31"));

    fireEvent.change(screen.getByLabelText("Answer"), { target: { value: "unhappy" } });
    await waitFor(() => expect(query(lastFeedbackCall()).get("rating")).toBe("unhappy"));
    fireEvent.change(screen.getByLabelText("Reason"), { target: { value: "delivery" } });
    await waitFor(() => expect(query(lastFeedbackCall()).get("reason")).toBe("delivery"));
    fireEvent.change(screen.getByLabelText("Courier"), { target: { value: "Mylerz" } });
    await waitFor(() => expect(query(lastFeedbackCall()).get("courier")).toBe("Mylerz"));
    fireEvent.change(screen.getByLabelText("Follow-up"), { target: { value: "reopened" } });
    await waitFor(() => expect(query(lastFeedbackCall()).get("state")).toBe("reopened"));
    fireEvent.change(screen.getByLabelText("Product"), { target: { value: "linen" } });
    await waitFor(() => expect(query(lastFeedbackCall()).get("product")).toBe("linen"));
    fireEvent.change(screen.getByLabelText("Search"), { target: { value: "7003" } });
    await waitFor(() => expect(query(lastFeedbackCall()).get("q")).toBe("7003"));

    const address = new URLSearchParams(where());
    expect(Object.fromEntries(address)).toMatchObject({
      since: "2026-10-01",
      until: "2026-10-31",
      rating: "unhappy",
      reason: "delivery",
      courier: "Mylerz",
      state: "reopened",
      product: "linen",
      q: "7003",
    });
  });

  it("waits for the typing to stop before it asks", async () => {
    serve();
    show();
    await screen.findByRole("table");
    const before = feedbackCalls().length;

    const box = screen.getByLabelText("Search");
    fireEvent.change(box, { target: { value: "7" } });
    fireEvent.change(box, { target: { value: "70" } });
    fireEvent.change(box, { target: { value: "700" } });

    await waitFor(() => expect(query(lastFeedbackCall()).get("q")).toBe("700"));
    expect(feedbackCalls().length).toBe(before + 1);
  });

  it("is filled in from the address, so a filtered view can be linked and survives a reload", async () => {
    serve();
    show("/inbox/feedback?since=2026-10-01&until=2026-10-31&rating=unhappy&reason=size_fit&courier=Bosta&state=resolved&product=shirt&q=habiba");

    await screen.findByRole("table");
    const asked = query(feedbackCalls()[0]);
    expect(Object.fromEntries(asked)).toEqual({
      since: "2026-10-01",
      until: "2026-10-31",
      rating: "unhappy",
      reason: "size_fit",
      courier: "Bosta",
      state: "resolved",
      product: "shirt",
      q: "habiba",
    });
    expect((screen.getByLabelText("From") as HTMLInputElement).value).toBe("2026-10-01");
    expect((screen.getByLabelText("To") as HTMLInputElement).value).toBe("2026-10-31");
    expect((screen.getByLabelText("Answer") as HTMLSelectElement).value).toBe("unhappy");
    expect((screen.getByLabelText("Reason") as HTMLSelectElement).value).toBe("size_fit");
    expect((screen.getByLabelText("Courier") as HTMLSelectElement).value).toBe("Bosta");
    expect((screen.getByLabelText("Follow-up") as HTMLSelectElement).value).toBe("resolved");
    expect((screen.getByLabelText("Product") as HTMLInputElement).value).toBe("shirt");
    expect((screen.getByLabelText("Search") as HTMLInputElement).value).toBe("habiba");
  });

  it("offers reasons that belong to the answer, and only once an answer is chosen", async () => {
    serve();
    show();
    await screen.findByRole("table");

    const reason = screen.getByLabelText("Reason") as HTMLSelectElement;
    expect(reason.disabled).toBe(true);
    // Short enough to be read whole in a narrow box; the reason it is shut is its tooltip.
    expect(within(reason).getByText("Any reason")).toBeTruthy();
    expect(reason.getAttribute("title")).toBe("Choose an answer first");

    fireEvent.change(screen.getByLabelText("Answer"), { target: { value: "okay" } });
    await waitFor(() => expect(reason.disabled).toBe(false));
    expect(within(reason).getAllByRole("option").map((option) => option.textContent)).toEqual(["Any reason", "Price"]);

    fireEvent.change(reason, { target: { value: "price" } });
    await waitFor(() => expect(query(lastFeedbackCall()).get("reason")).toBe("price"));

    // Another answer has other reasons, and the old one is dropped.
    fireEvent.change(screen.getByLabelText("Answer"), { target: { value: "unhappy" } });
    await waitFor(() => expect(query(lastFeedbackCall()).get("rating")).toBe("unhappy"));
    expect(query(lastFeedbackCall()).get("reason")).toBeNull();
    expect(within(reason).getAllByRole("option").map((option) => option.textContent)).toEqual([
      "Any reason", "Size / fit", "Delivery",
    ]);

    // Back to any answer: no reason is asked for, even if the address still held one.
    fireEvent.change(screen.getByLabelText("Answer"), { target: { value: "" } });
    await waitFor(() => expect(query(lastFeedbackCall()).get("rating")).toBeNull());
    expect(reason.disabled).toBe(true);
  });

  it("does not ask for a reason the address names without an answer", async () => {
    serve();
    show("/inbox/feedback?reason=delivery");
    await screen.findByRole("table");
    expect(query(feedbackCalls()[0]).get("reason")).toBeNull();
  });

  it("clears every filter at once", async () => {
    serve();
    show("/inbox/feedback?rating=unhappy&product=shirt");
    await screen.findByRole("table");

    fireEvent.click(screen.getByRole("button", { name: "Clear filters" }));

    await waitFor(() => expect(where()).toBe(""));
    expect((screen.getByLabelText("Product") as HTMLInputElement).value).toBe("");
    expect(query(lastFeedbackCall()).get("since")).toBe(thirtyDaysBack());
    expect(query(lastFeedbackCall()).get("rating")).toBeNull();
    expect(screen.queryByRole("button", { name: "Clear filters" })).toBeNull();
  });

  it("clears the start date to mean no start at all", async () => {
    serve();
    show();
    await screen.findByRole("table");

    fireEvent.change(screen.getByLabelText("From"), { target: { value: "" } });

    await waitFor(() => expect(query(lastFeedbackCall()).get("since")).toBeNull());
    expect(where()).toContain("since=");
  });

  it("reaches every answer, a page at a time", async () => {
    serve({
      page: (url) =>
        url.includes("offset=50")
          ? [200, { rows: [row(51, { customer_name: "Laila Emad" })], next_offset: null, summary: SUMMARY, options: OPTIONS }]
          : [200, { rows: [row(1)], next_offset: 50, summary: SUMMARY, options: OPTIONS }],
    });
    show("/inbox/feedback?rating=loved");

    fireEvent.click(await screen.findByRole("button", { name: "Show more" }));

    expect(await screen.findByText("Laila Emad")).toBeTruthy();
    const more = query(lastFeedbackCall());
    expect(more.get("offset")).toBe("50");
    // Asked with the same filters.
    expect(more.get("rating")).toBe("loved");
    expect(screen.getAllByText("Habiba Tarek")).toHaveLength(1);
    expect(screen.queryByRole("button", { name: "Show more" })).toBeNull();
  });

  it("says so, with the way to try again, when more could not be loaded", async () => {
    serve({
      page: (url) =>
        url.includes("offset=")
          ? [500, { detail: "No" }]
          : [200, { rows: [row(1)], next_offset: 50, summary: SUMMARY, options: OPTIONS }],
    });
    show();

    fireEvent.click(await screen.findByRole("button", { name: "Show more" }));

    expect(await screen.findByText("Couldn't load more. Try again.")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Show more" })).toBeTruthy();
    expect(screen.getByText("Habiba Tarek")).toBeTruthy();
  });

  it("truncates a long comment and opens it out on a tap, keeping its full text", async () => {
    serve();
    show();
    const table = await screen.findByRole("table");

    const full = "It came two days late and the box was damaged";
    const comment = within(table).getByText(full);
    expect(comment.getAttribute("title")).toBe(full);
    expect(comment.className).not.toContain("--open");
    // Short enough to read whole: nothing to open.
    expect(within(table).queryByRole("button", { name: /^Show all/ })).toBeNull();

    cleanup();
    serve({
      page: () => [
        200,
        {
          rows: [row(1, { comment: "x".repeat(200) })],
          next_offset: null,
          summary: SUMMARY,
          options: OPTIONS,
        },
      ],
    });
    show();
    // Each button says whose comment it opens: a screen reader hears them one after another.
    const open = await screen.findByRole("button", { name: "Show all of the comment on #7001" });
    expect(open.getAttribute("aria-expanded")).toBe("false");
    fireEvent.click(open);
    expect(screen.getByRole("button", { name: "Show less of the comment on #7001" }).getAttribute("aria-expanded")).toBe("true");
    expect(screen.getByTitle("x".repeat(200)).className).toContain("--open");
  });

  it("says nobody has been asked, or that nothing matches the filters", async () => {
    serve({ page: () => [200, { rows: [], next_offset: null, summary: { ...SUMMARY, asked: 0 }, options: OPTIONS }] });
    show();
    expect(await screen.findByText("No one has been asked in the last 30 days.")).toBeTruthy();
    cleanup();

    serve({ page: () => [200, { rows: [], next_offset: null, summary: { ...SUMMARY, asked: 0 }, options: OPTIONS }] });
    show("/inbox/feedback?courier=Aramex");
    expect(await screen.findByText("Nothing matches these filters.")).toBeTruthy();
    expect(screen.queryByRole("table")).toBeNull();
  });

  it("says so, and offers another try, when the sheet could not be loaded", async () => {
    let fail = true;
    serve({
      page: () =>
        fail ? [500, { detail: "No" }] : [200, { rows: ROWS, next_offset: null, summary: SUMMARY, options: OPTIONS }],
    });
    show();

    expect(await screen.findByText(/Couldn't load the feedback\./)).toBeTruthy();
    expect(screen.queryByText("Loading…")).toBeNull();
    fail = false;
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));

    expect(await screen.findByRole("table")).toBeTruthy();
    expect(screen.queryByText(/Couldn't load the feedback\./)).toBeNull();
  });

  it("gives the server's own words when it refuses the dates", async () => {
    serve({ page: () => [422, { detail: "The first day cannot be after the last day." }] });
    show("/inbox/feedback?since=2026-11-05&until=2026-11-01");

    const notice = await screen.findByRole("alert");
    expect(notice.textContent).toBe("The first day cannot be after the last day.");
    expect(screen.queryByText(/Couldn't load the feedback\./)).toBeNull();
  });

  it("says when the questions are switched off, and nothing otherwise", async () => {
    serve({ enabled: false });
    show();
    expect(await screen.findByText("Feedback questions are switched off. Nothing is being sent.")).toBeTruthy();
    // The sheet itself is read as usual.
    expect(await screen.findByRole("table")).toBeTruthy();
    cleanup();

    serve({ enabled: true });
    show();
    await screen.findByRole("table");
    expect(screen.queryByText(/switched off/)).toBeNull();
    // The switch comes with the sheet: no second read, and none that asks Shopify.
    expect(calls.filter((url) => url.startsWith("/api/inbox/feedback/settings"))).toEqual([]);
  });

  it("reads everybody's words in their own direction", async () => {
    serve({
      page: () => [
        200,
        {
          rows: [
            row(1, {
              customer_name: "نور الهدى",
              comment: "القماش جميل جدا والتغليف كان ممتازا",
              products: ["قميص كتان"],
            }),
          ],
          next_offset: null,
          summary: SUMMARY,
          options: OPTIONS,
        },
      ],
    });
    show();
    const table = await screen.findByRole("table");

    expect(within(table).getByText("نور الهدى").getAttribute("dir")).toBe("auto");
    expect(within(table).getByText("القماش جميل جدا والتغليف كان ممتازا").getAttribute("dir")).toBe("auto");
    expect(within(table).getByText("قميص كتان").getAttribute("dir")).toBe("auto");
  });
});

describe("downloading the sheet", () => {
  function file(name = 'attachment; filename="feedback-2026-11-12.xlsx"') {
    return Promise.resolve({
      ok: true,
      status: 200,
      headers: { get: (header: string) => (header.toLowerCase() === "content-disposition" ? name : null) },
      blob: () => Promise.resolve(new Blob(["xlsx"])),
      text: () => Promise.resolve(""),
    } as unknown as Response);
  }

  beforeEach(() => {
    URL.createObjectURL = vi.fn(() => "blob:feedback");
    URL.revokeObjectURL = vi.fn();
  });

  it("fetches the file for the filters on screen and saves it under the name the server gave", async () => {
    const clicked: { href: string; download: string }[] = [];
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (this: HTMLAnchorElement) {
      clicked.push({ href: this.href, download: this.download });
    });
    serve({ download: () => file() });
    show("/inbox/feedback?rating=unhappy&courier=Bosta&since=2026-10-01");

    const button = await screen.findByRole("button", { name: /Download/ });
    await waitFor(() => expect((button as HTMLButtonElement).disabled).toBe(false));
    fireEvent.click(button);

    await waitFor(() => expect(clicked).toHaveLength(1));
    const url = calls.find((call) => call.startsWith("/api/inbox/feedback/download"))!;
    expect(Object.fromEntries(query(url))).toEqual({ since: "2026-10-01", rating: "unhappy", courier: "Bosta" });
    // Every row the filters match, not one page of them.
    expect(query(url).get("offset")).toBeNull();
    expect(query(url).get("limit")).toBeNull();
    expect(clicked[0]).toEqual({ href: "blob:feedback", download: "feedback-2026-11-12.xlsx" });
  });

  it("shows that it is working, and does not start a second file meanwhile", async () => {
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => undefined);
    let finish: (response: Response) => void = () => undefined;
    serve({ download: () => new Promise<Response>((resolve) => (finish = resolve)) });
    show();

    const button = await screen.findByRole("button", { name: /Download/ });
    await waitFor(() => expect((button as HTMLButtonElement).disabled).toBe(false));
    fireEvent.click(button);

    expect(await screen.findByRole("button", { name: /Preparing the file/ })).toBeTruthy();
    expect((screen.getByRole("button", { name: /Preparing the file/ }) as HTMLButtonElement).disabled).toBe(true);

    finish(await file());
    expect(await screen.findByRole("button", { name: /^Download/ })).toBeTruthy();
  });

  it("is off when there is nothing to download", async () => {
    serve({ page: () => [200, { rows: [], next_offset: null, summary: { ...SUMMARY, asked: 0 }, options: OPTIONS }] });
    show();

    await screen.findByText("No one has been asked in the last 30 days.");
    expect((screen.getByRole("button", { name: /Download/ }) as HTMLButtonElement).disabled).toBe(true);
  });

  it("gives the server's words when the file is refused, for example for a range too wide", async () => {
    serve({
      download: () =>
        reply(422, { detail: "That is more than 50,000 rows. Choose a narrower date range." }),
    });
    show();

    const button = await screen.findByRole("button", { name: /Download/ });
    await waitFor(() => expect((button as HTMLButtonElement).disabled).toBe(false));
    fireEvent.click(button);

    const problem = await screen.findByRole("alert");
    expect(problem.textContent).toBe("That is more than 50,000 rows. Choose a narrower date range.");
    expect(URL.createObjectURL).not.toHaveBeenCalled();
    expect((screen.getByRole("button", { name: /Download/ }) as HTMLButtonElement).disabled).toBe(false);
  });

  it("says plainly when the platform could not be reached at all", async () => {
    serve({ download: () => Promise.reject(new TypeError("Failed to fetch")) });
    show();

    const button = await screen.findByRole("button", { name: /Download/ });
    await waitFor(() => expect((button as HTMLButtonElement).disabled).toBe(false));
    fireEvent.click(button);

    expect((await screen.findByRole("alert")).textContent).toBe("The file could not be downloaded. Try again.");
  });
});

describe("the sheet on a phone", () => {
  it("is a list of cards, not a table to scroll sideways", async () => {
    narrowScreen(true);
    serve();
    show();

    await screen.findByText("Cotton shirt, Linen trousers · Bosta");
    expect(screen.queryByRole("table")).toBeNull();

    const cards = screen.getAllByRole("listitem");
    expect(cards).toHaveLength(6);
    const first = cards[0];
    expect(within(first).getByText("#7001")).toBeTruthy();
    expect(within(first).getByText("Habiba Tarek")).toBeTruthy();
    expect(within(first).getByText("Not happy")).toBeTruthy();
    expect(within(first).getByText("Delivery")).toBeTruthy();
    expect(within(first).getByText("It came two days late and the box was damaged")).toBeTruthy();
    expect(within(first).getByText("Needs follow-up")).toBeTruthy();
    expect(within(first).getByText("Reopened 1×")).toBeTruthy();
    expect(within(cards[1]).getByText("Used on #7100")).toBeTruthy();
    expect(within(cards[2]).getByText("No answer yet")).toBeTruthy();
    expect(within(cards[4]).getByText("Could not be sent: Meta said no")).toBeTruthy();
  });
});
