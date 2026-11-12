// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { GiftOrders } from "../GiftOrders";

const reply = (status: number, body: unknown) =>
  Promise.resolve({
    ok: status < 400, status,
    headers: { get: () => "application/json" },
    json: () => Promise.resolve(body),
    text: () => Promise.resolve(JSON.stringify(body)),
  } as unknown as Response);

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

describe("The gift orders placed for a model", () => {
  it("lists each order with its date, pieces and where it got to, linking to Shopify", async () => {
    vi.stubGlobal("fetch", vi.fn((url: string) => url === "/api/affiliates/7/wardrobe/orders"
      ? reply(200, { orders: [
          { shopify_order_id: "2", order_number: "#31002", placed_at: "2026-11-03T10:00:00Z", state: "processing",
            delivered_at: null, admin_url: "https://hbawear.myshopify.com/admin/orders/2",
            items: [{ title: "HBA CLUB pants", size: "L", quantity: 1 }] },
          { shopify_order_id: "1", order_number: "#30001", placed_at: "2026-10-01T10:00:00Z", state: "received",
            delivered_at: "2026-10-04T10:00:00Z", admin_url: null,
            items: [{ title: "Realtree Jersey", size: "M", quantity: 2 }] },
        ] })
      : reply(404, { detail: "unexpected" })));

    render(<GiftOrders affiliateId={7} name="Sara" reload={0} />);

    const link = await screen.findByRole("link", { name: "#31002" });
    expect(link.getAttribute("href")).toBe("https://hbawear.myshopify.com/admin/orders/2");
    expect(screen.getByText("2 orders")).toBeTruthy();
    expect(screen.getByText("HBA CLUB pants (L)")).toBeTruthy();
    expect(screen.getByText("Realtree Jersey (M) ×2")).toBeTruthy();
    expect(screen.getByText("On its way")).toBeTruthy();
    expect(screen.getByText("Delivered")).toBeTruthy();
    expect(screen.getByText("#30001")).toBeTruthy();
  });

  it("says plainly when no order has been placed", async () => {
    vi.stubGlobal("fetch", vi.fn(() => reply(200, { orders: [] })));
    render(<GiftOrders affiliateId={7} name="Sara" reload={0} />);
    expect(await screen.findByText("No gift order has been placed for Sara yet.")).toBeTruthy();
  });
});
