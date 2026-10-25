// @vitest-environment jsdom
/**
 * Where each person lands, and what they can reach (ADR 0057).
 *
 * The operations manager signs in to Operations and nothing else: no
 * affiliate section in his sidebar, and no request to the affiliate side's
 * endpoints - a 403 that is swallowed is still a door left on the latch.
 */
import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import App from "../App";

const PLATFORM = { working_month: "2026-10", go_live_month: "2026-10", start_month: "2026-01" };
const ADMIN_PERMISSIONS = [
  "affiliates.view", "affiliates.manage", "affiliates.erase", "compensation.manage",
  "targets.record", "targets.manage", "targets.verify", "payroll.approve",
  "payroll.reopen", "payments.record", "invitations.send", "audit.view",
  "settings.manage", "order_ops.view",
];

function session(role: string, permissions: string[]) {
  return {
    // ADR 0067: the roles are for naming the person; where they land is
    // decided by `permissions` alone.
    actor: {
      id: 7, email: "someone@example.com", display_name: "Amr",
      roles: role.split("+"), is_staff: role !== "affiliate", is_model: role === "affiliate",
    },
    permissions,
    platform: PLATFORM,
  };
}

function reply(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

let requested: string[] = [];

function serve(me: unknown) {
  requested = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
      requested.push(url);
      if (url.endsWith("/api/auth/me")) return reply(200, me);
      if (url.endsWith("/api/staff/me/preferences")) {
        return reply(200, { preferences: {}, labels: {}, descriptions: {}, theme: null });
      }
      return reply(404, { detail: "Not here" });
    }),
  );
}

beforeEach(() => window.history.pushState({}, "", "/"));
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("the operations manager", () => {
  it("lands on Operations, on Shopify", async () => {
    serve(session("operations_manager", ["order_ops.view"]));
    render(<App />);

    expect(await screen.findByRole("heading", { name: "Shopify" })).toBeTruthy();
    const sidebar = screen.getByRole("navigation", { name: "Operations" });
    for (const name of ["Shopify", "Bosta", "E-stebdal"]) {
      expect(within(sidebar).getByRole("link", { name })).toBeTruthy();
    }
  });

  it("sees nothing of the affiliate side, and asks it nothing", async () => {
    serve(session("operations_manager", ["order_ops.view"]));
    render(<App />);
    await screen.findByRole("heading", { name: "Shopify" });

    for (const name of ["Home", "Models", "Products", "Targets", "Payments", "Settings", "Affiliates"]) {
      expect(screen.queryByRole("link", { name })).toBeNull();
    }
    const strayed = requested.filter(
      (url) => url.includes("/api/affiliates") || url.includes("/api/operations/"),
    );
    expect(strayed).toEqual([]);
  });

  it("is taken to Operations from any other address", async () => {
    window.history.pushState({}, "", "/payments");
    serve(session("operations_manager", ["order_ops.view"]));
    render(<App />);

    expect(await screen.findByRole("heading", { name: "Shopify" })).toBeTruthy();
    expect(window.location.pathname).toBe("/operations/shopify");
  });
});

describe("the admin", () => {
  it("can switch from the affiliate dashboard to Operations", async () => {
    serve(session("admin", ADMIN_PERMISSIONS));
    render(<App />);

    const toOperations = await screen.findByRole("link", { name: "Operations" });
    expect(toOperations.getAttribute("href")).toBe("/operations");
  });

  it("reaches Operations, and can switch back", async () => {
    window.history.pushState({}, "", "/operations/bosta");
    serve(session("admin", ADMIN_PERMISSIONS));
    render(<App />);

    expect(await screen.findByRole("heading", { name: "Bosta" })).toBeTruthy();
    expect(screen.getByRole("link", { name: "Affiliates" }).getAttribute("href")).toBe("/");
  });
});

describe("the other managers", () => {
  it("have no way into Operations", async () => {
    serve(session("affiliate_manager", ["affiliates.view", "affiliates.manage", "invitations.send"]));
    render(<App />);
    await screen.findByRole("navigation", { name: "Sections" });

    expect(screen.queryByRole("link", { name: "Operations" })).toBeNull();
  });
});
