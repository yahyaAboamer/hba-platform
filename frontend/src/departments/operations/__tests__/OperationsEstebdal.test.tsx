// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { OperationsEstebdal } from "../OperationsEstebdal";

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
  source: "estebdal",
  label: "E-stebdal",
  state: "fresh",
  updated_at: minutesAgo(1),
  checked_at: minutesAgo(1),
  error: null,
  row_count: 3,
  ...extra,
});

const URL = "https://hbawear.myshopify.com/admin/apps/e-stebdal";
const request = (number: string, days: number) => ({
  return_number: `#${number}-R1`,
  order_number: `#${number}`,
  requested_at: "2026-10-03T10:49:00+00:00",
  waiting_days: days,
  url: URL,
});

const three = [
  { key: "needs_review", count: 3, requests: [request("30830", 0), request("30794", 1), request("30751", 3)] },
];

function narrowScreen(narrow: boolean) {
  vi.stubGlobal(
    "matchMedia",
    vi.fn(() => ({ matches: narrow, addEventListener: () => undefined, removeEventListener: () => undefined })),
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

describe("Operations → E-stebdal (ADR 0057)", () => {
  it("shows the one card with its count and when it was read", async () => {
    fetchMock.mockImplementation(() => reply(200, { freshness: freshness(), total: 3, cards: three }));
    render(<OperationsEstebdal />);

    const card = await screen.findByRole("button", { name: /Needs review/ });
    expect(fetchMock.mock.calls[0][0]).toContain("/api/order-ops/estebdal");
    expect(card.textContent).toContain("3");
    expect(card.textContent).toContain("Nobody has approved or rejected them yet");
    expect(screen.getByText("Updated 1 minute ago")).toBeTruthy();
  });

  it("opens the requests, each opening E-stebdal", async () => {
    fetchMock.mockImplementation(() => reply(200, { freshness: freshness(), total: 3, cards: three }));
    render(<OperationsEstebdal />);

    const card = await screen.findByRole("button", { name: /Needs review/ });
    fireEvent.click(card);

    expect(card.getAttribute("aria-expanded")).toBe("true");
    expect(screen.getByText("Needs review · 3 requests")).toBeTruthy();
    const link = screen.getByRole("link", { name: /#30830-R1/ });
    expect(link.getAttribute("href")).toBe(URL);
    expect(link.getAttribute("target")).toBe("_blank");
    expect(screen.getByText("#30830")).toBeTruthy();
    expect(screen.getByText("Today")).toBeTruthy();
    expect(screen.getByText("3 days")).toBeTruthy();

    fireEvent.click(card);
    expect(screen.queryByText("Needs review · 3 requests")).toBeNull();
  });

  it("on a phone lists each request with its order on the line below", async () => {
    narrowScreen(true);
    fetchMock.mockImplementation(() => reply(200, { freshness: freshness(), total: 3, cards: three }));
    render(<OperationsEstebdal />);

    fireEvent.click(await screen.findByRole("button", { name: /Needs review/ }));

    expect(screen.getByText("Needs review · 3")).toBeTruthy();
    expect(screen.getAllByRole("link")).toHaveLength(3);
    expect(screen.getByText(/Order #30830 ·/)).toBeTruthy();
  });

  it("draws nothing waiting as a zero that does not open", async () => {
    fetchMock.mockImplementation(() =>
      reply(200, { freshness: freshness(), total: 0, cards: [{ key: "needs_review", count: 0, requests: [] }] }),
    );
    render(<OperationsEstebdal />);

    await waitFor(() => expect(screen.getByText("Nothing waiting")).toBeTruthy());
    expect(screen.queryByRole("button", { name: /Needs review/ })).toBeNull();
  });

  it("when not connected, says the key is missing and shows no numbers", async () => {
    fetchMock.mockImplementation(() =>
      reply(200, { freshness: freshness({ state: "not_connected" }), total: null, cards: null }),
    );
    render(<OperationsEstebdal />);

    await waitFor(() => expect(screen.getByText("E-stebdal isn't connected yet.")).toBeTruthy());
    expect(screen.getByText(/An admin adds the E-stebdal key/)).toBeTruthy();
    expect(screen.queryByText("0")).toBeNull();
  });

  it("when a read failed, says so and keeps the last count with its time", async () => {
    fetchMock.mockImplementation(() =>
      reply(200, {
        freshness: freshness({ state: "failed", updated_at: minutesAgo(15), error: "E-stebdal didn't answer." }),
        total: 3,
        cards: three,
      }),
    );
    const { container } = render(<OperationsEstebdal />);

    await waitFor(() => expect(screen.getByText("Can't reach E-stebdal")).toBeTruthy());
    expect(screen.getByRole("alert").textContent).toContain("E-stebdal didn't answer.");
    expect(container.querySelector(".ops-tiles--old")).toBeTruthy();
    expect(screen.getByText(/^As of /)).toBeTruthy();
  });

  it("before the first read says it is reading", async () => {
    fetchMock.mockImplementation(() =>
      reply(200, {
        freshness: freshness({ state: "never", updated_at: null, checked_at: null }),
        total: null,
        cards: null,
      }),
    );
    render(<OperationsEstebdal />);

    await waitFor(() => expect(screen.getByText("Reading E-stebdal…")).toBeTruthy());
    expect(screen.getByText("Reading…")).toBeTruthy();
  });
});
