// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { PreferenceSwitches } from "../Settings";

const reply = (status: number, body: unknown) =>
  Promise.resolve({
    ok: status < 400, status,
    headers: { get: () => "application/json" },
    json: () => Promise.resolve(body),
    text: () => Promise.resolve(JSON.stringify(body)),
  } as unknown as Response);

const LABELS = { home_notices: "Show pop-up notices on Home", weekly_targets_reminder: "Weekly reminder to record achieved content" };
const body = (home: boolean, weekly: boolean) => ({ preferences: { home_notices: home, weekly_targets_reminder: weekly }, labels: LABELS });

let fetchMock: ReturnType<typeof vi.fn>;
beforeEach(() => { fetchMock = vi.fn(); vi.stubGlobal("fetch", fetchMock); });
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

describe("Settings → Appearance switches (item 11)", () => {
  it("shows what the server holds and saves a change there", async () => {
    fetchMock.mockImplementation((_: string, init?: RequestInit) =>
      init?.method === "PUT" ? reply(200, body(false, true)) : reply(200, body(true, true)));
    render(<PreferenceSwitches />);
    const notices = await screen.findByRole("switch", { name: "Show pop-up notices on Home" });
    expect(notices.getAttribute("aria-checked")).toBe("true");

    fireEvent.click(notices);
    await waitFor(() => expect(notices.getAttribute("aria-checked")).toBe("false"));
    const put = fetchMock.mock.calls.find(([, init]) => init?.method === "PUT")!;
    expect(JSON.parse(put[1].body)).toEqual({ key: "home_notices", enabled: false });
  });

  it("a refusal leaves the switch where it was and says so", async () => {
    fetchMock.mockImplementation((_: string, init?: RequestInit) =>
      init?.method === "PUT" ? reply(500, { detail: "Could not save." }) : reply(200, body(true, true)));
    render(<PreferenceSwitches />);
    const weekly = await screen.findByRole("switch", { name: "Weekly reminder to record achieved content" });
    fireEvent.click(weekly);
    await waitFor(() => expect(screen.getByRole("alert").textContent).toContain("Nothing changed."));
    expect(weekly.getAttribute("aria-checked")).toBe("true");
  });
});
