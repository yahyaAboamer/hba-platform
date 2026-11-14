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
