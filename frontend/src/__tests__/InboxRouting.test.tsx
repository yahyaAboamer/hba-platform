// @vitest-environment jsdom
/**
 * Who reaches the Inbox, and what else they can reach (ADR 0059; the
 * approved mockup's frame 5, "Who switches between what").
 *
 * Customer service signs in to the Inbox and nothing else. The operations
 * manager gains it beside Operations; the admin holds all three dashboards.
 */
import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import App from "../App";

const PLATFORM = { working_month: "2026-10", go_live_month: "2026-10", start_month: "2026-01" };
const ADMIN_PERMISSIONS = [
  "affiliates.view", "affiliates.manage", "affiliates.erase", "compensation.manage",
  "targets.record", "targets.manage", "targets.verify", "payroll.approve",
  "payroll.reopen", "payments.record", "invitations.send", "audit.view",
  "settings.manage", "order_ops.view", "inbox.use",
];

function session(role: string, permissions: string[]) {
  return {
    // ADR 0067: the roles are for naming the person; where they land is
    // decided by `permissions` alone.
    actor: {
      id: 7, email: "someone@example.com", display_name: "Mariam",
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
      if (url.includes("/api/inbox/conversations")) {
        return reply(200, { conversations: [], next: null, counts: { all: 0, unread: 4, edit: 0 } });
      }
      if (url.includes("/api/inbox/health")) {
        return reply(200, { connected: true, sending: true, last_heard_at: null, quiet_since: null });
      }
      if (url.includes("/api/inbox/confirmations")) {
        return reply(200, {
          days: 7,
          total: 0,
          tiles: { waiting: 0, edit: 0, cancelled: 0, not_sent: 0, no_whatsapp: 0, confirmed: 0 },
          orders: null,
        });
      }
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

describe("customer service", () => {
  it("lands on the Inbox, on Chats, with its two sections", async () => {
    serve(session("customer_service", ["inbox.use"]));
    render(<App />);

    expect(await screen.findByRole("heading", { name: "Chats" })).toBeTruthy();
    expect(window.location.pathname).toBe("/inbox/chats");
    const sidebar = screen.getByRole("navigation", { name: "Inbox" });
    expect(within(sidebar).getByRole("link", { name: /^Chats/ })).toBeTruthy();
    expect(within(sidebar).getByRole("link", { name: "Confirmations" })).toBeTruthy();
  });

  it("holds one dashboard, so is shown no switch and nothing of the others", async () => {
    serve(session("customer_service", ["inbox.use"]));
    render(<App />);
    await screen.findByRole("heading", { name: "Chats" });

    expect(screen.queryByRole("group", { name: "Dashboard" })).toBeNull();
    for (const name of ["Affiliates", "Operations", "Shopify", "Models", "Payments", "Settings"]) {
      expect(screen.queryByRole("link", { name })).toBeNull();
    }
    const strayed = requested.filter(
      (url) =>
        url.includes("/api/affiliates") || url.includes("/api/operations/") || url.includes("/api/order-ops"),
    );
    expect(strayed).toEqual([]);
  });

  it("is taken to Chats from any other address", async () => {
    window.history.pushState({}, "", "/payments");
    serve(session("customer_service", ["inbox.use"]));
    render(<App />);

    expect(await screen.findByRole("heading", { name: "Chats" })).toBeTruthy();
    expect(window.location.pathname).toBe("/inbox/chats");
  });

  it("sees how many chats are unread beside Chats", async () => {
    serve(session("customer_service", ["inbox.use"]));
    render(<App />);

    const chats = await screen.findByRole("link", { name: /^Chats/ });
    await within(chats).findByText("4");
  });

  it("reaches Confirmations", async () => {
    window.history.pushState({}, "", "/inbox/confirmations");
    serve(session("customer_service", ["inbox.use"]));
    render(<App />);

    expect(await screen.findByRole("heading", { name: "Confirmations" })).toBeTruthy();
  });
});

describe("the operations manager", () => {
  it("switches between Operations and the Inbox, and no further", async () => {
    window.history.pushState({}, "", "/operations/whatsapp");
    serve(session("operations_manager+customer_service", ["order_ops.view", "inbox.use"]));
    render(<App />);

    const switcher = await screen.findByRole("group", { name: "Dashboard" });
    expect(within(switcher).getByRole("link", { name: "Operations" }).getAttribute("aria-current")).toBe("page");
    expect(within(switcher).getByRole("link", { name: "Inbox" }).getAttribute("href")).toBe("/inbox");
    expect(within(switcher).queryByRole("link", { name: "Affiliates" })).toBeNull();
  });

  it("has WhatsApp as Operations' fourth tab", async () => {
    window.history.pushState({}, "", "/operations/whatsapp");
    serve(session("operations_manager+customer_service", ["order_ops.view", "inbox.use"]));
    render(<App />);

    expect(await screen.findByRole("heading", { name: "WhatsApp" })).toBeTruthy();
    const sidebar = screen.getByRole("navigation", { name: "Operations" });
    expect(within(sidebar).getAllByRole("link").map((link) => link.textContent)).toEqual(
      expect.arrayContaining(["Shopify", "Bosta", "E-stebdal", "WhatsApp"]),
    );
  });

  it("reaches the Inbox, and can switch back", async () => {
    window.history.pushState({}, "", "/inbox/confirmations");
    serve(session("operations_manager+customer_service", ["order_ops.view", "inbox.use"]));
    render(<App />);

    expect(await screen.findByRole("heading", { name: "Confirmations" })).toBeTruthy();
    expect(screen.getByRole("link", { name: "Operations" }).getAttribute("href")).toBe("/operations");
  });
});

describe("the admin", () => {
  it("holds all three dashboards", async () => {
    window.history.pushState({}, "", "/inbox/confirmations");
    serve(session("admin", ADMIN_PERMISSIONS));
    render(<App />);

    const switcher = await screen.findByRole("group", { name: "Dashboard" });
    expect(within(switcher).getAllByRole("link").map((link) => link.textContent)).toEqual([
      "Affiliates",
      "Operations",
      "Inbox",
    ]);
    expect(within(switcher).getByRole("link", { name: "Inbox" }).getAttribute("aria-current")).toBe("page");
  });

  it("is offered the Inbox from the affiliate dashboard", async () => {
    serve(session("admin", ADMIN_PERMISSIONS));
    render(<App />);

    const toInbox = await screen.findByRole("link", { name: "Inbox" });
    expect(toInbox.getAttribute("href")).toBe("/inbox");
  });
});

describe("the other managers", () => {
  it("have no way into the Inbox", async () => {
    window.history.pushState({}, "", "/inbox/chats");
    serve(session("affiliate_manager", ["affiliates.view", "affiliates.manage", "invitations.send"]));
    render(<App />);
    await screen.findByRole("navigation", { name: "Sections" });

    expect(screen.queryByRole("link", { name: "Inbox" })).toBeNull();
    expect(screen.queryByRole("heading", { name: "Chats" })).toBeNull();
    expect(requested.filter((url) => url.includes("/api/inbox"))).toEqual([]);
  });
});
