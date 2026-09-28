// @vitest-environment jsdom
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { StaleFulfilments } from "../DataPanel";

const reply = (status: number, body: unknown) =>
  Promise.resolve({
    ok: status < 400,
    status,
    headers: { get: () => "application/json" },
    json: () => Promise.resolve(body),
    text: () => Promise.resolve(JSON.stringify(body)),
  } as unknown as Response);

const row = (order_number: string, extra: object = {}) => ({
  shopify_order_id: order_number.slice(1),
  order_number,
  days: 72,
  courier: null,
  attributed: false,
  admin_url: `https://hbawear.myshopify.com/admin/orders/${order_number.slice(1)}`,
  ...extra,
});

let fetchMock: ReturnType<typeof vi.fn>;
beforeEach(() => { fetchMock = vi.fn(); vi.stubGlobal("fetch", fetchMock); });
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

describe("Shipped, and nobody will report on it (ADR 0051)", () => {
  it("groups the orders by why, each linking to Shopify where it is fixed", async () => {
    fetchMock.mockImplementation(() => reply(200, {
      after_days: 14,
      total: 3,
      groups: [
        { reason: "no_tracking", orders: [row("#27611")] },
        { reason: "other_courier", orders: [row("#29406", { courier: "Aramex" })] },
        { reason: "courier_silent", orders: [row("#29533", { courier: "Bosta", attributed: true })] },
        { reason: "not_yet_read", orders: [] },
      ],
    }));
    render(<StaleFulfilments />);

    await waitFor(() => expect(screen.getByText(/3 orders shipped over 14 days ago/)).toBeTruthy());
    expect(screen.getByText("No tracking number · 1")).toBeTruthy();
    expect(screen.getByText("Shipped with another courier · 1")).toBeTruthy();
    expect(screen.getByText("Bosta has gone quiet · 1")).toBeTruthy();
    // An empty group is not drawn.
    expect(screen.queryByText(/Not read since the rules changed/)).toBeNull();

    const link = screen.getByRole("link", { name: "#27611" }) as HTMLAnchorElement;
    expect(link.href).toBe("https://hbawear.myshopify.com/admin/orders/27611");
    expect(screen.getByText("72 days · Aramex")).toBeTruthy();
    expect(screen.getByText("72 days · Bosta · a model's code")).toBeTruthy();
  });

  it("draws nothing when nothing is waiting", async () => {
    fetchMock.mockImplementation(() => reply(200, { after_days: 14, total: 0, groups: [] }));
    const { container } = render(<StaleFulfilments />);
    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    expect(container.textContent).toBe("");
  });

  it("says so when the list cannot load, rather than looking empty", async () => {
    fetchMock.mockImplementation(() => reply(500, { detail: "no" }));
    render(<StaleFulfilments />);
    await waitFor(() => expect(screen.getByText("Could not load this list.")).toBeTruthy());
  });
});
