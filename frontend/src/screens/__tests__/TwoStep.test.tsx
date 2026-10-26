// @vitest-environment jsdom
/**
 * Two-step sign-in, signed-in devices and suspending (Batch 1.3).
 *
 * Everything here talks to a fake `fetch` that answers by address, so what is
 * checked is what the screens ask the server and what they show of the answer.
 */
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import App from "../../App";
import { Settings } from "../Settings";
import { ResetPassword } from "../ResetPassword";
import { SignIn } from "../SignIn";
import type { Session } from "../../lib/api";

const reply = (status: number, body: unknown) =>
  Promise.resolve({
    ok: status < 400, status,
    headers: { get: () => "application/json" },
    json: () => Promise.resolve(body),
    text: () => Promise.resolve(JSON.stringify(body)),
  } as unknown as Response);

const ADMIN_PERMISSIONS = [
  "affiliates.view", "affiliates.manage", "compensation.manage", "invitations.send",
  "payments.record", "payroll.approve", "settings.manage", "audit.view",
];

const ME = {
  // Where the server really sends it: inside `actor` (found on production,
  // 26 October - the screens read it from the top and never saw it).
  actor: {
    id: 1, email: "owner@hbawear.store", display_name: "Yahya", roles: ["admin"], is_staff: true, is_model: false,
    two_step: { enabled: true, required: true, must_set_up: false },
  },
  permissions: ADMIN_PERMISSIONS,
  platform: { working_month: "2026-10", go_live_month: "2026-10", start_month: "2026-01" },
} as unknown as Session;

type Call = { url: string; method: string; body: unknown };
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
afterEach(() => { cleanup(); vi.unstubAllGlobals(); window.history.pushState({}, "", "/"); });

const called = (method: string, url: string) => calls.find((c) => c.method === method && c.url === url);

// ── Signing in ──────────────────────────────────────────────────────────────

function typeCredentials() {
  fireEvent.change(screen.getByLabelText("Email"), { target: { value: "owner@hbawear.store" } });
  fireEvent.change(screen.getByLabelText(/^Password/), { target: { value: "correct horse" } });
  fireEvent.click(screen.getByRole("button", { name: "Sign in" }));
}

function renderSignIn() {
  const onSignedIn = vi.fn();
  render(<MemoryRouter><SignIn onSignedIn={onSignedIn} /></MemoryRouter>);
  return onSignedIn;
}

describe("Sign in", () => {
  it("goes straight in when there is no second step", async () => {
    routes = (url) => {
      if (url === "/api/auth/login") return reply(200, { actor: ME.actor, csrf: "c" });
      if (url === "/api/auth/me") return reply(200, ME);
    };
    const onSignedIn = renderSignIn();
    typeCredentials();
    await waitFor(() => expect(onSignedIn).toHaveBeenCalledWith(ME));
    expect(screen.queryByLabelText("6-digit code")).toBeNull();
  });

  it("asks for a code after the password, then signs in", async () => {
    routes = (url) => {
      if (url === "/api/auth/login") return reply(200, { two_step: "code", pending: "tok", expires_in: 300 });
      if (url === "/api/auth/login/two-step") return reply(200, { actor: ME.actor, csrf: "c" });
      if (url === "/api/auth/me") return reply(200, ME);
    };
    const onSignedIn = renderSignIn();
    typeCredentials();

    const field = await screen.findByLabelText("6-digit code") as HTMLInputElement;
    expect(field.getAttribute("inputmode")).toBe("numeric");
    expect(field.getAttribute("autocomplete")).toBe("one-time-code");
    expect(document.activeElement).toBe(field);
    expect(onSignedIn).not.toHaveBeenCalled();

    fireEvent.change(field, { target: { value: "123 456" } });
    fireEvent.click(screen.getByRole("button", { name: "Sign in" }));
    await waitFor(() => expect(onSignedIn).toHaveBeenCalledWith(ME, undefined));
    expect(called("POST", "/api/auth/login/two-step")?.body).toEqual({ pending: "tok", code: "123 456" });
  });

  it("says a wrong code did not work, and stays on the code step", async () => {
    routes = (url) => {
      if (url === "/api/auth/login") return reply(200, { two_step: "code", pending: "tok", expires_in: 300 });
      if (url === "/api/auth/login/two-step") return reply(401, { detail: "That code did not work." });
    };
    renderSignIn();
    typeCredentials();
    fireEvent.change(await screen.findByLabelText("6-digit code"), { target: { value: "000000" } });
    fireEvent.click(screen.getByRole("button", { name: "Sign in" }));
    expect((await screen.findByRole("alert")).textContent).toBe("That code did not work.");
    expect(screen.getByLabelText("6-digit code")).toBeTruthy();
  });

  it("sends you back to the password when the sign-in has lapsed", async () => {
    routes = (url) => {
      if (url === "/api/auth/login") return reply(200, { two_step: "code", pending: "tok", expires_in: 300 });
      if (url === "/api/auth/login/two-step") return reply(410, { detail: "Sign-in took too long. Start again." });
    };
    renderSignIn();
    typeCredentials();
    fireEvent.change(await screen.findByLabelText("6-digit code"), { target: { value: "123456" } });
    fireEvent.click(screen.getByRole("button", { name: "Sign in" }));
    expect((await screen.findByRole("alert")).textContent).toBe("Sign-in took too long. Start again.");
    expect(screen.getByLabelText("Email")).toBeTruthy();
    expect(screen.queryByLabelText("6-digit code")).toBeNull();
  });

  it("shows the wait when the server throttles the code", async () => {
    routes = (url) => {
      if (url === "/api/auth/login") return reply(200, { two_step: "code", pending: "tok", expires_in: 300 });
      if (url === "/api/auth/login/two-step") return reply(429, { detail: "Too many tries. Try again in 5 minutes." });
    };
    renderSignIn();
    typeCredentials();
    fireEvent.change(await screen.findByLabelText("6-digit code"), { target: { value: "123456" } });
    fireEvent.click(screen.getByRole("button", { name: "Sign in" }));
    expect((await screen.findByRole("alert")).textContent).toContain("Try again in 5 minutes");
  });

  it("offers a recovery code instead, and a way back, and says how many are left", async () => {
    routes = (url) => {
      if (url === "/api/auth/login") return reply(200, { two_step: "code", pending: "tok", expires_in: 300 });
      if (url === "/api/auth/login/two-step") return reply(200, { actor: ME.actor, csrf: "c", recovery_codes_left: 7 });
      if (url === "/api/auth/me") return reply(200, ME);
    };
    const onSignedIn = renderSignIn();
    typeCredentials();

    fireEvent.click(await screen.findByRole("button", { name: "Use a recovery code instead" }));
    const field = screen.getByLabelText("Recovery code") as HTMLInputElement;
    expect(field.getAttribute("inputmode")).toBe("text");
    fireEvent.change(field, { target: { value: "abcde-fghjk" } });
    fireEvent.click(screen.getByRole("button", { name: "Sign in" }));

    await waitFor(() => expect(onSignedIn).toHaveBeenCalled());
    expect(onSignedIn.mock.calls[0][1]).toContain("7 left");
    expect(called("POST", "/api/auth/login/two-step")?.body).toEqual({ pending: "tok", code: "abcde-fghjk" });
  });

  it("goes back to the email and password step on request", async () => {
    routes = (url) => {
      if (url === "/api/auth/login") return reply(200, { two_step: "code", pending: "tok", expires_in: 300 });
    };
    renderSignIn();
    typeCredentials();
    fireEvent.click(await screen.findByRole("button", { name: "Back to email and password" }));
    expect(screen.getByLabelText("Email")).toBeTruthy();
  });
});

// ── The forced set-up screen ────────────────────────────────────────────────

// ── A password reset, for somebody with two-step on ─────────────────────────

describe("Password reset with two-step on", () => {
  it("still asks for the code before signing in", async () => {
    routes = (url) => {
      if (url.startsWith("/api/auth/password-reset/preview")) return reply(200, { email: "owner@hbawear.store" });
      if (url === "/api/auth/password-reset") return reply(200, { two_step: "code", pending: "tok", expires_in: 300 });
      if (url === "/api/auth/login/two-step") return reply(200, { actor: ME.actor, csrf: "c" });
      if (url === "/api/auth/me") return reply(200, ME);
    };
    const onSignedIn = vi.fn();
    render(
      <MemoryRouter initialEntries={["/reset-password?token=link"]}>
        <ResetPassword onSignedIn={onSignedIn} />
      </MemoryRouter>,
    );
    const password = await screen.findByLabelText(/password/i, { selector: "input" });
    fireEvent.change(password, { target: { value: "a much longer new password" } });
    fireEvent.submit(password.closest("form")!);

    const field = await screen.findByLabelText("6-digit code");
    expect(onSignedIn).not.toHaveBeenCalled();
    fireEvent.change(field, { target: { value: "123456" } });
    fireEvent.click(screen.getByRole("button", { name: "Sign in" }));
    await waitFor(() => expect(onSignedIn).toHaveBeenCalledWith(ME, undefined));
    expect(called("POST", "/api/auth/login/two-step")?.body).toEqual({ pending: "tok", code: "123456" });
  });
});

const QR = '<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10"><rect width="10" height="10"/></svg>';
const CODES = Array.from({ length: 10 }, (_, i) => `aaaa${i}-bbbb${i}`);

async function enterPassword(value = "correct horse") {
  fireEvent.change(await screen.findByLabelText("Password"), { target: { value } });
  fireEvent.click(screen.getByRole("button", { name: "Continue" }));
}

function twoStepRoutes() {
  return (url: string, method: string): Promise<Response> | undefined => {
    if (url === "/api/auth/two-step/start" && method === "POST") {
      return reply(200, { secret: "ABCDEFGHJKLMNPQR", otpauth_uri: "otpauth://totp/x", qr_svg: QR });
    }
    if (url === "/api/auth/two-step/confirm") return reply(200, { recovery_codes: CODES });
    return undefined;
  };
}

describe("When two-step sign-in is required and not on yet", () => {
  it("shows only the set-up, never the desk", async () => {
    const must = { ...ME, actor: { ...ME.actor, two_step: { enabled: false, required: true, must_set_up: true } } };
    const base = twoStepRoutes();
    routes = (url, method) => {
      if (url === "/api/auth/me") return reply(200, must);
      return base(url, method);
    };
    render(<App />);

    expect(await screen.findByRole("heading", { name: "Set up two-step sign-in" })).toBeTruthy();
    await enterPassword();
    expect(screen.queryByRole("navigation", { name: "Sections" })).toBeNull();
    expect(screen.getByRole("button", { name: "Sign out" })).toBeTruthy();
    // The server's QR is an image, not inserted markup.
    const image = await screen.findByAltText("QR code for your authenticator app") as HTMLImageElement;
    expect(image.src.startsWith("data:image/svg+xml")).toBe(true);
    expect(screen.getByLabelText("Setup key").textContent).toBe("ABCD EFGH JKLM NPQR");
  });
});

// ── Settings → My preferences ───────────────────────────────────────────────

const STATUS_ON = { enabled: true, required: false, must_set_up: false, enabled_at: "2026-10-20T10:00:00Z", recovery_codes_left: 8 };
const NOW = new Date().toISOString();
const SESSIONS = {
  sessions: [
    { id: 5, device: "Chrome on Windows", ip_address: "41.2.3.4", created_at: NOW, last_seen_at: NOW, current: true },
    { id: 9, device: "Safari on iPhone", ip_address: "41.9.9.9", created_at: "2026-10-01T10:00:00Z", last_seen_at: "2026-10-20T21:14:00Z", current: false },
  ],
};

function renderSettings(section: string) {
  return render(
    <MemoryRouter initialEntries={[`/settings?section=${section}`]}><Settings session={ME} /></MemoryRouter>,
  );
}

describe("Settings → My preferences", () => {
  beforeEach(() => {
    routes = (url, method) => {
      if (url === "/api/staff/me/preferences") return reply(200, { preferences: {}, labels: {}, descriptions: {}, theme: null });
      if (url === "/api/auth/two-step" && method === "GET") return reply(200, STATUS_ON);
      if (url === "/api/auth/sessions") return reply(200, SESSIONS);
      if (url === "/api/auth/sessions/9/end") return reply(200, { ended: true });
      if (url === "/api/auth/sessions/end-others") return reply(200, { ended: 1 });
      return twoStepRoutes()(url, method);
    };
  });

  it("lists the devices and signs one out", async () => {
    renderSettings("appearance");
    const list = await screen.findByRole("list", { name: "Devices" });
    const items = within(list).getAllByRole("listitem");
    expect(items[0].textContent).toContain("This device");
    expect(within(items[0]).queryByRole("button")).toBeNull();
    fireEvent.click(within(items[1]).getByRole("button", { name: "Sign out Safari on iPhone" }));
    await waitFor(() => expect(called("POST", "/api/auth/sessions/9/end")).toBeTruthy());
  });

  it("signs out of every other device", async () => {
    renderSettings("appearance");
    fireEvent.click(await screen.findByRole("button", { name: "Sign out of every other device" }));
    await waitFor(() => expect(called("POST", "/api/auth/sessions/end-others")).toBeTruthy());
  });

  it("says it is on, and offers new recovery codes with a code", async () => {
    const codes = Array.from({ length: 10 }, (_, i) => `zzzz${i}-yyyy${i}`);
    const base = routes;
    routes = (url, method, body) =>
      url === "/api/auth/two-step/recovery-codes" ? reply(200, { recovery_codes: codes }) : base(url, method, body);
    renderSettings("appearance");

    const panel = (await screen.findByRole("heading", { name: "Two-step sign-in" })).closest("section")!;
    await within(panel).findByText("On");
    fireEvent.click(within(panel).getByRole("button", { name: "New recovery codes" }));
    fireEvent.change(within(panel).getByLabelText("6-digit code"), { target: { value: "123456" } });
    fireEvent.click(within(panel).getByRole("button", { name: "Make new recovery codes" }));
    expect(await within(panel).findByText("zzzz0-yyyy0")).toBeTruthy();
    expect(called("POST", "/api/auth/two-step/recovery-codes")?.body).toEqual({ code: "123456" });

    fireEvent.click(within(panel).getByRole("button", { name: "I've saved these" }));
    await waitFor(() => expect(within(panel).queryByText("zzzz0-yyyy0")).toBeNull());
  });

  it("turns it off with a code", async () => {
    const base = routes;
    routes = (url, method, body) =>
      url === "/api/auth/two-step/turn-off" ? reply(200, { enabled: false }) : base(url, method, body);
    renderSettings("appearance");
    fireEvent.click(await screen.findByRole("button", { name: "Turn off" }));
    fireEvent.change(screen.getByLabelText("6-digit code"), { target: { value: "654321" } });
    fireEvent.click(screen.getByRole("button", { name: "Turn off two-step sign-in" }));
    await waitFor(() => expect(called("POST", "/api/auth/two-step/turn-off")?.body).toEqual({ code: "654321" }));
  });

  it("says it is required, and does not offer to turn it off", async () => {
    const base = routes;
    routes = (url, method, body) =>
      url === "/api/auth/two-step" && method === "GET" ? reply(200, { ...STATUS_ON, required: true }) : base(url, method, body);
    renderSettings("appearance");
    expect(await screen.findByText(/Required for your access/)).toBeTruthy();
    expect(screen.getByRole("button", { name: "New recovery codes" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Turn off" })).toBeNull();
  });

  it("shows the server's message when the password is wrong, and sends none of it again", async () => {
    const base = routes;
    routes = (url, method, body) => {
      if (url === "/api/auth/two-step" && method === "GET")
        return reply(200, { enabled: false, required: false, must_set_up: false, enabled_at: null, recovery_codes_left: 0 });
      if (url === "/api/auth/two-step/start") return reply(400, { detail: "That password is not right." });
      return base(url, method, body);
    };
    renderSettings("appearance");
    fireEvent.click(await screen.findByRole("button", { name: "Set up two-step sign-in" }));
    await enterPassword("nope");
    expect((await screen.findByRole("alert")).textContent).toBe("That password is not right.");
    expect(called("POST", "/api/auth/two-step/start")?.body).toEqual({ password: "nope" });
    expect((screen.getByLabelText("Password") as HTMLInputElement).value).toBe("");
    expect(screen.queryByAltText("QR code for your authenticator app")).toBeNull();
  });

  it("sets it up: key, code, recovery codes shown once, then gone", async () => {
    const base = routes;
    routes = (url, method, body) =>
      url === "/api/auth/two-step" && method === "GET"
        ? reply(200, { enabled: false, required: false, must_set_up: false, enabled_at: null, recovery_codes_left: 0 })
        : base(url, method, body);
    renderSettings("appearance");

    fireEvent.click(await screen.findByRole("button", { name: "Set up two-step sign-in" }));
    await enterPassword();
    expect(await screen.findByAltText("QR code for your authenticator app")).toBeTruthy();
    fireEvent.change(screen.getByLabelText("6-digit code"), { target: { value: "123456" } });
    fireEvent.click(screen.getByRole("button", { name: "Turn on" }));

    expect(await screen.findByText("aaaa0-bbbb0")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Copy all codes" })).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "I've saved these" }));
    await waitFor(() => expect(screen.queryByText("aaaa0-bbbb0")).toBeNull());
    expect(called("POST", "/api/auth/two-step/confirm")?.body).toEqual({ code: "123456" });
  });
});

// ── Settings → Team ─────────────────────────────────────────────────────────

const ROSTER = {
  staff: [
    { id: 1, email: "owner@hbawear.store", display_name: "Yahya", roles: ["admin"], status: "active", two_step_enabled: true, last_login_at: null, created_at: null },
    { id: 2, email: "mona@hbawear.store", display_name: "Mona", roles: ["content_manager"], status: "active", two_step_enabled: true, last_login_at: null, created_at: null },
    { id: 3, email: "aya@hbawear.store", display_name: "Aya", roles: ["customer_service"], status: "active", two_step_enabled: false, last_login_at: null, created_at: null },
  ],
  invitations: [],
  assignable_roles: ["admin", "content_manager", "customer_service"],
  invitable_roles: ["admin", "content_manager", "customer_service"],
  role_permissions: { admin: ADMIN_PERMISSIONS, content_manager: ["affiliates.view"], customer_service: ["inbox.use"] },
};

describe("Settings → Team", () => {
  beforeEach(() => {
    routes = (url, method) => {
      if (url === "/api/staff") return reply(200, ROSTER);
      if (url === "/api/staff/invitations") return reply(200, { invitations: [], invitable_roles: [], role_permissions: {} });
      if (url === "/api/staff/2/sessions") return reply(200, SESSIONS);
      if (url === "/api/staff/2/sessions/end-all") return reply(200, { ended: 2 });
      if (url === "/api/staff/2/two-step/reset" && method === "POST") return reply(200, { enabled: false });
      if (url === "/api/staff/2/suspend") return reply(200, { id: 2, status: "suspended", roles: [], sessions_ended: 2 });
      if (url === "/api/staff/2/reactivate") return reply(200, { id: 2, status: "active", roles: [] });
    };
  });

  it("marks only the people who have two-step sign-in on", async () => {
    renderSettings("team");
    const mona = (await screen.findByText("Mona")).closest("tr")!;
    expect(within(mona).getByLabelText("Two-step sign-in on")).toBeTruthy();
    expect(within(screen.getByText("Aya").closest("tr")!).queryByLabelText("Two-step sign-in on")).toBeNull();
  });

  it("lists somebody's devices and signs them out of every one", async () => {
    renderSettings("team");
    fireEvent.click(await screen.findByRole("button", { name: "More for Mona" }));
    fireEvent.click(screen.getByRole("button", { name: /Signed in on/ }));
    const dialog = await screen.findByRole("dialog");
    expect(await within(dialog).findByText("Safari on iPhone")).toBeTruthy();
    fireEvent.click(within(dialog).getByRole("button", { name: "Sign out of every device" }));
    await waitFor(() => expect(called("POST", "/api/staff/2/sessions/end-all")).toBeTruthy());
    expect(await within(dialog).findByText("Not signed in anywhere.")).toBeTruthy();
  });

  it("resets somebody's two-step sign-in with the owner's own code", async () => {
    renderSettings("team");
    fireEvent.click(await screen.findByRole("button", { name: "More for Mona" }));
    fireEvent.click(screen.getByRole("button", { name: /Reset two-step sign-in/ }));
    const dialog = await screen.findByRole("dialog");
    expect(dialog.textContent).toContain("set it up again");
    fireEvent.change(within(dialog).getByLabelText("Your own 6-digit code"), { target: { value: "111222" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Reset two-step sign-in" }));
    await waitFor(() => expect(called("POST", "/api/staff/2/two-step/reset")?.body).toEqual({ code: "111222" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  });

  it("shows the owner's refusal when their code is wrong", async () => {
    const base = routes;
    routes = (url, method, body) =>
      url === "/api/staff/2/two-step/reset" ? reply(400, { detail: "That code did not work." }) : base(url, method, body);
    renderSettings("team");
    fireEvent.click(await screen.findByRole("button", { name: "More for Mona" }));
    fireEvent.click(screen.getByRole("button", { name: /Reset two-step sign-in/ }));
    const dialog = await screen.findByRole("dialog");
    fireEvent.change(within(dialog).getByLabelText("Your own 6-digit code"), { target: { value: "000000" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Reset two-step sign-in" }));
    expect((await within(dialog).findByRole("alert")).textContent).toBe("That code did not work.");
  });

  it("does not offer a reset to somebody who has no two-step sign-in", async () => {
    renderSettings("team");
    fireEvent.click(await screen.findByRole("button", { name: "More for Aya" }));
    expect(screen.queryByRole("button", { name: /Reset two-step sign-in/ })).toBeNull();
  });

  it("says what suspending does, in the mockup's words", async () => {
    renderSettings("team");
    fireEvent.click(await screen.findByRole("button", { name: "More for Mona" }));
    fireEvent.click(screen.getByRole("button", { name: /Suspend/ }));
    const dialog = await screen.findByRole("dialog");
    expect(dialog.textContent).toContain("Removes every department and signs out every device at once.");
    expect(dialog.textContent).toContain("The record of what Mona did stays.");
  });

  it("says reactivating gives no access back", async () => {
    const suspended = { ...ROSTER, staff: ROSTER.staff.map((row) => row.id === 2 ? { ...row, status: "suspended", roles: [] } : row) };
    routes = (url) => {
      if (url === "/api/staff") return reply(200, suspended);
      if (url === "/api/staff/invitations") return reply(200, { invitations: [], invitable_roles: [], role_permissions: {} });
    };
    renderSettings("team");
    fireEvent.click(await screen.findByRole("button", { name: "More for Mona" }));
    fireEvent.click(screen.getByRole("button", { name: /Reactivate/ }));
    const dialog = await screen.findByRole("dialog");
    expect(dialog.textContent).toContain("gives no access");
    expect(dialog.textContent).toContain("Add it again with Add access.");
  });
});
