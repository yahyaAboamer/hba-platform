// @vitest-environment jsdom
/**
 * Inbox → Chats (ADR 0059; the approved mockup's frames 1 and 2). Every
 * name, number, order and message here is made up.
 */
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { InboxChats } from "../InboxChats";

const reply = (status: number, body: unknown) =>
  Promise.resolve({
    ok: status < 400,
    status,
    headers: { get: () => "application/json" },
    json: () => Promise.resolve(body),
    text: () => Promise.resolve(JSON.stringify(body)),
  } as unknown as Response);

const minutesAgo = (minutes: number) => new Date(Date.now() - minutes * 60_000).toISOString();
const hoursFromNow = (hours: number) => new Date(Date.now() + hours * 3_600_000).toISOString();

const chat = (id: number, extra: object = {}) => ({
  id,
  phone: "201005550188",
  name: "Nour Adel",
  last_message_at: minutesAgo(1),
  last_preview: "Yes M",
  last_direction: "in",
  unread_count: 0,
  window_open: true,
  window_closes_at: hoursFromNow(23),
  answer: null,
  ...extra,
});

const message = (id: number, extra: object = {}) => ({
  id,
  direction: "in",
  kind: "text",
  body: "Hello",
  status: "received",
  error: null,
  origin: "customer",
  sender: null,
  reply_to: null,
  template: null,
  buttons: null,
  tapped: null,
  voice: false,
  order_id: null,
  at: minutesAgo(30 - id),
  media: null,
  ...extra,
});

const chatOrder = (extra: object = {}) => ({
  order_id: "5001",
  order: "#31044",
  admin_url: "https://hbawear.myshopify.com/admin/orders/5001",
  state: "sent",
  answer: "edit",
  answered_at: minutesAgo(20),
  placed_at: minutesAgo(25),
  sent_at: minutesAgo(24),
  total: "1450.00",
  tag: "Edit ✏️",
  why: null,
  can_send_again: false,
  ...extra,
});

const COUNTS = { all: 2995, unread: 4, edit: 3 };
const HEALTH = { connected: true, sending: true, last_heard_at: minutesAgo(1), quiet_since: null };

type Served = {
  list?: (url: string) => unknown;
  detail?: object;
  messages?: object[];
  earlier?: string | null;
  health?: object;
  post?: (url: string, body: Record<string, unknown>) => [number, unknown];
};

let calls: { method: string; url: string; body: Record<string, unknown> | null }[] = [];

function serve(served: Served = {}) {
  calls = [];
  const detail = { ...chat(12), orders: [chatOrder()], ...served.detail };
  vi.stubGlobal(
    "fetch",
    vi.fn((url: string, init?: RequestInit) => {
      const method = init?.method ?? "GET";
      const body = init?.body ? (JSON.parse(String(init.body)) as Record<string, unknown>) : null;
      calls.push({ method, url, body });
      if (method === "POST") {
        const [status, answer] = served.post?.(url, body ?? {}) ?? [200, { ...detail, unread_count: 0 }];
        return reply(status, answer);
      }
      if (url.startsWith("/api/inbox/health")) return reply(200, served.health ?? HEALTH);
      if (/\/conversations\/\d+\/messages/.test(url)) {
        return reply(200, { messages: served.messages ?? [], earlier: served.earlier ?? null });
      }
      if (/\/conversations\/999$/.test(url)) return reply(404, { detail: "No such conversation." });
      if (/\/conversations\/\d+$/.test(url)) return reply(200, detail);
      return reply(
        200,
        served.list?.(url) ?? {
          conversations: [chat(12), chat(13, { name: "Salma Hany" })],
          next: null,
          counts: COUNTS,
        },
      );
    }),
  );
}

const posts = () => calls.filter((call) => call.method === "POST");

function show(address = "/inbox/chats") {
  return render(
    <MemoryRouter initialEntries={[address]}>
      <Routes>
        <Route path="/inbox/chats" element={<InboxChats />} />
        <Route path="/inbox/chats/:conversationId" element={<InboxChats />} />
      </Routes>
    </MemoryRouter>,
  );
}

beforeEach(() => {
  vi.stubGlobal(
    "matchMedia",
    vi.fn(() => ({ matches: false, addEventListener: () => undefined, removeEventListener: () => undefined })),
  );
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("the list of chats", () => {
  it("shows who each chat is with, what was last said, and what is unread", async () => {
    serve({
      list: () => ({
        conversations: [
          chat(12, { unread_count: 2, last_preview: "Voice note" }),
          chat(13, { name: null, phone: "201005550143", last_preview: "Photo" }),
          chat(14, { name: "Habiba Tarek", last_direction: "out", last_preview: "Done, it will ship tomorrow." }),
          chat(15, { name: "Mai Ashraf", last_preview: "Tapped Cancel", answer: "cancelled" }),
        ],
        next: null,
        counts: COUNTS,
      }),
    });
    show();

    const nour = await screen.findByRole("link", { name: /Nour Adel/ });
    expect(nour.getAttribute("href")).toBe("/inbox/chats/12");
    expect(within(nour).getByText("2")).toBeTruthy();
    expect(within(nour).getByText("Voice note")).toBeTruthy();
    // Nobody has named her yet: her number stands in.
    expect(screen.getByRole("link", { name: /\+20 100 555 0143/ })).toBeTruthy();
    expect(within(screen.getByRole("link", { name: /Habiba Tarek/ })).getByText("Sent:")).toBeTruthy();
    expect(within(screen.getByRole("link", { name: /Mai Ashraf/ })).getByText("Cancel")).toBeTruthy();

    expect(screen.getByText("2,995 conversations")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Unread · 4" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Wants a change · 3" })).toBeTruthy();
    expect(screen.getByText("Live")).toBeTruthy();
  });

  it("narrows to a view", async () => {
    serve();
    show();

    fireEvent.click(await screen.findByRole("button", { name: "Unread · 4" }));

    await waitFor(() =>
      expect(calls.some((call) => call.url === "/api/inbox/conversations?view=unread")).toBe(true),
    );
    expect(screen.getByRole("button", { name: "Unread · 4" }).getAttribute("aria-pressed")).toBe("true");
  });

  it("searches by name, phone or order number, and says when nothing matches", async () => {
    serve({
      list: (url) =>
        url.includes("q=")
          ? { conversations: [], next: null, counts: COUNTS }
          : { conversations: [chat(12)], next: null, counts: COUNTS },
    });
    show();
    await screen.findByRole("link", { name: /Nour Adel/ });

    fireEvent.change(screen.getByRole("searchbox", { name: "Search chats" }), {
      target: { value: "#99999" },
    });

    expect(await screen.findByText(/No chat matches “#99999”\./)).toBeTruthy();
    expect(screen.getByText(/Check the number, or search by phone\./)).toBeTruthy();
    expect(calls.some((call) => call.url === "/api/inbox/conversations?q=%2399999")).toBe(true);
  });

  it("reaches every chat, a page at a time", async () => {
    serve({
      list: (url) =>
        url.includes("before=")
          ? {
              conversations: [chat(3, { name: "Laila Emad", last_message_at: minutesAgo(900) })],
              next: null,
              counts: COUNTS,
            }
          : { conversations: [chat(12)], next: "2026-10-11T10:00:00+00:00|12", counts: COUNTS },
    });
    show();

    fireEvent.click(await screen.findByRole("button", { name: "Show older chats" }));

    expect(await screen.findByRole("link", { name: /Laila Emad/ })).toBeTruthy();
    expect(screen.getByRole("link", { name: /Nour Adel/ })).toBeTruthy();
    expect(
      calls.some((call) => call.url.includes("before=2026-10-11T10%3A00%3A00%2B00%3A00%7C12")),
    ).toBe(true);
    expect(screen.queryByRole("button", { name: "Show older chats" })).toBeNull();
  });

  it("says so when WhatsApp has gone quiet", async () => {
    serve({ health: { ...HEALTH, quiet_since: minutesAgo(40) } });
    show();

    expect(await screen.findByText("WhatsApp quiet for 40 minutes")).toBeTruthy();
  });

  it("asks for a chat to be chosen before one is open", async () => {
    serve();
    show();

    expect(await screen.findByText("Choose a chat to read it.")).toBeTruthy();
    expect(screen.queryByRole("textbox", { name: "Message" })).toBeNull();
  });
});

describe("an open chat", () => {
  const THREAD = [
    message(1, {
      direction: "out",
      kind: "template",
      origin: "automatic",
      status: "read",
      order_id: "5001",
      body: "Hi Nour, thank you for your order #31044.",
      buttons: ["Confirm", "Edit", "Cancel"],
    }),
    message(2, { kind: "button", body: "Edit", tapped: "edit", order_id: "5001" }),
    message(3, { body: "I want it in beige please" }),
    message(4, {
      kind: "image",
      body: "This one",
      media: {
        id: 9,
        state: "stored",
        mime_type: "image/jpeg",
        filename: "a.jpg",
        size_bytes: 2048,
        url: "/api/inbox/media/9",
      },
    }),
    message(5, {
      direction: "out",
      origin: "staff",
      sender: "Mariam",
      status: "delivered",
      body: "Beige in the same size, M?",
      reply_to: { id: 4, direction: "in", kind: "image", body: "This one" },
    }),
  ];

  const ours = (id: number, extra: object = {}) =>
    message(id, { direction: "out", origin: "staff", sender: "Mariam", status: "sent", at: minutesAgo(0), ...extra });

  it("shows who she is, how long replies stay open, and the chat itself", async () => {
    serve({ messages: THREAD });
    show("/inbox/chats/12");

    const pane = await screen.findByRole("region", { name: "Chat with Nour Adel" });
    expect(within(pane).getByRole("heading", { name: "Nour Adel" })).toBeTruthy();
    expect(
      within(pane).getByText(/\+20 100 555 0188 · can reply freely until \d\d:\d\d (today|tomorrow)/),
    ).toBeTruthy();

    await within(pane).findByText("I want it in beige please");
    expect(within(pane).getByText("Today")).toBeTruthy();
    expect(within(pane).getByText("Automatic · order confirmation")).toBeTruthy();
    // The button she tapped is marked on the confirmation, and noted below it.
    expect(within(pane).getByText("(tapped)").parentElement?.textContent).toContain("Edit");
    expect(within(pane).getByText("Nour tapped Edit · the order is now tagged Edit ✏️")).toBeTruthy();
    // Every reply carries the name of who sent it, and how far it got.
    expect(within(pane).getByText("Mariam")).toBeTruthy();
    expect(within(pane).getByRole("img", { name: "Delivered" })).toBeTruthy();
    expect(within(pane).getByRole("img", { name: "Read" })).toBeTruthy();
    expect(within(pane).getByRole("img", { name: "Photo from Nour" }).getAttribute("src")).toBe(
      "/api/inbox/media/9",
    );
    expect(within(pane).getByText("In reply to:").parentElement?.textContent).toContain("This one");
  });

  it("marks her read when it opens with something unread", async () => {
    serve({ detail: { unread_count: 2 }, messages: THREAD });
    show("/inbox/chats/12");

    await waitFor(() =>
      expect(posts().map((call) => call.url)).toContain("/api/inbox/conversations/12/read"),
    );
  });

  it("leaves a chat with nothing unread alone", async () => {
    serve({ messages: THREAD });
    show("/inbox/chats/12");

    await screen.findByText("I want it in beige please");
    expect(posts()).toEqual([]);
  });

  it("sends what is typed, under the staff member's name", async () => {
    serve({ messages: THREAD, post: () => [200, ours(6, { body: "Done ✅" })] });
    show("/inbox/chats/12");
    const box = (await screen.findByRole("textbox", { name: "Message" })) as HTMLTextAreaElement;

    fireEvent.change(box, { target: { value: "Done ✅" } });
    fireEvent.click(screen.getByRole("button", { name: "Send" }));

    expect(await screen.findByText("Done ✅")).toBeTruthy();
    expect(posts()[0]).toMatchObject({
      url: "/api/inbox/conversations/12/messages",
      body: { body: "Done ✅", reply_to: null },
    });
    await waitFor(() => expect(box.value).toBe(""));
  });

  it("sends on Enter, and keeps Shift+Enter for a new line", async () => {
    serve({ messages: THREAD, post: () => [200, ours(6, { body: "Yes" })] });
    show("/inbox/chats/12");
    const box = await screen.findByRole("textbox", { name: "Message" });

    fireEvent.change(box, { target: { value: "Yes" } });
    fireEvent.keyDown(box, { key: "Enter", shiftKey: true });
    expect(posts()).toEqual([]);
    fireEvent.keyDown(box, { key: "Enter" });

    await waitFor(() => expect(posts()).toHaveLength(1));
  });

  it("keeps the words and gives the reason when a message may not be sent", async () => {
    serve({
      messages: THREAD,
      post: () => [409, { detail: "Sending is switched off. An admin turns it on in Settings." }],
    });
    show("/inbox/chats/12");
    const box = (await screen.findByRole("textbox", { name: "Message" })) as HTMLTextAreaElement;

    fireEvent.change(box, { target: { value: "Hello" } });
    fireEvent.click(screen.getByRole("button", { name: "Send" }));

    expect((await screen.findByRole("alert")).textContent).toBe(
      "Sending is switched off. An admin turns it on in Settings.",
    );
    expect(box.value).toBe("Hello");
  });

  it("shows a message WhatsApp refused, with why and a way to try again", async () => {
    serve({
      messages: [
        ...THREAD,
        ours(6, { status: "failed", body: "Yes, it is.", error: "WhatsApp could not reach this number." }),
      ],
      post: () => [200, ours(7, { body: "Yes, it is." })],
    });
    show("/inbox/chats/12");

    expect(await screen.findByText(/Not sent: WhatsApp could not reach this number\./)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));

    await waitFor(() =>
      expect(posts()[0]).toMatchObject({
        url: "/api/inbox/conversations/12/messages",
        body: { body: "Yes, it is.", reply_to: null },
      }),
    );
  });

  it("answers one message in particular", async () => {
    serve({ messages: THREAD, post: () => [200, ours(6, { body: "Of course" })] });
    show("/inbox/chats/12");
    const hers = (await screen.findByText("I want it in beige please")).closest(".inbox-msg") as HTMLElement;

    fireEvent.click(within(hers).getByRole("button", { name: "Reply to this message" }));
    expect(screen.getByText("Replying to:").parentElement?.textContent).toContain("I want it in beige please");
    fireEvent.change(screen.getByRole("textbox", { name: "Message" }), { target: { value: "Of course" } });
    fireEvent.click(screen.getByRole("button", { name: "Send" }));

    await waitFor(() => expect(posts()[0]?.body).toEqual({ body: "Of course", reply_to: 3 }));
    await waitFor(() => expect(screen.queryByText("Replying to:")).toBeNull());
  });

  it("reacts to a message", async () => {
    serve({
      messages: THREAD,
      post: () => [
        200,
        ours(6, { kind: "reaction", body: "👍", reply_to: { id: 3, direction: "in", kind: "text", body: "x" } }),
      ],
    });
    show("/inbox/chats/12");
    const hers = (await screen.findByText("I want it in beige please")).closest(".inbox-msg") as HTMLElement;

    fireEvent.click(within(hers).getByRole("button", { name: "React to this message" }));
    fireEvent.click(within(hers).getByRole("button", { name: "👍" }));

    await waitFor(() =>
      expect(posts()[0]).toMatchObject({
        url: "/api/inbox/conversations/12/reactions",
        body: { message_id: 3, emoji: "👍" },
      }),
    );
    // It sits on her message, not as a message of its own.
    expect(await within(hers).findByText("from the team")).toBeTruthy();
  });

  it("replaces the box with the reason once her 24 hours have passed", async () => {
    serve({ detail: { window_open: false, window_closes_at: minutesAgo(600) }, messages: THREAD });
    show("/inbox/chats/12");

    expect(await screen.findByText("You can't type a message here.")).toBeTruthy();
    expect(screen.queryByRole("textbox", { name: "Message" })).toBeNull();
    // Nor can a message be answered or reacted to.
    expect(screen.queryByRole("button", { name: "Reply to this message" })).toBeNull();
  });

  it("shows an old chat as it was brought over, with what is gone marked gone", async () => {
    const gone = (id: number, filename: string | null) => ({
      id,
      state: "gone",
      mime_type: null,
      filename,
      size_bytes: null,
      url: null,
    });
    serve({
      detail: { window_open: false, window_closes_at: null, orders: [] },
      messages: [
        message(1, { kind: "image", body: null, origin: "imported", media: gone(1, null) }),
        message(2, {
          direction: "out",
          origin: "imported",
          status: "read",
          body: "We will send a replacement.",
        }),
        message(3, { kind: "document", body: null, origin: "imported", media: gone(2, "receipt.pdf") }),
      ],
    });
    show("/inbox/chats/12");

    expect(await screen.findByText("Photo no longer available")).toBeTruthy();
    expect(
      screen.getByText(/Brought over from the old inbox\. Who sent each reply was not recorded there\./),
    ).toBeTruthy();
    expect(screen.getByText("HBA")).toBeTruthy();
    expect(screen.getByText("receipt.pdf").textContent).toContain("No longer available");
  });

  it("says so when there is no chat at the address", async () => {
    serve();
    show("/inbox/chats/999");

    expect(await screen.findByText(/There is no chat at this address\./)).toBeTruthy();
  });
});

describe("the order beside the chat", () => {
  it("shows the order, where its confirmation stands and its tag", async () => {
    serve({
      detail: {
        orders: [
          chatOrder(),
          chatOrder({
            order_id: "4001",
            order: "#29871",
            answer: "confirmed",
            tag: "Confirmed ✅",
            placed_at: "2026-09-02T10:00:00+00:00",
          }),
        ],
      },
    });
    show("/inbox/chats/12");

    const panel = await screen.findByRole("complementary", { name: "Order" });
    const link = await within(panel).findByRole("link", { name: /#31044/ });
    expect(link.getAttribute("href")).toBe("https://hbawear.myshopify.com/admin/orders/5001");
    expect(within(panel).getByText("EGP 1,450")).toBeTruthy();
    expect(within(panel).getByText("Wants a change")).toBeTruthy();
    expect(within(panel).getByText("Edit ✏️")).toBeTruthy();
    expect(within(panel).getByText("Confirmed · 2 Sep")).toBeTruthy();
    // The answer it already has is not offered again.
    expect(within(panel).queryByRole("button", { name: "Mark wants a change" })).toBeNull();
  });

  it("records her answer by hand, which is what changes the tag", async () => {
    serve({ post: () => [200, chatOrder({ answer: "confirmed", tag: "Confirmed ✅" })] });
    show("/inbox/chats/12");
    const panel = await screen.findByRole("complementary", { name: "Order" });

    fireEvent.click(await within(panel).findByRole("button", { name: "Mark confirmed" }));

    await waitFor(() =>
      expect(posts()[0]).toMatchObject({
        url: "/api/inbox/confirmations/5001/answer",
        body: { answer: "confirmed" },
      }),
    );
    expect(within(panel).getByText(/It does not cancel or change the order there\./)).toBeTruthy();
  });

  it("says so when the number has no order with a confirmation", async () => {
    serve({ detail: { orders: [] } });
    show("/inbox/chats/12");

    expect(await screen.findByText("No order with a confirmation for this number.")).toBeTruthy();
  });
});
