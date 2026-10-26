// @vitest-environment jsdom
/**
 * Where a person lands is decided by what they may do, never by a role's name
 * (ADR 0067, decision 9).
 *
 * Every role that existed before several roles per person must land exactly
 * where it did then; a person holding two roles gets the screens of both; and
 * a role's name, whatever it says, changes nothing.
 */
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import App from "../App";
import { deskFor, roleLabel } from "../lib/api";
import type { Session } from "../lib/api";

const PLATFORM = { working_month: "2026-10", go_live_month: "2026-10", start_month: "2026-01" };

/** What each role's holder may do, as `/api/auth/me` reports it. The
 *  operations manager is a person holding two roles since ADR 0067. */
const HELD: Record<string, { roles: string[]; permissions: string[] }> = {
  admin: {
    roles: ["admin"],
    permissions: [
      "affiliates.view", "affiliates.manage", "affiliates.erase", "compensation.manage",
      "targets.record", "targets.manage", "targets.verify", "payroll.approve",
      "payroll.reopen", "payments.record", "invitations.send", "audit.view",
      "settings.manage", "order_ops.view", "inbox.use",
    ],
  },
  affiliate_manager: {
    roles: ["affiliate_manager"],
    permissions: [
      "affiliates.view", "affiliates.manage", "compensation.manage", "targets.manage",
      "targets.verify", "targets.record", "payroll.approve", "invitations.send", "audit.view",
    ],
  },
  content_manager: {
    roles: ["content_manager"],
    permissions: [
      "affiliates.view", "affiliates.manage", "compensation.manage", "targets.record",
      "targets.manage", "targets.verify", "audit.view",
    ],
  },
  operations_manager: {
    roles: ["operations_manager", "customer_service"],
    permissions: ["order_ops.view", "inbox.use"],
  },
  customer_service: { roles: ["customer_service"], permissions: ["inbox.use"] },
  affiliate: { roles: ["affiliate"], permissions: [] },
};

function session(roles: string[], permissions: string[], isModel = false): Session {
  return {
    actor: {
      id: 7, email: "someone@example.com", display_name: "Nour",
      roles, is_staff: roles.some((role) => role !== "affiliate"), is_model: isModel,
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

describe("deskFor", () => {
  it("sends every role that existed where its name used to", () => {
    // The routing before ADR 0067, by name: affiliate → portal,
    // operations_manager → Operations, customer_service → Inbox, else the
    // affiliate dashboard.
    const before: Record<string, string> = {
      admin: "affiliates",
      affiliate_manager: "affiliates",
      content_manager: "affiliates",
      operations_manager: "operations",
      customer_service: "inbox",
      affiliate: "portal",
    };
    for (const [role, held] of Object.entries(HELD)) {
      expect(deskFor(session(held.roles, held.permissions)), role).toBe(before[role]);
    }
  });

  it("never reads a role's name", () => {
    // Names that would once have chosen another tree change nothing.
    expect(deskFor(session(["operations_manager"], HELD.content_manager.permissions))).toBe("affiliates");
    expect(deskFor(session(["admin"], []))).toBe("portal");
    expect(deskFor(session(["affiliate"], ["inbox.use"]))).toBe("inbox");
  });

  it("gives a model, and somebody invited to become one, the portal", () => {
    expect(deskFor(session(["affiliate"], [], true))).toBe("portal");
    expect(deskFor(session([], [], false))).toBe("portal");
  });

  it("names a person by the widest role they hold", () => {
    expect(roleLabel(session(HELD.operations_manager.roles, []).actor)).toBe("operations manager");
    expect(roleLabel(session([], []).actor)).toBe("");
  });
});

describe("a person holding two roles", () => {
  it("lands on the affiliate dashboard and is offered the Inbox beside it", async () => {
    const both = [...HELD.content_manager.permissions, "inbox.use"];
    serve(session(["content_manager", "customer_service"], both));
    render(<App />);

    await screen.findByRole("navigation", { name: "Sections" });
    expect(screen.getByRole("link", { name: "Inbox" }).getAttribute("href")).toBe("/inbox");
    expect(screen.queryByRole("link", { name: "Operations" })).toBeNull();
  });

  it("reaches the Inbox at its own address", async () => {
    window.history.pushState({}, "", "/inbox/confirmations");
    serve(session(["content_manager", "customer_service"], [...HELD.content_manager.permissions, "inbox.use"]));
    render(<App />);

    expect(await screen.findByRole("heading", { name: "Confirmations" })).toBeTruthy();
  });
});

describe("the operations manager, now two roles", () => {
  it("still lands on Operations and asks the affiliate side nothing", async () => {
    window.history.pushState({}, "", "/payments");
    serve(session(HELD.operations_manager.roles, HELD.operations_manager.permissions));
    render(<App />);

    expect(await screen.findByRole("heading", { name: "Shopify" })).toBeTruthy();
    expect(window.location.pathname).toBe("/operations/shopify");
    expect(requested.filter((url) => url.includes("/api/affiliates"))).toEqual([]);
  });
});
