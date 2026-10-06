// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { IntegrationKeys } from "../IntegrationKey";

const reply = (status: number, body: unknown) =>
  Promise.resolve({
    ok: status < 400,
    status,
    headers: { get: () => "application/json" },
    json: () => Promise.resolve(body),
    text: () => Promise.resolve(JSON.stringify(body)),
  } as unknown as Response);

const state = (provider: "bosta" | "estebdal", extra: object = {}) => ({
  provider,
  label: provider === "bosta" ? "Bosta" : "E-stebdal",
  source: null,
  hint: null,
  verified_at: null,
  problem: null,
  can_save: true,
  key_problem: null,
  ...extra,
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

function card(name: string) {
  return screen.getByRole("region", { name });
}

async function openCard(name: string, button: string) {
  const region = await screen.findByRole("region", { name });
  fireEvent.click(await within(region).findByRole("button", { name: button }));
}

describe("Operations' keys in Settings (ADR 0057 §10)", () => {
  it("says where each key comes from and shows only its last four", async () => {
    fetchMock.mockImplementation((url: string) =>
      url.endsWith("/bosta")
        ? reply(
            200,
            state("bosta", {
              source: "saved",
              hint: "ends in a1b2",
              verified_at: "2026-10-03T11:02:00Z",
            }),
          )
        : reply(200, state("estebdal", { source: "environment", hint: "ends in 9f3c" })),
    );
    render(<IntegrationKeys />);

    await waitFor(() => expect(within(card("Bosta")).getByText(/Connected/)).toBeTruthy());
    expect(
      within(card("Bosta")).getByText("Connected · ends in a1b2 · checked 3 Oct, 14:02"),
    ).toBeTruthy();
    expect(within(card("Bosta")).getByRole("button", { name: "Replace key" })).toBeTruthy();
    expect(
      within(card("E-stebdal")).getByText("From Railway · set on the server, ends in 9f3c"),
    ).toBeTruthy();
    expect(
      within(card("E-stebdal")).getByRole("button", { name: "Save a key here instead" }),
    ).toBeTruthy();
  });

  it("checks a new key with the provider, saves it, and clears the field", async () => {
    let sent: unknown = null;
    fetchMock.mockImplementation((url: string, init?: RequestInit) => {
      if (url.endsWith("/estebdal")) return reply(200, state("estebdal"));
      if (init?.method === "PUT") {
        sent = JSON.parse(String(init.body));
        return reply(
          200,
          state("bosta", {
            source: "saved",
            hint: "ends in c3d4",
            verified_at: "2026-10-07T08:00:00Z",
          }),
        );
      }
      return reply(200, state("bosta"));
    });
    render(<IntegrationKeys />);

    await openCard("Bosta", "Add key");
    expect(screen.getByText(/Use a read-only key/)).toBeTruthy();
    fireEvent.change(screen.getByLabelText("New Bosta key"), {
      target: { value: "bosta-new-key-0000c3d4" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Check and save" }));

    await waitFor(() => expect(screen.getByText("Key saved. Bosta answered with it.")).toBeTruthy());
    expect(sent).toEqual({ key: "bosta-new-key-0000c3d4" });
    expect(screen.queryByLabelText("New Bosta key")).toBeNull();
    expect(within(card("Bosta")).getByText(/ends in c3d4/)).toBeTruthy();
  });

  it("a refused key says why and keeps what was typed", async () => {
    fetchMock.mockImplementation((url: string, init?: RequestInit) => {
      if (url.endsWith("/estebdal")) return reply(200, state("estebdal"));
      if (init?.method === "PUT") {
        return reply(422, {
          detail:
            "Bosta did not accept this key (Bosta refused the key.). The key in use has not changed.",
        });
      }
      return reply(200, state("bosta", { source: "saved", hint: "ends in a1b2" }));
    });
    render(<IntegrationKeys />);

    await openCard("Bosta", "Replace key");
    fireEvent.change(screen.getByLabelText("New Bosta key"), { target: { value: "wrong-key-zzzz" } });
    fireEvent.click(screen.getByRole("button", { name: "Check and save" }));

    await waitFor(() =>
      expect(screen.getByRole("alert").textContent).toContain("The key in use has not changed."),
    );
    expect((screen.getByLabelText("New Bosta key") as HTMLInputElement).value).toBe(
      "wrong-key-zzzz",
    );
  });

  it("cannot save while the server has no key to protect it with", async () => {
    fetchMock.mockImplementation((url: string) =>
      reply(
        200,
        state(url.endsWith("/bosta") ? "bosta" : "estebdal", {
          can_save: false,
          key_problem: "SETTINGS_ENCRYPTION_KEY is not set",
        }),
      ),
    );
    render(<IntegrationKeys />);

    const region = await screen.findByRole("region", { name: "Bosta" });
    const button = await within(region).findByRole("button", { name: "Add key" });
    expect((button as HTMLButtonElement).disabled).toBe(true);
    expect(within(region).getByText(/SETTINGS_ENCRYPTION_KEY is not set/)).toBeTruthy();
  });
});
