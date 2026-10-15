// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { GiftReview } from "../GiftReview";

const reply = (status: number, body: unknown) =>
  Promise.resolve({
    ok: status < 400,
    status,
    headers: { get: () => "application/json" },
    json: () => Promise.resolve(body),
    text: () => Promise.resolve(JSON.stringify(body)),
  } as unknown as Response);

const gift = {
  shopify_order_id: "7826437800167",
  order_number: "#28411",
  placed_at: "2026-08-02T10:00:00+00:00",
  discount_codes: ["sponsordis"],
  recipient_name: "Mahmoud M",
  phone: "+20 103 000 0882",
  items: ["1× HBA Washed pants", "1× APEX Compression"],
  same_number: 6,
};

const listing = (gifts: object[], extra: object = {}) => ({
  gifts,
  total: gifts.length,
  models: [{ id: 17, name: "Mahmoud mohammed eldahshan" }, { id: 10, name: "MOHAMED FAYTOURY" }],
  names_unavailable: false,
  ...extra,
});

let fetchMock: ReturnType<typeof vi.fn>;
beforeEach(() => { fetchMock = vi.fn(); vi.stubGlobal("fetch", fetchMock); });
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

describe("Gifts that reached no model (ADR 0060)", () => {
  it("shows who each gift went to and how many share the number", async () => {
    const onCount = vi.fn();
    fetchMock.mockImplementation(() => reply(200, listing([gift])));
    render(<GiftReview onCount={onCount} />);

    await waitFor(() => expect(screen.getByText(/1 free order with a discount code/)).toBeTruthy());
    expect(screen.getByText(/Mahmoud M/)).toBeTruthy();
    expect(screen.getByText(/6 parcels to this number/)).toBeTruthy();
    expect(screen.getByText("1× HBA Washed pants, 1× APEX Compression")).toBeTruthy();
    expect(onCount).toHaveBeenCalledWith(1);
  });

  it("attaches nothing until a model is chosen, then sends her id", async () => {
    fetchMock
      .mockImplementationOnce(() => reply(200, listing([gift])))
      .mockImplementationOnce(() => reply(200, { affiliate_id: 17, orders: ["1", "2", "3", "4", "5", "6"] }))
      .mockImplementation(() => reply(200, listing([])));
    render(<GiftReview />);

    const attach = await screen.findByRole("button", { name: "Attach" }) as HTMLButtonElement;
    expect(attach.disabled).toBe(true);

    fireEvent.change(screen.getByRole("combobox", { name: "Whose gift is #28411?" }), { target: { value: "17" } });
    fireEvent.click(attach);

    await waitFor(() => expect(screen.getByText(/6 parcels attached to Mahmoud mohammed eldahshan/)).toBeTruthy());
    const [url, init] = fetchMock.mock.calls[1];
    expect(url).toBe("/api/operations/unclaimed-gifts/7826437800167/assign");
    expect(JSON.parse(init.body)).toEqual({ affiliate_id: 17 });
  });

  it("says why an answer was refused", async () => {
    fetchMock
      .mockImplementationOnce(() => reply(200, listing([gift])))
      .mockImplementationOnce(() => reply(409, { detail: "This number belongs to Sara Edris. Fix the phone on her profile instead." }));
    render(<GiftReview />);

    fireEvent.click(await screen.findByRole("button", { name: "Not a model" }));

    await waitFor(() => expect(screen.getByRole("alert").textContent).toMatch(/belongs to Sara Edris/));
  });

  it("draws nothing when no gift is waiting", async () => {
    fetchMock.mockImplementation(() => reply(200, listing([])));
    const { container } = render(<GiftReview />);
    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    expect(container.textContent).toBe("");
  });
});
