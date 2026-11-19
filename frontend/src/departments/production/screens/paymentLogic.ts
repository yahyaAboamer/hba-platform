/**
 * What the Payments screen decides, kept apart so each rule can be tested on its own: the quick date
 * ranges, the list's address and the words. The server lists and totals; nothing here adds money up.
 */
import { formatEgp, monthAdd } from "../../../lib/money";
import { addDays, plural } from "./format";

export type PayRange = { from: string; to: string };

export type Preset = "month" | "last" | "year" | "all";

export const PRESETS: readonly Preset[] = ["month", "last", "year", "all"];

export const PRESET_LABELS: Record<Preset, string> = {
  month: "This month",
  last: "Last month",
  year: "This year",
  all: "All",
};

/** The last day of a `YYYY-MM` month. */
const monthEnd = (month: string): string => addDays(`${monthAdd(month, 1)}-01`, -1);

/** The dates a quick choice stands for, from Cairo's today. "All" is no bounds at all. */
export function presetRange(preset: Preset, today: string): PayRange {
  const month = today.slice(0, 7);
  switch (preset) {
    case "month":
      return { from: `${month}-01`, to: monthEnd(month) };
    case "last": {
      const last = monthAdd(month, -1);
      return { from: `${last}-01`, to: monthEnd(last) };
    }
    case "year":
      return { from: `${today.slice(0, 4)}-01-01`, to: `${today.slice(0, 4)}-12-31` };
    case "all":
      return { from: "", to: "" };
  }
}

/** Which quick choice the range is, if it is one. */
export function presetOf(range: PayRange, today: string): Preset | null {
  return PRESETS.find((preset) => {
    const found = presetRange(preset, today);
    return found.from === range.from && found.to === range.to;
  }) ?? null;
}

/** The refusal for a range the wrong way round; `null` when it reads. */
export function payRangeProblem(range: PayRange): string | null {
  return range.from && range.to && range.from > range.to ? "The From date is after the To date." : null;
}

/** `from=…&to=…&supplier=…`, leaving out what is not set; empty when nothing is. */
export function paymentsQuery(range: PayRange, supplier: string): string {
  const query = new URLSearchParams();
  if (range.from) query.set("from", range.from);
  if (range.to) query.set("to", range.to);
  if (supplier) query.set("supplier", supplier);
  return query.toString();
}

/** `/api/prod/payments?from=…&to=…&supplier=…`, leaving out what is not set. */
export function paymentsAddress(range: PayRange, supplier: string): string {
  const text = paymentsQuery(range, supplier);
  return text ? `/api/prod/payments?${text}` : "/api/prod/payments";
}

/** "3 payments · EGP 12,340.00". */
export function paymentsSentence(count: number, totalPiastres: number): string {
  return `${plural(count, "payment")} · ${formatEgp(totalPiastres)}`;
}

/** The server takes a photo or a PDF up to 20 MB. */
export const MAX_PHOTO_BYTES = 20 * 1024 * 1024;
export const PHOTO_ACCEPT = "image/*,application/pdf";

/** What the photos that could not be added say, after the payment itself was recorded. */
export function photoFailures(failed: readonly { name: string; why: string }[]): string | null {
  if (failed.length === 0) return null;
  const list = failed.map((one) => `${one.name}${one.why ? ` (${one.why})` : ""}`).join(", ");
  return `${failed.length === 1 ? "A photo" : `${failed.length} photos`} could not be added: ${list}. Add ${failed.length === 1 ? "it" : "them"} with Add photos.`;
}
