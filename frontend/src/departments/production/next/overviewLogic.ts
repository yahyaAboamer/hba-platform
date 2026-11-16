/**
 * What the Overview screen decides, kept apart from the screen so each rule can be tested on its own:
 * the header and figures, the words on a row, and where a button goes.
 *
 * The server works out every figure, flag and lateness (`services/overview.py`); nothing here compares a
 * date with today except "waiting N days", which counts from the server's own `today`. Money is drawn only
 * when the answer carries it: a missing key is never replaced by a zero.
 */
import { formatEgp } from "../../../lib/money";
import { daysBetween, pieces, plural, shortDay, weekdayOf, WHO } from "./format";
import type { Powers } from "./logic";
import { taskLink } from "./taskLogic";
import type { IncomingArrival, OrderRow, Overview, OverviewDecision, OverviewLink, OverviewProblem } from "./types";

const MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"];

/** "Friday 13 Nov · 5 orders in production, 3,900 pieces planned". */
export function headerLine(data: Overview): string {
  const { open_orders: open, planned_pieces: planned } = data.summary;
  return `${weekdayOf(data.today)} ${shortDay(data.today)} · ${plural(open, "order")} in production, ${plural(planned, "piece")} planned`;
}

/** The month's name for "Arriving in November", from the name itself or from `YYYY-MM`. */
export function monthName(month: { month: string; label?: string }): string {
  if (month.label) return month.label;
  const match = /^\d{4}-(\d{2})/.exec(month.month);
  return match ? (MONTHS[Number(match[1]) - 1] ?? month.month) : month.month;
}

export type Figure = { label: string; value: string; tone: "late" | "warn" | "" };

/** The figures, left to right: four with the money, three without. The words carry the meaning; the tone adds to them. */
export function figuresOf(data: Overview, isOwner: boolean): Figure[] {
  const { figures } = data;
  const out: Figure[] = [
    { label: isOwner ? "Waiting for your decision" : "Waiting for the owner", value: pieces(figures.decisions), tone: figures.decisions > 0 ? "warn" : "" },
    { label: "Orders running late", value: `${pieces(figures.late_orders)} of ${pieces(figures.open_orders)}`, tone: figures.late_orders > 0 ? "late" : "" },
    { label: `Arriving in ${monthName(figures.arriving_this_month)}`, value: plural(figures.arriving_this_month.pieces, "piece"), tone: "" },
  ];
  if (figures.owed_piastres !== undefined) {
    out.push({ label: "You owe suppliers", value: formatEgp(figures.owed_piastres), tone: "" });
  }
  return out;
}

// ── Waiting for the decision ─────────────────────────────────────────────────

/** "Zip hoodie · Olive · waiting 3 days"; a hand-added one with no order says so. */
export function decisionLine(item: OverviewDecision, today: string): string {
  const parts: string[] = [];
  if (item.order) parts.push(`${item.order.style_name} · ${item.order.colour}`);
  if (item.kind === "manual") parts.push(item.order ? "Added by hand" : "Added by hand · no order");
  const days = item.since ? Math.max(0, daysBetween(item.since, today)) : 0;
  if (days > 0) parts.push(`waiting ${plural(days, "day")}`);
  return parts.join(" · ");
}

export type Action = { label: string; to: string };

/**
 * The owner's button on a decision: the order with the form open, as on the Tasks screen ("Review sample",
 * "Settle"); "Open tasks" for a hand-added one, or one with no order to go to. Nobody else is given a button.
 */
export function decisionAction(item: OverviewDecision, powers: Powers): Action | null {
  if (!powers.isOwner) return null;
  if (item.kind === "generated") {
    const link = taskLink(
      { ...item, kind: "generated", who: "owner", stage: null, waiting_on: null, group: "week" },
      powers,
    );
    if (link) return { label: link.label, to: link.to };
  }
  return { label: "Open tasks", to: "/production/next/tasks" };
}

// ── Problems ─────────────────────────────────────────────────────────────────

export const orderAddress = (id: number): string => `/production/next/orders/${id}`;

/** Where a problem's "Open" goes. */
export function linkAddress(link: OverviewLink): string {
  if (link.to === "order") return link.open ? `${orderAddress(link.id)}?open=${link.open}` : orderAddress(link.id);
  return link.to === "incoming" ? "/production/next/incoming" : "/production/next/tasks";
}

/** What a screen reader hears on a problem's link: the problem itself. */
export const problemLabel = (problem: OverviewProblem): string => `Open: ${problem.title}`;

// ── The orders ───────────────────────────────────────────────────────────────

/** How many pieces, and of what: "925 of 1,000 counted", "300 of 985 shipped", "972 cut", "800 planned". */
export function quantityLine(row: OrderRow): string {
  const whole = row.cut_total ?? row.planned_total;
  if (row.received_total !== null && row.received_total > 0) return `${pieces(row.received_total)} of ${pieces(whole)} counted`;
  if (row.shipped_total > 0) return `${pieces(row.shipped_total)} of ${pieces(whole)} shipped`;
  if (row.cut_total !== null) return `${pieces(row.cut_total)} cut`;
  return `${pieces(row.planned_total)} planned`;
}

/** "9 of 10 · Warehouse receipt · 925 of 1,000 counted". */
export function orderLine(row: OrderRow): string {
  const stage = row.stage ? `${row.stage.position} of 10 · ${row.stage.label}` : "Settled and closed";
  return `${stage} · ${quantityLine(row)}`;
}

/** "Next: record cut quantities · QC manager"; the owner's own is said so in the colour as well. */
export function nextWords(row: OrderRow): { text: string; ownerTurn: boolean } | null {
  const action = row.next_action;
  if (!action) return null;
  return { text: `Next: ${action.what.charAt(0).toLowerCase()}${action.what.slice(1)} · ${WHO[action.who]}`, ownerTurn: action.who === "owner" };
}

/** The date the order is due, and how it stands: "26 Nov · 6 days late", "15 Nov · on time", "17 Nov · finished 6 days late". */
export function dueWords(row: OrderRow): { text: string; late: boolean } {
  const day = shortDay(row.delivery_date);
  const late = row.lateness_days > 0;
  const days = plural(row.lateness_days, "day");
  if (row.finished_on) return { text: `${day} · ${late ? `finished ${days} late` : "finished on time"}`, late };
  return { text: `${day} · ${late ? `${days} late` : "on time"}`, late };
}

// ── Arriving next ────────────────────────────────────────────────────────────

/** "30 fix pieces · Oversized hoodie · Black", "685 pieces · Oversized hoodie · Off-white". */
export function arrivalWords(row: IncomingArrival): string {
  const what = row.kind === "fix" ? plural(row.to_come.total, "fix piece", "fix pieces") : plural(row.to_come.total, "piece");
  return `${what} · ${row.order.style_name} · ${row.order.colour}`;
}

/** "17 Nov", or "by 26 Nov" when it is late. */
export const arrivalDate = (row: IncomingArrival): string => (row.late_days > 0 ? `by ${shortDay(row.due)}` : shortDay(row.due));
