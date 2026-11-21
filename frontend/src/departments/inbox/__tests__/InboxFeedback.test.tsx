// @vitest-environment jsdom
/**
 * Inbox → Feedback (ADR 0083 decision 6, ADR 0088): four summary cards, the
 * *To follow up* list of everyone still waiting, and the sheet of every
 * answer. Every name, number, order and comment here is made up.
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
  history: [],
  no_answer_count: 0,
  message_sent: false,
  waiting_since: null,
  unreached_at: null,
  unreached_by_name: null,
  follow_up_round: 0,
  follow_up_state: null,
  conversation_id: null,
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
  overdue: 1,
  unreached: 1,
  solved: 1,
  solved_asked: 2,
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
    { id: "needs_follow_up", title: "To follow up" },
    { id: "resolved", title: "Resolved" },
    { id: "reopened", title: "Reopened" },
    { id: "unreached", title: "Couldn't reach" },
  ],
};

const ROWS = [
  row(1, {
    rating: "unhappy",
    reason: "delivery",
    comment: "It came two days late and the box was damaged",
    needs_follow_up: true,
    step: "support",
    follow_up_state: "needs_follow_up",
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
    follow_up_state: "resolved",
    history: [
      { id: 1, round: 0, kind: "no_answer", note: null, at: "2026-11-09T08:00:00+00:00", by_name: "Mariam" },
      { id: 2, round: 0, kind: "resolved", note: "Sent a new shirt", at: "2026-11-09T10:00:00+00:00", by_name: "Mariam" },
    ],
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

/** Someone waiting: unhappy, not called yet, her chat is 55. */
const WAITING = row(11, {
  customer_name: "Salma Fathy",
  phone: "201211112233",
  order_name: "#7120",
  rating: "unhappy",
  reason: "size_fit",
  step: "support",
  needs_follow_up: true,
  follow_up_state: "needs_follow_up",
  waiting_since: new Date(Date.now() - 6.5 * 3_600_000).toISOString(),
  conversation_id: 55,
});

type Served = {
  page?: (url: string) => [number, unknown];
  /** The open follow-ups (`/feedback/follow-up`); nobody waiting unless a test says otherwise. */
  followUp?: () => [number, unknown];
  /** The feature's switch, as the sheet itself reports it. On unless a test says otherwise. */
  enabled?: boolean;
  download?: () => Promise<Response>;
};

let calls: string[] = [];
let posts: { url: string; body: unknown }[] = [];
const feedbackCalls = () => calls.filter((url) => /^\/api\/inbox\/feedback\?/.test(url));
const followUpCalls = () => calls.filter((url) => url.startsWith("/api/inbox/feedback/follow-up"));
const lastFeedbackCall = () => feedbackCalls()[feedbackCalls().length - 1];
const query = (url: string) => new URL(url, "http://x").searchParams;

function serve(served: Served = {}) {
  calls = [];
  posts = [];
  vi.stubGlobal(
    "fetch",
    vi.fn((url: string, init?: RequestInit) => {
      if (init?.method === "POST") {
        posts.push({ url, body: init.body ? JSON.parse(String(init.body)) : null });
        return reply(200, { ...WAITING, no_answer_count: 1 });
      }
      calls.push(url);
      if (url.startsWith("/api/inbox/feedback/download")) {
        return served.download?.() ?? reply(200, {});
      }
      if (url.startsWith("/api/inbox/feedback/follow-up")) {
        const [status, body] = served.followUp?.() ?? [200, { rows: [], reply_hours: 24 }];
        return reply(status, body);
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
const answerGroup = () => screen.getByRole("group", { name: "Answer" });

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

describe("the summary cards", () => {
  it("four cards and the bar", async () => {
    serve();
    show();
    const summary = await screen.findByRole("group", { name: "Summary of these answers" });
    const card = (label: string) => within(summary).getByText(label).closest(".ops-tile") as HTMLElement;

    expect(summary.querySelectorAll(".ops-tile")).toHaveLength(4);

    const answered = card("Answered");
    expect(answered.textContent).toContain("5");
    expect(within(answered).getByText("of 6 asked")).toBeTruthy();
    expect(within(answered).getByText("83% answered")).toBeTruthy();

    const felt = card("How they felt");
    const bar = felt.querySelector(".inbox-fb__bar") as HTMLElement;
    expect(bar.children).toHaveLength(3);
    expect((bar.children[2] as HTMLElement).style.width).toBe("60%");
    for (const name of ["Loved it 1", "It was okay 1", "Not happy 3"]) {
      expect(within(felt).getByRole("button", { name }).getAttribute("aria-pressed")).toBe("false");
    }

    const waiting = card("To follow up");
    expect(waiting.textContent).toContain("2");
    expect(within(waiting).getByText("1 past the 24-hour promise")).toBeTruthy();

    const codes = card("Reward codes used");
    expect(within(codes).getByText("of 1 sent")).toBeTruthy();
    expect(within(codes).getByText("Problems solved: 1 of 2 asked")).toBeTruthy();

    // Nothing unreached: nothing said about it.
    expect(within(summary).queryByText(/couldn't be reached/)).toBeNull();
  });

  it("says how many could not be reached, and hides the percentage when nobody was asked", async () => {
    serve({
      page: () => [200, { rows: ROWS, next_offset: null, summary: { ...SUMMARY, not_reached: 3 }, options: OPTIONS }],
    });
    show();
    const summary = await screen.findByRole("group", { name: "Summary of these answers" });
    expect(within(summary).getByText("83% answered · 3 couldn't be reached")).toBeTruthy();
    cleanup();

    serve({
      page: () => [
        200,
        {
          rows: ROWS,
          next_offset: null,
          summary: { ...SUMMARY, asked: 0, answered: 0, not_reached: 2, overdue: 0, solved_asked: 0 },
          options: OPTIONS,
        },
      ],
    });
    show();
    const again = await screen.findByRole("group", { name: "Summary of these answers" });
    expect(within(again).queryByText(/% answered/)).toBeNull();
    expect(within(again).getByText("2 couldn't be reached")).toBeTruthy();
    expect(within(again).queryByText(/past the/)).toBeNull();
    expect(within(again).queryByText(/Problems solved/)).toBeNull();
  });

  it("narrows to an answer from its place in the bar, and back off again", async () => {
    serve();
    show();
    const summary = await screen.findByRole("group", { name: "Summary of these answers" });

    fireEvent.click(within(summary).getByRole("button", { name: "Not happy 3" }));
    await waitFor(() => expect(query(lastFeedbackCall()).get("rating")).toBe("unhappy"));
    expect(where()).toContain("rating=unhappy");
    expect(within(summary).getByRole("button", { name: "Not happy 3" }).getAttribute("aria-pressed")).toBe("true");

    fireEvent.click(within(summary).getByRole("button", { name: "Not happy 3" }));
    await waitFor(() => expect(query(lastFeedbackCall()).get("rating")).toBeNull());
  });
});

describe("the To follow up list", () => {
  it("the follow-up list shows only when someone waits and ignores filters", async () => {
    serve();
    show("/inbox/feedback?rating=loved&courier=Aramex");
    await screen.findByRole("table");
    await waitFor(() => expect(followUpCalls()).toHaveLength(1));
    expect(screen.queryByRole("heading", { name: /To follow up/ })).toBeNull();
    cleanup();

    serve({ followUp: () => [200, { rows: [WAITING], reply_hours: 24 }] });
    show("/inbox/feedback?rating=loved&courier=Aramex");
    const heading = await screen.findByRole("heading", { name: /To follow up/ });
    // Every open follow-up, whatever the sheet's filters say.
    expect(followUpCalls()[0]).toBe("/api/inbox/feedback/follow-up");
    expect(heading.textContent).toContain("1");

    const list = screen.getByRole("region", { name: /To follow up/ });
    expect(within(list).getByText("Longest-waiting first")).toBeTruthy();
    const card = within(list).getAllByRole("listitem")[0];
    expect(within(card).getByText("Salma Fathy").getAttribute("dir")).toBe("auto");
    expect(within(card).getByText("+20 121 111 2233 · #7120")).toBeTruthy();
    expect(within(card).getByText(/^Waiting 6 h · 17 h left$/)).toBeTruthy();
    expect(within(card).getByText("Not happy")).toBeTruthy();
    expect(within(card).getByText("Size / fit")).toBeTruthy();
    expect(within(card).getByText("No comment written")).toBeTruthy();
    expect(within(card).getByText("Not called yet")).toBeTruthy();
    expect(within(card).getByRole("button", { name: "Resolved…" })).toBeTruthy();
    expect(within(card).getByRole("button", { name: "No answer" })).toBeTruthy();
    expect(within(card).getByRole("button", { name: "Add note" })).toBeTruthy();
    expect(within(card).getByRole("link", { name: /Open chat/ }).getAttribute("href")).toBe(
      "/inbox/chats/55?view=follow_up",
    );
  });

  it("its pop-ups say what the server will really do", async () => {
    const twice = { ...WAITING, reopened_count: 2, no_answer_count: 1, message_sent: false };
    serve({ followUp: () => [200, { rows: [twice], reply_hours: 24 }], enabled: false });
    show();
    const list = await screen.findByRole("region", { name: /To follow up/ });
    await screen.findByRole("table");
    const card = within(list).getAllByRole("listitem")[0];

    fireEvent.click(within(card).getByRole("button", { name: "Resolved…" }));
    expect(screen.getByRole("dialog").textContent).toContain(
      "This closes the follow-up. She has said it wasn't solved twice, so she won't be asked again.",
    );
    fireEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Cancel" }));
    fireEvent.click(within(card).getByRole("button", { name: "No answer" }));
    expect(screen.getByRole("dialog").textContent).toContain(
      "Feedback messages are switched off, so nothing will be sent to her.",
    );
  });

  it("goes to the list from the To follow up card", async () => {
    serve({ followUp: () => [200, { rows: [WAITING], reply_hours: 24 }] });
    show();
    const heading = await screen.findByRole("heading", { name: /To follow up/ });
    const summary = screen.getByRole("group", { name: "Summary of these answers" });

    fireEvent.click(within(summary).getByRole("button", { name: /To follow up/ }));
    expect(document.activeElement).toBe(heading);
  });

  it("an action re-reads the list and the sheet", async () => {
    serve({ followUp: () => [200, { rows: [WAITING], reply_hours: 24 }] });
    show();
    const list = await screen.findByRole("region", { name: /To follow up/ });
    await screen.findByRole("table");
    const sheetReads = feedbackCalls().length;

    fireEvent.click(within(list).getByRole("button", { name: "No answer" }));
    const dialog = screen.getByRole("dialog", { name: "No answer: #7120" });
    fireEvent.click(within(dialog).getByRole("button", { name: "Save call" }));

    await waitFor(() => expect(posts).toHaveLength(1));
    expect(posts[0].url).toBe("/api/inbox/feedback/11/no-answer");
    await waitFor(() => expect(followUpCalls()).toHaveLength(2));
    await waitFor(() => expect(feedbackCalls().length).toBe(sheetReads + 1));
  });
});

describe("the Feedback sheet", () => {
  it("the sheet has seven columns", async () => {
    serve();
    show();

    const table = await screen.findByRole("table");
    expect(query(lastFeedbackCall()).get("since")).toBe(thirtyDaysBack());
    expect(query(lastFeedbackCall()).get("until")).toBeNull();

    const headings = within(table).getAllByRole("columnheader").map((cell) => cell.textContent);
    expect(headings).toEqual([
      "Asked", "Customer", "Order", "Answer", "What she said", "Follow-up", "Reward code",
    ]);

    const rows = within(table).getAllByRole("row").slice(1);
    expect(rows).toHaveLength(6);

    // Unhappy, reopened, still waiting on a person.
    const first = rows[0];
    expect(within(first).getByText("8 Nov")).toBeTruthy();
    expect(within(first).getByText("12:00")).toBeTruthy();
    expect(within(first).getByText("Habiba Tarek")).toBeTruthy();
    expect(within(first).getByText("+20 100 555 0103")).toBeTruthy();
    expect(within(first).getByText("#7001")).toBeTruthy();
    expect(within(first).getByText("Cotton shirt, Linen trousers · Bosta")).toBeTruthy();
    expect(within(first).getByText("Not happy")).toBeTruthy();
    expect(within(first).getByText("Delivery")).toBeTruthy();
    expect(within(first).getByText("To follow up").className).toContain("inbox-status--owed");
    expect(within(first).getByText("Not called yet · Reopened 1×")).toBeTruthy();

    // Resolved with a note, solved, would order again, code used on an order.
    const second = rows[1];
    expect(within(second).getByText("No name")).toBeTruthy();
    expect(within(second).getByText("Size / fit")).toBeTruthy();
    expect(within(second).getByText("Order again: Very likely")).toBeTruthy();
    expect(within(second).getByText("Resolved").className).toContain("inbox-status--settled");
    expect(within(second).getByText('Mariam · "Sent a new shirt" · solved')).toBeTruthy();
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

  it("says where each follow-up stands in one line under its chip", async () => {
    serve({
      page: () => [
        200,
        {
          rows: [
            row(1, {
              rating: "unhappy", step: "support", needs_follow_up: true, follow_up_state: "needs_follow_up",
              no_answer_count: 2, message_sent: true,
            }),
            row(2, {
              rating: "unhappy", step: "support", needs_follow_up: true, follow_up_state: "needs_follow_up",
              history: [{ id: 9, round: 0, kind: "note", note: "Wants a refund", at: "2026-11-09T10:00:00+00:00", by_name: "Ahmed" }],
            }),
            row(3, {
              rating: "unhappy", step: "done", follow_up_state: "unreached", no_answer_count: 3,
              unreached_at: "2026-11-10T10:00:00+00:00", unreached_by_name: "Mona",
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
    const rows = within(table).getAllByRole("row").slice(1);

    expect(within(rows[0]).getByText("2 calls, no answer · WhatsApp sent")).toBeTruthy();
    expect(within(rows[1]).getByText('"Wants a refund"')).toBeTruthy();
    expect(within(rows[2]).getByText("Couldn't reach").className).toContain("inbox-status--plain");
    expect(within(rows[2]).getByText("3 calls, no answer · closed by Mona")).toBeTruthy();
  });

  it("has a link to the feedback setup in its head, beside Download", async () => {
    serve();
    show();

    await screen.findByRole("table");
    const link = screen.getByRole("link", { name: "Feedback setup" });
    expect(link.getAttribute("href")).toBe("/inbox/feedback/setup");
  });

  it("asks again with each filter, and keeps each in the address", async () => {
    serve();
    show();
    await screen.findByRole("table");

    fireEvent.change(screen.getByLabelText("From"), { target: { value: "2026-10-01" } });
    await waitFor(() => expect(query(lastFeedbackCall()).get("since")).toBe("2026-10-01"));
    fireEvent.change(screen.getByLabelText("To"), { target: { value: "2026-10-31" } });
    await waitFor(() => expect(query(lastFeedbackCall()).get("until")).toBe("2026-10-31"));

    fireEvent.click(within(answerGroup()).getByRole("button", { name: "Not happy" }));
    await waitFor(() => expect(query(lastFeedbackCall()).get("rating")).toBe("unhappy"));
    fireEvent.click(screen.getByRole("button", { name: /More filters/ }));
    fireEvent.change(screen.getByLabelText("Reason"), { target: { value: "delivery" } });
    await waitFor(() => expect(query(lastFeedbackCall()).get("reason")).toBe("delivery"));
    fireEvent.change(screen.getByLabelText("Courier"), { target: { value: "Mylerz" } });
    await waitFor(() => expect(query(lastFeedbackCall()).get("courier")).toBe("Mylerz"));
    fireEvent.change(screen.getByLabelText("Follow-up"), { target: { value: "unreached" } });
    await waitFor(() => expect(query(lastFeedbackCall()).get("state")).toBe("unreached"));
    fireEvent.change(screen.getByLabelText("Search"), { target: { value: "7003" } });
    await waitFor(() => expect(query(lastFeedbackCall()).get("q")).toBe("7003"));

    const address = new URLSearchParams(where());
    expect(Object.fromEntries(address)).toMatchObject({
      since: "2026-10-01",
      until: "2026-10-31",
      rating: "unhappy",
      reason: "delivery",
      courier: "Mylerz",
      state: "unreached",
      q: "7003",
    });
  });

  it("no answer yet filters rating=none", async () => {
    serve();
    show();
    await screen.findByRole("table");

    const all = within(answerGroup()).getByRole("button", { name: "All" });
    expect(all.getAttribute("aria-pressed")).toBe("true");
    fireEvent.click(within(answerGroup()).getByRole("button", { name: "No answer yet" }));
    await waitFor(() => expect(query(lastFeedbackCall()).get("rating")).toBe("none"));
    expect(where()).toContain("rating=none");
    expect(within(answerGroup()).getByRole("button", { name: "No answer yet" }).getAttribute("aria-pressed")).toBe("true");
    // No answer has no reasons.
    fireEvent.click(screen.getByRole("button", { name: /More filters/ }));
    expect((screen.getByLabelText("Reason") as HTMLSelectElement).disabled).toBe(true);

    fireEvent.click(within(answerGroup()).getByRole("button", { name: "All" }));
    await waitFor(() => expect(query(lastFeedbackCall()).get("rating")).toBeNull());
  });

  it("more filters holds courier and reason and opens when one is set", async () => {
    serve();
    show();
    await screen.findByRole("table");

    const more = screen.getByRole("button", { name: /More filters/ });
    expect(more.getAttribute("aria-expanded")).toBe("false");
    expect(screen.queryByLabelText("Courier")).toBeNull();
    expect(screen.queryByLabelText("Reason")).toBeNull();
    fireEvent.click(more);
    expect(more.getAttribute("aria-expanded")).toBe("true");
    expect(screen.getByLabelText("Courier")).toBeTruthy();
    expect(screen.getByLabelText("Reason")).toBeTruthy();
    cleanup();

    serve();
    show("/inbox/feedback?courier=Bosta");
    await screen.findByRole("table");
    expect(screen.getByRole("button", { name: /More filters/ }).getAttribute("aria-expanded")).toBe("true");
    expect((screen.getByLabelText("Courier") as HTMLSelectElement).value).toBe("Bosta");
  });

  it("search covers products", async () => {
    serve();
    show();
    await screen.findByRole("table");

    // One box for order, name, phone and product; no separate Product box.
    expect(screen.queryByLabelText("Product")).toBeNull();
    const box = screen.getByLabelText("Search") as HTMLInputElement;
    expect(box.placeholder).toBe("Order, name, phone or product");
    fireEvent.change(box, { target: { value: "linen" } });
    await waitFor(() => expect(query(lastFeedbackCall()).get("q")).toBe("linen"));
    cleanup();

    // An old link with product= still filters, and says so.
    serve();
    show("/inbox/feedback?product=shirt");
    await screen.findByRole("table");
    expect(query(feedbackCalls()[0]).get("product")).toBe("shirt");
    expect(screen.getByRole("button", { name: /Product: shirt/ })).toBeTruthy();
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
    expect(within(answerGroup()).getByRole("button", { name: "Not happy" }).getAttribute("aria-pressed")).toBe("true");
    expect((screen.getByLabelText("Reason") as HTMLSelectElement).value).toBe("size_fit");
    expect((screen.getByLabelText("Courier") as HTMLSelectElement).value).toBe("Bosta");
    expect((screen.getByLabelText("Follow-up") as HTMLSelectElement).value).toBe("resolved");
    expect((screen.getByLabelText("Search") as HTMLInputElement).value).toBe("habiba");
  });

  it("offers reasons that belong to the answer, and only once an answer is chosen", async () => {
    serve();
    show();
    await screen.findByRole("table");
    fireEvent.click(screen.getByRole("button", { name: /More filters/ }));

    const reason = screen.getByLabelText("Reason") as HTMLSelectElement;
    expect(reason.disabled).toBe(true);
    expect(within(reason).getByText("Any reason")).toBeTruthy();
    expect(reason.getAttribute("title")).toBe("Choose an answer first");

    fireEvent.click(within(answerGroup()).getByRole("button", { name: "It was okay" }));
    await waitFor(() => expect(reason.disabled).toBe(false));
    expect(within(reason).getAllByRole("option").map((option) => option.textContent)).toEqual(["Any reason", "Price"]);

    fireEvent.change(reason, { target: { value: "price" } });
    await waitFor(() => expect(query(lastFeedbackCall()).get("reason")).toBe("price"));

    // Another answer has other reasons, and the old one is dropped.
    fireEvent.click(within(answerGroup()).getByRole("button", { name: "Not happy" }));
    await waitFor(() => expect(query(lastFeedbackCall()).get("rating")).toBe("unhappy"));
    expect(query(lastFeedbackCall()).get("reason")).toBeNull();
    expect(within(reason).getAllByRole("option").map((option) => option.textContent)).toEqual([
      "Any reason", "Size / fit", "Delivery",
    ]);

    // Back to any answer: no reason is asked for.
    fireEvent.click(within(answerGroup()).getByRole("button", { name: "All" }));
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
    expect(screen.queryByRole("button", { name: /Product: shirt/ })).toBeNull();
    expect(query(lastFeedbackCall()).get("since")).toBe(thirtyDaysBack());
    expect(query(lastFeedbackCall()).get("rating")).toBeNull();
    expect(query(lastFeedbackCall()).get("product")).toBeNull();
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
              courier: null,
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
  it("is a list of cards in the table's order, not a table to scroll sideways", async () => {
    narrowScreen(true);
    serve();
    show();

    const sheet = await screen.findByRole("region", { name: "All answers" });
    await within(sheet).findByText("Cotton shirt, Linen trousers · Bosta");
    expect(screen.queryByRole("table")).toBeNull();

    const cards = within(sheet).getAllByRole("listitem");
    expect(cards).toHaveLength(6);
    const first = cards[0];
    expect(within(first).getByText("#7001")).toBeTruthy();
    expect(within(first).getByText("Habiba Tarek")).toBeTruthy();
    expect(within(first).getByText("Not happy")).toBeTruthy();
    expect(within(first).getByText("Delivery")).toBeTruthy();
    expect(within(first).getByText("It came two days late and the box was damaged")).toBeTruthy();
    expect(within(first).getByText("To follow up")).toBeTruthy();
    expect(within(first).getByText("Not called yet · Reopened 1×")).toBeTruthy();
    expect(within(cards[1]).getByText("Used on #7100")).toBeTruthy();
    expect(within(cards[2]).getByText("No answer yet")).toBeTruthy();
    expect(within(cards[4]).getByText("Could not be sent: Meta said no")).toBeTruthy();
  });
});
