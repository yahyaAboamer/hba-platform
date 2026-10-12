// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { InboxConnections } from "../InboxConnection";

const reply = (status: number, body: unknown) =>
  Promise.resolve({
    ok: status < 400,
    status,
    headers: { get: () => "application/json" },
    json: () => Promise.resolve(body),
    text: () => Promise.resolve(JSON.stringify(body)),
  } as unknown as Response);

const whatsapp = (extra: object = {}) => ({
  connected: false,
  phone_number_id: null,
  business_account_id: null,
  display_number: null,
  verified_name: null,
  access_token_hint: null,
  app_secret_hint: null,
  verified_at: null,
  sending_enabled: false,
  problem: null,
  can_save: true,
  key_problem: null,
  test_numbers_only: false,
  ...extra,
});

const tags = (extra: object = {}) => ({
  connected: false,
  shop_domain: "hba-test.myshopify.com",
  client_id_hint: null,
  client_secret_hint: null,
  verified_at: null,
  problem: null,
  can_save: true,
  key_problem: null,
  ...extra,
});

const CONNECTED = whatsapp({
  connected: true,
  phone_number_id: "100200300400500",
  business_account_id: "777888999000111",
  display_number: "+20 100 555 0100",
  verified_name: "HBA Wear",
  access_token_hint: "a1b2",
  app_secret_hint: "9f3c",
  verified_at: "2026-10-11T11:02:00Z",
});

let fetchMock: ReturnType<typeof vi.fn>;
beforeEach(() => {
  fetchMock = vi.fn();
  vi.stubGlobal("fetch", fetchMock);
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const card = (name: string) => screen.findByRole("region", { name });
const sentBody = (init?: RequestInit) => JSON.parse(String(init?.body));

describe("The inbox's connections in Settings (ADR 0059)", () => {
  it("says when WhatsApp was last heard from, and how Meta rates the number", async () => {
    fetchMock.mockImplementation((url: string) =>
      url.endsWith("/connection/health")
        ? reply(200, {
            connected: true,
            sending: true,
            last_heard_at: "2026-10-12T08:20:00Z",
            quiet_since: null,
            rating: "GREEN",
          })
        : reply(200, { whatsapp: CONNECTED, tags: tags() }),
    );
    render(<InboxConnections />);

    const region = await card("WhatsApp");
    expect(
      await within(region).findByText("Last heard from 12 Oct, 11:20 · number rating high"),
    ).toBeTruthy();
  });

  it("does not guess a rating it could not read, or a callback that has not come", async () => {
    fetchMock.mockImplementation((url: string) =>
      url.endsWith("/connection/health")
        ? reply(200, { connected: true, sending: false, last_heard_at: null, quiet_since: null, rating: null })
        : reply(200, { whatsapp: CONNECTED, tags: tags() }),
    );
    render(<InboxConnections />);

    const region = await card("WhatsApp");
    expect(await within(region).findByText("Not heard from yet · number rating not known")).toBeTruthy();
  });

  it("shows a connected number, two last-fours and the sending switch, and no key", async () => {
    fetchMock.mockImplementation(() =>
      reply(200, {
        whatsapp: { ...CONNECTED, test_numbers_only: true },
        tags: tags({ connected: true, client_secret_hint: "c7d8" }),
      }),
    );
    render(<InboxConnections />);

    const region = await card("WhatsApp");
    expect(
      within(region).getByText("Connected · HBA Wear · +20 100 555 0100 · checked 11 Oct, 14:02"),
    ).toBeTruthy();
    expect(
      within(region).getByText("Access key ends in a1b2 · app secret ends in 9f3c"),
    ).toBeTruthy();
    expect(
      within(region).getByText("Sending is off · this server only messages its test numbers"),
    ).toBeTruthy();
    expect(within(region).getByRole("button", { name: "Turn sending on" })).toBeTruthy();

    const second = await card("Shopify, for order tags");
    expect(
      within(second).getByText("Connected · hba-test.myshopify.com · secret ends in c7d8"),
    ).toBeTruthy();
  });

  it("checks new keys with WhatsApp, saves them, and clears the fields", async () => {
    let sent: Record<string, string> | null = null;
    fetchMock.mockImplementation((_url: string, init?: RequestInit) => {
      if (init?.method === "PUT") {
        sent = sentBody(init);
        return reply(200, { whatsapp: CONNECTED, tags: tags() });
      }
      return reply(200, { whatsapp: whatsapp(), tags: tags() });
    });
    render(<InboxConnections />);

    const region = await card("WhatsApp");
    expect(within(region).getByText("Not connected")).toBeTruthy();
    fireEvent.click(within(region).getByRole("button", { name: "Connect WhatsApp" }));
    const type = (label: string, value: string) =>
      fireEvent.change(within(region).getByLabelText(label), { target: { value } });
    type("WhatsApp number ID", " 100200300400500 ");
    type("WhatsApp business account ID", "777888999000111");
    type("Access key", "EAAG-made-up-access-key-0000a1b2");
    type("App secret", "made-up-app-secret-000000009f3c");
    type("Check word", "made-up-check-word-0001");
    fireEvent.click(within(region).getByRole("button", { name: "Check and save" }));

    await waitFor(() => expect(within(region).getByRole("status")).toBeTruthy());
    expect(sent).toEqual({
      phone_number_id: "100200300400500",
      business_account_id: "777888999000111",
      access_token: "EAAG-made-up-access-key-0000a1b2",
      app_secret: "made-up-app-secret-000000009f3c",
      verify_token: "made-up-check-word-0001",
    });
    expect(within(region).queryByLabelText("Access key")).toBeNull();
    expect(region.textContent).not.toContain("EAAG-made-up-access-key-0000a1b2");
    expect(within(region).getByText(/Connected · HBA Wear/)).toBeTruthy();
  });

  it("keeps what was typed and says why when WhatsApp refuses", async () => {
    fetchMock.mockImplementation((_url: string, init?: RequestInit) =>
      init?.method === "PUT"
        ? reply(422, {
            detail:
              "WhatsApp did not accept these details (WhatsApp did not accept the access key (code 190)). The connection in use has not changed.",
          })
        : reply(200, { whatsapp: CONNECTED, tags: tags() }),
    );
    render(<InboxConnections />);

    const region = await card("WhatsApp");
    fireEvent.click(within(region).getByRole("button", { name: "Change keys" }));
    const field = within(region).getByLabelText("Access key") as HTMLInputElement;
    expect(field.placeholder).toBe("Leave blank to keep the saved one");
    fireEvent.change(field, { target: { value: "EAAG-a-wrong-key" } });
    fireEvent.click(within(region).getByRole("button", { name: "Check and save" }));

    const alert = await within(region).findByRole("alert");
    expect(alert.textContent).toContain("The connection in use has not changed.");
    expect((within(region).getByLabelText("Access key") as HTMLInputElement).value).toBe(
      "EAAG-a-wrong-key",
    );
  });

  it("turns sending on and off with one press each", async () => {
    const asked: boolean[] = [];
    fetchMock.mockImplementation((_url: string, init?: RequestInit) => {
      if (init?.method === "PUT") {
        const enabled = sentBody(init).enabled as boolean;
        asked.push(enabled);
        return reply(200, { whatsapp: { ...CONNECTED, sending_enabled: enabled }, tags: tags() });
      }
      return reply(200, { whatsapp: CONNECTED, tags: tags() });
    });
    render(<InboxConnections />);

    const region = await card("WhatsApp");
    fireEvent.click(within(region).getByRole("button", { name: "Turn sending on" }));
    fireEvent.click(await within(region).findByRole("button", { name: "Turn sending off" }));
    await within(region).findByRole("button", { name: "Turn sending on" });
    expect(asked).toEqual([true, false]);
    expect(within(region).getByRole("status").textContent).toBe(
      "Sending is off. Nothing will be sent.",
    );
  });

  it("says why the money app is refused as the second app", async () => {
    fetchMock.mockImplementation((_url: string, init?: RequestInit) =>
      init?.method === "PUT"
        ? reply(422, {
            detail:
              "That is the app the platform already reads Shopify with, which must stay read-only. Use the other app. Nothing was changed.",
          })
        : reply(200, { whatsapp: whatsapp(), tags: tags() }),
    );
    render(<InboxConnections />);

    const region = await card("Shopify, for order tags");
    fireEvent.click(within(region).getByRole("button", { name: "Connect the second app" }));
    fireEvent.change(within(region).getByLabelText("Client ID"), { target: { value: "main-app" } });
    fireEvent.change(within(region).getByLabelText("Client secret"), {
      target: { value: "main-secret" },
    });
    fireEvent.click(within(region).getByRole("button", { name: "Check and save" }));

    const alert = await within(region).findByRole("alert");
    expect(alert.textContent).toContain("must stay read-only");
  });

  it("offers no save when this server cannot protect a key", async () => {
    fetchMock.mockImplementation(() =>
      reply(200, {
        whatsapp: whatsapp({ can_save: false, key_problem: "SETTINGS_ENCRYPTION_KEY is not set" }),
        tags: tags({ can_save: false, key_problem: "SETTINGS_ENCRYPTION_KEY is not set" }),
      }),
    );
    render(<InboxConnections />);

    const region = await card("WhatsApp");
    expect(within(region).getByText(/cannot protect a saved key yet/)).toBeTruthy();
    expect(
      (within(region).getByRole("button", { name: "Connect WhatsApp" }) as HTMLButtonElement)
        .disabled,
    ).toBe(true);
  });
});
