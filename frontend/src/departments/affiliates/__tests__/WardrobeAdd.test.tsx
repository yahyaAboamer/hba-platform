// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { WardrobeAdd } from "../WardrobeAdd";

const reply = (status: number, body: unknown) =>
  Promise.resolve({
    ok: status < 400, status,
    headers: { get: () => "application/json" },
    json: () => Promise.resolve(body),
    text: () => Promise.resolve(JSON.stringify(body)),
  } as unknown as Response);

const FOUND = {
  products: [
    { shopify_product_id: "pants", title: "HBA CLUB pants", image_url: null },
    { shopify_product_id: "jersey", title: "Realtree Jersey", image_url: null },
  ],
};

let fetchMock: ReturnType<typeof vi.fn>;
beforeEach(() => {
  fetchMock = vi.fn((url: string) => {
    if (url.startsWith("/api/products?")) return reply(200, FOUND);
    if (url === "/api/products/jersey") return reply(200, { sizes: [{ title: "L" }, { title: "XL" }] });
    if (url === "/api/products/jersey/manual-assignments") return reply(200, { added: [7], roster: {} });
    return reply(404, { detail: "unexpected" });
  });
  vi.stubGlobal("fetch", fetchMock);
});
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

describe("Add a product to a model's wardrobe (ADR 0061)", () => {
  it("searches the whole catalogue and will not offer what she already has", async () => {
    render(<WardrobeAdd affiliateId={7} name="Ziad Mohamed" owned={new Set(["pants"])} onDone={() => {}} onCancel={() => {}} />);
    fireEvent.change(screen.getByRole("textbox", { name: "Search products" }), { target: { value: "hba" } });

    const owned = await screen.findByRole("button", { name: /HBA CLUB pants/ }) as HTMLButtonElement;
    expect(owned.disabled).toBe(true);
    expect(owned.textContent).toContain("Already received");
    expect((screen.getByRole("button", { name: /Realtree Jersey/ }) as HTMLButtonElement).disabled).toBe(false);
    expect(fetchMock.mock.calls[0][0]).toBe("/api/products?all_products=true&limit=20&search=hba");
  });

  it("saves the chosen product and size for her", async () => {
    const onDone = vi.fn();
    render(<WardrobeAdd affiliateId={7} name="Ziad Mohamed" owned={new Set()} onDone={onDone} onCancel={() => {}} />);
    const save = screen.getByRole("button", { name: "Add to wardrobe" }) as HTMLButtonElement;
    expect(save.disabled).toBe(true);

    fireEvent.change(screen.getByRole("textbox", { name: "Search products" }), { target: { value: "jersey" } });
    fireEvent.click(await screen.findByRole("button", { name: /Realtree Jersey/ }));
    fireEvent.change(await screen.findByRole("combobox", { name: "Size" }), { target: { value: "XL" } });
    fireEvent.click(save);

    await waitFor(() => expect(onDone).toHaveBeenCalled());
    const [url, init] = fetchMock.mock.calls.at(-1)!;
    expect(url).toBe("/api/products/jersey/manual-assignments");
    expect(JSON.parse(init.body)).toEqual({ affiliate_ids: [7], size: "XL" });
  });

  it("says why when the save is refused", async () => {
    fetchMock.mockImplementation((url: string) => {
      if (url.startsWith("/api/products?")) return reply(200, FOUND);
      if (url === "/api/products/jersey") return reply(200, { sizes: [] });
      return reply(400, { detail: "Choose models only." });
    });
    const onDone = vi.fn();
    render(<WardrobeAdd affiliateId={7} name="Ziad Mohamed" owned={new Set()} onDone={onDone} onCancel={() => {}} />);
    fireEvent.change(screen.getByRole("textbox", { name: "Search products" }), { target: { value: "jersey" } });
    fireEvent.click(await screen.findByRole("button", { name: /Realtree Jersey/ }));
    fireEvent.click(await screen.findByRole("button", { name: "Add to wardrobe" }));

    expect((await screen.findByRole("alert")).textContent).toContain("Choose models only.");
    expect(onDone).not.toHaveBeenCalled();
  });
});
