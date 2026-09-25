// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ShopifyConnection } from "../ShopifyConnection";

const reply = (status: number, body: unknown) =>
  Promise.resolve({
    ok: status < 400,
    status,
    headers: { get: () => "application/json" },
    json: () => Promise.resolve(body),
    text: () => Promise.resolve(JSON.stringify(body)),
  } as unknown as Response);

const SAVED = {
  source: "saved", shop_domain: "hbawear.myshopify.com", client_id_hint: "••••abcd",
  secret_saved: true, verified_at: "2026-09-25T10:00:00Z", shop_name: "HBA Wear", problem: null, can_save: true,
};

let fetchMock: ReturnType<typeof vi.fn>;
beforeEach(() => { fetchMock = vi.fn(); vi.stubGlobal("fetch", fetchMock); });
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

describe("the Shopify connection form (decision b)", () => {
  it("shows the saved connection without any credential, and keeps blank fields as saved", async () => {
    fetchMock.mockImplementation((_: string, init?: RequestInit) =>
      init?.method === "PUT" ? reply(200, SAVED) : reply(200, SAVED));
    render(<ShopifyConnection />);

    await waitFor(() => expect((screen.getByLabelText("Store domain") as HTMLInputElement).value).toBe("hbawear.myshopify.com"));
    expect((screen.getByLabelText("Client ID") as HTMLInputElement).value).toBe("");
    expect((screen.getByLabelText("Client ID") as HTMLInputElement).placeholder).toContain("••••abcd");
    expect((screen.getByLabelText("Client secret") as HTMLInputElement).type).toBe("password");

    fireEvent.click(screen.getByRole("button", { name: "Update connection" }));
    await waitFor(() => expect(screen.getByRole("status").textContent).toContain("HBA Wear"));
    const put = fetchMock.mock.calls.find(([, init]) => init?.method === "PUT")!;
    expect(JSON.parse(put[1].body)).toEqual({ shop_domain: "hbawear.myshopify.com", client_id: null, client_secret: null });
  });

  it("says why a refused connection was not saved, and keeps what was typed", async () => {
    fetchMock.mockImplementation((_: string, init?: RequestInit) =>
      init?.method === "PUT"
        ? reply(422, { detail: "Shopify did not accept this connection (Shopify rejected the credentials (401)). The connection in use has not changed." })
        : reply(200, SAVED));
    render(<ShopifyConnection />);
    await waitFor(() => expect((screen.getByLabelText("Store domain") as HTMLInputElement).value).toBe("hbawear.myshopify.com"));

    fireEvent.change(screen.getByLabelText("Client ID"), { target: { value: "new-id" } });
    fireEvent.change(screen.getByLabelText("Client secret"), { target: { value: "typed-secret" } });
    fireEvent.click(screen.getByRole("button", { name: "Update connection" }));

    await waitFor(() => expect(screen.getByRole("alert").textContent).toContain("has not changed"));
    expect((screen.getByLabelText("Client ID") as HTMLInputElement).value).toBe("new-id");
    expect((screen.getByLabelText("Client secret") as HTMLInputElement).value).toBe("typed-secret");
  });

  it("clears a secret from the page once it has been saved", async () => {
    fetchMock.mockImplementation(() => reply(200, SAVED));
    render(<ShopifyConnection />);
    await waitFor(() => expect((screen.getByLabelText("Store domain") as HTMLInputElement).value).toBe("hbawear.myshopify.com"));
    fireEvent.change(screen.getByLabelText("Client secret"), { target: { value: "typed-secret" } });
    fireEvent.click(screen.getByRole("button", { name: "Update connection" }));
    await waitFor(() => expect(screen.getByRole("status")).toBeTruthy());
    expect((screen.getByLabelText("Client secret") as HTMLInputElement).value).toBe("");
  });

  it("will not save where the server cannot protect a secret", async () => {
    fetchMock.mockImplementation(() => reply(200, { ...SAVED, can_save: false }));
    render(<ShopifyConnection />);
    await waitFor(() => expect(screen.getByText(/SETTINGS_ENCRYPTION_KEY/)).toBeTruthy());
    expect((screen.getByRole("button", { name: "Update connection" }) as HTMLButtonElement).disabled).toBe(true);
  });
});
