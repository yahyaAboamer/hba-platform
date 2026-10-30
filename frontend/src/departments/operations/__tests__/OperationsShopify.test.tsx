// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { OperationsShopify } from "../OperationsShopify";

const reply = (status: number, body: unknown) =>
  Promise.resolve({
    ok: status < 400,
    status,
    headers: { get: () => "application/json" },
    json: () => Promise.resolve(body),
    text: () => Promise.resolve(JSON.stringify(body)),
  } as unknown as Response);

const minutesAgo = (minutes: number) => new Date(Date.now() - minutes * 60_000).toISOString();

const freshness = (extra: object = {}) => ({
  source: "shopify",
  label: "Shopify",
  state: "fresh",
  updated_at: minutesAgo(2),
  checked_at: minutesAgo(2),
  error: null,
  row_count: 29,
  ...extra,
});

const order = (number: string, tags: [string, boolean][], days = 2) => ({
  order_number: number,
  placed_at: "2026-10-01T10:15:00+00:00",
  waiting_days: days,
  tags: tags.map(([text, hit]) => ({ text, hit })),
  admin_url: `https://hbawear.myshopify.com/admin/orders/${number.slice(1)}`,
});

const synced = [
  order("#30931", [["Confirmed ✅", false], ["bosta_sync_failed", true]], 0),
  order("#30927", [["Confirmed ✅", false], ["bosta_sync_failed", true]]),
  order("#30918", [["Confirmed ✅", false], ["bosta_sync_failed", true]]),
  order("#30904", [["Confirmed ✅", false], ["bosta_sync_failed", true]], 3),
  order("#30889", [["Confirmed ✅", false], ["bosta_sync_failed", true]], 4),
];

const cards = [
  { key: "confirmed", count: 17, orders: [] },
  { key: "no_answer", count: 7, orders: [] },
  { key: "no_answer_no_whatsapp_sent", count: 0, orders: [] },
  { key: "no_whatsapp", count: 1, orders: [] },
  { key: "bosta_sync_failed", count: 5, orders: synced },
  { key: "compression_not_call_confirmed", count: 5, orders: [] },
  { key: "cancel_in_shopify", count: 1, orders: [] },
];

function narrowScreen(narrow: boolean) {
  vi.stubGlobal(
    "matchMedia",
    vi.fn(() => ({
      matches: narrow,
      addEventListener: () => undefined,
      removeEventListener: () => undefined,
    })),
  );
}

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

describe("Operations → Shopify (ADR 0057)", () => {
  it("shows every card with its count, and when it was read", async () => {
    fetchMock.mockImplementation(() => reply(200, { freshness: freshness(), total: 29, cards }));
    render(<OperationsShopify />);

    await waitFor(() => expect(screen.getByText("Updated 2 minutes ago")).toBeTruthy());
    expect(fetchMock.mock.calls[0][0]).toContain("/api/order-ops/shopify");
    expect(screen.getByText("Open orders not shipped yet · 29")).toBeTruthy();
    const bosta = screen.getByRole("button", { name: /Bosta sync failed/ });
    expect(bosta.textContent).toContain("5");
    expect(bosta.getAttribute("aria-expanded")).toBe("false");
  });

  it("draws a zero as nothing waiting, not as a card to open", async () => {
    fetchMock.mockImplementation(() => reply(200, { freshness: freshness(), total: 29, cards }));
    render(<OperationsShopify />);

    await waitFor(() => expect(screen.getByText("No answer, WhatsApp not sent")).toBeTruthy());
    expect(screen.queryByRole("button", { name: /No answer, WhatsApp not sent/ })).toBeNull();
    expect(screen.getByText("Nothing waiting")).toBeTruthy();
  });

  it("opens a card's orders, each linking to Shopify, one list at a time", async () => {
    fetchMock.mockImplementation(() => reply(200, { freshness: freshness(), total: 29, cards }));
    render(<OperationsShopify />);

    const bosta = await screen.findByRole("button", { name: /Bosta sync failed/ });
    fireEvent.click(bosta);

    expect(bosta.getAttribute("aria-expanded")).toBe("true");
    expect(screen.getByText("Bosta sync failed · 5 orders")).toBeTruthy();
    expect(screen.getByText(/where it is sent to Bosta again/)).toBeTruthy();
    const link = screen.getByRole("link", { name: /#30931/ });
    expect(link.getAttribute("href")).toBe("https://hbawear.myshopify.com/admin/orders/30931");
    expect(link.getAttribute("target")).toBe("_blank");
    expect(screen.getByText("Today")).toBeTruthy();
    expect(screen.getAllByText("bosta_sync_failed")[0].className).toContain("ops-tag--hit");

    fireEvent.click(bosta);
    expect(screen.queryByText("Bosta sync failed · 5 orders")).toBeNull();
  });

  it("on a phone shows three orders, then the rest on request", async () => {
    narrowScreen(true);
    fetchMock.mockImplementation(() => reply(200, { freshness: freshness(), total: 29, cards }));
    render(<OperationsShopify />);

    fireEvent.click(await screen.findByRole("button", { name: /Bosta sync failed/ }));

    expect(screen.getAllByRole("link")).toHaveLength(3);
    fireEvent.click(screen.getByRole("button", { name: "Show the other 2" }));
    expect(screen.getAllByRole("link")).toHaveLength(5);
  });

  it("before the first read says it is reading, and shows no zeros", async () => {
    fetchMock.mockImplementation(() =>
      reply(200, {
        freshness: freshness({ state: "never", updated_at: null, checked_at: null, row_count: null }),
        total: null,
        cards: null,
      }),
    );
    render(<OperationsShopify />);

    await waitFor(() => expect(screen.getByText("Reading Shopify…")).toBeTruthy());
    expect(screen.getAllByText("Reading…")).toHaveLength(7);
    expect(screen.queryByText("0")).toBeNull();
  });

  it("when old, says so in amber and keeps the numbers with their time", async () => {
    fetchMock.mockImplementation(() =>
      reply(200, {
        freshness: freshness({ state: "stale", updated_at: minutesAgo(14) }),
        total: 29,
        cards,
      }),
    );
    const { container } = render(<OperationsShopify />);

    await waitFor(() => expect(screen.getByText("Not updated for 14 minutes")).toBeTruthy());
    expect(screen.getByText(/These are Shopify's numbers from/)).toBeTruthy();
    expect(container.querySelector(".ops-tiles--old")).toBeTruthy();
    expect(screen.getAllByText(/^As of /).length).toBeGreaterThan(0);
  });

  it("turns old by itself when the page cannot reach the platform for a while", async () => {
    // The last answer said fresh, but its numbers are 25 minutes old now.
    fetchMock.mockImplementation(() =>
      reply(200, { freshness: freshness({ updated_at: minutesAgo(25) }), total: 29, cards }),
    );
    const { container } = render(<OperationsShopify />);

    await waitFor(() => expect(screen.getByText("Not updated for 25 minutes")).toBeTruthy());
    expect(container.querySelector(".ops-tiles--old")).toBeTruthy();
  });

  it("when a read failed, says why and never shows the failure as 0", async () => {
    fetchMock.mockImplementation(() =>
      reply(200, {
        freshness: freshness({
          state: "failed",
          updated_at: null,
          error: "Shopify refused the platform's connection.",
        }),
        total: null,
        cards: null,
      }),
    );
    render(<OperationsShopify />);

    await waitFor(() => expect(screen.getByText("Can't reach Shopify")).toBeTruthy());
    expect(screen.getByRole("alert").textContent).toContain(
      "Shopify refused the platform's connection.",
    );
    expect(screen.getByText(/no numbers to show yet/)).toBeTruthy();
    expect(screen.queryByText("0")).toBeNull();
  });

  it("when not connected, says so and shows no numbers", async () => {
    fetchMock.mockImplementation(() =>
      reply(200, {
        freshness: freshness({ state: "not_connected" }),
        total: null,
        cards: null,
      }),
    );
    render(<OperationsShopify />);

    await waitFor(() => expect(screen.getByText("Not connected")).toBeTruthy());
    expect(screen.getByText("Shopify isn't connected yet.")).toBeTruthy();
    expect(screen.queryByRole("button", { name: /Confirmed/ })).toBeNull();
  });

  it("if the tab itself cannot load, says so and offers to try again", async () => {
    fetchMock.mockImplementation(() => reply(500, { detail: "boom" }));
    render(<OperationsShopify />);

    await waitFor(() => expect(screen.getByText(/Couldn't load this tab/)).toBeTruthy());
    expect(screen.getByRole("button", { name: "Try again" })).toBeTruthy();
  });
});
