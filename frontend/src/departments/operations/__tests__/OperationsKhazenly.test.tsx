// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { OperationsKhazenly } from "../OperationsKhazenly";

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
  row_count: 40,
  ...extra,
});

const built = {
  freshness: freshness(),
  rows_read: 4,
  stated_count: 4,
  skipped_rows: 0,
  confirmed: 2,
  not_confirmed: 2,
  left_out: [
    {
      reason: "not_open",
      label: "Not open in Shopify",
      count: 1,
      orders: [{ sales_order: "KH-HBA-08800009", order_number: "#31874" }],
    },
    {
      reason: "wa_sent",
      label: "Sent on WhatsApp, no answer yet (WA Sent 📤)",
      count: 1,
      orders: [{ sales_order: "KH-HBA-08800003", order_number: "#31842" }],
    },
  ],
  file: { name: "khazenly-bulk-confirm-2026-10-30-2245.xlsx", content_base64: btoa("PK fake") },
};

function respond(post: () => Promise<Response>, tab = { freshness: freshness() }) {
  fetchMock.mockImplementation((_path: string, init?: RequestInit) =>
    init?.method === "POST" ? post() : reply(200, tab),
  );
}

async function chooseAndBuild() {
  const input = await screen.findByLabelText(/Choose Khazenly's export/);
  const file = new File(["xlsx"], "Dashboard - Active Orders.xlsx", { type: "application/octet-stream" });
  fireEvent.change(input, { target: { files: [file] } });
  fireEvent.click(screen.getByRole("button", { name: "Build the file" }));
}

let fetchMock: ReturnType<typeof vi.fn>;
beforeEach(() => {
  fetchMock = vi.fn();
  vi.stubGlobal("fetch", fetchMock);
  vi.stubGlobal(
    "matchMedia",
    vi.fn(() => ({ matches: false, addEventListener: () => undefined, removeEventListener: () => undefined })),
  );
  URL.createObjectURL = vi.fn(() => "blob:khazenly");
  URL.revokeObjectURL = vi.fn();
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("Operations → Khazenly (ADR 0071)", () => {
  it("says how fresh Shopify's tags are and waits for a file", async () => {
    respond(() => reply(200, built));
    render(<OperationsKhazenly />);

    expect(await screen.findByText("Updated 2 minutes ago")).toBeTruthy();
    expect(fetchMock.mock.calls[0][0]).toContain("/api/order-ops/khazenly");
    const button = screen.getByRole("button", { name: "Build the file" }) as HTMLButtonElement;
    expect(button.disabled).toBe(true);
  });

  it("uploads the export, then shows the summary and the file to download", async () => {
    respond(() => reply(200, built));
    render(<OperationsKhazenly />);
    await chooseAndBuild();

    const download = await screen.findByRole("link", { name: /Download khazenly-bulk-confirm-2026-10-30-2245.xlsx/ });
    expect(download.getAttribute("href")).toBe("blob:khazenly");
    expect(download.getAttribute("download")).toBe("khazenly-bulk-confirm-2026-10-30-2245.xlsx");

    const post = fetchMock.mock.calls.find(([, init]) => init?.method === "POST")!;
    expect(post[0]).toBe("/api/order-ops/khazenly");
    expect(post[1].body).toBeInstanceOf(FormData);

    expect(screen.getByText("In Khazenly's file").parentElement?.textContent).toContain("4");
    expect(screen.getByText("Confirmed").parentElement?.textContent).toContain("2");
    expect(screen.getByText("Left out · 2 orders")).toBeTruthy();
    expect(screen.getByText("Held back for safety")).toBeTruthy();

    // The summary comes before the download, as asked.
    const summary = screen.getByText("Left out · 2 orders");
    expect(summary.compareDocumentPosition(download) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it("opens a reason to show its orders by number only", async () => {
    respond(() => reply(200, built));
    render(<OperationsKhazenly />);
    await chooseAndBuild();

    const reason = await screen.findByRole("button", { name: /Not open in Shopify/ });
    expect(screen.queryByText("#31874")).toBeNull();
    fireEvent.click(reason);

    expect(reason.getAttribute("aria-expanded")).toBe("true");
    expect(screen.getByText("#31874")).toBeTruthy();
    expect(screen.getByText("KH-HBA-08800009")).toBeTruthy();
  });

  it("says when rows were not read as orders", async () => {
    respond(() => reply(200, { ...built, skipped_rows: 1 }));
    render(<OperationsKhazenly />);
    await chooseAndBuild();

    expect(await screen.findByText(/1 row in the export had no Khazenly sales order number/)).toBeTruthy();
  });

  it("offers no file when nothing is confirmed", async () => {
    respond(() =>
      reply(200, { ...built, confirmed: 0, not_confirmed: 4, file: null }),
    );
    render(<OperationsKhazenly />);
    await chooseAndBuild();

    expect(await screen.findByText(/no file to upload/)).toBeTruthy();
    expect(screen.queryByRole("link", { name: /Download/ })).toBeNull();
  });

  it("shows a refused file's reason in words", async () => {
    respond(() => reply(422, { detail: "The sales order number KH-HBA-08800001 is in the file twice. Nothing was built." }));
    render(<OperationsKhazenly />);
    await chooseAndBuild();

    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toContain("is in the file twice");
    expect(screen.queryByRole("link", { name: /Download/ })).toBeNull();
  });

  it("builds nothing while Shopify's tags are old", async () => {
    respond(() => reply(200, built), { freshness: freshness({ state: "stale", updated_at: minutesAgo(25) }) });
    render(<OperationsKhazenly />);

    const input = await screen.findByLabelText(/Choose Khazenly's export/);
    fireEvent.change(input, { target: { files: [new File(["x"], "a.xlsx")] } });

    const button = screen.getByRole("button", { name: "Build the file" }) as HTMLButtonElement;
    expect(button.disabled).toBe(true);
    expect(screen.getByText(/must be up to date before a file is built/)).toBeTruthy();
    expect(screen.getByText("Not updated for 25 minutes")).toBeTruthy();
  });

  it("builds nothing while Shopify isn't connected", async () => {
    respond(() => reply(200, built), { freshness: freshness({ state: "not_connected" }) });
    render(<OperationsKhazenly />);

    expect(await screen.findByText("Shopify isn't connected yet.")).toBeTruthy();
    await waitFor(() =>
      expect((screen.getByRole("button", { name: "Build the file" }) as HTMLButtonElement).disabled).toBe(true),
    );
  });
});
