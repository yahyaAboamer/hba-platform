// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { DataPanel, longWhen } from "../DataPanel";
import type { Refresh } from "../DataPanel";

const reply = (status: number, body: unknown) =>
  Promise.resolve({
    ok: status < 400,
    status,
    headers: { get: () => "application/json" },
    json: () => Promise.resolve(body),
    text: () => Promise.resolve(JSON.stringify(body)),
  } as unknown as Response);

const OLD = "2026-09-24T10:00:00Z"; // 13:00 in Cairo
const NEW = "2026-09-25T08:15:00Z"; // 11:15 in Cairo

const sync = (refresh: Refresh) => ({
  shopify_configured: refresh.state !== "not_connected",
  webhooks_configured: true,
  orders_indexed: 2,
  last_order_synced_at: OLD,
  last_event_received_at: null,
  proof_stored_bytes: 0,
  jobs: { pending: 0, running: 0, succeeded: 1, failed: 0 },
  refresh,
});

const SUCCEEDED: Refresh = { state: "succeeded", last_success_at: OLD, failed_at: null, error_line: null };
const FAILED: Refresh = {
  state: "failed", last_success_at: OLD, failed_at: NEW,
  error_line: "Shopify limited how fast orders could be read (429). Nothing from this attempt was saved; the next refresh reads the same orders again.",
};

let fetchMock: ReturnType<typeof vi.fn>;
let status: Refresh[];
function serve(post: (init?: RequestInit) => Promise<Response>) {
  fetchMock.mockImplementation((url: string, init?: RequestInit) => {
    if (url.endsWith("/api/operations/refresh")) return post(init);
    if (url.endsWith("/api/operations/sync")) return reply(200, sync(status.length > 1 ? status.shift()! : status[0]));
    if (url.endsWith("/failed-jobs")) return reply(200, { jobs: [] });
    if (url.endsWith("/unregistered-codes")) return reply(200, { codes: [] });
    if (url.endsWith("/notifications")) return reply(200, { configured: false, from_address: null, counts: {}, failed: [] });
    if (url.endsWith("/catalogue")) return reply(200, { products: 0, active_products: 0, variants: 0, line_items: 0, last_synced_at: null });
    if (url.endsWith("/unmatched-parcels")) return reply(200, { parcels: [], summary: { needs_you: 0, customers: 0, unusable_phone: 0, no_phone: 0, matched: 0 } });
    if (url.endsWith("/shopify-connection")) return reply(200, { source: "environment", shop_domain: "hbawear.myshopify.com", client_id_hint: null, secret_saved: false, verified_at: null, shop_name: null, problem: null, can_save: true });
    return reply(404, { detail: "not found" });
  });
}

const show = () => render(<MemoryRouter><DataPanel goLiveMonth="2026-09" /></MemoryRouter>);
const button = () => screen.getByRole("button", { name: /Refresh now|Refreshing…|Try again/ }) as HTMLButtonElement;

beforeEach(() => { fetchMock = vi.fn(); vi.stubGlobal("fetch", fetchMock); });
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

describe("Refresh now (Settings → Shopify, item 17)", () => {
  it("prints the last successful refresh as the export does, in Cairo time", () => {
    expect(longWhen(OLD)).toBe("24 September 2026, 13:00");
  });

  it("shows Refreshing until the sweep finishes, and only then moves the time", async () => {
    status = [SUCCEEDED];
    serve(() => reply(200, { accepted: true, job_id: 7, joined_running: false,
      refresh: { ...SUCCEEDED, state: "queued" } }));
    show();
    await waitFor(() => expect(screen.getByText("Connected")).toBeTruthy());
    expect(screen.getByText("· last successful refresh 24 September 2026, 13:00")).toBeTruthy();

    // Accepted, then running, then finished.
    status = [{ ...SUCCEEDED, state: "running" }, { ...SUCCEEDED, last_success_at: NEW }];
    fireEvent.click(button());
    await waitFor(() => expect(button().textContent).toBe("Refreshing…"));
    expect(button().disabled).toBe(true);
    expect(screen.getByText("Refreshing")).toBeTruthy();
    // Accepting did not move the time.
    expect(screen.getByText("· last successful refresh 24 September 2026, 13:00")).toBeTruthy();

    await waitFor(() => expect(button().textContent).toBe("Refresh now"), { timeout: 6000 });
    expect(screen.getByText("· last successful refresh 25 September 2026, 11:15")).toBeTruthy();
    expect(fetchMock.mock.calls.filter(([url]) => String(url).endsWith("/refresh"))).toHaveLength(1);
  }, 10000);

  it("says a failure, keeps the last success, and offers Try again", async () => {
    status = [FAILED];
    serve(() => reply(200, {}));
    show();
    await waitFor(() => expect(screen.getByText("Last refresh failed")).toBeTruthy());
    expect(screen.getByText("· last successful refresh 24 September 2026, 13:00")).toBeTruthy();
    expect(screen.getByText(FAILED.error_line!)).toBeTruthy();
    expect(button().textContent).toBe("Try again");
  });

  it("a refused request says why and changes nothing on the card", async () => {
    status = [SUCCEEDED];
    serve(() => reply(409, { detail: "There is no Shopify connection to refresh from." }));
    show();
    await waitFor(() => expect(screen.getByText("Connected")).toBeTruthy());

    fireEvent.click(button());
    await waitFor(() => expect(screen.getByRole("alert").textContent).toContain("no Shopify connection"));
    expect(screen.getByText("Connected")).toBeTruthy();
    expect(button().textContent).toBe("Refresh now");
    expect(screen.getByText("· last successful refresh 24 September 2026, 13:00")).toBeTruthy();
  });

  it("cannot be pressed without a connection", async () => {
    status = [{ state: "not_connected", last_success_at: null, failed_at: null, error_line: null }];
    serve(() => reply(200, {}));
    show();
    await waitFor(() => expect(screen.getByText("Not connected")).toBeTruthy());
    expect(button().disabled).toBe(true);
  });

  it("a double click sends one request", async () => {
    status = [SUCCEEDED];
    let release: (r: Response) => void = () => undefined;
    serve(() => new Promise<Response>((resolve) => { release = resolve; }));
    show();
    await waitFor(() => expect(screen.getByText("Connected")).toBeTruthy());

    fireEvent.click(button());
    fireEvent.click(button());
    expect(fetchMock.mock.calls.filter(([url]) => String(url).endsWith("/refresh"))).toHaveLength(1);
    release(await reply(200, { accepted: true, job_id: 1, joined_running: false, refresh: SUCCEEDED }));
  });
});
