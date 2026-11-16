/**
 * What the Incoming screen decides, kept apart from the screen so each rule can be tested on its own:
 * the words on a row, the pill a delivery gets, and which button a person is given.
 *
 * The server works out every figure and state (`services/incoming.py`); nothing here recomputes a count,
 * and no date is compared with today.
 */
import { plural, pieces, shortDay } from "./format";
import type { Powers } from "./logic";
import { SIZES } from "./types";
import type { IncomingArrival, IncomingDelivery, IncomingTotals, Size } from "./types";

// ── The header and the four figures ──────────────────────────────────────────

/** "2,615 pieces still to leave the factory · 300 shipped and waiting for Khazenly's count". */
export function summaryLine(totals: IncomingTotals): string {
  return `${plural(totals.to_come_total, "piece")} still to leave the factory · ${pieces(totals.waiting_for_count)} shipped and waiting for Khazenly's count`;
}

export type Figure = { label: string; value: string; tone: "late" | "warn" | "" };

/** The four figures, left to right. The words carry the meaning; the tone only adds to them. */
export function figures(totals: IncomingTotals): Figure[] {
  return [
    { label: `Arriving in ${totals.this_month.label}`, value: pieces(totals.this_month.pieces), tone: "" },
    { label: `Arriving in ${totals.next_month.label}`, value: pieces(totals.next_month.pieces), tone: "" },
    {
      label: "Waiting for Khazenly's count",
      value: pieces(totals.waiting_for_count),
      tone: totals.waiting_for_count > 0 ? "warn" : "",
    },
    {
      label: "Counts that do not match",
      value: totals.mismatch_pieces > 0 ? plural(totals.mismatch_pieces, "piece") : "None",
      tone: totals.mismatch_pieces > 0 ? "late" : "",
    },
  ];
}

// ── Arrivals ─────────────────────────────────────────────────────────────────

/** "S 148 · M 296 · L 295": only the sizes that are not zero, in the order the screens show them. */
export function sizeLine(counts: Partial<Record<Size, number>>): string {
  return SIZES.filter((size) => (counts[size] ?? 0) > 0)
    .map((size) => `${size} ${pieces(counts[size])}`)
    .join(" · ");
}

/** "Oversized hoodie · Off-white · 685 of 985 still to come". */
export function arrivalTitle(row: IncomingArrival): string {
  const name = `${row.order.style_name} · ${row.order.colour}`;
  const { to_come: left, expected, shipped } = row;
  if (row.kind === "fix") return `${name} · ${plural(left.total, "fix piece")}`;
  if (shipped.total > 0) return `${name} · ${pieces(left.total)} of ${pieces(expected.total)} still to come`;
  if (row.basis === "planned") return `${name} · ${pieces(expected.total)} planned`;
  return `${name} · ${pieces(left.total)} still to come`;
}

/**
 * The sizes still to come on one line, then what is already shipped, and what the numbers are:
 * "S 148 · M 296 · XXL 69 · 300 already shipped". Numbers taken from the cut say so, since the final
 * numbers come after the inspection.
 */
export function arrivalSizes(row: IncomingArrival): string {
  const parts = [sizeLine(row.to_come.sizes)];
  if (row.basis === "cut") parts.push("as cut");
  if (row.shipped.total > 0) parts.push(`${pieces(row.shipped.total)} already shipped`);
  return parts.filter(Boolean).join(" · ");
}

/** "PO-2610-02 · Main factory · arriving as pieces finish". */
export function arrivalOrderLine(row: IncomingArrival): string {
  return [row.order.code, row.factory, row.status_words].filter(Boolean).join(" · ");
}

/** "26 Nov", or "26 Nov · 6 days late". */
export function arrivalDue(row: IncomingArrival): string {
  const day = shortDay(row.due);
  return row.late_days > 0 ? `${day} · ${plural(row.late_days, "day")} late` : day;
}

export const orderAddress = (id: number): string => `/production/orders/${id}`;

/**
 * Where "Record delivery" goes, or `null` when this person may not record or the order's own form would
 * not take a delivery yet. Fix pieces name their kind, so the form opens for them even when finished
 * pieces are still to come on the same order.
 */
export function recordLink(row: IncomingArrival, powers: Powers): string | null {
  if (!powers.canEdit || !row.can_record) return null;
  return `${orderAddress(row.order.id)}?open=${row.kind === "fix" ? "delivery:fix" : "delivery"}`;
}

// ── Deliveries ───────────────────────────────────────────────────────────────

/** "Oversized hoodie · Black · delivery 2", and "· fix pieces" for pieces that came back from fixing. */
export function deliveryTitle(delivery: IncomingDelivery): string {
  const title = `${delivery.order.style_name} · ${delivery.order.colour} · delivery ${delivery.number}`;
  return delivery.kind === "fix" ? `${title} · fix pieces` : title;
}

/** "size M is 1 short", "size S is 2 more than shipped". */
function differenceWords(line: IncomingDelivery["sizes_differ"][number]): string {
  return line.difference < 0
    ? `size ${line.size} is ${pieces(-line.difference)} short`
    : `size ${line.size} is ${pieces(line.difference)} more than shipped`;
}

/** The sizes shipped that Khazenly has not counted, once a count date is in. */
function uncounted(delivery: IncomingDelivery): Size[] {
  return SIZES.filter((size) => (delivery.shipped[size] ?? 0) > 0 && delivery.counted[size] === undefined);
}

/** "11 Nov · factory shipped 446 · Khazenly counted 445 · size M is 1 short". */
export function deliveryLine(delivery: IncomingDelivery): string {
  const parts = [shortDay(delivery.shipped_on), `factory shipped ${pieces(delivery.shipped_total)}`];
  if (delivery.counted_total === null) {
    parts.push("Khazenly's count not entered yet");
  } else {
    parts.push(`Khazenly counted ${pieces(delivery.counted_total)}`);
    if (delivery.state === "waiting_for_count") {
      const left = uncounted(delivery);
      if (left.length) parts.push(`${left.length === 1 ? "size" : "sizes"} ${left.join(", ")} not counted yet`);
    }
  }
  if (delivery.state === "mismatch" || delivery.state === "explained") {
    parts.push(delivery.sizes_differ.map(differenceWords).join(", "));
  }
  return parts.join(" · ");
}

export type Pill = { text: string; tone: "late" | "wait" | "ok" | "" };

/** The state in words: Counts match, Waiting for count, N pieces missing, N more than shipped, Explained. */
export function deliveryPill(delivery: IncomingDelivery): Pill {
  switch (delivery.state) {
    case "match":
      return { text: "Counts match", tone: "ok" };
    case "waiting_for_count":
      return { text: "Waiting for count", tone: "wait" };
    case "explained":
      return { text: "Explained", tone: "" };
    default: {
      const short = plural(delivery.missing, "piece");
      const over = `${pieces(delivery.extra)} more than shipped`;
      if (delivery.missing > 0 && delivery.extra > 0) return { text: `${short} missing, ${over}`, tone: "late" };
      return { text: delivery.extra > 0 ? over : `${short} missing`, tone: "late" };
    }
  }
}

export type DeliveryButton = { label: string; to: string };

/**
 * The one button a delivery may have: the count to enter, or the reason to add. Only for somebody who
 * may record; a delivery that is counted and matches, or explained, has nothing left to do.
 */
export function deliveryButton(delivery: IncomingDelivery, powers: Powers): DeliveryButton | null {
  if (!powers.canEdit) return null;
  const page = orderAddress(delivery.order.id);
  if (delivery.state === "waiting_for_count") {
    return { label: "Enter Khazenly's count", to: `${page}?open=delivery:${delivery.id}` };
  }
  if (delivery.state === "mismatch") return { label: "Add reason", to: `${page}?open=delivery-reason:${delivery.id}` };
  return null;
}
