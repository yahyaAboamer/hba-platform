// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { Session } from "../../../lib/api";
import { Products, syncedAgo } from "../Products";

const reply = (status: number, body: unknown) =>
  Promise.resolve({
    ok: status < 400, status,
    headers: { get: () => "application/json" },
    json: () => Promise.resolve(body),
    text: () => Promise.resolve(JSON.stringify(body)),
  } as unknown as Response);

const MANAGER = { actor: {}, permissions: ["affiliates.view", "affiliates.manage"], platform: {} } as unknown as Session;
const VIEWER = { actor: {}, permissions: ["affiliates.view"], platform: {} } as unknown as Session;

const listing = (over: Record<string, unknown> = {}) => ({
  products: [{ shopify_product_id: "p1", title: "HBA CLUB pants", status: "active", image_url: null, sizes: 3, models_with_it: 4, featured: null, synced_at: null }],
  total: 1103, counts: { active: 900, all: 1103, requests: 0 }, active_models: 12,
  last_synced_at: new Date(Date.now() - 3 * 3600_000).toISOString(), refreshing: false,
  ...over,
});

let fetchMock: ReturnType<typeof vi.fn>;
beforeEach(() => {
  window.localStorage.clear();
  fetchMock = vi.fn(() => reply(200, listing()));
  vi.stubGlobal("fetch", fetchMock);
});
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

const urls = () => fetchMock.mock.calls.map(([url]) => String(url));
const at = (session: Session) => render(<MemoryRouter><Products session={session} /></MemoryRouter>);

describe("the catalogue's pager", () => {
  it("shows 50 rows by default, with the range and two arrows", async () => {
    at(MANAGER);
    expect(await screen.findByText("1–50 of 1103")).toBeTruthy();
    expect((screen.getByRole("combobox", { name: "Rows per page" }) as HTMLSelectElement).value).toBe("50");
    expect(urls()[0]).toContain("limit=50");
    expect((screen.getByRole("button", { name: "Previous page" }) as HTMLButtonElement).disabled).toBe(true);
  });

  it("asks for the next page, and for a new page size from the start", async () => {
    at(MANAGER);
    fireEvent.click(await screen.findByRole("button", { name: "Next page" }));
    await waitFor(() => expect(urls().at(-1)).toContain("offset=50"));

    fireEvent.change(screen.getByRole("combobox", { name: "Rows per page" }), { target: { value: "100" } });
    await waitFor(() => expect(urls().at(-1)).toMatch(/limit=100&offset=0$/));
    expect(window.localStorage.getItem("hba.products.pageSize")).toBe("100");
  });
});

describe("sorting by most received", () => {
  it("asks the server to sort the whole shop", async () => {
    at(MANAGER);
    fireEvent.change(await screen.findByRole("combobox", { name: "Sort products" }), { target: { value: "received" } });
    await waitFor(() => expect(urls().at(-1)).toContain("sort=received"));
  });
});

describe("refreshing from Shopify", () => {
  it("says how fresh the list is, and queues a read on the button", async () => {
    at(MANAGER);
    expect(await screen.findByText("Updated from Shopify 3 h ago")).toBeTruthy();

    fetchMock.mockImplementation((url: string) =>
      url === "/api/products/refresh" ? reply(200, { status: "queued" }) : reply(200, listing({ refreshing: true })));
    fireEvent.click(screen.getByRole("button", { name: "Refresh products" }));

    expect(await screen.findByText("Reading products from Shopify…")).toBeTruthy();
    expect(urls()).toContain("/api/products/refresh");
    expect((screen.getByRole("button", { name: "Refreshing…" }) as HTMLButtonElement).disabled).toBe(true);
  });

  it("is not offered to someone who cannot manage models", async () => {
    at(VIEWER);
    await screen.findByText("1–50 of 1103");
    expect(screen.queryByRole("button", { name: "Refresh products" })).toBeNull();
  });

  it("words the age of the last read", () => {
    const now = Date.parse("2026-11-09T12:00:00Z");
    expect(syncedAgo(null, now)).toBe("never");
    expect(syncedAgo("2026-11-09T11:59:40Z", now)).toBe("just now");
    expect(syncedAgo("2026-11-09T11:15:00Z", now)).toBe("45 min ago");
    expect(syncedAgo("2026-11-08T12:00:00Z", now)).toBe("1 day ago");
  });
});
