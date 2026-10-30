/**
 * What the frame's tests share: a signed-in person of each kind, and a
 * `fetch` that answers as the server would. Not a test file itself.
 */
import { vi } from "vitest";

import type { Session } from "../lib/api";

const PLATFORM = { working_month: "2026-10", go_live_month: "2026-10", start_month: "2026-01" };

/** What each kind of person holds, as `app/core/permissions.py` gives it. */
export const HELD = {
  owner: {
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
  // A person holding two roles since ADR 0067.
  operations_manager: {
    roles: ["operations_manager", "customer_service"],
    permissions: ["order_ops.view", "inbox.use"],
  },
  operations_only: { roles: ["operations_manager"], permissions: ["order_ops.view"] },
  customer_service: { roles: ["customer_service"], permissions: ["inbox.use"] },
  model: { roles: ["affiliate"], permissions: [] as string[] },
} as const;

export type Kind = keyof typeof HELD;

export function sessionOf(kind: Kind, name = "Nour"): Session {
  const held = HELD[kind];
  return {
    actor: {
      id: 7,
      email: "someone@example.com",
      display_name: name,
      roles: [...held.roles],
      is_staff: kind !== "model",
      is_model: kind === "model",
    },
    permissions: [...held.permissions],
    platform: PLATFORM,
  } as Session;
}

export function reply(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

export type Answers = {
  /** Unread chats, or null for a refused read. */
  unread?: number | null;
  /** `/api/operations/counts`, or null for a refused read. */
  counts?: Record<string, number> | null;
  /** `/api/operations/freshness` sources, or null for a refused read. */
  freshness?: Record<string, { state: string; updated_at?: string | null }> | null;
};

let requested: string[] = [];

/** Every address asked of the server since the last `serve`. */
export const asked = () => requested;

export function serve(me: unknown, answers: Answers = {}) {
  requested = [];
  const { unread = 4, counts = { models_awaiting_approval: 0, payments_awaiting_approval: 0 } } = answers;
  const freshness = answers.freshness === undefined ? {} : answers.freshness;
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
      requested.push(url);
      if (url.endsWith("/api/auth/me")) return reply(200, me);
      if (url.endsWith("/api/staff/me/preferences")) {
        return reply(200, { preferences: {}, labels: {}, descriptions: {}, theme: null });
      }
      if (url.includes("/api/inbox/conversations")) {
        if (unread === null) return reply(403, { detail: "No" });
        return reply(200, { conversations: [], next: null, counts: { all: 0, unread, edit: 0 } });
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
      if (url.endsWith("/api/operations/counts")) {
        return counts === null ? reply(403, { detail: "No" }) : reply(200, counts);
      }
      if (url.endsWith("/api/operations/freshness")) {
        if (freshness === null) return reply(403, { detail: "No" });
        const labels: Record<string, string> = { shopify: "Shopify", bosta: "Bosta", estebdal: "E-stebdal" };
        return reply(200, {
          sources: Object.keys(labels).map((source) => ({
            source,
            label: labels[source],
            state: freshness[source]?.state ?? "fresh",
            updated_at: freshness[source] && "updated_at" in freshness[source] ? freshness[source].updated_at : "2026-10-30T10:00:00+00:00",
            failed_at: freshness[source]?.state === "failed" ? "2026-10-30T10:20:00+00:00" : null,
          })),
        });
      }
      return reply(404, { detail: "Not here" });
    }),
  );
}
