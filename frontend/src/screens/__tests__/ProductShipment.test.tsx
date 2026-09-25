// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { Session } from "../../lib/api";
import { ProductDetail } from "../Products";

const reply = (status: number, body: unknown) =>
  Promise.resolve({
    ok: status < 400, status,
    headers: { get: () => "application/json" },
    json: () => Promise.resolve(body),
    text: () => Promise.resolve(JSON.stringify(body)),
  } as unknown as Response);

const SESSION = { actor: {}, permissions: ["affiliates.view", "affiliates.manage"], platform: {} } as unknown as Session;
const DETAIL = {
  shopify_product_id: "track-jacket", title: "Panel Track Jacket", status: "active", image_url: null, sizes: [],
  roster: {
    received: [], needs_checking: [],
    processing: [{ affiliate_id: 1, name: "Sara Edrees", status: "active", shopify_order_id: "2001", order_number: "#G2001", size: "M" }],
    not_sent: [{ affiliate_id: 2, name: "Aya Sherif", status: "active" }],
  },
  feature_request: null,
};

let fetchMock: ReturnType<typeof vi.fn>;
beforeEach(() => { fetchMock = vi.fn(() => reply(200, DETAIL)); vi.stubGlobal("fetch", fetchMock); });
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

const at = (url: string) => render(
  <MemoryRouter initialEntries={[url]}>
    <Routes><Route path="/products/:id" element={<ProductDetail session={SESSION} />} /></Routes>
  </MemoryRouter>,
);

describe("a product's coverage names the order that carried it (item 16)", () => {
  it("prints the order beside a model who has it, and not sent beside one who does not", async () => {
    at("/products/track-jacket");
    const order = await screen.findByRole("link", { name: "#G2001" });
    expect(order.getAttribute("href")).toBe("/products/track-jacket?shipment=2001&model=1");
    expect(screen.getByText("not sent")).toBeTruthy();
  });

  it("opens the export's shipment record from the address alone", async () => {
    at("/products/track-jacket?shipment=2001&model=1");
    expect(await screen.findByRole("heading", { name: "Shipment record" })).toBeTruthy();
    expect(screen.getByText("Panel Track Jacket · Sara Edrees")).toBeTruthy();
    expect(screen.getByText("Processing")).toBeTruthy();
    expect(screen.getByText("M")).toBeTruthy();
    expect(screen.getByText("#G2001")).toBeTruthy();
  });

  it("the message presets fill the message, which counts its characters", async () => {
    at("/products/track-jacket?view=promotion");
    fireEvent.click(await screen.findByRole("button", { name: "New colourway" }));
    await waitFor(() => expect((screen.getByLabelText(/Short message/) as HTMLTextAreaElement).value)
      .toBe("New colourway — we would love to see it styled."));
    expect(screen.getByText(`${"New colourway — we would love to see it styled.".length} characters`)).toBeTruthy();
  });
});
