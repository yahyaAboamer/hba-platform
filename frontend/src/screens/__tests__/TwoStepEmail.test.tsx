// @vitest-environment jsdom
/**
 * Where the second code comes from, and remembered browsers (Batch 1.3b):
 * email for most people, an authenticator app for the owner, and no second
 * step at all on a browser remembered for 30 days.
 */
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { Settings } from "../Settings";
import { SignIn } from "../SignIn";
import type { Session } from "../../lib/api";

const reply = (status: number, body: unknown) =>
  Promise.resolve({
    ok: status < 400, status,
    headers: { get: () => "application/json" },
    json: () => Promise.resolve(body),
    text: () => Promise.resolve(JSON.stringify(body)),
  } as unknown as Response);

const PERMISSIONS = ["affiliates.view", "settings.manage", "payroll.approve", "invitations.send", "audit.view"];
const ME = {
  actor: { id: 1, email: "owner@hbawear.store", display_name: "Yahya", roles: ["admin"], is_staff: true, is_model: false },
  permissions: PERMISSIONS,
  platform: { working_month: "2026-10", go_live_month: "2026-10", start_month: "2026-01" },
} as unknown as Session;

type Call = { url: string; method: string; body: any };
let calls: Call[];
let routes: (url: string, method: string, body: any) => Promise<Response> | undefined;

beforeEach(() => {
  calls = [];
  routes = () => undefined;
  vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === "string" ? input : String(input);
    const method = init?.method ?? "GET";
    const body = init?.body ? JSON.parse(String(init.body)) : undefined;
    calls.push({ url, method, body });
    return routes(url, method, body) ?? reply(404, { detail: "Not here" });
  }));
});
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

const called = (method: string, url: string) => calls.find((c) => c.method === method && c.url === url);

// ── The code step ───────────────────────────────────────────────────────────

function signInThrough(answer: Record<string, unknown>) {
  routes = (url) => {
    if (url === "/api/auth/login") return reply(200, { two_step: "code", pending: "tok", expires_in: 600, ...answer });
    if (url === "/api/auth/login/two-step") return reply(200, { actor: ME.actor, csrf: "c" });
    if (url === "/api/auth/me") return reply(200, ME);
  };
  const onSignedIn = vi.fn();
  render(<MemoryRouter><SignIn onSignedIn={onSignedIn} /></MemoryRouter>);
  fireEvent.change(screen.getByLabelText("Email"), { target: { value: "mona@hbawear.store" } });
  fireEvent.change(screen.getByLabelText(/^Password/), { target: { value: "correct horse" } });
  fireEvent.click(screen.getByRole("button", { name: "Sign in" }));
  return onSignedIn;
}

describe("The code step", () => {
  it("says an email code was sent, to the masked address, and has no recovery code", async () => {
    signInThrough({ method: "email", sent_to: "m•••@hbawear.store" });
    expect(await screen.findByText("We sent a 6-digit code to m•••@hbawear.store. It works for 10 minutes.")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Send a new code" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: /recovery code/ })).toBeNull();
  });

  it("says where an authenticator code comes from", async () => {
    signInThrough({ method: "authenticator" });
    expect(await screen.findByText(/Open your authenticator app \(for example Google Authenticator\)/)).toBeTruthy();
    expect(screen.getByRole("button", { name: "Use a recovery code instead" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Send a new code" })).toBeNull();
  });

  it("remembers the browser by default, and not when it is unticked", async () => {
    const first = signInThrough({ method: "email", sent_to: "m•••@hbawear.store" });
    const box = await screen.findByLabelText("Remember this browser for 30 days") as HTMLInputElement;
    expect(box.checked).toBe(true);
    fireEvent.change(screen.getByLabelText("6-digit code"), { target: { value: "123456" } });
    fireEvent.click(screen.getByRole("button", { name: "Sign in" }));
    await waitFor(() => expect(first).toHaveBeenCalled());
    expect(called("POST", "/api/auth/login/two-step")?.body).toEqual({ pending: "tok", code: "123456", remember: true });

    cleanup();
    calls = [];
    const second = signInThrough({ method: "email", sent_to: "m•••@hbawear.store" });
    fireEvent.click(await screen.findByLabelText("Remember this browser for 30 days"));
    fireEvent.change(screen.getByLabelText("6-digit code"), { target: { value: "654321" } });
    fireEvent.click(screen.getByRole("button", { name: "Sign in" }));
    await waitFor(() => expect(second).toHaveBeenCalled());
    expect(called("POST", "/api/auth/login/two-step")?.body).toEqual({ pending: "tok", code: "654321", remember: false });
  });

  it("tells you to leave remembering off on a shared computer", async () => {
    signInThrough({ method: "email", sent_to: "m•••@hbawear.store" });
    expect(await screen.findByText("Leave this off on a shared computer.")).toBeTruthy();
    expect((screen.getByLabelText("Remember this browser for 30 days") as HTMLInputElement).checked).toBe(true);
  });

  it("goes back to the password with the server's words after too many wrong codes", async () => {
    signInThrough({ method: "email", sent_to: "m•••@hbawear.store" });
    const base = routes;
    routes = (url, method, body) =>
      url === "/api/auth/login/two-step" ? reply(410, { detail: "Too many wrong codes. Start again." }) : base(url, method, body);
    fireEvent.change(await screen.findByLabelText("6-digit code"), { target: { value: "000000" } });
    fireEvent.click(screen.getByRole("button", { name: "Sign in" }));
    expect((await screen.findByRole("alert")).textContent).toBe("Too many wrong codes. Start again.");
    expect(screen.getByLabelText("Email")).toBeTruthy();
  });

  it("shows the server's words, not a wrong-password line, when too many code emails were asked for", async () => {
    routes = (url) => url === "/api/auth/login" ? reply(429, { detail: "Too many sign-in codes sent. Try again in 15 minutes." }) : undefined;
    render(<MemoryRouter><SignIn onSignedIn={vi.fn()} /></MemoryRouter>);
    fireEvent.change(screen.getByLabelText("Email"), { target: { value: "mona@hbawear.store" } });
    fireEvent.change(screen.getByLabelText(/^Password/), { target: { value: "correct horse" } });
    fireEvent.click(screen.getByRole("button", { name: "Sign in" }));
    expect((await screen.findByRole("alert")).textContent).toBe("Too many sign-in codes sent. Try again in 15 minutes.");
  });

  it("sends a new code, and shows the wait when asked too soon", async () => {
    signInThrough({ method: "email", sent_to: "m•••@hbawear.store" });
    const base = routes;
    let tries = 0;
    routes = (url, method, body) => {
      if (url === "/api/auth/login/resend") {
        tries += 1;
        return tries === 1
          ? reply(200, { sent_to: "m•••@hbawear.store", expires_in: 600 })
          : reply(429, { detail: "Wait 60 seconds before asking for another code." });
      }
      return base(url, method, body);
    };
    fireEvent.click(await screen.findByRole("button", { name: "Send a new code" }));
    expect((await screen.findByRole("status")).textContent).toContain("A new code is on its way");
    expect(called("POST", "/api/auth/login/resend")?.body).toEqual({ pending: "tok" });

    fireEvent.click(screen.getByRole("button", { name: "Send a new code" }));
    expect((await screen.findByRole("alert")).textContent).toBe("Wait 60 seconds before asking for another code.");
  });
});

// ── Settings → My preferences ───────────────────────────────────────────────

const NOW = new Date().toISOString();
const BROWSERS = {
  browsers: [
    { id: 3, device: "Chrome on Windows", ip_address: "41.2.3.4", created_at: NOW, last_used_at: NOW, expires_at: "2026-11-20T10:00:00Z", current: true },
    { id: 4, device: "Safari on iPhone", ip_address: null, created_at: NOW, last_used_at: null, expires_at: "2026-11-15T10:00:00Z", current: false },
  ],
};

const statusOf = (over: Record<string, unknown>) => ({
  enabled: false, required: false, must_set_up: false, method: null, email_on: false, required_method: null,
  enabled_at: null, recovery_codes_left: 0, ...over,
});

function settingsWith(status: Record<string, unknown>) {
  let current = status;
  routes = (url, method) => {
    if (url === "/api/staff/me/preferences") return reply(200, { preferences: {}, labels: {}, descriptions: {}, theme: null });
    if (url === "/api/auth/two-step" && method === "GET") return reply(200, current);
    if (url === "/api/auth/sessions") return reply(200, { sessions: [] });
    if (url === "/api/auth/trusted-browsers") return reply(200, BROWSERS);
    if (url === "/api/auth/trusted-browsers/4/forget") return reply(200, { forgotten: 1 });
    if (url === "/api/auth/trusted-browsers/forget-all") return reply(200, { forgotten: 2 });
    if (url === "/api/auth/two-step/email") {
      current = statusOf({ email_on: true, method: "email" });
      return reply(200, current);
    }
  };
  render(<MemoryRouter initialEntries={["/settings?section=appearance"]}><Settings session={ME} /></MemoryRouter>);
}

describe("Settings → Two-step sign-in", () => {
  it("tells the owner an authenticator app is required, and offers no email choice", async () => {
    settingsWith(statusOf({ enabled: true, method: "authenticator", required: true, required_method: "authenticator", recovery_codes_left: 9 }));
    expect(await screen.findByText("Required for your access: a code from an authenticator app on a new browser.")).toBeTruthy();
    expect(screen.queryByRole("switch", { name: "Code by email" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Turn off" })).toBeNull();
  });

  it("tells somebody who approves money a code by email is required, with nothing to set up", async () => {
    settingsWith(statusOf({ method: "email", email_on: true, required: true, required_method: "email" }));
    expect(await screen.findByText("Required for your access: a code by email on a new browser.")).toBeTruthy();
    const email = screen.getByRole("switch", { name: "Code by email" }) as HTMLButtonElement;
    expect(email.getAttribute("aria-checked")).toBe("true");
    expect(email.disabled).toBe(true);
  });

  it("offers other staff two choices, and asks the password before turning email codes on", async () => {
    settingsWith(statusOf({}));
    const email = await screen.findByRole("switch", { name: "Code by email" });
    expect(email.getAttribute("aria-checked")).toBe("false");
    expect(screen.getByRole("button", { name: "Set up two-step sign-in" })).toBeTruthy();

    fireEvent.click(email);
    fireEvent.change(await screen.findByLabelText("Password"), { target: { value: "correct horse" } });
    fireEvent.click(screen.getByRole("button", { name: "Turn on" }));
    await waitFor(() => expect(called("POST", "/api/auth/two-step/email")?.body).toEqual({ on: true, password: "correct horse" }));
    await waitFor(() => expect(screen.getByRole("switch", { name: "Code by email" }).getAttribute("aria-checked")).toBe("true"));
  });

  it("shows the server's message when the password is wrong", async () => {
    settingsWith(statusOf({}));
    const base = routes;
    routes = (url, method, body) =>
      url === "/api/auth/two-step/email" ? reply(400, { detail: "That password is not right." }) : base(url, method, body);
    fireEvent.click(await screen.findByRole("switch", { name: "Code by email" }));
    fireEvent.change(await screen.findByLabelText("Password"), { target: { value: "nope" } });
    fireEvent.click(screen.getByRole("button", { name: "Turn on" }));
    expect((await screen.findByRole("alert")).textContent).toBe("That password is not right.");
  });

  it("lists remembered browsers, and forgets one or all", async () => {
    settingsWith(statusOf({}));
    const list = await screen.findByRole("list", { name: "Remembered browsers" });
    const rows = within(list).getAllByRole("listitem");
    expect(rows[0].textContent).toContain("This browser");
    expect(rows[1].textContent).toContain("Safari on iPhone");
    fireEvent.click(within(rows[1]).getByRole("button", { name: "Forget Safari on iPhone" }));
    await waitFor(() => expect(called("POST", "/api/auth/trusted-browsers/4/forget")).toBeTruthy());
    fireEvent.click(screen.getByRole("button", { name: "Forget every browser" }));
    await waitFor(() => expect(called("POST", "/api/auth/trusted-browsers/forget-all")).toBeTruthy());
  });
});

// ── Team ────────────────────────────────────────────────────────────────────

const ROSTER = {
  staff: [
    { id: 1, email: "owner@hbawear.store", display_name: "Yahya", roles: ["admin"], status: "active", two_step_enabled: true, two_step_method: "authenticator", last_login_at: null, created_at: null },
    { id: 2, email: "mona@hbawear.store", display_name: "Mona", roles: ["affiliate_manager"], status: "active", two_step_enabled: true, two_step_method: "email", last_login_at: null, created_at: null },
    { id: 3, email: "aya@hbawear.store", display_name: "Aya", roles: ["customer_service"], status: "active", two_step_enabled: false, two_step_method: null, last_login_at: null, created_at: null },
  ],
  invitations: [],
  assignable_roles: ["admin"],
  invitable_roles: ["admin"],
  role_permissions: { admin: PERMISSIONS },
};

describe("Settings → Team", () => {
  beforeEach(() => {
    routes = (url) => {
      if (url === "/api/staff") return reply(200, ROSTER);
      if (url === "/api/staff/invitations") return reply(200, { invitations: [], invitable_roles: [], role_permissions: {} });
      if (url === "/api/staff/2/sessions") return reply(200, { sessions: [] });
      if (url === "/api/staff/2/trusted-browsers") return reply(200, BROWSERS);
    };
    render(<MemoryRouter initialEntries={["/settings?section=team"]}><Settings session={ME} /></MemoryRouter>);
  });

  it("says which kind of two-step sign-in a person has", async () => {
    const mona = (await screen.findByText("Mona")).closest("tr")!;
    expect(within(mona).getByLabelText("Two-step sign-in on, code by email")).toBeTruthy();
    expect(within(screen.getByText("Yahya").closest("tr")!).getByLabelText("Two-step sign-in on, authenticator app")).toBeTruthy();
    expect(within(screen.getByText("Aya").closest("tr")!).queryByLabelText(/Two-step sign-in on/)).toBeNull();
  });

  it("lists a person's remembered browsers beside their devices", async () => {
    fireEvent.click(await screen.findByRole("button", { name: "More for Mona" }));
    // Email codes have no authenticator to reset.
    expect(screen.queryByRole("button", { name: /Reset two-step sign-in/ })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: /Signed in on/ }));
    const dialog = await screen.findByRole("dialog");
    const list = await within(dialog).findByRole("list", { name: "Remembered browsers for Mona" });
    expect(within(list).getAllByRole("listitem")).toHaveLength(2);
  });
});
