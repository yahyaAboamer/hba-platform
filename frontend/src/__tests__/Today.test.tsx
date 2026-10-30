// @vitest-environment jsdom
/**
 * Today (Phase 2, Batch 2.2): who gets it and where they start, the page as
 * the approved mockup draws it, and the sidebar's numbers coming from the
 * same one read of `/api/today`.
 */
import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import App from "../App";
import { startFor } from "../departments";
import { headingDate, ordersSentence, waitingSentence, weekRange, whenText } from "../departments/today/Today";
import type { TodayItem, TodayOrders } from "../departments/today/types";
import { asked, serve, sessionOf } from "./frameHarness";
import type { Answers, Kind } from "./frameHarness";

beforeEach(() => window.history.pushState({}, "", "/"));
afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

const NOW = Date.parse("2026-10-25T09:23:00Z"); // 12:23 in Cairo (UTC+3 until the 29th)

function item(over: Partial<TodayItem>): TodayItem {
  return {
    key: "x",
    department: "inbox",
    broken: false,
    late: false,
    what: "Something",
    detail: "A detail",
    since: null,
    due: null,
    when: null,
    go: { label: "Open", to: "/inbox/chats" },
    ...over,
  };
}

const BOSTA = item({
  key: "operations.source_failed.bosta",
  department: "operations",
  broken: true,
  late: true,
  what: "Bosta has not been read since 09:40",
  detail: "Its last try failed at 14:20. Its screen shows the last good read.",
  since: "2026-10-25T04:40:00Z",
  when: "elapsed",
  go: { label: "Open Bosta", to: "/operations/bosta" },
});
const CHATS = item({
  key: "inbox.unread",
  what: "6 customers are waiting for a reply",
  detail: "The oldest wrote at 12:13",
  since: "2026-10-25T07:13:00Z",
  late: true,
  when: "elapsed",
  go: { label: "Open Chats", to: "/inbox/chats" },
});
const EDITS = item({
  key: "inbox.edit",
  what: "3 customers asked to change their order",
  detail: "They answered Change on the confirmation message",
  since: "2026-10-25T07:05:00Z",
  when: "since",
  go: { label: "Open", to: "/inbox/chats" },
});
const TARGETS = item({
  key: "affiliates.targets",
  department: "affiliates",
  what: "November targets are not set",
  detail: "23 active models; November starts Sunday",
  due: "2026-11-01",
  when: "deadline",
  go: { label: "Set targets", to: "/affiliates/targets?month=2026-11" },
});
const PAYMENTS = item({
  key: "affiliates.payments",
  department: "affiliates",
  what: "19 payments waiting for approval",
  detail: "October 2026",
  go: { label: "Review", to: "/affiliates/payments?month=2026-10" },
});

const ORDERS: TodayOrders = {
  from: "2026-10-19",
  to: "2026-10-25",
  placed: 412,
  bosta_as_of: "2026-10-25T06:38:00Z",
  rows: [
    { key: "waiting", label: "Waiting for an answer", department: "Inbox", count: 8 },
    { key: "confirmed", label: "Confirmed, not with Bosta", department: "Operations", count: 17 },
    { key: "with_bosta", label: "With Bosta", department: "Operations", count: 121 },
    { key: "delivered", label: "Delivered", department: "", count: 241 },
    { key: "cancelled", label: "Cancelled or returned", department: "Operations", count: 25 },
  ],
};

async function open(address: string, kind: Kind, answers: Answers = {}) {
  window.history.pushState({}, "", address);
  serve(sessionOf(kind), answers);
  render(<App />);
  await screen.findByRole("navigation", { name: "Departments" });
}

const here = () => window.location.pathname + window.location.search;

function narrow() {
  vi.stubGlobal("matchMedia", (query: string) => ({
    matches: query.includes("max-width"),
    media: query,
    addEventListener: () => undefined,
    removeEventListener: () => undefined,
  }));
}

describe("who has Today and where they start", () => {
  it("starts anyone holding two or more departments on Today", () => {
    expect(startFor(sessionOf("owner"))).toBe("/today");
    expect(startFor(sessionOf("operations_manager"))).toBe("/today");
  });

  it("starts a one-department person in it, as before", () => {
    expect(startFor(sessionOf("operations_only"))).toBe("/operations/shopify");
    expect(startFor(sessionOf("customer_service"))).toBe("/inbox/chats");
    expect(startFor(sessionOf("affiliate_manager"))).toBe("/affiliates/overview");
    expect(startFor(sessionOf("content_manager"))).toBe("/affiliates/overview");
  });

  it("opens `/` on Today for the owner and the operations manager", async () => {
    await open("/", "owner");
    await waitFor(() => expect(here()).toBe("/today"));
    cleanup();

    await open("/", "operations_manager");
    await waitFor(() => expect(here()).toBe("/today"));
  });

  it("sends `/today` to their start for somebody holding one department", async () => {
    await open("/today", "customer_service");
    await waitFor(() => expect(here()).toBe("/inbox/chats"));
    cleanup();

    await open("/today", "affiliate_manager");
    await waitFor(() => expect(here()).toBe("/affiliates/overview"));
  });

  it("puts a Today row first, only for two or more departments", async () => {
    await open("/operations/shopify", "owner");
    const today = screen.getByRole("link", { name: /^Today/ });
    expect(today.getAttribute("href")).toBe("/today");
    expect(today.getAttribute("aria-current")).toBeNull();
    const rows = within(screen.getByRole("navigation", { name: "Departments" })).getAllByRole("listitem");
    expect(rows[0].textContent).toContain("Today");
    cleanup();

    await open("/operations/shopify", "operations_only");
    expect(screen.queryByRole("link", { name: /^Today/ })).toBeNull();
    cleanup();

    await open("/inbox/chats", "customer_service");
    expect(screen.queryByRole("link", { name: /^Today/ })).toBeNull();
  });

  it("marks Today as the current page, with the brand and the phone's bar saying Today", async () => {
    await open("/today", "owner", { items: [BOSTA] });

    expect(screen.getByRole("link", { name: /^Today/ }).getAttribute("aria-current")).toBe("page");
    expect(screen.getByText("Today", { selector: ".frame__role" })).toBeTruthy();
    expect(document.querySelector(".frame__pbar-title")?.textContent).toBe("Today");
  });

  it("counts the things waiting in the row, with a sentence for whoever cannot see it", async () => {
    await open("/operations/shopify", "owner", { items: [BOSTA, CHATS, EDITS] });

    const today = screen.getByRole("link", { name: /^Today/ });
    await waitFor(() => expect(today.textContent).toContain("3"));
    expect(today.textContent).toContain("things waiting for you");
  });

  it("draws no count when nothing is waiting", async () => {
    await open("/operations/shopify", "owner", { items: [] });

    await waitFor(() => expect(asked().some((url) => url.endsWith("/api/today"))).toBe(true));
    await new Promise((resolve) => setTimeout(resolve, 50));
    expect(within(screen.getByRole("link", { name: /^Today/ })).queryByText(/\d/)).toBeNull();
  });
});

describe("the sidebar's numbers come from the one read of /api/today", () => {
  it("shows counts and the red dot from it, and asks for nothing else", async () => {
    await open("/affiliates/overview", "owner", {
      unread: 6,
      counts: { models_awaiting_approval: 2, payments_awaiting_approval: 3 },
      freshness: { bosta: { state: "failed", updated_at: "2026-01-15T10:05:00+00:00" } },
    });

    const inbox = screen.getByRole("button", { name: /^Inbox/ });
    await waitFor(() => expect(inbox.textContent).toContain("6"));
    await waitFor(() =>
      expect(screen.getByRole("button", { name: /^Operations/ }).querySelector(".frame__alert")).not.toBeNull(),
    );
    const models = screen.getByRole("link", { name: /^Models/ });
    await within(models).findByText("2");

    const urls = asked();
    expect(urls.filter((url) => url.endsWith("/api/today"))).toHaveLength(1);
    expect(urls.some((url) => url.endsWith("/api/operations/counts"))).toBe(false);
    expect(urls.some((url) => url.endsWith("/api/operations/freshness"))).toBe(false);
    expect(urls.some((url) => url.includes("/api/inbox/conversations"))).toBe(false);
  });

  it("shows no numbers at all when the read fails, never 0", async () => {
    await open("/operations/shopify", "owner", { today: "failed" });

    await new Promise((resolve) => setTimeout(resolve, 50));
    expect(document.querySelector(".frame__count")).toBeNull();
    expect(document.querySelector(".frame__alert")).toBeNull();
  });
});

describe("the time column", () => {
  it("writes elapsed time as minutes, hours and minutes, or days", () => {
    const at = (iso: string) => whenText({ when: "elapsed", since: iso, due: null }, NOW);
    expect(at("2026-10-25T09:00:00Z")).toBe("23 m");
    expect(at("2026-10-25T04:40:00Z")).toBe("4 h 43 m");
    expect(at("2026-10-24T09:23:00Z")).toBe("1 day");
    expect(at("2026-10-22T08:00:00Z")).toBe("3 days");
  });

  it("writes since as a time today, yesterday, or a date", () => {
    const at = (iso: string) => whenText({ when: "since", since: iso, due: null }, NOW);
    expect(at("2026-10-25T07:05:00Z")).toBe("since 10:05");
    expect(at("2026-10-24T15:00:00Z")).toBe("since yesterday");
    expect(at("2026-10-20T15:00:00Z")).toBe("since 20 Oct");
  });

  it("writes a deadline as days left, counting Cairo days", () => {
    const at = (due: string) => whenText({ when: "deadline", since: null, due }, NOW);
    expect(at("2026-11-01")).toBe("7 days left");
    expect(at("2026-10-26")).toBe("1 day left");
    expect(at("2026-10-25")).toBe("today");
    expect(at("2026-10-24")).toBe("overdue");
  });

  it("leaves it blank when the server gives no style", () => {
    expect(whenText({ when: null, since: "2026-10-25T07:05:00Z", due: null }, NOW)).toBe("");
  });

  it("says the heading date and the count in plain words", () => {
    expect(headingDate(NOW)).toBe("Sunday 25 October");
    expect(waitingSentence(9)).toBe("9 things are waiting for you");
    expect(waitingSentence(1)).toBe("1 thing is waiting for you");
    expect(waitingSentence(0)).toBe("Nothing is waiting for you");
  });
});

describe("the page", () => {
  beforeEach(() => vi.useFakeTimers({ toFake: ["Date"], now: NOW }));

  it("lists the items in the order given, broken first and red, with each button's address", async () => {
    await open("/today", "owner", { items: [BOSTA, CHATS, EDITS, TARGETS, PAYMENTS] });

    const list = await screen.findByRole("list", { name: "" }).catch(() => null);
    expect(list).toBeNull(); // the list has no name of its own: the panel's heading names it
    const rows = await waitFor(() => {
      const found = Array.from(document.querySelectorAll(".wait > li"));
      expect(found).toHaveLength(5);
      return found as HTMLElement[];
    });
    expect(rows.map((row) => row.querySelector(".wait__what")?.firstChild?.textContent)).toEqual([
      BOSTA.what,
      CHATS.what,
      EDITS.what,
      TARGETS.what,
      PAYMENTS.what,
    ]);

    expect(rows[0].classList.contains("is-alert")).toBe(true);
    expect(rows[1].classList.contains("is-alert")).toBe(false);
    expect(within(rows[0]).getByText("Operations").className).toBe("wait__from");
    expect(rows[0].textContent).toContain("Its last try failed at 14:20.");
    const go = rows.map((row) => within(row).getByRole("link"));
    expect(go.map((link) => [link.textContent, link.getAttribute("href")])).toEqual([
      ["Open Bosta", "/operations/bosta"],
      ["Open Chats", "/inbox/chats"],
      ["Open", "/inbox/chats"],
      ["Set targets", "/affiliates/targets?month=2026-11"],
      ["Review", "/affiliates/payments?month=2026-10"],
    ]);
    // The first, because it is broken, is the primary button.
    expect(go[0].classList.contains("button--primary")).toBe(true);
    expect(go[1].classList.contains("button--primary")).toBe(false);
  });

  it("writes each time in its style, orange when late, blank when there is none", async () => {
    await open("/today", "owner", { items: [BOSTA, CHATS, EDITS, TARGETS, PAYMENTS] });

    const whens = await waitFor(() => {
      const found = Array.from(document.querySelectorAll(".wait__when"));
      expect(found).toHaveLength(5);
      return found as HTMLElement[];
    });
    expect(whens.map((cell) => cell.textContent)).toEqual(["4 h 43 m", "2 h 10 m", "since 10:05", "7 days left", ""]);
    expect(whens.map((cell) => cell.classList.contains("wait__when--late"))).toEqual([true, true, false, false, false]);
  });

  it("says what is waiting under the heading, and when it was read", async () => {
    await open("/today", "owner", { items: [BOSTA, CHATS] });

    expect(await screen.findByText("Sunday 25 October · 2 things are waiting for you")).toBeTruthy();
    expect(screen.getByRole("heading", { name: "Waiting for you" })).toBeTruthy();
    expect(screen.getByText("From Inbox, Operations and Affiliates")).toBeTruthy();
    expect(screen.getByRole("status").textContent).toBe("Updated just now");
  });

  it("names only the departments this person holds", async () => {
    await open("/today", "operations_manager", { items: [CHATS] });

    expect(await screen.findByText("From Inbox and Operations")).toBeTruthy();
  });

  it("says Nothing is waiting for you inside the panel", async () => {
    await open("/today", "owner", { items: [] });

    expect(await screen.findByText("Nothing is waiting for you.")).toBeTruthy();
    expect(screen.getByText("Sunday 25 October · Nothing is waiting for you")).toBeTruthy();
  });

  it("says a department could not be read, at the end of the list, and does not claim nothing waits", async () => {
    await open("/today", "owner", { items: [BOSTA], unreadDepartments: ["inbox"] });

    const note = await screen.findByText("Inbox could not be read just now.");
    expect(note.parentElement?.lastElementChild).toBe(note);
    cleanup();

    await open("/today", "owner", { items: [], unreadDepartments: ["inbox"] });
    await screen.findByText("Inbox could not be read just now.");
    expect(screen.queryByText("Nothing is waiting for you.")).toBeNull();
  });

  it("says so when the whole read fails, and that it will try again", async () => {
    await open("/today", "owner", { today: "failed" });

    expect(await screen.findByText("Could not read what is waiting. Trying again every 30 seconds.")).toBeTruthy();
  });
});

describe("Orders, last 7 days", () => {
  beforeEach(() => vi.useFakeTimers({ toFake: ["Date"], now: NOW }));

  it("is absent when the server sends none, and the list takes the full width", async () => {
    await open("/today", "owner", { items: [BOSTA], orders: null });

    await screen.findByText(BOSTA.what);
    expect(screen.queryByRole("heading", { name: "Orders, last 7 days" })).toBeNull();
    expect(document.querySelector(".today--single")).not.toBeNull();
  });

  it("draws the bar, the rows with their share to one decimal, and the total", async () => {
    await open("/today", "owner", { items: [BOSTA], orders: ORDERS });

    const panel = (await screen.findByRole("heading", { name: "Orders, last 7 days" })).closest("section") as HTMLElement;
    expect(within(panel).getByText("19–25 October")).toBeTruthy();
    const body = Array.from(panel.querySelectorAll("tbody tr")).map((row) =>
      Array.from(row.querySelectorAll("td")).map((cell) => cell.textContent),
    );
    expect(body).toEqual([
      ["Waiting for an answerInbox", "8", "1.9%"],
      ["Confirmed, not with BostaOperations", "17", "4.1%"],
      ["With BostaOperations · as of 09:38", "121", "29.4%"],
      ["Delivered", "241", "58.5%"],
      ["Cancelled or returnedOperations", "25", "6.1%"],
      ["Placed", "412", "100%"],
    ]);
    const bar = within(panel).getByRole("img");
    expect(bar.getAttribute("aria-label")).toBe(
      "412 orders: 8 waiting for an answer, 17 confirmed, not with Bosta, 121 with Bosta, 241 delivered, 25 cancelled or returned",
    );
    expect(Array.from(bar.children).map((part) => (part as HTMLElement).style.flexGrow)).toEqual([
      "8", "17", "121", "241", "25",
    ]);
  });

  it("writes the week across a month's end, and one order in the singular", () => {
    expect(weekRange("2026-10-28", "2026-11-03")).toBe("28 October – 3 November");
    expect(ordersSentence({ ...ORDERS, placed: 1, rows: [{ ...ORDERS.rows[3], count: 1 }] })).toBe(
      "1 order: 1 delivered",
    );
  });
});

describe("on a phone", () => {
  beforeEach(() => {
    vi.useFakeTimers({ toFake: ["Date"], now: NOW });
    narrow();
  });

  it("has no head row, only a heading for screen readers: the sub line, then every row a link, the orders below", async () => {
    await open("/today", "operations_manager", { items: [BOSTA, CHATS], orders: ORDERS });

    expect(await screen.findByText("Sunday 25 October · 2 things are waiting for you")).toBeTruthy();
    // No visible head row: the heading is there for screen readers only.
    expect(screen.getByRole("heading", { level: 1, name: "Today" }).classList.contains("visually-hidden")).toBe(true);
    expect(document.querySelector(".page__head")).toBeNull();
    const rows = Array.from(document.querySelectorAll("a.prow")) as HTMLAnchorElement[];
    expect(rows.map((row) => row.getAttribute("href"))).toEqual(["/operations/bosta", "/inbox/chats"]);
    expect(rows[0].classList.contains("is-alert")).toBe(true);
    expect(rows[0].textContent).toContain("Operations");
    expect(rows[0].textContent).toContain(BOSTA.what);
    expect(rows[0].querySelector(".prow__when--late")?.textContent).toBe("4 h 43 m");
    expect(screen.getByRole("heading", { name: "Orders, last 7 days" })).toBeTruthy();
  });
});
