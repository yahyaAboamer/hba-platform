/**
 * What the production tests share: orders shaped as `GET /api/prod/orders/{id}`
 * answers them, a `fetch` that answers as the server would, and a render at an
 * address. Not a test file itself.
 */
import { render } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { vi } from "vitest";

import type { Session } from "../../../../lib/api";
import { sessionOf } from "../../../../__tests__/frameHarness";
import { productionRoutes } from "../routes";
import type {
  Cost,
  Delivery,
  GeneratedTask,
  Incoming,
  IncomingArrival,
  IncomingCounts,
  IncomingDelivery,
  ManualTask,
  OrderRow,
  OrderStage,
  OrderView,
  ProductDetails,
  Settlement,
  SizeLine,
  StageKey,
  StageStatus,
  Task,
  TaskList,
} from "../types";
import { STAGE_KEYS } from "../types";

export const owner = (): Session => sessionOf("owner");
/** The QC manager: reads and records, no owner permission. */
export const qc = (): Session => sessionOf("production_staff");

export const reply = (status: number, body: unknown): Response =>
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

export function narrowScreen(narrow: boolean) {
  vi.stubGlobal(
    "matchMedia",
    vi.fn(() => ({ matches: narrow, addEventListener: () => undefined, removeEventListener: () => undefined })),
  );
}

export type Call = { method: string; path: string; /** With its query string. */ url: string; body: unknown };
type Handler = (body: unknown, call: Call) => unknown;

/**
 * A `fetch` that answers `"METHOD /path"` from a table (query strings
 * ignored), records every call, and refuses what it was not told about.
 * A handler may return a `Response` to refuse with a status.
 */
export function mockApi(table: Record<string, Handler | unknown>) {
  const calls: Call[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
      const path = url.split("?")[0];
      const method = (init?.method ?? "GET").toUpperCase();
      const raw = typeof init?.body === "string" ? init.body : undefined;
      const call: Call = { method, path, url, body: raw ? JSON.parse(raw) : undefined };
      calls.push(call);
      const entry = table[`${method} ${path}`];
      if (entry === undefined) return reply(404, { detail: `Not served: ${method} ${path}` });
      // A handler may answer later (a promise), to play a slow response.
      const answer = await (typeof entry === "function" ? (entry as Handler)(call.body, call) : entry);
      return answer instanceof Response ? answer : reply(200, answer);
    }),
  );
  return calls;
}

export function renderAt(address: string, session: Session) {
  return render(
    <MemoryRouter initialEntries={[address]}>
      <Routes>
        <Route path="/production">{productionRoutes(session)}</Route>
      </Routes>
    </MemoryRouter>,
  );
}

// ── Orders ───────────────────────────────────────────────────────────────────

const LABELS: Record<StageKey, string> = {
  plan: "Plan",
  sample: "Sample",
  materials: "Materials",
  fabric_check: "Fabric check",
  pattern_check: "Pattern check",
  cutting: "Cutting",
  making: "Making",
  final_inspection: "Final inspection",
  warehouse: "Warehouse receipt",
  settle: "Settle",
};

const PLANNED = { S: 10, M: 20 } as const;

/**
 * An order whose current stage is `stage`: everything before it done, the
 * sample skipped. Two sizes, S and M, planned 10 and 20. From the final
 * inspection on, 10 and 20 were cut (9 and 20 passed or in hand as the test
 * sets them through `sizes`).
 */
export function makeOrder(
  stage: StageKey,
  options: { money?: boolean; sizes?: Partial<SizeLine>[]; deliveries?: Delivery[]; extra?: Partial<OrderView> } = {},
): OrderView {
  const at = STAGE_KEYS.indexOf(stage);
  const status = (key: StageKey): StageStatus => {
    if (key === "sample") return "skipped";
    return STAGE_KEYS.indexOf(key) < at ? "done" : "todo";
  };
  const stages: OrderStage[] = STAGE_KEYS.map((key, index) => ({
    key,
    label: LABELS[key],
    position: index + 1,
    status: status(key),
    expected_date: `2030-10-${String(index + 1).padStart(2, "0")}`,
    done_on: status(key) === "done" ? "2030-09-28" : null,
    done_by: status(key) === "done" ? "Nour" : null,
    note: key === "sample" ? "Repeat run, nothing changed" : null,
  }));
  const cutDone = at > STAGE_KEYS.indexOf("cutting");
  const sizes: SizeLine[] = (["S", "M"] as const).map((size, index) => ({
    size,
    planned: PLANNED[size],
    cut: cutDone ? PLANNED[size] : null,
    passed: null,
    to_fix: null,
    rejected: null,
    shipped: 0,
    counted: 0,
    fix_shipped: 0,
    fix_counted: 0,
    ...(options.sizes?.[index] ?? {}),
  }));
  const sum = (key: "passed" | "to_fix" | "rejected" | "cut" | "shipped" | "counted") =>
    sizes.some((line) => line[key] !== null) ? sizes.reduce((total, line) => total + (line[key] ?? 0), 0) : null;
  const deliveries = options.deliveries ?? [];
  const order: OrderView = {
    id: 3,
    code: "PO-2611-01",
    style_name: "Oversized hoodie",
    colour: "Black",
    status: "open",
    factory: { id: "SUP-1", name: "Main factory" },
    image_url: null,
    colour_code: null,
    fabric_type: null,
    print_supplier_name: null,
    stage: { key: stage, label: LABELS[stage], position: at + 1 },
    steps: STAGE_KEYS.map(status),
    planned_total: 30,
    cut_total: cutDone ? 30 : null,
    shipped_total: 0,
    received_total: null,
    target_date: "2030-11-03",
    delivery_date: "2030-11-03",
    lateness_days: 0,
    finished_on: null,
    next_action: {
      stage,
      what: stage === "cutting" ? "Record cut quantities" : stage === "final_inspection" ? "Finish the final inspection" : stage === "warehouse" ? "Receive 30 pieces" : "Settle with the factory",
      who: stage === "settle" ? "owner" : "qc",
      by: "2030-11-03",
      since: "2030-09-28",
    },
    flags: { late: false, waiting_for_owner: stage === "settle", count_mismatch: false, fix_pieces_due: false },
    shopify_product_id: "P1",
    fabric_bought_by: "hba",
    printing: "factory",
    print_supplier: null,
    repeat_run: true,
    notes: null,
    created_at: "2030-09-28T08:00:00Z",
    created_by: "Nour",
    current_stage: stage,
    sample: { status: "none", note: null, decided_by: null, decided_at: null },
    stages,
    sizes,
    totals: {
      planned: 30,
      cut: sum("cut"),
      passed: sum("passed"),
      to_fix: sum("to_fix"),
      rejected: sum("rejected"),
      shipped: sum("shipped"),
      counted: sum("counted"),
      fix_shipped: 0,
      fix_counted: 0,
    },
    reasons: { cut_short: [], rejected: [], to_fix: [] },
    date_history: [
      { id: 1, old_date: null, new_date: "2030-11-03", set_by: "owner", reason: "Target when planned", created_at: "2030-09-28T08:00:00Z", created_by: "Nour" },
    ],
    deliveries,
    fix_not_returned: at > STAGE_KEYS.indexOf("final_inspection") ? 0 : null,
    files_count: 0,
    warehouse_done_on: null,
    product: emptyProduct(),
    ...options.extra,
  };
  if (options.money) {
    order.cost = cost();
    order.settlement = cutDone ? settlement() : null;
  }
  return order;
}

/** An order's product with nothing set but its factory. */
export function emptyProduct(): ProductDetails {
  return {
    colour_code: null,
    fabric_type: null,
    decoration_type: null,
    decoration_width_cm: null,
    suppliers: [{ id: "SUP-1", name: "Main factory", roles: ["Factory"] }],
    pattern_files: [],
    size_charts: [],
  };
}

export function cost(): Cost {
  const part = (key: Cost["parts"][number]["part"], label: string, target: number, actual: number | null) => ({
    part: key,
    label,
    target_piastres: target,
    actual_piastres: actual,
  });
  return {
    parts: [
      part("fabric", "Fabric", 16500, 17200),
      part("manufacturing", "Manufacturing", 8500, null),
      part("printing", "Printing", 3000, null),
      part("accessories", "Accessories", 1200, null),
      part("packaging", "Special packaging", 800, null),
    ],
    target_total_piastres: 30000,
    actual_total_piastres: 30700,
    piece_cost_piastres: 30700,
  };
}

export function settlement(): Settlement {
  return {
    making_rate_piastres: 11500,
    rate_includes_printing: true,
    pieces_cut: 30,
    work_value_piastres: 345000,
    rejected_pieces: 0,
    rejected_basis: "making",
    rejected_rate_piastres: 11500,
    rejected_deduction_piastres: 0,
    held_pieces: 0,
    held_piastres: 0,
    payable_piastres: 345000,
    settled: false,
    settled_at: null,
  };
}

export function makeRow(over: Partial<OrderRow> & { id: number; style_name: string }): OrderRow {
  const steps: StageStatus[] = ["done", "skipped", "done", "done", "done", "done", "todo", "todo", "todo", "todo"];
  return {
    code: `PO-2611-0${over.id}`,
    colour: "Black",
    status: "open",
    factory: { id: "SUP-1", name: "Main factory" },
    stage: { key: "making", label: "Making", position: 7 },
    steps,
    planned_total: 1000,
    cut_total: 972,
    shipped_total: 0,
    received_total: null,
    target_date: "2030-11-20",
    delivery_date: "2030-11-20",
    lateness_days: 0,
    finished_on: null,
    next_action: { stage: "making", what: "Final inspection", who: "qc", by: "2030-11-26", since: "2030-11-01" },
    flags: { late: false, waiting_for_owner: false, count_mismatch: false, fix_pieces_due: false },
    image_url: null,
    colour_code: null,
    fabric_type: null,
    print_supplier_name: null,
    notes: null,
    ...over,
  };
}

// ── Tasks ────────────────────────────────────────────────────────────────────

/** Cairo's "today" in the task tests: a Wednesday. */
export const TODAY = "2030-11-13";

const HOODIE = { id: 1, code: "PO-2610-01", style_name: "Oversized hoodie", colour: "Black" };

/** A task worked out from an order (`GET /api/prod/tasks`). */
export function makeTask(over: Partial<GeneratedTask> & { key: string; title: string }): GeneratedTask {
  return {
    kind: "generated",
    who: "qc",
    due: "2030-11-15",
    order: HOODIE,
    stage: null,
    waiting_on: null,
    since: null,
    open: null,
    group: "week",
    overdue_days: 0,
    ...over,
  };
}

/** A task somebody typed in. */
export function makeManual(over: Partial<ManualTask> & { id: number; title: string }): ManualTask {
  return {
    kind: "manual",
    key: `task:${over.id}`,
    who: "qc",
    due: null,
    order: null,
    stage: null,
    waiting_on: null,
    since: null,
    open: null,
    note: null,
    done: false,
    done_at: null,
    for_owner: false,
    next_action: null,
    updates: [],
    updated_at: null,
    group: "later",
    overdue_days: 0,
    ...over,
  };
}

/** The list as the server answers it: counts worked out from the open tasks. */
export function makeTaskList(tasks: Task[]): TaskList {
  const open = tasks.filter((task) => !(task.kind === "manual" && task.done));
  return {
    today: TODAY,
    counts: {
      all: open.length,
      overdue: open.filter((task) => task.group === "overdue").length,
      qc: open.filter((task) => task.who === "qc").length,
      owner: open.filter((task) => task.who === "owner").length,
      factory: open.filter((task) => task.who === "factory").length,
    },
    tasks,
  };
}

// ── Incoming ─────────────────────────────────────────────────────────────────

const NO_SIZES = { XS: 0, S: 0, M: 0, L: 0, XL: 0, XXL: 0 };

/** Pieces per size (every size, as the server sends them) and the total. */
export function counts(sizes: Partial<IncomingCounts["sizes"]> = {}): IncomingCounts {
  const all = { ...NO_SIZES, ...sizes };
  return { sizes: all, total: Object.values(all).reduce((sum, n) => sum + n, 0) };
}

/** Finished pieces still to come: 20 planned for the hoodie, none shipped. */
export function makeArrival(over: Partial<IncomingArrival> = {}): IncomingArrival {
  const planned = counts({ S: 8, M: 12 });
  return {
    key: "order:1:finished",
    kind: "finished",
    order: HOODIE,
    factory: "Main factory",
    basis: "planned",
    expected: planned,
    shipped: counts(),
    to_come: planned,
    due: "2030-11-26",
    late_days: 0,
    stage: { key: "cutting", label: "Cutting", position: 6 },
    status_words: "being cut, final numbers after cutting",
    can_record: false,
    ...over,
  };
}

/** A delivery of finished pieces, counted by Khazenly, every size matching. */
export function makeIncomingDelivery(over: Partial<IncomingDelivery> = {}): IncomingDelivery {
  return {
    id: 1,
    order: HOODIE,
    number: 1,
    kind: "finished",
    shipped_on: "2030-11-09",
    counted_on: "2030-11-10",
    shipped: { S: 200, M: 280 },
    shipped_total: 480,
    counted: { S: 200, M: 280 },
    counted_total: 480,
    state: "match",
    difference: null,
    missing: 0,
    extra: 0,
    sizes_differ: [],
    reason: null,
    ...over,
  };
}

/** The screen's answer, with the four figures worked out from the rows as the server does. */
export function makeIncoming(arrivals: IncomingArrival[], deliveries: IncomingDelivery[]): Incoming {
  const toCome = arrivals.reduce((sum, row) => sum + row.to_come.total, 0);
  const waiting = deliveries.filter((d) => d.state === "waiting_for_count").reduce((sum, d) => sum + d.shipped_total, 0);
  const off = deliveries.filter((d) => d.state === "mismatch").reduce((sum, d) => sum + d.missing + d.extra, 0);
  const inMonth = (month: string) =>
    arrivals.filter((row) => row.due.startsWith(month)).reduce((sum, row) => sum + row.to_come.total, 0);
  return {
    today: TODAY,
    totals: {
      to_come_total: toCome,
      this_month: { month: "2030-11", label: "November", pieces: inMonth("2030-11") },
      next_month: { month: "2030-12", label: "December", pieces: inMonth("2030-12") },
      waiting_for_count: waiting,
      mismatch_pieces: off,
    },
    arrivals,
    deliveries,
  };
}
