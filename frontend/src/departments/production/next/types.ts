/**
 * What `/api/prod` answers (`app/modules/production/orders/services/orders.py`:
 * `_row`, `view`, `history`, `choices`, `settings_view`; `files.view`).
 *
 * **Money keys end in `_piastres` and are absent, not null, for anybody
 * without `production.owner`.** `cost` and `settlement` are optional here for
 * that reason, and a screen draws a figure only when the key is there.
 */

export const SIZES = ["XS", "S", "M", "L", "XL", "XXL"] as const;
export type Size = (typeof SIZES)[number];

export const STAGE_KEYS = [
  "plan",
  "sample",
  "materials",
  "fabric_check",
  "pattern_check",
  "cutting",
  "making",
  "final_inspection",
  "warehouse",
  "settle",
] as const;
export type StageKey = (typeof STAGE_KEYS)[number];

export type StageStatus = "todo" | "done" | "skipped";
export type OrderStatus = "open" | "closed" | "cancelled";
export type Who = "owner" | "qc" | "factory";

export type NextAction = {
  stage: StageKey;
  what: string;
  who: Who;
  by: string | null;
  since: string | null;
};

export type Flags = {
  late: boolean;
  waiting_for_owner: boolean;
  count_mismatch: boolean;
  fix_pieces_due: boolean;
};

/** One line of the order list (`_row`). No money, for anybody. */
export type OrderRow = {
  id: number;
  code: string;
  style_name: string;
  colour: string;
  status: OrderStatus;
  factory: { id: string; name: string | null };
  stage: { key: StageKey; label: string; position: number } | null;
  steps: StageStatus[];
  planned_total: number;
  cut_total: number | null;
  shipped_total: number;
  received_total: number | null;
  target_date: string;
  delivery_date: string;
  lateness_days: number;
  finished_on: string | null;
  next_action: NextAction | null;
  flags: Flags;
};

export type OrderStage = {
  key: StageKey;
  label: string;
  position: number;
  status: StageStatus;
  expected_date: string | null;
  done_on: string | null;
  done_by: string | null;
  note: string | null;
};

export type SizeLine = {
  size: Size;
  planned: number;
  cut: number | null;
  passed: number | null;
  to_fix: number | null;
  rejected: number | null;
  shipped: number;
  counted: number;
  fix_shipped: number;
  fix_counted: number;
};

export type SizeTotals = {
  planned: number | null;
  cut: number | null;
  passed: number | null;
  to_fix: number | null;
  rejected: number | null;
  shipped: number | null;
  counted: number | null;
  fix_shipped: number | null;
  fix_counted: number | null;
};

export type ReasonLine = { id: number; reason: string; quantity: number };
export type Reasons = { cut_short: ReasonLine[]; rejected: ReasonLine[]; to_fix: ReasonLine[] };

export type DateChange = {
  id: number;
  old_date: string | null;
  new_date: string;
  set_by: "owner" | "factory";
  reason: string;
  created_at: string | null;
  created_by: string | null;
};

export type DeliveryKind = "finished" | "fix";

export type Delivery = {
  id: number;
  number: number;
  kind: DeliveryKind;
  shipped_on: string;
  counted_on: string | null;
  mismatch_reason: string | null;
  sizes: { size: Size; shipped: number; counted: number | null }[];
  shipped_total: number;
  counted_total: number | null;
  waiting_for_count: boolean;
  mismatch: boolean;
  needs_reason: boolean;
};

export type CostPart = {
  part: "fabric" | "manufacturing" | "printing" | "accessories" | "packaging";
  label: string;
  target_piastres: number;
  actual_piastres: number | null;
};

export type Cost = {
  parts: CostPart[];
  target_total_piastres: number;
  actual_total_piastres: number | null;
  piece_cost_piastres: number;
  /** Owner only: what the purchases for this order say each part costs per piece (batch 4). */
  from_purchases?: FromPurchases;
};

/** The four parts a purchase can be of that an order's cost also has. Manufacturing is never bought. */
export type BoughtPart = "fabric" | "printing" | "accessories" | "packaging";

export type PurchaseBehind = { id: number; item: string; supplier: { id: string; name: string }; total_piastres: number };

export type FromPurchasesPart = {
  part: BoughtPart;
  label: string;
  purchases: PurchaseBehind[];
  total_piastres: number;
  /** `null` when there are no purchases for the part. */
  per_piece_piastres: number | null;
};

export type FromPurchases = {
  /** The pieces cut once cutting is done, else the pieces planned. */
  pieces: number;
  basis: "cut" | "planned";
  parts: FromPurchasesPart[];
  /** Purchases for the order that belong to no part. */
  other: { purchases: PurchaseBehind[]; total_piastres: number };
};

export type Settlement = {
  making_rate_piastres: number;
  rate_includes_printing: boolean;
  pieces_cut: number;
  work_value_piastres: number;
  rejected_pieces: number;
  rejected_basis: "making" | "fabric_and_making";
  rejected_rate_piastres: number;
  rejected_deduction_piastres: number;
  held_pieces: number;
  held_piastres: number;
  payable_piastres: number;
  settled: boolean;
  settled_at: string | null;
};

export type Printing = "factory" | "outside" | "none";
export type FabricBuyer = "hba" | "factory";

/** `view`: the row, and everything on the order. */
export type OrderView = OrderRow & {
  shopify_product_id: string | null;
  fabric_bought_by: FabricBuyer;
  printing: Printing;
  print_supplier: { id: string; name: string | null } | null;
  repeat_run: boolean;
  notes: string | null;
  created_at: string | null;
  created_by: string | null;
  current_stage: StageKey | null;
  sample: { status: "none" | "pending" | "approved" | "changes"; note: string | null; decided_by: string | null; decided_at: string | null };
  stages: OrderStage[];
  sizes: SizeLine[];
  totals: SizeTotals;
  reasons: Reasons;
  date_history: DateChange[];
  deliveries: Delivery[];
  fix_not_returned: number | null;
  files_count: number;
  warehouse_done_on: string | null;
  /** Owner only. */
  cost?: Cost;
  /** Owner only; `null` until cutting is done. */
  settlement?: Settlement | null;
};

/** Every write answers with the order as this person may see it. */
export type OrderAnswer = { order: OrderView; delivery_id?: number };

export type HistoryEvent = { id: number; at: string | null; who: string | null; action: string; summary: string | null };

export type ProdFile = {
  id: number;
  name: string;
  stage: StageKey | null;
  mime_type: string;
  size_bytes: number;
  created_at: string | null;
  uploaded_by: string | null;
  url: string;
};

export type StageDaysRow = {
  stage: StageKey;
  label: string;
  days: number;
  updated_at: string | null;
  updated_by: string | null;
};

export type Choices = {
  suppliers: { id: string; name: string; category: string | null }[];
  products: { id: string; title: string }[];
  sizes: Size[];
  stage_days: Record<string, number>;
};

// ── Tasks (`app/modules/production/orders/services/tasks.py`) ────────────────

/** `done` is only there when the list was asked for recently done tasks. */
export type TaskGroup = "overdue" | "today" | "week" | "later" | "done";

export type TaskOrder = { id: number; code: string; style_name: string; colour: string };

type TaskCommon = {
  /** Stable for the same work. */
  key: string;
  title: string;
  who: Who;
  due: string | null;
  order: TaskOrder | null;
  stage: StageKey | null;
  /** The supplier's name when `who` is the factory. */
  waiting_on: string | null;
  /** The day it started waiting. */
  since: string | null;
  /** Only on the two purchase tasks (`open` is `purchase:<id>`): the supplier the goods are from. */
  supplier?: { id: string; name: string };
  group: TaskGroup;
  overdue_days: number;
};

/** Worked out from an open order on each read; never stored. */
export type GeneratedTask = TaskCommon & {
  kind: "generated";
  /**
   * Which form of the order page does the work: `sample`, `stage:<key>`, `cut`, `inspection`,
   * `delivery`, `delivery:<id>`, `delivery-reason:<id>`, `settle`; `null` when there is nothing to fill in.
   */
  open: string | null;
};

/** Typed in by somebody. */
export type ManualTask = TaskCommon & {
  kind: "manual";
  id: number;
  open: null;
  note: string | null;
  done: boolean;
  done_at: string | null;
  for_owner: boolean;
};

export type Task = GeneratedTask | ManualTask;

export type TaskCounts = { all: number; overdue: number; qc: number; owner: number; factory: number };

export type TaskList = { today: string; counts: TaskCounts; tasks: Task[] };

/** What a write to a hand-added task answers with. */
export type TaskAnswer = { task: ManualTask };

// ── Incoming (`app/modules/production/orders/services/incoming.py`) ──────────
// No money in any of it, for anybody.

/** Pieces per size (every size, zero where there are none) and in total. */
export type IncomingCounts = { sizes: Record<Size, number>; total: number };

export type IncomingArrival = {
  key: string;
  /** Finished pieces still to leave the factory, or pieces sent back for fixing. */
  kind: "finished" | "fix";
  order: TaskOrder;
  factory: string | null;
  /** Which count `expected` comes from; `null` for fix pieces. */
  basis: "planned" | "cut" | "passed" | null;
  expected: IncomingCounts;
  shipped: IncomingCounts;
  to_come: IncomingCounts;
  due: string;
  late_days: number;
  stage: { key: StageKey; label: string; position: number } | null;
  status_words: string;
  /** The order's own delivery form would accept a delivery now. */
  can_record: boolean;
};

export type DeliveryState = "waiting_for_count" | "mismatch" | "explained" | "match";

export type IncomingDelivery = {
  id: number;
  order: TaskOrder;
  number: number;
  kind: DeliveryKind;
  shipped_on: string;
  counted_on: string | null;
  /** Only the sizes the delivery holds. */
  shipped: Partial<Record<Size, number>>;
  shipped_total: number;
  /** Only the sizes Khazenly has counted; empty until the count date is entered. */
  counted: Partial<Record<Size, number>>;
  counted_total: number | null;
  state: DeliveryState;
  /** Counted minus shipped, signed; `null` unless the counts differ. */
  difference: number | null;
  missing: number;
  extra: number;
  sizes_differ: { size: Size; shipped: number; counted: number; difference: number }[];
  /** The reason somebody gave, when the counts differ and one was given. */
  reason: string | null;
};

export type IncomingMonth = { month: string; label: string; pieces: number };

export type IncomingTotals = {
  to_come_total: number;
  this_month: IncomingMonth;
  next_month: IncomingMonth;
  waiting_for_count: number;
  mismatch_pieces: number;
};

export type Incoming = {
  today: string;
  totals: IncomingTotals;
  arrivals: IncomingArrival[];
  deliveries: IncomingDelivery[];
};

// ── Overview (`app/modules/production/orders/services/overview.py`) ─────────
// Money keys (`owed_piastres`, `owed`, the `cost_over` problems) are absent, not null, for anybody without
// `production.owner`: a screen draws money only when its key is there.

/** One thing waiting for the owner: an open task of his (`tasks.listing`), with the fields the screen needs. */
export type OverviewDecision = {
  key: string;
  title: string;
  kind: "generated" | "manual";
  /** The hand-added task's id; `null` for a generated one. */
  id?: number | null;
  order: TaskOrder | null;
  due: string | null;
  since: string | null;
  open: string | null;
  overdue_days: number;
};

export type OverviewProblemKind = "late_order" | "late_material" | "count_mismatch" | "cost_over";

/** Where a problem's "Open" goes: an order (perhaps with a form open), Incoming, or Tasks. */
export type OverviewLink = { to: "order"; id: number; open?: string | null } | { to: "incoming" } | { to: "tasks" };

export type OverviewProblem = { kind: OverviewProblemKind; title: string; detail: string; link: OverviewLink };

export type OverviewOwed = {
  supplier: { id: string; name: string };
  owed_piastres: number;
  /** One short line ("Rest of the fleece purchase"), or nothing. */
  detail?: string | null;
};

export type Overview = {
  today: string;
  summary: { open_orders: number; planned_pieces: number };
  figures: {
    decisions: number;
    late_orders: number;
    open_orders: number;
    /** `month` is the month's name ("November") or `YYYY-MM`; `label` is the name when the server sends both. */
    arriving_this_month: { month: string; label?: string; pieces: number };
    owed_piastres?: number;
  };
  decisions: OverviewDecision[];
  problems: OverviewProblem[];
  orders: OrderRow[];
  arriving: IncomingArrival[];
  owed?: OverviewOwed[];
};

// ── Suppliers (`app/modules/production/orders/services/suppliers.py`, `account.py`) ──
// Money keys are absent, not null, for anybody without `production.owner`: every one is optional here,
// and a screen draws a figure only when its key is there.

export type SectionRef = { id: number; name: string };
export type Section = SectionRef & { position: number; supplier_count: number };

export type PayMethod = "bank_transfer" | "cash" | "instapay" | "wallet" | "cheque";
export type PayKind = "weekly" | "deposit" | "final";
export type PurchaseUnit = "kg" | "m" | "piece";
export type PurchasePart = "fabric" | "printing" | "accessories" | "packaging" | "other";

type SupplierBasics = {
  /** `fac`, or a UUID: whatever the old table holds. */
  id: string;
  code: string;
  name: string;
  contact_person: string | null;
  phone: string | null;
  whatsapp: string | null;
  city: string | null;
  notes: string | null;
  active: boolean;
  sections: SectionRef[];
  open_orders: number;
  /** Purchases not yet received. */
  open_purchases: number;
};

/** One line of the supplier list. */
export type SupplierRow = SupplierBasics & {
  /** Positive: HBA owes. Negative: overpaid. Owner only. */
  owed_piastres?: number;
  held_piastres?: number;
};

export type SupplierList = {
  sections: Section[];
  suppliers: SupplierRow[];
  unsectioned: number;
  /** What is owed in total, leaving out suppliers that are overpaid. Owner only. */
  owed_total_piastres?: number;
};

export type PurchaseView = {
  id: number;
  supplier_id: string;
  item: string;
  /** A decimal string (`"1075"`, `"12.5"`), never a float. */
  quantity: string;
  unit: PurchaseUnit;
  part: PurchasePart;
  order: { id: number; code: string; style_name: string; colour: string; status: OrderStatus } | null;
  bought_on: string;
  expected_on: string | null;
  received_on: string | null;
  note: string | null;
  voided: boolean;
  voided_at: string | null;
  // Owner only.
  unit_price_piastres?: number;
  total_piastres?: number;
  deposit_piastres?: number;
  /** Voided, and the supplier kept the deposit: it stands on the account as credit. */
  deposit_kept?: boolean;
  void_reason?: string | null;
};

export type AccountLine = {
  /** `null` for the line "so far, not settled", which is worked out on each read and is not a ledger line. */
  id: number | null;
  kind: "opening" | "purchase" | "work" | "payment" | "adjustment";
  what: string;
  /** Positive: HBA owes more. Negative: HBA owes less. */
  amount_piastres: number;
  /** What HBA owes after this line. */
  balance_after_piastres: number;
  happened_on: string | null;
  order: { id: number; code: string } | null;
  purchase: { id: number; item: string } | null;
  method: PayMethod | null;
  payment_kind: PayKind | null;
  note: string | null;
  /** This line undoes `reverses_id`, and `note` is the reason. */
  reversal: boolean;
  reverses_id: number | null;
  reversed: boolean;
  reversed_by_id: number | null;
  not_settled: boolean;
  receipt: { url: string; mime_type: string; size_bytes: number } | null;
  created_by: string | null;
  created_at: string | null;
};

export type SupplierOrder = {
  id: number;
  code: string;
  style_name: string;
  colour: string;
  status: OrderStatus;
  role: "factory" | "print";
  /** `null` unless the order is open. */
  stage: { key: StageKey; label: string; position: number } | null;
};

/** `GET /suppliers/{id}`, and what every write on a supplier answers with. */
export type SupplierView = SupplierBasics & {
  purchases: PurchaseView[];
  orders: SupplierOrder[];
  // Owner only.
  owed_piastres?: number;
  held_piastres?: number;
  /** This calendar year's payments that still stand. */
  paid_piastres?: number;
  paid_year?: number;
  /** A balance brought forward still stands. */
  has_opening?: boolean;
  /** Newest first. */
  account?: AccountLine[];
};

/** Every write on a supplier answers with its page. `notice` is added by the screen, never sent. */
export type SupplierAnswer = { supplier: SupplierView; purchase_id?: number; entry_id?: number; notice?: string };

export type SectionsAnswer = { sections: Section[]; section_id?: number; deleted?: number };
