/**
 * The arithmetic of the production forms, kept apart from the screens so each
 * rule can be tested on its own.
 *
 * **Every rule here is one the server enforces** (`services/orders.py`), said
 * before anything is sent and in the server's own words where it has them. The
 * server still decides: a screen that passes its own check and is refused
 * shows the server's `detail` as it is.
 */
import { parseEgp } from "../../../lib/money";
import { addDays, plural } from "./format";
import type { DeliveryKind, FabricBuyer, OrderView, Size, StageKey, StageStatus } from "./types";
import { SIZES, STAGE_KEYS } from "./types";

// ── Counts typed per size ────────────────────────────────────────────────────

/** What a person typed in each size's box. Blank is blank, not zero. */
export type Counts = Record<Size, string>;

export function blankCounts(): Counts {
  return Object.fromEntries(SIZES.map((size) => [size, ""])) as Counts;
}

/** Counts from numbers (`null` stays blank). */
export function countsFrom(values: Partial<Record<Size, number | null | undefined>>): Counts {
  const counts = blankCounts();
  for (const size of SIZES) {
    const value = values[size];
    counts[size] = value === null || value === undefined ? "" : String(value);
  }
  return counts;
}

export const isBlank = (text: string): boolean => text.trim() === "";
export const isWhole = (text: string): boolean => /^\d{1,6}$/.test(text.trim());

/** A typed count as a number; blank or unreadable counts as 0 for a total. */
export const whole = (text: string): number => (isWhole(text) ? Number(text.trim()) : 0);

export const totalOf = (counts: Counts): number => SIZES.reduce((sum, size) => sum + whole(counts[size]), 0);

/** The sizes whose box holds something that is not a whole number. */
export const unreadable = (counts: Counts): Size[] =>
  SIZES.filter((size) => !isBlank(counts[size]) && !isWhole(counts[size]));

export const NOT_WHOLE = "Each count must be a whole number, 0 or more.";

// ── Reasons ──────────────────────────────────────────────────────────────────

export type ReasonRow = { reason: string; quantity: string };

export const blankReason = (): ReasonRow => ({ reason: "", quantity: "" });

export const reasonsFrom = (lines: { reason: string; quantity: number }[]): ReasonRow[] =>
  lines.map((line) => ({ reason: line.reason, quantity: String(line.quantity) }));

const untouched = (row: ReasonRow): boolean => isBlank(row.reason) && isBlank(row.quantity);

/** The reasons that were filled in; a wholly empty row is just an unused line. */
export const filledReasons = (rows: ReasonRow[]): ReasonRow[] => rows.filter((row) => !untouched(row));

export const reasonTotal = (rows: ReasonRow[]): number =>
  filledReasons(rows).reduce((sum, row) => sum + whole(row.quantity), 0);

/** `null` when every filled reason has words and a number above 0. */
export function reasonShape(rows: ReasonRow[]): string | null {
  for (const row of filledReasons(rows)) {
    if (isBlank(row.reason)) return "Each reason needs words saying why.";
    if (!isWhole(row.quantity) || whole(row.quantity) <= 0) return "Each reason needs a number of pieces, more than 0.";
  }
  return null;
}

export const reasonBody = (rows: ReasonRow[]) =>
  filledReasons(rows).map((row) => ({ reason: row.reason.trim(), quantity: whole(row.quantity) }));

// ── Cutting ──────────────────────────────────────────────────────────────────

export type CutDraft = {
  cut: Counts;
  planned: number;
  reasons: ReasonRow[];
  promised: string;
  today: string;
};

export function cutShortfall(draft: Pick<CutDraft, "cut" | "planned">): number {
  return draft.planned - totalOf(draft.cut);
}

/** The first thing wrong with a cut record, or `null`. */
export function cutProblem(draft: CutDraft): string | null {
  if (unreadable(draft.cut).length) return NOT_WHOLE;
  const total = totalOf(draft.cut);
  if (total <= 0) return "Give the number cut for at least one size.";
  if (isBlank(draft.promised)) return "Give the date the factory promised.";
  const shape = reasonShape(draft.reasons);
  const shortfall = draft.planned - total;
  if (shortfall > 0) {
    const given = reasonTotal(draft.reasons);
    if (given !== shortfall) {
      return (
        `${plural(shortfall, "piece")} fewer were cut than planned; the reasons account for ${pieceCount(given)}. ` +
        `Make them add up to ${pieceCount(shortfall)}.`
      );
    }
    if (shape) return shape;
  }
  return null;
}

const pieceCount = (count: number): string => count.toLocaleString("en-GB");

// ── Final inspection ─────────────────────────────────────────────────────────

export type InspectionLine = { size: Size; cut: number; passed: string; to_fix: string; rejected: string };

export type InspectionDraft = {
  lines: InspectionLine[];
  rejectedReasons: ReasonRow[];
  toFixReasons: ReasonRow[];
};

export const lineTotal = (line: InspectionLine): number => whole(line.passed) + whole(line.to_fix) + whole(line.rejected);

export function inspectionTotals(draft: InspectionDraft) {
  return {
    cut: draft.lines.reduce((sum, line) => sum + line.cut, 0),
    passed: draft.lines.reduce((sum, line) => sum + whole(line.passed), 0),
    to_fix: draft.lines.reduce((sum, line) => sum + whole(line.to_fix), 0),
    rejected: draft.lines.reduce((sum, line) => sum + whole(line.rejected), 0),
  };
}

/**
 * The first thing wrong with the inspection. Saving counts in batches only
 * needs no size over its cut and no reasons over their totals; completing it
 * needs every size to add up and every reason to be accounted for.
 */
export function inspectionProblem(draft: InspectionDraft, complete: boolean): string | null {
  for (const line of draft.lines) {
    if ([line.passed, line.to_fix, line.rejected].some((text) => !isBlank(text) && !isWhole(text))) return NOT_WHOLE;
  }
  for (const line of draft.lines) {
    const inspected = lineTotal(line);
    if (inspected > line.cut) {
      return `Size ${line.size}: ${pieceCount(inspected)} inspected, more than the ${pieceCount(line.cut)} cut.`;
    }
  }
  const shape = reasonShape(draft.rejectedReasons) ?? reasonShape(draft.toFixReasons);
  if (shape) return shape;
  const totals = inspectionTotals(draft);
  const rejectedGiven = reasonTotal(draft.rejectedReasons);
  const toFixGiven = reasonTotal(draft.toFixReasons);
  if (rejectedGiven > totals.rejected) {
    return `The reasons for rejecting add up to more than the ${pieceCount(totals.rejected)} counted.`;
  }
  if (toFixGiven > totals.to_fix) {
    return `The reasons for sending to fix add up to more than the ${pieceCount(totals.to_fix)} counted.`;
  }
  if (!complete) return null;
  for (const line of draft.lines) {
    const inspected = lineTotal(line);
    if (inspected !== line.cut) {
      return (
        `Size ${line.size}: ${pieceCount(inspected)} inspected of ${pieceCount(line.cut)} cut. ` +
        "Passed, to fix and rejected must add up to the cut for every size."
      );
    }
  }
  if (rejectedGiven !== totals.rejected) {
    return `${pieceCount(totals.rejected)} rejected, and the reasons account for ${pieceCount(rejectedGiven)}. Make them add up.`;
  }
  if (toFixGiven !== totals.to_fix) {
    return `${pieceCount(totals.to_fix)} to fix, and the reasons account for ${pieceCount(toFixGiven)}. Make them add up.`;
  }
  return null;
}

// ── Deliveries ───────────────────────────────────────────────────────────────

export type DeliveryDraft = {
  kind: DeliveryKind;
  shippedOn: string;
  shipped: Counts;
  countedOn: string;
  counted: Counts;
  /** What this kind of delivery may still take, ignoring the delivery being edited. */
  room: number;
  today: string;
};

/** Sizes where Khazenly's count differs from what the factory shipped. */
export function countDifferences(draft: Pick<DeliveryDraft, "shipped" | "counted">) {
  return SIZES.filter((size) => !isBlank(draft.counted[size]) && whole(draft.counted[size]) !== whole(draft.shipped[size])).map(
    (size) => ({ size, shipped: whole(draft.shipped[size]), counted: whole(draft.counted[size]) }),
  );
}

/** Whether any count, or the count date, has been started. */
export const countStarted = (draft: Pick<DeliveryDraft, "counted" | "countedOn">): boolean =>
  !isBlank(draft.countedOn) || SIZES.some((size) => !isBlank(draft.counted[size]));

export function deliveryProblem(draft: DeliveryDraft): string | null {
  if (unreadable(draft.shipped).length || unreadable(draft.counted).length) return NOT_WHOLE;
  const shippedTotal = totalOf(draft.shipped);
  if (shippedTotal <= 0) return "Give the number shipped for at least one size.";
  if (shippedTotal > draft.room) {
    return draft.kind === "finished"
      ? `That makes ${pieceCount(shippedTotal)} finished pieces shipped, more than the ${pieceCount(draft.room)} still to come from those that passed inspection.`
      : `That makes ${pieceCount(shippedTotal)} fixed pieces back, more than the ${pieceCount(draft.room)} still to come from those sent to fix.`;
  }
  if (isBlank(draft.shippedOn)) return "Give the date it left the factory.";
  if (draft.shippedOn > draft.today) return "The shipping date can't be in the future.";
  if (countStarted(draft)) {
    if (isBlank(draft.countedOn)) return "Give the date Khazenly counted it.";
    if (draft.countedOn > draft.today) return "Khazenly's count date can't be in the future.";
    if (draft.countedOn < draft.shippedOn) return "Khazenly can't have counted it before it left the factory.";
    const missing = SIZES.find((size) => whole(draft.shipped[size]) > 0 && isBlank(draft.counted[size]));
    if (missing) return "Give Khazenly's count for each size that shipped, even if it is 0.";
  }
  return null;
}

export function sizesBody(counts: Counts, keep: (size: Size) => boolean = () => true): Partial<Record<Size, number>> {
  const body: Partial<Record<Size, number>> = {};
  for (const size of SIZES) {
    if (keep(size) || !isBlank(counts[size])) body[size] = whole(counts[size]);
  }
  return body;
}

// ── Money typed in pounds ───────────────────────────────────────────────────

export const COST_PARTS = ["fabric", "manufacturing", "printing", "accessories", "packaging"] as const;
export type CostPartKey = (typeof COST_PARTS)[number];
export const COST_LABELS: Record<CostPartKey, string> = {
  fabric: "Fabric",
  manufacturing: "Manufacturing",
  printing: "Printing",
  accessories: "Accessories",
  packaging: "Special packaging",
};

export type CostText = Record<CostPartKey, string>;

export const blankCost = (): CostText => ({ fabric: "", manufacturing: "", printing: "", accessories: "", packaging: "" });

/** One part in piastres; blank is 0 for a target, so a part not used costs nothing. */
export function partPiastres(text: string): number | null {
  if (isBlank(text)) return 0;
  const found = parseEgp(text);
  return found === null || found < 0 ? null : found;
}

/** The parts' sum in piastres, or `null` while any is not a figure. */
export function costTotal(cost: CostText): number | null {
  let total = 0;
  for (const part of COST_PARTS) {
    const piastres = partPiastres(cost[part]);
    if (piastres === null) return null;
    total += piastres;
  }
  return total;
}

// ── Dates filled backwards (the server's `fill_dates`) ───────────────────────

/** The stages with a date of their own on the New order form, in order. */
export const DATED_STAGES = [
  "sample",
  "materials",
  "fabric_check",
  "pattern_check",
  "cutting",
  "making",
  "final_inspection",
  "warehouse",
] as const;
export type DatedStage = (typeof DATED_STAGES)[number];

export const DATE_LABELS: Record<DatedStage, string> = {
  sample: "Sample approved",
  materials: "Materials arrive",
  fabric_check: "Fabric check",
  pattern_check: "Pattern check",
  cutting: "Cutting",
  making: "Making finished",
  final_inspection: "Final inspection",
  warehouse: "At the warehouse",
};

/**
 * Each stage's expected date, backwards from the target date, exactly as the
 * server does it: the warehouse is the target date, each earlier stage is the
 * next stage's date minus the next stage's days, and a skipped stage has no
 * date and takes no days.
 */
export function fillDates(
  target: string,
  days: Record<string, number>,
  skipped: ReadonlySet<StageKey> = new Set(),
  notBefore?: string,
): Partial<Record<StageKey, string | null>> {
  const dates: Partial<Record<StageKey, string | null>> = {
    warehouse: target,
    settle: addDays(target, days.settle ?? 0),
  };
  let following: StageKey = "warehouse";
  const before = STAGE_KEYS.slice(0, STAGE_KEYS.indexOf("warehouse")).reverse();
  for (const key of before) {
    if (skipped.has(key)) {
      dates[key] = null;
      continue;
    }
    dates[key] = addDays(dates[following] as string, -(days[following] ?? 0));
    following = key;
  }
  // No stage is expected before the day the order is made (as the server does).
  if (notBefore) {
    for (const key of Object.keys(dates) as StageKey[]) {
      const day = dates[key];
      if (day && day < notBefore) dates[key] = notBefore;
    }
  }
  return dates;
}

// ── The order, read for what to offer ────────────────────────────────────────

export type Panel =
  | { kind: "complete"; stage: "materials" | "pattern_check" | "making" }
  | { kind: "fabric" }
  | { kind: "cut" }
  | { kind: "inspection" }
  | { kind: "sample" }
  | { kind: "delivery"; id: number | null; deliveryKind: DeliveryKind }
  | { kind: "date" }
  | { kind: "writeoff" }
  | { kind: "settle" }
  | { kind: "reopen"; stage: StageKey }
  | { kind: "cancel" }
  | { kind: "edit" }
  | { kind: "actual" };

export function panelKey(panel: Panel): string {
  switch (panel.kind) {
    case "complete":
      return `complete:${panel.stage}`;
    case "delivery":
      return `delivery:${panel.id ?? `new-${panel.deliveryKind}`}`;
    case "reopen":
      return `reopen:${panel.stage}`;
    default:
      return panel.kind;
  }
}

export type Powers = { canEdit: boolean; isOwner: boolean };

/** The stage a person can still reopen: the latest done one, never the plan. */
export function reopenable(order: OrderView): StageKey | null {
  const done = order.stages.filter((stage) => stage.status === "done").map((stage) => stage.key);
  const latest = done.at(-1);
  return latest && latest !== "plan" ? latest : null;
}

export const stageStatus = (order: OrderView, key: StageKey): StageStatus =>
  order.stages.find((stage) => stage.key === key)?.status ?? "todo";

/** Finished pieces that passed inspection and have not left the factory yet. */
export const finishedToCome = (order: OrderView): number =>
  Math.max(0, (order.totals.passed ?? 0) - (order.totals.shipped ?? 0));

/**
 * What the next-action bar's button does, for this person; `null` when there is nothing for them to
 * press. Somebody who may record has a button for every action on an open order: the warehouse stage
 * in particular is "Add the reason", "Enter Khazenly's count" or "Record a delivery", never nothing.
 */
export function nextButton(order: OrderView, powers: Powers): { label: string; panel: Panel } | null {
  const action = order.next_action;
  if (order.status !== "open" || !action) return null;
  const { canEdit, isOwner } = powers;
  switch (action.stage) {
    case "sample":
      return isOwner ? { label: "Review the sample", panel: { kind: "sample" } } : null;
    case "materials":
      return canEdit ? { label: "Mark materials arrived", panel: { kind: "complete", stage: "materials" } } : null;
    case "fabric_check":
      return canEdit ? { label: "Record the fabric check", panel: { kind: "fabric" } } : null;
    case "pattern_check":
      return canEdit ? { label: "Confirm the pattern check", panel: { kind: "complete", stage: "pattern_check" } } : null;
    case "cutting":
      return canEdit ? { label: "Record cut quantities", panel: { kind: "cut" } } : null;
    case "making":
      return canEdit ? { label: "Mark making finished", panel: { kind: "complete", stage: "making" } } : null;
    case "final_inspection":
      return canEdit ? { label: "Record the inspection", panel: { kind: "inspection" } } : null;
    case "warehouse": {
      if (!canEdit) return null;
      const unexplained = order.deliveries.find((delivery) => delivery.needs_reason);
      if (unexplained) {
        return { label: "Add the reason", panel: { kind: "delivery", id: unexplained.id, deliveryKind: unexplained.kind } };
      }
      const waiting = order.deliveries.find((delivery) => delivery.waiting_for_count);
      if (waiting) {
        return { label: "Enter Khazenly's count", panel: { kind: "delivery", id: waiting.id, deliveryKind: waiting.kind } };
      }
      if (finishedToCome(order) > 0) {
        return { label: "Record a delivery", panel: { kind: "delivery", id: null, deliveryKind: "finished" } };
      }
      if ((order.fix_not_returned ?? 0) > 0) {
        return { label: "Record the fix pieces", panel: { kind: "delivery", id: null, deliveryKind: "fix" } };
      }
      // Everything is shipped and counted: a receipt the owner reopened. Saving a delivery
      // completes it again, so the bar still has a button rather than an action nobody can take.
      const last = order.deliveries.at(-1);
      if (last) return { label: "Check the counts", panel: { kind: "delivery", id: last.id, deliveryKind: last.kind } };
      return { label: "Record a delivery", panel: { kind: "delivery", id: null, deliveryKind: "finished" } };
    }
    case "settle":
      return isOwner ? { label: "Settle with the factory", panel: { kind: "settle" } } : null;
    default:
      return null;
  }
}

/** Who buys the fabric, in words. */
export const BUYER_WORDS: Record<FabricBuyer, string> = { hba: "HBA", factory: "the factory" };

// ── Opening a form from a task (`?open=` on the order page) ──────────────────

/**
 * The panel a Tasks button asked the order page to open (`open` on a task, `?open=<value>` in the
 * address), or `null` when nothing should open: a value this page does not know, a form this person
 * may not use, or work the order has already moved past. The server decides again on save; this only
 * keeps the page from opening a form that would be refused.
 */
export function panelFromOpen(open: string | null, order: OrderView, powers: Powers): Panel | null {
  if (!open || order.status !== "open") return null;
  const { canEdit, isOwner } = powers;
  const todo = (key: StageKey) => stageStatus(order, key) === "todo";
  const [kind, argument] = open.split(":") as [string, string | undefined];
  switch (kind) {
    case "sample":
      return isOwner && todo("sample") ? { kind: "sample" } : null;
    case "settle":
      return isOwner && todo("settle") ? { kind: "settle" } : null;
    case "cut":
      return canEdit && todo("cutting") ? { kind: "cut" } : null;
    case "inspection":
      return canEdit && todo("final_inspection") ? { kind: "inspection" } : null;
    case "stage": {
      if (!canEdit || !argument || !STAGE_KEYS.includes(argument as StageKey) || !todo(argument as StageKey)) return null;
      if (argument === "fabric_check") return { kind: "fabric" };
      return argument === "materials" || argument === "pattern_check" || argument === "making"
        ? { kind: "complete", stage: argument }
        : null;
    }
    case "delivery": {
      if (!canEdit) return null;
      if (argument === undefined) {
        // A new delivery: of finished pieces while any are still to come, else of fix pieces.
        if (finishedToCome(order) > 0) return { kind: "delivery", id: null, deliveryKind: "finished" };
        if ((order.fix_not_returned ?? 0) > 0) return { kind: "delivery", id: null, deliveryKind: "fix" };
        return null;
      }
      return deliveryPanel(order, argument);
    }
    case "delivery-reason":
      // The reason is typed in the delivery's own form, beside the counts it explains.
      return canEdit ? deliveryPanel(order, argument) : null;
    default:
      return null;
  }
}

function deliveryPanel(order: OrderView, id: string | undefined): Panel | null {
  const found = order.deliveries.find((delivery) => String(delivery.id) === id);
  return found ? { kind: "delivery", id: found.id, deliveryKind: found.kind } : null;
}
