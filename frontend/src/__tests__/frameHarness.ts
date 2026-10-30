/**
 * What the frame's tests share: a signed-in person of each kind, and a
 * `fetch` that answers as the server would. Not a test file itself.
 */
import { vi } from "vitest";

import type { TodayDepartment, TodayItem, TodayOrders } from "../departments/today/types";
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
  /** Unread chats, or null for a number the server could not read. */
  unread?: number | null;
  /** The two Affiliates numbers, or null when they could not be read. */
  counts?: Record<string, number> | null;
  /** Operations sources, by how their latest read went; null for none read. */
  freshness?: Record<string, { state: string; updated_at?: string | null }> | null;
  /** The things waiting, in the order the server gives them. */
  items?: TodayItem[];
  /** The week's orders, or null (the default) for somebody who does not hold both. */
  orders?: TodayOrders | null;
  /** Departments the server could not read. */
  unreadDepartments?: TodayDepartment[];
  /** `GET /api/today` itself failing, whole. */
  today?: "failed";
};

let requested: string[] = [];

/** Every address asked of the server since the last `serve`. */
export const asked = () => requested;

/** `GET /api/today` for this person: the numbers and failures the sidebar reads, and whatever else the test gave. */
function todayBody(me: Session, answers: Answers) {
  const { unread = 4, counts = { models_awaiting_approval: 0, payments_awaiting_approval: 0 } } = answers;
  const holds = (permission: string) => me.permissions.includes(permission);
  const departments: TodayDepartment[] = [
    ...(holds("inbox.use") ? (["inbox"] as const) : []),
    ...(holds("order_ops.view") ? (["operations"] as const) : []),
    ...(holds("affiliates.view") ? (["affiliates"] as const) : []),
  ];
  const read: Record<string, number> = {};
  if (holds("inbox.use") && unread !== null) read.chats_unread = unread;
  if (holds("affiliates.view") && counts !== null) Object.assign(read, counts);
  const failures = Object.fromEntries(
    Object.entries(answers.freshness ?? {})
      .filter(([, source]) => source.state === "failed")
      .map(([name, source]) => [name, source.updated_at ?? null]),
  );
  return {
    now: "2026-10-30T10:00:00Z",
    departments,
    items: answers.items ?? [],
    counts: read,
    failures: holds("order_ops.view") ? failures : {},
    orders: answers.orders ?? null,
    ...(answers.unreadDepartments ? { unread: answers.unreadDepartments } : {}),
  };
}

export function serve(me: unknown, answers: Answers = {}) {
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
      if (url.endsWith("/api/today")) {
        return answers.today === "failed" ? reply(500, { detail: "No" }) : reply(200, todayBody(me as Session, answers));
      }
      if (url.includes("/api/inbox/conversations")) {
        return reply(200, { conversations: [], next: null, counts: { all: 0, unread: answers.unread ?? 4, edit: 0 } });
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
      return reply(404, { detail: "Not here" });
    }),
  );
}
