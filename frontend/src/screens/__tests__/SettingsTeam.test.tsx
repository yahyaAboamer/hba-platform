// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { Settings, historicalState } from "../Settings";
import type { Session } from "../../lib/api";

const reply = (status: number, body: unknown) =>
  Promise.resolve({
    ok: status < 400, status,
    headers: { get: () => "application/json" },
    json: () => Promise.resolve(body),
    text: () => Promise.resolve(JSON.stringify(body)),
  } as unknown as Response);

const PERMISSIONS = {
  admin: ["affiliates.erase", "affiliates.manage", "affiliates.view", "audit.view", "compensation.manage", "invitations.send", "payments.record", "payroll.approve", "payroll.reopen", "settings.manage", "targets.manage", "targets.record", "targets.verify"],
  affiliate_manager: ["affiliates.manage", "affiliates.view", "audit.view", "compensation.manage", "invitations.send", "payroll.approve", "targets.manage", "targets.record", "targets.verify"],
  content_manager: ["affiliates.manage", "affiliates.view", "audit.view", "compensation.manage", "targets.manage", "targets.record", "targets.verify"],
};

const ROSTER = {
  staff: [
    { id: 1, email: "owner@hbawear.store", display_name: "Yahya", role: "admin", status: "active", last_login_at: null, created_at: null },
    { id: 2, email: "mona@hbawear.store", display_name: "Mona", role: "content_manager", status: "active", last_login_at: null, created_at: null },
  ],
  invitations: [],
  assignable_roles: ["admin", "affiliate_manager", "content_manager"],
  invitable_roles: ["admin", "affiliate_manager", "content_manager"],
  role_permissions: PERMISSIONS,
};

function session(role: keyof typeof PERMISSIONS): Session {
  return {
    actor: { id: 1, email: "owner@hbawear.store", display_name: "Yahya", role },
    permissions: PERMISSIONS[role],
    platform: { go_live_month: "2026-10" },
  } as unknown as Session;
}

let fetchMock: ReturnType<typeof vi.fn>;
beforeEach(() => {
  fetchMock = vi.fn((url: string, init?: RequestInit) => {
    if (url.includes("/api/auth/invitations") && init?.method === "POST") {
      return reply(201, { token: "t0k3n", link: "https://hba.test/accept-invitation?token=t0k3n", emailed: false, invitation: {} });
    }
    if (url.includes("/api/staff/invitations")) return reply(200, { invitations: [], invitable_roles: ["affiliate_manager", "content_manager"], role_permissions: PERMISSIONS });
    if (url.includes("/api/staff")) return reply(200, ROSTER);
    if (url.includes("/api/payroll/historical/review")) return reply(200, { totals: { ready: 0, blocked: 0 } });
    return reply(200, {});
  });
  vi.stubGlobal("fetch", fetchMock);
});
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

const renderAt = (role: keyof typeof PERMISSIONS, section = "") =>
  render(<MemoryRouter initialEntries={[`/settings${section ? `?section=${section}` : ""}`]}><Settings session={session(role)} /></MemoryRouter>);

describe("Settings → Team", () => {
  it("shows the link once, after an invitation is sent", async () => {
    renderAt("admin", "team");
    fireEvent.change(await screen.findByLabelText("Email"), { target: { value: "new@hbawear.store" } });
    fireEvent.click(screen.getByRole("button", { name: "Send invitation" }));
    expect((await screen.findByRole("status")).textContent).toContain("https://hba.test/accept-invitation?token=t0k3n");
    expect(screen.getByRole("button", { name: "Copy link" })).toBeTruthy();
  });

  it("never offers you your own access or a way to suspend yourself", async () => {
    renderAt("admin", "team");
    const own = (await screen.findByText("You")).closest("tr")!;
    expect(within(own).queryByRole("combobox")).toBeNull();
    expect(within(own).queryByRole("button", { name: /More for/ })).toBeNull();
    expect(screen.getByRole("button", { name: "More for Mona" })).toBeTruthy();
  });

  it("asks before changing somebody's access, and says what they gain", async () => {
    renderAt("admin", "team");
    fireEvent.change(await screen.findByLabelText("Access for Mona"), { target: { value: "admin" } });
    const dialog = await screen.findByRole("dialog");
    expect(dialog.textContent).toContain("Make Mona an admin?");
    expect(dialog.textContent).toContain("record payments and reopen approved months");
    expect(fetchMock.mock.calls.some(([url]) => String(url).includes("/role"))).toBe(false);
  });

  it("offers an affiliate manager only the access they hold", async () => {
    renderAt("affiliate_manager");
    const select = await screen.findByLabelText("Access");
    const offered = within(select).getAllByRole("option").map((option) => option.textContent);
    expect(offered).toEqual(["Content manager", "Affiliate manager"]);
  });
});

describe("Settings → the rail", () => {
  it("names the operations manager, and says what that access can do", async () => {
    const permissions = { ...PERMISSIONS, operations_manager: ["order_ops.view"] };
    const roster = {
      ...ROSTER,
      staff: [...ROSTER.staff, { id: 3, email: "amr@hbawear.store", display_name: "Amr", role: "operations_manager", status: "active", last_login_at: null, created_at: null }],
      assignable_roles: [...ROSTER.assignable_roles, "operations_manager"],
      invitable_roles: [...ROSTER.invitable_roles, "operations_manager"],
      role_permissions: permissions,
    };
    fetchMock.mockImplementation((url: string) => {
      if (url.includes("/api/staff/invitations")) return reply(200, { invitations: [], invitable_roles: roster.invitable_roles, role_permissions: permissions });
      if (url.includes("/api/staff")) return reply(200, roster);
      return reply(200, {});
    });
    renderAt("admin", "team");

    expect((await screen.findAllByText("Operations manager")).length).toBeGreaterThan(0);
    expect(screen.queryByText("operations_manager")).toBeNull();
    expect(screen.getByText("See the operations dashboard")).toBeTruthy();
    expect(screen.getByRole("columnheader", { name: "Operations manager" })).toBeTruthy();
  });

  it("lists only what a content manager can use, and opens on the first", async () => {
    renderAt("content_manager");
    const rail = screen.getByRole("navigation", { name: "Settings sections" });
    const labels = within(rail).getAllByRole("button").map((button) => button.textContent);
    expect(labels).not.toContain("Team");
    expect(labels).not.toContain("Pay policy");
    expect(within(rail).getByRole("button", { name: "Shopify and sync" }).getAttribute("aria-current")).toBe("page");
  });

  it("drops Historical setup once every month before go-live is final", async () => {
    renderAt("admin");
    const rail = screen.getByRole("navigation", { name: "Settings sections" });
    await waitFor(() => expect(within(rail).queryByRole("button", { name: "Historical setup" })).toBeNull());
  });
});

describe("Historical setup's state", () => {
  const row = (setup: object | null) => ({ id: 7, name: "Aya", account_kind: "model", status: "active", historical_setup: setup as never });
  const text = (node: React.ReactNode) => render(<MemoryRouter>{node}</MemoryRouter>).container.textContent;

  it("splits the months at go-live, so the row and the review agree", () => {
    expect(text(historicalState(row({ eligible: 9, ready: 0, blocking: 9, blocking_before_go_live: 5, first_gap: "2026-01", start_is_recorded: true }))))
      .toContain("5 months before go-live · 4 after cannot be calculated");
  });

  it("sends a model with no start to where it is recorded", () => {
    expect(text(historicalState(row({ eligible: 0, ready: 0, blocking: 0, first_gap: null, start_is_recorded: false }))))
      .toContain("Record her start month");
  });
});
