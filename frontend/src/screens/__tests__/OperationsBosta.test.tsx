// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { OperationsBosta } from "../OperationsBosta";

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
  source: "bosta",
  label: "Bosta",
  state: "fresh",
  updated_at: minutesAgo(4),
  checked_at: minutesAgo(4),
  error: null,
  row_count: 9000,
  ...extra,
});

const order = (tracking: string, extra: object = {}) => ({
  tracking_number: tracking,
  shopify_order_number: "#30412",
  type: "Send",
  status: "Pickup requested",
  created_at: "2026-09-14T09:00:00+00:00",
  collected_at: null,
  awb_printed_at: "2026-09-14T10:00:00+00:00",
  waiting_working_days: 16,
  url: `https://business.bosta.co/orders/${tracking}`,
  ...extra,
});

/** Seven days from Saturday 3 Oct back to Sunday 27 Sep; 2 Oct is a Friday. */
const seven = (counts: number[]) =>
  counts.map((count, n) => {
    const date = new Date(Date.UTC(2026, 9, 3 - n, 12)).toISOString().slice(0, 10);
    return {
      date,
      count,
      orders: Array.from({ length: count }, (_, i) =>
        order(`${date}-${i}`, { collected_at: `${date}T09:00:00+00:00` }),
      ),
    };
  });

const tabBody = (extra: object = {}) => ({
  freshness: freshness(),
  cards: [
    {
      key: "new_not_shipped",
      count: 7,
      orders: [order("5041829317"), ...Array.from({ length: 6 }, (_, i) => order(`50000${i}`))],
    },
    { key: "not_printed", count: 1, orders: [order("5058130772", { awb_printed_at: null })] },
    { key: "awaiting_action", count: 0, orders: [] },
    {
      key: "shipped_not_delivered",
      count: 9,
      orders: [order("7", { collected_at: "2026-09-28T10:00:00+00:00", status: "In transit" })],
    },
  ],
  pickups: { complete: true, read_back_to: "2026-01-01", days: seven([5, 0, 70, 13, 35, 32, 86]) },
  ...extra,
});

const rateBody = {
  from: "2026-09-01",
  to: "2026-09-30",
  available: true,
  successful: 970,
  unsuccessful: 176,
  finished: 1146,
  rate: 0.8464,
};

let fetchMock: ReturnType<typeof vi.fn>;

function serve(tab: unknown, rate: unknown = rateBody, rateStatus = 200) {
  fetchMock.mockImplementation((url: string) =>
    url.includes("success-rate") ? reply(rateStatus, rate) : reply(200, tab),
  );
}

function rateCalls(): URLSearchParams[] {
  return fetchMock.mock.calls
    .map(([url]) => url as string)
    .filter((url) => url.includes("success-rate"))
    .map((url) => new URL(url, "http://x").searchParams);
}

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

beforeEach(() => {
  fetchMock = vi.fn();
  vi.stubGlobal("fetch", fetchMock);
  narrowScreen(false);
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("Operations → Bosta (ADR 0057)", () => {
  it("shows the four cards with their counts and when Bosta was read", async () => {
    serve(tabBody());
    render(<OperationsBosta />);

    const card = await screen.findByRole("button", { name: /New, not shipped/ });
    expect(card.textContent).toContain("7");
    expect(screen.getByText("Updated 4 minutes ago")).toBeTruthy();
    expect(screen.getByRole("button", { name: /Shipped, not delivered/ }).textContent).toContain("9");
    // A zero is nothing waiting, not a card to open.
    expect(screen.queryByRole("button", { name: /Awaiting your action/ })).toBeNull();
  });

  it("opens a card's orders, oldest first, five then the rest, each opening Bosta", async () => {
    serve(tabBody());
    render(<OperationsBosta />);

    fireEvent.click(await screen.findByRole("button", { name: /New, not shipped/ }));

    expect(screen.getByText("New, not shipped · 7 orders")).toBeTruthy();
    expect(screen.getByText(/Oldest first/)).toBeTruthy();
    const link = screen.getByRole("link", { name: /5041829317/ });
    expect(link.getAttribute("href")).toBe("https://business.bosta.co/orders/5041829317");
    expect(screen.getAllByText("16 working days")).toHaveLength(5);
    expect(screen.getAllByText("Printed 14 Sep")).toHaveLength(5);
    fireEvent.click(screen.getByRole("button", { name: "Show the other 2" }));
    expect(screen.getAllByText("16 working days")).toHaveLength(7);
  });

  it("says when an airway bill was never printed", async () => {
    serve(tabBody());
    render(<OperationsBosta />);

    fireEvent.click(await screen.findByRole("button", { name: /Not printed/ }));

    // The card's own label, and the bill in its list.
    expect(screen.getAllByText("Not printed").length).toBeGreaterThan(1);
  });

  it("lists the last seven days, Friday as a day off, and opens a day's pickups", async () => {
    serve(tabBody());
    render(<OperationsBosta />);

    await screen.findByText("Picked up, last 7 days");
    expect(screen.getByText("Day off, no pickups")).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: /Thursday/ }));

    expect(screen.getByText("Picked up 1 Oct · 70 orders")).toBeTruthy();
  });

  it("says when the pickups may be short because history is still being read", async () => {
    serve(
      tabBody({
        pickups: { complete: false, read_back_to: "2026-09-27", days: seven([5, 0, 1, 1, 1, 1, 1]) },
      }),
    );
    render(<OperationsBosta />);

    expect(
      await screen.findByText(/Still reading Bosta's history \(back to 27 Sep so far\)/),
    ).toBeTruthy();
  });

  it("shows a day history has not reached as not read, never as 0 or a day off", async () => {
    serve(
      tabBody({
        pickups: { complete: false, read_back_to: "2026-10-01", days: seven([5, 0, 70, 13, 35, 32, 86]) },
      }),
    );
    render(<OperationsBosta />);

    await screen.findByText("Picked up, last 7 days");
    // 30 Sep back to 27 Sep are before what history has read.
    expect(screen.getAllByText("Not read yet")).toHaveLength(4);
    expect(screen.queryByText("Day off, no pickups")).toBeTruthy(); // 2 Oct was read: a real day off
    expect(screen.queryByRole("button", { name: /Sunday/ })).toBeNull();
  });

  it("marks the success rate and the pickups as old when Bosta's numbers are", async () => {
    serve(tabBody({ freshness: freshness({ state: "stale", updated_at: minutesAgo(25) }) }));
    const { container } = render(<OperationsBosta />);

    await screen.findByText("84.6%");
    expect(container.querySelector(".ops-rate--old")).toBeTruthy();
    expect(container.querySelector(".ops-days--old")).toBeTruthy();
    expect(screen.getAllByText(/^As of /).length).toBeGreaterThan(1);
  });

  it("asks for the last 30 days first and shows the rate with its parts", async () => {
    serve(tabBody());
    render(<OperationsBosta />);

    await screen.findByText("84.6%");
    const asked = rateCalls()[0];
    const days = (Date.parse(asked.get("to")!) - Date.parse(asked.get("from")!)) / 86_400_000;
    expect(days).toBe(29);
    expect(screen.getByText("970 successful")).toBeTruthy();
    expect(screen.getByText("176 unsuccessful")).toBeTruthy();
    expect(screen.getByText("1,146 finished")).toBeTruthy();
    expect(screen.getByRole("img", { name: "84.6% successful" })).toBeTruthy();
  });

  it("asks again for today when Today is chosen", async () => {
    serve(tabBody());
    render(<OperationsBosta />);
    await screen.findByText("84.6%");

    fireEvent.click(screen.getByRole("button", { name: "Today" }));

    await waitFor(() => {
      const last = rateCalls().at(-1)!;
      expect(last.get("from")).toBe(last.get("to"));
    });
  });

  it("says why a range cannot be asked", async () => {
    serve(tabBody(), { detail: "Not available before 1 Jan 2026." }, 422);
    render(<OperationsBosta />);

    expect(await screen.findByText("Not available before 1 Jan 2026.")).toBeTruthy();
    expect(screen.queryByRole("img", { name: /successful/ })).toBeNull();
  });

  it("says when the range is older than what history has read so far", async () => {
    serve(tabBody(), {
      from: "2026-09-01",
      to: "2026-09-30",
      available: false,
      read_back_to: "2026-09-27",
    });
    render(<OperationsBosta />);

    expect(await screen.findByText(/read back to 27 Sep so far/)).toBeTruthy();
  });

  it("before the first read says it is reading and shows no numbers", async () => {
    serve({
      freshness: freshness({ state: "never", updated_at: null, checked_at: null }),
      cards: null,
      pickups: null,
    });
    render(<OperationsBosta />);

    await waitFor(() => expect(screen.getByText("Reading Bosta…")).toBeTruthy());
    expect(screen.getAllByText("Reading…")).toHaveLength(4);
    expect(screen.queryByText("Success rate")).toBeNull();
  });

  it("when the key is missing, says so and shows no numbers", async () => {
    serve({ freshness: freshness({ state: "not_connected" }), cards: null, pickups: null });
    render(<OperationsBosta />);

    await waitFor(() => expect(screen.getByText("Bosta isn't connected yet.")).toBeTruthy());
    expect(screen.getByText(/An admin adds the Bosta key/)).toBeTruthy();
    expect(screen.queryByText("Picked up, last 7 days")).toBeNull();
  });

  it("on a phone puts the success rate above the pickups and shortens the notes", async () => {
    narrowScreen(true);
    serve(tabBody());
    const { container } = render(<OperationsBosta />);

    await screen.findByText("Over 2 working days");
    const titles = Array.from(container.querySelectorAll(".ops-split .panel__title")).map(
      (node) => node.textContent,
    );
    expect(titles).toEqual(["Success rate", "Picked up, last 7 days"]);
  });
});
