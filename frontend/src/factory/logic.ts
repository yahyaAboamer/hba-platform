/**
 * The factory desk's small rules, kept out of the screens so they can be
 * tested without drawing anything. What the server checks again is checked
 * here first, so a mistake is told next to the box that caused it.
 */
import { cairoDay, shortDay } from "../departments/production/screens/format";
import type { FactoryOrder, FactoryOrderRow, FactorySizeLine } from "./types";

/** The most pieces one size may be reported at (the server's own limit). */
export const MOST_PER_SIZE = 100000;

/** A typed count per size, as typed. */
export type Typed = Record<string, string>;

/** Typed counts for the order's sizes: what was reported (to correct it), or blank boxes. */
export function typedFrom(lines: FactorySizeLine[], pick: "reported" | "blank"): Typed {
  return Object.fromEntries(
    lines.map((line) => [line.size, pick === "reported" && line.reported !== null ? String(line.reported) : ""]),
  );
}

const WHOLE = /^\d{1,6}$/;

/** A typed count as a number: blank counts as none, and anything unreadable as none for a total. */
export const asCount = (text: string): number => (WHOLE.test(text.trim()) ? Number(text.trim()) : 0);

export const totalTyped = (typed: Typed): number => Object.values(typed).reduce((sum, text) => sum + asCount(text), 0);

/** What is wrong with the counts, in words, or `null` when they can be sent. */
export function reportProblem(typed: Typed): string | null {
  for (const text of Object.values(typed)) {
    const value = text.trim();
    if (value !== "" && !WHOLE.test(value)) return "Use whole numbers only, with no spaces or letters.";
    if (value !== "" && Number(value) > MOST_PER_SIZE) {
      return `A size can be at most ${MOST_PER_SIZE.toLocaleString("en-GB")} pieces.`;
    }
  }
  if (totalTyped(typed) <= 0) return "Give the number cut for at least one size.";
  return null;
}

/** The body of `PUT /orders/{id}/cut-report`: every size the order has, blank as none. */
export function reportBody(typed: Typed, note: string): { sizes: Record<string, number>; note: string | null } {
  return {
    sizes: Object.fromEntries(Object.entries(typed).map(([size, text]) => [size, asCount(text)])),
    note: note.trim() === "" ? null : note.trim(),
  };
}

/** `5 Dec` for a day or an instant the server stamped. */
export function dayWords(value: string | null | undefined): string {
  if (!value) return "—";
  return shortDay(value.length > 10 ? (cairoDay(value) ?? value) : value);
}

/** The pieces reported, from the figure the server sums or, failing that, the sizes. */
export function reportedTotal(order: Pick<FactoryOrder, "cut" | "sizes">): number {
  return order.cut.reported_total ?? order.sizes.reduce((sum, line) => sum + (line.reported ?? 0), 0);
}

/** "800 planned", "792 reported cut" or "985 cut": the figure that stands on the order now. */
export function cutWords(row: Pick<FactoryOrderRow, "planned_total" | "cut">, pieces: (n: number) => string): string {
  if (row.cut.confirmed_total !== null) return `${pieces(row.cut.confirmed_total)} cut`;
  if (row.cut.reported_total !== null) return `${pieces(row.cut.reported_total)} reported cut`;
  return `${pieces(row.planned_total)} planned`;
}

/** What the server's answer holds: the object itself, or the object under `key`. */
export function unwrap<T>(answer: unknown, key: string): T {
  if (answer !== null && typeof answer === "object" && key in (answer as Record<string, unknown>)) {
    return (answer as Record<string, T>)[key];
  }
  return answer as T;
}
