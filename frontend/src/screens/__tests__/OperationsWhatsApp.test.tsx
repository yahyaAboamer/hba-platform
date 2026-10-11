// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { OperationsWhatsApp } from "../OperationsWhatsApp";

const reply = (status: number, body: unknown) =>
  Promise.resolve({
    ok: status < 400,
    status,
    headers: { get: () => "application/json" },
    json: () => Promise.resolve(body),
    text: () => Promise.resolve(JSON.stringify(body)),
  } as unknown as Response);

const minutesAgo = (minutes: number) => new Date(Date.now() - minutes * 60_000).toISOString();

const order = (number: string, extra: object = {}) => ({
  order_id: `50${number}`,
  order: `#${number}`,
  placed_at: "2026-10-11T10:40:00+00:00",
  waiting_days: 0,
  why: "WhatsApp was not answering",
  state: "failed",
  answer: null,
  tag: null,
  ...extra,
});

const tab = (extra: object = {}) => ({
  connected: true,
  sending: true,
  last_heard_at: minutesAgo(1),
  quiet_since: null,
  read_at: minutesAgo(0),
  days: 7,
  cards: { failed: 2, no_whatsapp: 1, never_messaged: 2, answers_not_recorded: 0, waiting: 9 },
  orders: null,
  ...extra,
});

function narrowScreen(narrow: boolean) {
  vi.stubGlobal(
    "matchMedia",
    vi.fn(() => ({ matches: narrow, addEventListener: () => undefined, removeEventListener: () => undefined })),
  );
}

const show = () =>
  render(
    <MemoryRouter>
      <OperationsWhatsApp />
    </MemoryRouter>,
  );

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

describe("Operations → WhatsApp (ADR 0059)", () => {
  it("shows the five cards and when WhatsApp was last heard from", async () => {
    fetchMock.mockImplementation(() => reply(200, tab()));
    show();

    const failed = await screen.findByRole("button", { name: /Failed to send/ });
    expect(fetchMock.mock.calls[0][0]).toBe("/api/order-ops/whatsapp");
    expect(failed.textContent).toContain("2");
    expect(failed.textContent).toContain("Tried 5 times and gave up");
    for (const name of [/No WhatsApp/, /Never messaged/, /Waiting over 24 hours/]) {
      expect(screen.getByRole("button", { name })).toBeTruthy();
    }
    expect(screen.getByText("Updated just now · WhatsApp last heard from 1 minute ago")).toBeTruthy();
  });

  it("draws a card with nothing in it as a zero that does not open", async () => {
    fetchMock.mockImplementation(() => reply(200, tab()));
    show();

    await screen.findByRole("button", { name: /Failed to send/ });
    expect(screen.getByText("Answers not recorded")).toBeTruthy();
    expect(screen.queryByRole("button", { name: /Answers not recorded/ })).toBeNull();
  });

  it("opens a card's orders, each opening in the Inbox where it is fixed", async () => {
    fetchMock.mockImplementation((url: string) =>
      reply(200, url.includes("card=failed") ? tab({ orders: [order("31040"), order("31033")] }) : tab()),
    );
    show();

    const card = await screen.findByRole("button", { name: /Failed to send/ });
    fireEvent.click(card);

    expect(await screen.findByText("Failed to send · 2 orders")).toBeTruthy();
    expect(card.getAttribute("aria-expanded")).toBe("true");
    const link = screen.getByRole("link", { name: /#31040/ });
    expect(link.getAttribute("href")).toBe("/inbox/confirmations?card=not_sent&order=5031040");
    expect(link.getAttribute("target")).toBeNull();
    expect(screen.getAllByText("WhatsApp was not answering")).toHaveLength(2);
    expect(screen.getAllByText("None yet")).toHaveLength(2);
    expect(screen.getAllByText("Today")).toHaveLength(2);

    fireEvent.click(card);
    expect(screen.queryByText("Failed to send · 2 orders")).toBeNull();
  });

  it("sends an order to the card it stands under in the Inbox", async () => {
    fetchMock.mockImplementation((url: string) =>
      reply(
        200,
        url.includes("card=waiting")
          ? tab({
              orders: [
                order("31001", { state: "sent", why: null, tag: "WA Sent 📤", waiting_days: 2 }),
              ],
            })
          : tab(),
      ),
    );
    show();

    fireEvent.click(await screen.findByRole("button", { name: /Waiting over 24 hours/ }));

    const link = await screen.findByRole("link", { name: /#31001/ });
    expect(link.getAttribute("href")).toBe("/inbox/confirmations?card=waiting&order=5031001");
    expect(screen.getByText("WA Sent 📤")).toBeTruthy();
    expect(screen.getByText("2 days")).toBeTruthy();
    expect(screen.getByText("No answer yet")).toBeTruthy();
  });

  it("never shows one card's orders under another card's heading", async () => {
    let answerWaiting: (value: Response) => void = () => undefined;
    fetchMock.mockImplementation((url: string) => {
      if (url.includes("card=failed")) return reply(200, tab({ orders: [order("31040")] }));
      if (url.includes("card=waiting")) {
        return new Promise<Response>((resolve) => {
          answerWaiting = resolve;
        });
      }
      return reply(200, tab());
    });
    show();

    fireEvent.click(await screen.findByRole("button", { name: /Failed to send/ }));
    await screen.findByRole("link", { name: /#31040/ });
    fireEvent.click(screen.getByRole("button", { name: /Waiting over 24 hours/ }));

    // Its own answer has not arrived: the last card's order is not relabelled.
    expect(screen.queryByRole("link", { name: /#31040/ })).toBeNull();
    answerWaiting(await reply(200, tab({ orders: [order("31001", { state: "sent" })] })));
    expect(await screen.findByRole("link", { name: /#31001/ })).toBeTruthy();
  });

  it("says so when WhatsApp has gone quiet", async () => {
    fetchMock.mockImplementation(() =>
      reply(200, tab({ last_heard_at: minutesAgo(40), quiet_since: minutesAgo(40) })),
    );
    show();

    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toContain("WhatsApp has not been heard from for 40 minutes.");
    expect(alert.textContent).toContain("New confirmations may not be going out.");
    // The cards keep their numbers; they never drop to 0.
    expect(screen.getByRole("button", { name: /Failed to send/ }).textContent).toContain("2");
  });

  it("says when WhatsApp is not connected, and when sending is off", async () => {
    fetchMock.mockImplementation(() => reply(200, tab({ connected: false, sending: false, last_heard_at: null })));
    const { unmount } = show();
    await waitFor(() => expect(screen.getByText("WhatsApp isn't connected yet.")).toBeTruthy());
    unmount();

    fetchMock.mockImplementation(() => reply(200, tab({ sending: false })));
    show();
    await waitFor(() => expect(screen.getByText("The platform is not sending confirmations.")).toBeTruthy());
  });

  it("keeps the last numbers, with their time, when the platform stops answering", async () => {
    let fail = false;
    fetchMock.mockImplementation((url: string) => {
      if (fail) return reply(500, { detail: "down" });
      return reply(200, url.includes("card=") ? tab({ orders: [order("31040")] }) : tab());
    });
    const { container } = show();

    const card = await screen.findByRole("button", { name: /Failed to send/ });
    fail = true;
    fireEvent.click(card);

    await waitFor(() => expect(screen.getByRole("alert").textContent).toContain("Couldn't load this tab."));
    expect(container.querySelector(".ops-tiles--old")).toBeTruthy();
    expect(screen.getAllByText(/^As of /).length).toBeGreaterThan(0);
    expect(screen.getByRole("button", { name: /Failed to send/ }).textContent).toContain("2");
  });

  it("on a phone lists each order with its reason on the line below", async () => {
    narrowScreen(true);
    fetchMock.mockImplementation((url: string) =>
      reply(200, url.includes("card=failed") ? tab({ orders: [order("31040"), order("31033")] }) : tab()),
    );
    show();

    fireEvent.click(await screen.findByRole("button", { name: /Failed to send/ }));

    expect(await screen.findByText("Failed to send · 2")).toBeTruthy();
    expect(screen.getAllByRole("link")).toHaveLength(2);
    expect(screen.queryByRole("table")).toBeNull();
  });
});
