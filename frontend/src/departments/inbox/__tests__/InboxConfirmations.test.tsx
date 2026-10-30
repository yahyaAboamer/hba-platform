// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { InboxConfirmations } from "../InboxConfirmations";

const reply = (status: number, body: unknown) =>
  Promise.resolve({
    ok: status < 400,
    status,
    headers: { get: () => "application/json" },
    json: () => Promise.resolve(body),
    text: () => Promise.resolve(JSON.stringify(body)),
  } as unknown as Response);

const SHOPIFY = "https://hbawear.myshopify.com/admin/orders/";

const order = (number: string, extra: object = {}) => ({
  order_id: `50${number}`,
  order: `#${number}`,
  admin_url: `${SHOPIFY}50${number}`,
  state: "failed",
  answer: null,
  answered_at: null,
  placed_at: "2026-10-10T17:55:00+00:00",
  sent_at: null,
  why: "WhatsApp was not answering · tried 5 times",
  can_send_again: true,
  customer: "Dina Fouad",
  phone: "201005550121",
  conversation_id: null,
  ...extra,
});

const body = (extra: object = {}) => ({
  days: 7,
  total: 262,
  tiles: { waiting: 31, edit: 3, cancelled: 2, not_sent: 4, no_whatsapp: 1, confirmed: 221 },
  orders: null,
  ...extra,
});

function narrowScreen(narrow: boolean) {
  vi.stubGlobal(
    "matchMedia",
    vi.fn(() => ({ matches: narrow, addEventListener: () => undefined, removeEventListener: () => undefined })),
  );
}

const show = (address = "/inbox/confirmations") =>
  render(
    <MemoryRouter initialEntries={[address]}>
      <InboxConfirmations />
    </MemoryRouter>,
  );

const NOT_SENT = [
  order("31040"),
  order("31007", {
    state: "bad_phone",
    why: "The phone number on the order is not a valid Egyptian number",
    can_send_again: false,
    customer: "Malak Nabil",
  }),
];

let fetchMock: ReturnType<typeof vi.fn>;
beforeEach(() => {
  fetchMock = vi.fn();
  vi.stubGlobal("fetch", fetchMock);
  narrowScreen(false);
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("Inbox → Confirmations (ADR 0059)", () => {
  it("shows the six cards and how many cash-on-delivery orders they cover", async () => {
    fetchMock.mockImplementation(() => reply(200, body()));
    show();

    const waiting = await screen.findByRole("button", { name: /Waiting for an answer/ });
    expect(fetchMock.mock.calls[0][0]).toBe("/api/inbox/confirmations");
    expect(waiting.textContent).toContain("31");
    for (const name of [/Wants a change/, /Asked to cancel/, /Not sent/, /No WhatsApp/, /Confirmed/]) {
      expect(screen.getByRole("button", { name })).toBeTruthy();
    }
    expect(
      screen.getByText("Cash-on-delivery and unpaid international orders from the last 7 days · 262"),
    ).toBeTruthy();
    expect(screen.getByText("Updated just now")).toBeTruthy();
  });

  it("says under each action card how many were already shipped or cancelled (ADR 0063)", async () => {
    fetchMock.mockImplementation(() =>
      reply(200, body({ tiles: { ...body().tiles, cancelled: 1 }, done: { cancelled: 14, waiting: 30 } })),
    );
    show();

    const cancel = await screen.findByRole("button", { name: /Asked to cancel/ });
    expect(cancel.textContent).toContain("14 already shipped or cancelled");
    expect(screen.getByRole("button", { name: /Waiting for an answer/ }).textContent).toContain(
      "30 already shipped or cancelled",
    );
    // An outcome card says nothing of the kind.
    expect(screen.getByRole("button", { name: /Confirmed/ }).textContent).not.toContain("already");
  });

  it("lists international orders waiting for payment, and the ones unpaid for 3 days (ADR 0062)", async () => {
    const waiting = [
      order("31510", {
        state: "sent", kind: "payment", sent_at: "2026-10-14T09:00:00+00:00",
        reminded_at: "2026-10-15T09:00:00+00:00", needs_a_person: true, why: null,
        can_send_again: false, customer: "Sara", conversation_id: 7,
      }),
    ];
    const counts = { ...body().tiles, awaiting_payment: 1, paid: 2 };
    fetchMock.mockImplementation((url: string) =>
      reply(200, body({ tiles: counts, orders: url.includes("tile=awaiting_payment") ? waiting : null })),
    );
    show();

    expect((await screen.findByRole("button", { name: /Paid by link/ })).textContent).toContain("2");
    fireEvent.click(screen.getByRole("button", { name: /Waiting for payment/ }));

    expect(await screen.findByText("Waiting for payment · 1 order")).toBeTruthy();
    expect(screen.getByText(/Nothing is cancelled automatically/)).toBeTruthy();
    const row = screen.getByText("Sara").closest("tr") as HTMLElement;
    expect(row.textContent).toContain("Unpaid for 3 days: get in touch");
    expect(within(row).getByRole("link", { name: /Open chat/ }).getAttribute("href")).toBe("/inbox/chats/7");
  });

  it("opens Not sent, with why, and the one action each order can take", async () => {
    fetchMock.mockImplementation((url: string) =>
      reply(200, url.includes("tile=not_sent") ? body({ orders: NOT_SENT }) : body()),
    );
    show();

    fireEvent.click(await screen.findByRole("button", { name: /Not sent/ }));

    expect(await screen.findByText("Not sent · 4 orders")).toBeTruthy();
    expect(screen.getByText(/Sending again never sends twice/)).toBeTruthy();
    const sendable = screen.getByText("Dina Fouad").closest("tr") as HTMLElement;
    expect(within(sendable).getByRole("link", { name: /#31040/ }).getAttribute("href")).toBe(`${SHOPIFY}5031040`);
    expect(within(sendable).getByRole("button", { name: /Send again/ })).toBeTruthy();
    // A number that cannot be messaged is corrected on the order, in Shopify.
    const unsendable = screen.getByText("Malak Nabil").closest("tr") as HTMLElement;
    expect(within(unsendable).queryByRole("button", { name: /Send again/ })).toBeNull();
    expect(within(unsendable).getByRole("link", { name: /Open in Shopify/ }).getAttribute("href")).toBe(
      `${SHOPIFY}5031007`,
    );
    // Only the newest are listed: the card counts 4 and the server sent 2.
    expect(screen.getByText("Showing the newest 2.")).toBeTruthy();
  });

  it("sends an order again and says it is queued", async () => {
    fetchMock.mockImplementation((url: string, init?: RequestInit) => {
      if (init?.method === "POST") return reply(200, order("31040", { state: "pending" }));
      return reply(200, url.includes("tile=not_sent") ? body({ orders: NOT_SENT }) : body());
    });
    show();

    fireEvent.click(await screen.findByRole("button", { name: /Not sent/ }));
    fireEvent.click(await screen.findByRole("button", { name: /Send again/ }));

    expect((await screen.findByRole("status")).textContent).toBe("#31040 is queued to send again.");
    const posted = fetchMock.mock.calls.find(([, init]) => init?.method === "POST");
    expect(posted?.[0]).toBe("/api/inbox/confirmations/5031040/send-again");
  });

  it("shows the server's reason when an order may not be sent again", async () => {
    fetchMock.mockImplementation((url: string, init?: RequestInit) => {
      if (init?.method === "POST") {
        return reply(422, { detail: "This order already has its confirmation. Nothing was sent." });
      }
      return reply(200, url.includes("tile=not_sent") ? body({ orders: NOT_SENT }) : body());
    });
    show();

    fireEvent.click(await screen.findByRole("button", { name: /Not sent/ }));
    fireEvent.click(await screen.findByRole("button", { name: /Send again/ }));

    expect((await screen.findByRole("alert")).textContent).toBe(
      "This order already has its confirmation. Nothing was sent.",
    );
  });

  it("opens on the card and the order somebody was sent to from Operations", async () => {
    fetchMock.mockImplementation((url: string) =>
      reply(200, url.includes("tile=not_sent") ? body({ orders: NOT_SENT }) : body()),
    );
    show("/inbox/confirmations?card=not_sent&order=5031007");

    await screen.findByText("Not sent · 4 orders");
    expect(fetchMock.mock.calls[0][0]).toBe("/api/inbox/confirmations?tile=not_sent");
    expect(screen.getByText("Malak Nabil").closest("tr")?.getAttribute("aria-current")).toBe("true");
    expect(screen.getByText("Dina Fouad").closest("tr")?.getAttribute("aria-current")).toBeNull();
  });

  it("gives the number to call for an order with no WhatsApp", async () => {
    fetchMock.mockImplementation((url: string) =>
      reply(
        200,
        url.includes("tile=no_whatsapp")
          ? body({ orders: [order("31012", { state: "no_whatsapp", why: null, can_send_again: false })] })
          : body(),
      ),
    );
    show();

    fireEvent.click(await screen.findByRole("button", { name: /No WhatsApp/ }));

    expect(await screen.findByText("+20 100 555 0121")).toBeTruthy();
    expect(screen.getByRole("columnheader", { name: "Phone" })).toBeTruthy();
  });

  it("opens the chat of an order that has answered", async () => {
    fetchMock.mockImplementation((url: string) =>
      reply(
        200,
        url.includes("tile=edit")
          ? body({
              orders: [
                order("31044", {
                  state: "sent",
                  answer: "edit",
                  answered_at: "2026-10-10T18:05:00+00:00",
                  why: null,
                  can_send_again: false,
                  conversation_id: 12,
                }),
              ],
            })
          : body(),
      ),
    );
    show();

    fireEvent.click(await screen.findByRole("button", { name: /Wants a change/ }));

    const chat = await screen.findByRole("link", { name: /Open chat/ });
    expect(chat.getAttribute("href")).toBe("/inbox/chats/12");
    expect(screen.getByRole("columnheader", { name: "Answered" })).toBeTruthy();
  });

  it("draws a card with nothing in it as a zero that does not open", async () => {
    fetchMock.mockImplementation(() =>
      reply(200, body({ tiles: { waiting: 0, edit: 0, cancelled: 0, not_sent: 0, no_whatsapp: 0, confirmed: 5 } })),
    );
    show();

    await screen.findByRole("button", { name: /Confirmed/ });
    expect(screen.getByText("Not sent")).toBeTruthy();
    expect(screen.queryByRole("button", { name: /Not sent/ })).toBeNull();
  });

  it("says so when it cannot be loaded", async () => {
    fetchMock.mockImplementation(() => reply(500, { detail: "down" }));
    show();

    await waitFor(() => expect(screen.getByRole("alert").textContent).toContain("Couldn't load Confirmations."));
  });

  it("on a phone lists each order with its action under it", async () => {
    narrowScreen(true);
    fetchMock.mockImplementation((url: string) =>
      reply(200, url.includes("tile=not_sent") ? body({ orders: NOT_SENT }) : body()),
    );
    show();

    fireEvent.click(await screen.findByRole("button", { name: /Not sent/ }));

    expect(await screen.findByText("Not sent · 4")).toBeTruthy();
    expect(screen.queryByRole("table")).toBeNull();
    expect(screen.getByRole("button", { name: /Send again/ })).toBeTruthy();
  });
});
