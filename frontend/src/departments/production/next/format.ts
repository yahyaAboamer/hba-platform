/**
 * Words and dates for the production screens.
 *
 * Dates arrive as `YYYY-MM-DD` and are **never parsed through `Date` for
 * display** (see `formatDay` in `lib/money.ts`). The small arithmetic below
 * (adding days, counting days between two dates) is done on UTC midnights, so
 * the browser's timezone cannot move a date.
 */
import { shortMonth } from "../../../lib/money";
import type { NextAction, OrderRow, Who } from "./types";

/** `1,000`. */
export const pieces = (count: number | null | undefined): string =>
  count === null || count === undefined ? "—" : count.toLocaleString("en-GB");

/** `1 piece`, `30 pieces`. */
export function plural(count: number, one: string, many = `${one}s`): string {
  return `${pieces(count)} ${count === 1 ? one : many}`;
}

/** `3 Nov`. The year is left off: these are working dates, all of them near today. */
export function shortDay(day: string | null | undefined): string {
  if (!day) return "—";
  const [year, month, date] = day.split("-");
  const name = shortMonth(`${year}-${month}`);
  return name === `${year}-${month}` ? day : `${Number(date)} ${name}`;
}

/** Cairo's date, as the server counts "today" (ADR 0005). */
export function cairoToday(): string {
  return new Intl.DateTimeFormat("en-CA", {
    timeZone: "Africa/Cairo",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(new Date());
}

/** The Cairo date of an instant the server stamped (`...Z`). */
export function cairoDay(iso: string | null | undefined): string | null {
  if (!iso) return null;
  const moment = new Date(iso);
  if (Number.isNaN(moment.getTime())) return null;
  return new Intl.DateTimeFormat("en-CA", {
    timeZone: "Africa/Cairo",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(moment);
}

/** `13 Nov, 14:20` in Cairo, for an instant (history). */
export function stamp(iso: string | null | undefined): string {
  if (!iso) return "";
  const moment = new Date(iso);
  if (Number.isNaN(moment.getTime())) return "";
  return new Intl.DateTimeFormat("en-GB", {
    timeZone: "Africa/Cairo",
    day: "numeric",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  }).format(moment);
}

const midnight = (day: string): number => {
  const [year, month, date] = day.split("-").map(Number);
  return Date.UTC(year, month - 1, date);
};

const DAY_MS = 86_400_000;

/** `later` minus `earlier`, in whole days. */
export function daysBetween(earlier: string, later: string): number {
  return Math.round((midnight(later) - midnight(earlier)) / DAY_MS);
}

/** `day` plus `count` days (negative to go back), as `YYYY-MM-DD`. */
export function addDays(day: string, count: number): string {
  return new Date(midnight(day) + count * DAY_MS).toISOString().slice(0, 10);
}

const WEEKDAYS = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"];

/** `Friday` for a calendar day (a UTC midnight, so the browser's timezone cannot move it). */
export function weekdayOf(day: string): string {
  return WEEKDAYS[new Date(midnight(day)).getUTCDay()];
}

export const WHO: Record<Who, string> = { owner: "Owner", qc: "QC manager", factory: "Factory" };

export type Tone = "late" | "warn" | "ok" | "";

/** How the order stands against its target date, in words (never colour alone). */
export function lateWords(row: Pick<OrderRow, "status" | "lateness_days" | "finished_on" | "delivery_date" | "target_date">): {
  text: string;
  tone: Tone;
} {
  if (row.status === "cancelled") return { text: "Cancelled", tone: "" };
  const days = row.lateness_days;
  const late = plural(days, "day");
  if (row.finished_on) {
    return days > 0 ? { text: `Finished ${late} late`, tone: "late" } : { text: "Finished on time", tone: "ok" };
  }
  if (days > 0) {
    return row.delivery_date !== row.target_date
      ? { text: `Now due ${shortDay(row.delivery_date)} · ${late} late`, tone: "late" }
      : { text: `${late} late`, tone: "late" };
  }
  if (row.delivery_date !== row.target_date) return { text: `Now due ${shortDay(row.delivery_date)}`, tone: "" };
  return { text: "On time", tone: "ok" };
}

/** "Owner · waiting 3 days", "QC manager · 16 Nov". */
export function whoWhen(action: NextAction, today: string, flagged: boolean): string {
  const parts: string[] = [WHO[action.who]];
  if (action.who === "owner" && flagged && action.since) {
    const waiting = daysBetween(action.since, today);
    if (waiting > 0) parts.push(`waiting ${plural(waiting, "day")}`);
    return parts.join(" · ");
  }
  if (action.by) parts.push(shortDay(action.by));
  return parts.join(" · ");
}

/** The stage, as the list and the order's pill say it: `7 of 10 · Making`. */
export function stagePhrase(row: Pick<OrderRow, "stage" | "status">): string {
  // A cancelled or closed order is at no stage (`_row.stage` is null), but the status is asked first anyway.
  if (row.status === "cancelled") return "Cancelled";
  if (row.status === "closed" || !row.stage) return "Settled and closed";
  return `${row.stage.position} of 10 · ${row.stage.label}`;
}

/** What the stage bar says to somebody who cannot see it. */
export function stepsSentence(steps: OrderRow["steps"]): string {
  const done = steps.filter((step) => step === "done").length;
  const skipped = steps.filter((step) => step === "skipped").length;
  return `${done} of ${steps.length} stages done${skipped ? `, ${skipped} skipped` : ""}`;
}
