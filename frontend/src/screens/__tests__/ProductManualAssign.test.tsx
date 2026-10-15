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

const MANAGER = { actor: {}, permissions: ["affiliates.view", "affiliates.manage"], platform: {} } as unknown as Session;
const VIEWER = { actor: {}, permissions: ["affiliates.view"], platform: {} } as unknown as Session;

const ROSTER = {
  received: [{ affiliate_id: 1, name: "Sara Edris", status: "active", shopify_order_id: "2001", order_number: "#2001", size: "M", manual: false }],
  processing: [], needs_checking: [],
  not_sent: [
    { affiliate_id: 2, name: "Ziad Mohamed", status: "active", manual: false },
    { affiliate_id: 3, name: "Mahmoud eldahshan", status: "active", manual: false },
    { affiliate_id: 4, name: "Left Already", status: "archived", manual: false },
  ],
};
const DETAIL = {
  shopify_product_id: "pants", title: "HBA CLUB pants", status: "active", image_url: null,
  sizes: [{ title: "M", sku: null }, { title: "L", sku: null }],
  roster: ROSTER, feature_request: null,
};
const AFTER = {
  ...ROSTER,
  received: [...ROSTER.received, { affiliate_id: 3, name: "Mahmoud eldahshan", status: "active", shopify_order_id: null, order_number: null, size: "L", manual: true }],
  not_sent: ROSTER.not_sent.filter((row) => row.affiliate_id !== 3),
};

let fetchMock: ReturnType<typeof vi.fn>;
beforeEach(() => { fetchMock = vi.fn(() => reply(200, DETAIL)); vi.stubGlobal("fetch", fetchMock); });
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

const at = (session: Session) => render(
  <MemoryRouter initialEntries={["/products/pants"]}>
    <Routes><Route path="/products/:id" element={<ProductDetail session={session} />} /></Routes>
  </MemoryRouter>,
);

describe("Assign manually (ADR 0061)", () => {
  it("offers only models who have not received it, and not archived ones", async () => {
    at(MANAGER);
    fireEvent.click(await screen.findByRole("button", { name: "Assign manually" }));

    const panel = screen.getByRole("region", { name: "Assign manually" });
    expect(panel.textContent).toContain("Ziad Mohamed");
    expect(panel.textContent).toContain("Mahmoud eldahshan");
    expect(panel.textContent).not.toContain("Sara Edris");
    expect(panel.textContent).not.toContain("Left Already");
  });

  it("sends the ticked models and size, then shows her as assigned manually", async () => {
    at(MANAGER);
    fireEvent.click(await screen.findByRole("button", { name: "Assign manually" }));
    const save = screen.getByRole("button", { name: "Assign" }) as HTMLButtonElement;
    expect(save.disabled).toBe(true);

    fireEvent.click(screen.getByRole("checkbox", { name: "Mahmoud eldahshan" }));
    fireEvent.change(screen.getByRole("combobox", { name: "Size" }), { target: { value: "L" } });
    fetchMock.mockImplementationOnce(() => reply(200, { added: [3], roster: AFTER }));
    fireEvent.click(save);

    await waitFor(() => expect(screen.getByText("Assigned manually · L")).toBeTruthy());
    const [url, init] = fetchMock.mock.calls[1];
    expect(url).toBe("/api/products/pants/manual-assignments");
    expect(JSON.parse(init.body)).toEqual({ affiliate_ids: [3], size: "L" });
    expect(screen.queryByRole("region", { name: "Assign manually" })).toBeNull();
  });

  it("removes a manual assignment", async () => {
    fetchMock.mockImplementation(() => reply(200, { ...DETAIL, roster: AFTER }));
    at(MANAGER);
    const remove = await screen.findByRole("button", { name: "Remove the manual assignment for Mahmoud eldahshan" });

    fetchMock.mockImplementationOnce(() => reply(200, { roster: ROSTER }));
    fireEvent.click(remove);

    await waitFor(() => expect(screen.queryByText("Assigned manually · L")).toBeNull());
    expect(fetchMock.mock.calls.at(-1)?.[0]).toBe("/api/products/pants/manual-assignments/3");
  });

  it("is not offered to someone who may only view", async () => {
    at(VIEWER);
    await screen.findByRole("heading", { name: "HBA CLUB pants" });
    expect(screen.queryByRole("button", { name: "Assign manually" })).toBeNull();
  });
});
