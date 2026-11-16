/**
 * The arithmetic and the words of the Suppliers screens, kept apart from the screens so each rule can be
 * tested on its own.
 *
 * **Money never becomes a binary float here.** A quantity is read as exact thousandths (a `bigint`), a
 * price and every total as whole piastres, and the total of a purchase is worked out the way the server
 * does it (`services/suppliers.py::purchase_total`): quantity times unit price, rounded half up to a whole
 * piastre. Every rule is one the server enforces, said before anything is sent and in the server's own
 * words where it has them; the server still decides, and its `detail` is shown as it is.
 */
import { formatEgp, parseEgp } from "../../../lib/money";
import { addDays, daysBetween, plural, shortDay } from "./format";
import { isBlank } from "./logic";
import type { Powers } from "./logic";
import type {
  AccountLine,
  OrderRow,
  PayKind,
  PayMethod,
  PurchasePart,
  PurchaseUnit,
  PurchaseView,
  Section,
  SupplierRatings,
  SupplierRow,
  SupplierView,
} from "./types";

export type SupplierPowers = Powers & { canManage: boolean };

/** The server refuses a money entry dated further back than this (a typo guard in the year). */
export const MAX_DAYS_BACK = 366;

/** The oldest day a money entry may be dated, for the date box's `min`. */
export const oldestDay = (today: string): string => addDays(today, -MAX_DAYS_BACK);

/** The refusal for a day that is too far back, in the server's words, or `null`. */
const tooOld = (day: string, today: string, what: string): string | null =>
  day < oldestDay(today) ? `${what} can't be more than a year ago. Check the date.` : null;

// ── Words ────────────────────────────────────────────────────────────────────

export const METHODS: readonly { value: PayMethod; label: string }[] = [
  { value: "bank_transfer", label: "Bank transfer" },
  { value: "cash", label: "Cash" },
  { value: "instapay", label: "InstaPay" },
  { value: "wallet", label: "Mobile wallet" },
  { value: "cheque", label: "Cheque" },
];
export const METHOD_WORDS = Object.fromEntries(METHODS.map((method) => [method.value, method.label])) as Record<PayMethod, string>;

export const PAY_KINDS: readonly { value: PayKind; label: string }[] = [
  { value: "weekly", label: "Weekly payment" },
  { value: "deposit", label: "Deposit" },
  { value: "final", label: "Final payment" },
];

export const UNITS: readonly { value: PurchaseUnit; label: string }[] = [
  { value: "kg", label: "Kilograms" },
  { value: "m", label: "Metres" },
  { value: "piece", label: "Pieces" },
];
/** What the price is "per": the form's label follows the unit. */
export const UNIT_PER: Record<PurchaseUnit, string> = { kg: "kilogram", m: "metre", piece: "piece" };

export const PARTS: readonly { value: PurchasePart; label: string }[] = [
  { value: "fabric", label: "Fabric" },
  { value: "printing", label: "Printing" },
  { value: "accessories", label: "Accessories" },
  { value: "packaging", label: "Special packaging" },
  { value: "other", label: "Other" },
];
export const PART_WORDS = Object.fromEntries(PARTS.map((part) => [part.value, part.label])) as Record<PurchasePart, string>;

/** `You owe EGP 2,750.00`, `Overpaid EGP 73,740.00`, `Nothing owed`: in words, never a sign alone. */
export function owedWords(piastres: number): string {
  if (piastres > 0) return `You owe ${formatEgp(piastres)}`;
  if (piastres < 0) return `Overpaid ${formatEgp(-piastres)}`;
  return "Nothing owed";
}

/** The same for a figure that already sits under a heading ("You owe now"). */
export function owedFigure(piastres: number): string {
  if (piastres > 0) return formatEgp(piastres);
  if (piastres < 0) return `Overpaid ${formatEgp(-piastres)}`;
  return "Nothing owed";
}

/** The list's header sentence: "14 suppliers · you owe EGP 143,150.00 in total". */
export function listSentence(active: number, owedTotal: number | undefined): string {
  const count = active === 0 ? "No suppliers" : plural(active, "supplier");
  if (owedTotal === undefined) return count;
  return `${count} · ${owedTotal > 0 ? `you owe ${formatEgp(owedTotal)} in total` : "nothing owed"}`;
}

export const sectionNames = (sections: readonly { name: string }[]): string =>
  sections.length ? sections.map((section) => section.name).join(", ") : "No section";

/** "1 order open · 2 purchases not received", or "nothing open". */
export function openWords(row: Pick<SupplierRow, "open_orders" | "open_purchases">): string {
  const parts: string[] = [];
  if (row.open_orders > 0) parts.push(`${plural(row.open_orders, "order")} open`);
  if (row.open_purchases > 0) parts.push(`${plural(row.open_purchases, "purchase")} not received`);
  return parts.length ? parts.join(" · ") : "nothing open";
}

/** A quantity string for display: `1,075 kg`, `12.5 m`, `1 piece`, `1,000 pieces`. */
export function quantityWords(quantity: string, unit: PurchaseUnit): string {
  const [whole = "0", fraction] = quantity.split(".");
  const grouped = whole.replace(/\B(?=(\d{3})+(?!\d))/g, ",");
  const shown = fraction ? `${grouped}.${fraction}` : grouped;
  if (unit === "piece") return `${shown} ${quantity === "1" ? "piece" : "pieces"}`;
  return `${shown} ${unit}`;
}

/** A date with its year when that is not this year's: the account reaches back past New Year. */
export function accountDay(day: string | null, today: string): string {
  if (!day) return "—";
  return day.slice(0, 4) === today.slice(0, 4) ? shortDay(day) : `${shortDay(day)} ${day.slice(0, 4)}`;
}

// ── The list ─────────────────────────────────────────────────────────────────

/** A filter: every supplier, those in a section, or those in none. */
export type SectionFilter = "all" | "none" | number;

export function visibleSuppliers(rows: readonly SupplierRow[], filter: SectionFilter, showInactive: boolean): SupplierRow[] {
  return rows.filter((row) => {
    if (!row.active && !showInactive) return false;
    if (filter === "all") return true;
    if (filter === "none") return row.sections.length === 0;
    return row.sections.some((section) => section.id === filter);
  });
}

/** The count on a chip: what the list would show under it. */
export const chipCount = (rows: readonly SupplierRow[], filter: SectionFilter, showInactive: boolean): number =>
  visibleSuppliers(rows, filter, showInactive).length;

/** A section can be removed only while nobody is in it (the server's rule; inactive suppliers count). */
export const removable = (section: Section): boolean => section.supplier_count === 0;

// ── Quantity, price and total of a purchase ──────────────────────────────────

const MAX_QUANTITY_THOUSANDTHS = 1_000_000_000n;
const MAX_UNIT_PIASTRES = 100_000_000;
const MAX_LINE_PIASTRES = 10_000_000_000;

/** A typed quantity as exact thousandths, or `null` when it is not a number with at most three decimals. */
export function parseQuantity(text: string): bigint | null {
  const cleaned = text.trim().replace(/[,\s]/g, "");
  if (cleaned === "" || cleaned === "." || !/^\d*(\.\d{0,3})?$/.test(cleaned)) return null;
  const [whole = "", fraction = ""] = cleaned.split(".");
  return BigInt(whole || "0") * 1000n + BigInt(fraction.padEnd(3, "0"));
}

/** Thousandths as the plain decimal string the server takes: `1075`, `12.5`. */
export function quantityString(thousandths: bigint): string {
  const whole = thousandths / 1000n;
  const fraction = (thousandths % 1000n).toString().padStart(3, "0").replace(/0+$/, "");
  return fraction ? `${whole}.${fraction}` : `${whole}`;
}

/**
 * Quantity times unit price, rounded half up to a whole piastre, in whole numbers only
 * (the server's `purchase_total`). 1.005 of something at EGP 1.00 is 100.5 piastres: 101.
 */
export function purchaseTotal(thousandths: bigint, unitPricePiastres: number): number {
  return Number((thousandths * BigInt(unitPricePiastres) + 500n) / 1000n);
}

/** A total over some pieces, rounded half up to a whole piastre (the server's `per_piece`). */
export function perPiece(totalPiastres: number, pieces: number): number | null {
  if (pieces <= 0) return null;
  return Math.floor((2 * totalPiastres + pieces) / (2 * pieces));
}

/** The pieces a purchase's per-piece figure is over: those cut once cutting is done, else those planned. */
export function orderPieces(order: Pick<OrderRow, "cut_total" | "planned_total">): { pieces: number; basis: "cut" | "planned" } {
  return order.cut_total !== null ? { pieces: order.cut_total, basis: "cut" } : { pieces: order.planned_total, basis: "planned" };
}

export type PurchaseDraft = {
  supplierId: string;
  orderId: string;
  item: string;
  part: PurchasePart;
  quantity: string;
  unit: PurchaseUnit;
  price: string;
  boughtOn: string;
  expectedOn: string;
  deposit: string;
  depositMethod: PayMethod;
  note: string;
};

export type PurchaseSums = {
  /** `null` while the quantity is blank or unreadable. */
  quantity: bigint | null;
  price: number | null;
  total: number | null;
  /** `null` while blank; 0 is "none". */
  deposit: number | null;
};

/** The figures the form can already work out from what is typed. */
export function purchaseSums(draft: Pick<PurchaseDraft, "quantity" | "price" | "deposit">): PurchaseSums {
  const quantity = parseQuantity(draft.quantity);
  const typedPrice = isBlank(draft.price) ? null : parseEgp(draft.price);
  const price = typedPrice !== null && typedPrice > 0 ? typedPrice : null;
  const total = quantity !== null && quantity > 0n && price !== null ? purchaseTotal(quantity, price) : null;
  const deposit = isBlank(draft.deposit) ? null : parseEgp(draft.deposit);
  return { quantity, price, total, deposit };
}

/** The first thing wrong with a purchase, or `null`. `today` is Cairo's date. */
export function purchaseProblem(draft: PurchaseDraft, today: string): string | null {
  if (!draft.supplierId) return "Choose the supplier.";
  if (isBlank(draft.item)) return "Say what was bought.";
  const sums = purchaseSums(draft);
  if (sums.quantity === null) return "Give the quantity as a number, with at most three decimal places.";
  if (sums.quantity <= 0n) return "The quantity must be more than 0.";
  if (sums.quantity > MAX_QUANTITY_THOUSANDTHS) return "That quantity is too large. Check the number.";
  const typed = isBlank(draft.price) ? null : parseEgp(draft.price);
  if (typed === null) return `Give the price per ${UNIT_PER[draft.unit]}, in figures like 160 or 160.50.`;
  if (typed <= 0) return "The price must be more than 0.";
  if (typed > MAX_UNIT_PIASTRES) return "The price per unit is too large. Check the number.";
  if (sums.total === null || sums.total < 1) return "That comes to less than a piastre. Check the quantity and the price.";
  if (sums.total > MAX_LINE_PIASTRES) return "That total is too large. Check the quantity and the price.";
  if (isBlank(draft.boughtOn)) return "Give the date it was bought.";
  if (draft.boughtOn > today) return "The purchase date can't be in the future.";
  const old = tooOld(draft.boughtOn, today, "The purchase date");
  if (old) return old;
  if (draft.expectedOn && draft.expectedOn < draft.boughtOn) return "The expected date can't be before the day it was bought.";
  if (sums.deposit !== null) {
    if (sums.deposit < 0) return "The deposit must be more than 0, or left empty.";
    if (sums.deposit > sums.total) return "The deposit can't be more than the total.";
  } else if (!isBlank(draft.deposit)) {
    return "Check the deposit: use figures like 40,000 or 40,000.50.";
  }
  return null;
}

/** What `POST /suppliers/{id}/purchases` takes: pounds in, piastres out; the total is never sent. */
export function purchaseBody(draft: PurchaseDraft) {
  const sums = purchaseSums(draft);
  const deposit = sums.deposit !== null && sums.deposit > 0 ? sums.deposit : null;
  return {
    item: draft.item.trim(),
    quantity: quantityString(sums.quantity ?? 0n),
    unit: draft.unit,
    unit_price_piastres: sums.price ?? 0,
    part: draft.part,
    order_id: draft.orderId ? Number(draft.orderId) : null,
    bought_on: draft.boughtOn,
    expected_on: draft.expectedOn || null,
    note: draft.note.trim() || null,
    ...(deposit !== null ? { deposit_piastres: deposit, deposit_method: draft.depositMethod } : {}),
  };
}

/** The running sentence under the purchase form: the total, and what stays owed after the deposit. */
export function purchaseSentence(sums: PurchaseSums): string | null {
  if (sums.total === null) return null;
  const total = `Total ${formatEgp(sums.total)}.`;
  const deposit = sums.deposit !== null && sums.deposit > 0 && sums.deposit <= sums.total ? sums.deposit : null;
  if (deposit === null) return `${total} All of it goes on this supplier's balance until you pay it.`;
  const left = sums.total - deposit;
  return left === 0
    ? `${total} The deposit pays all of it, so nothing is left owed.`
    : `${total} After the deposit, ${formatEgp(left)} of it is still owed, and stays on this supplier's balance until you pay it.`;
}

/** What this one purchase adds to the order's cost per piece, when an order and a part are picked. */
export function perPieceSentence(total: number | null, part: PurchasePart, order: OrderRow | undefined): string | null {
  if (total === null || !order || part === "other") return null;
  const { pieces, basis } = orderPieces(order);
  const each = perPiece(total, pieces);
  if (each === null) return null;
  const label = PART_WORDS[part].toLowerCase();
  return `For ${order.code} that adds ${formatEgp(each)} per piece to its ${label} cost, over ${pieces.toLocaleString("en-GB")} ${basis} pieces.`;
}

// ── Payments, the balance brought forward and corrections ────────────────────

/**
 * What the balance will be after a payment, in words: what is still owed, nothing, or an overpayment.
 * `null` while the amount is not a figure above zero.
 */
export function afterPaymentSentence(owed: number, amount: number | null, name: string): string | null {
  if (amount === null || amount <= 0) return null;
  const after = owed - amount;
  if (after > 0) return `After this payment you will owe ${formatEgp(after)}.`;
  if (after === 0) return "After this payment you will owe nothing.";
  return `After this payment ${name} will be overpaid by ${formatEgp(-after)}, which comes off what you owe them next.`;
}

/** The same after a signed line (a balance brought forward is added to what is owed, a correction too). */
export function afterLineSentence(owed: number, signed: number | null): string | null {
  if (signed === null || signed === 0) return null;
  const after = owed + signed;
  if (after > 0) return `After this you will owe ${formatEgp(after)}.`;
  if (after === 0) return "After this you will owe nothing.";
  return `After this you will have overpaid by ${formatEgp(-after)}.`;
}

export type PaymentDraft = { amount: string; date: string; method: PayMethod; kind: PayKind; note: string };

/** An amount typed in pounds: whole piastres above zero, or `null`. */
export function poundsToPiastres(text: string): number | null {
  if (isBlank(text)) return null;
  const found = parseEgp(text);
  return found !== null && found > 0 ? found : null;
}

export function paymentProblem(draft: PaymentDraft, today: string): string | null {
  if (isBlank(draft.amount)) return "Give the amount.";
  const typed = parseEgp(draft.amount);
  if (typed === null) return "Check the amount: use figures like 30,000 or 30,000.50.";
  if (typed <= 0) return "The amount must be more than 0.";
  if (typed > MAX_LINE_PIASTRES) return "The amount is too large. Check the number.";
  if (isBlank(draft.date)) return "Give the date it was paid.";
  if (draft.date > today) return "The payment date can't be in the future.";
  return tooOld(draft.date, today, "The payment date");
}

/** Who owes whom on a balance brought forward or a correction. */
export type Direction = "more" | "less";

export type LineDraft = { amount: string; direction: Direction; date: string; note: string };

/** The amount as the account keeps it: positive when HBA owes more, negative when it owes less. */
export function signedPiastres(draft: Pick<LineDraft, "amount" | "direction">): number | null {
  const found = poundsToPiastres(draft.amount);
  if (found === null) return null;
  return draft.direction === "more" ? found : -found;
}

export function lineProblem(draft: LineDraft, today: string, noteRequired: boolean): string | null {
  if (isBlank(draft.amount)) return "Give the amount.";
  const typed = parseEgp(draft.amount);
  if (typed === null) return "Check the amount: use figures like 42,000 or 42,000.50.";
  if (typed <= 0) return "The amount must be more than 0; say below whether it adds to or takes off what you owe.";
  if (typed > MAX_LINE_PIASTRES) return "The amount is too large. Check the number.";
  if (isBlank(draft.date)) return "Give the date.";
  if (draft.date > today) return "The date can't be in the future.";
  const old = tooOld(draft.date, today, "The date");
  if (old) return old;
  if (noteRequired && isBlank(draft.note)) return "Say why: the note is kept with the line.";
  return null;
}

/** "Adds to what you owe" / "Takes off what you owe", for an account line's amount. */
export const directionWords = (piastres: number): string => (piastres > 0 ? "adds to what you owe" : "takes off what you owe");

/** The balance column: what is owed after the line, or an overpayment, in words. */
export function balanceAfterWords(piastres: number): string {
  if (piastres > 0) return formatEgp(piastres);
  if (piastres < 0) return `Overpaid ${formatEgp(-piastres)}`;
  return "Nothing owed";
}

// ── What can be done to a line, a purchase ───────────────────────────────────

/** Payments, a balance brought forward and corrections can be reversed; work, purchases and reversals cannot. */
export const canReverse = (line: AccountLine): boolean =>
  line.id !== null &&
  !line.not_settled &&
  !line.reversed &&
  !line.reversal &&
  (line.kind === "payment" || line.kind === "opening" || line.kind === "adjustment");

/** A receipt goes on a payment that still stands. */
export const canHaveReceipt = (line: AccountLine): boolean =>
  line.id !== null && line.kind === "payment" && !line.reversal && !line.reversed;

/** The reversing line of a struck-through one, for its reason. */
export function reversalOf(line: AccountLine, account: readonly AccountLine[]): AccountLine | undefined {
  return line.reversed_by_id === null ? undefined : account.find((other) => other.id === line.reversed_by_id);
}

/** Whether the supplier's page carries money (the keys are there only for the owner). */
export const hasMoney = (supplier: Pick<SupplierView, "owed_piastres">): boolean => supplier.owed_piastres !== undefined;

/** The dates of a purchase in words: "Bought 9 Nov · expected 12 Nov, 3 days late · not received yet". */
export function purchaseDates(purchase: PurchaseView, today: string): { text: string; late: boolean } {
  const parts = [`Bought ${shortDay(purchase.bought_on)}`];
  let late = false;
  if (purchase.received_on) {
    parts.push(`received ${shortDay(purchase.received_on)}`);
    if (purchase.expected_on) parts.push(`expected ${shortDay(purchase.expected_on)}`);
  } else if (purchase.voided) {
    if (purchase.expected_on) parts.push(`expected ${shortDay(purchase.expected_on)}`);
  } else if (purchase.expected_on) {
    const days = daysBetween(purchase.expected_on, today);
    late = days > 0;
    parts.push(`expected ${shortDay(purchase.expected_on)}${late ? `, ${plural(days, "day")} late` : ""}`, "not received yet");
  } else {
    parts.push("no date expected", "not received yet");
  }
  return { text: parts.join(" · "), late };
}

/** The purchase's price in words, from its own figures: "1,075 kg at EGP 160.00 a kilogram". */
export function priceWords(purchase: PurchaseView): string | null {
  if (purchase.unit_price_piastres === undefined) return null;
  return `${formatEgp(purchase.unit_price_piastres)} per ${UNIT_PER[purchase.unit]}`;
}

// ── The supplier's page: its panels, and `?open=` ────────────────────────────

export type SupplierPanel =
  | { kind: "payment" }
  | { kind: "purchase" }
  | { kind: "opening" }
  | { kind: "adjustment" }
  | { kind: "edit" }
  | { kind: "receive"; id: number }
  | { kind: "expected"; id: number }
  | { kind: "void"; id: number }
  | { kind: "reverse"; entry: number };

export function supplierPanelKey(panel: SupplierPanel): string {
  switch (panel.kind) {
    case "receive":
    case "expected":
    case "void":
      return `${panel.kind}:${panel.id}`;
    case "reverse":
      return `reverse:${panel.entry}`;
    default:
      return panel.kind;
  }
}

/**
 * The panel a Tasks button asked the page to open (`?open=purchase:<id>`): that purchase's "Mark received",
 * or `null` when nothing should open (an unknown value, a purchase that is gone, voided or already
 * received, or somebody who may not mark it). The server decides again on save.
 */
export function panelFromSupplierOpen(open: string | null, supplier: SupplierView, powers: Powers): SupplierPanel | null {
  if (!open) return null;
  const [kind, argument] = open.split(":") as [string, string | undefined];
  if (kind !== "purchase" || !powers.canEdit) return null;
  const purchase = supplier.purchases.find((candidate) => String(candidate.id) === argument);
  if (!purchase || purchase.voided || purchase.received_on) return null;
  return { kind: "receive", id: purchase.id };
}

// ── Voiding a purchase that has a deposit ────────────────────────────────────

/**
 * What the account will show after voiding a purchase with a deposit, for each answer; `null` until one is
 * chosen. (Built as recommended on 15 November 2026, awaiting the owner's confirmation.)
 */
export function voidSentence(returned: boolean | null, deposit: number, name: string): string | null {
  if (returned === null) return null;
  if (returned) return "The purchase and the deposit are both reversed, so the account shows neither of them any more.";
  return `Only the purchase is reversed. The ${formatEgp(deposit)} deposit stays on the account as credit with ${name}: it comes off what you owe them next, and the account reads Overpaid if nothing else is owed.`;
}

// ── Ratings and the record (batch 6a) ────────────────────────────────────────

/** One average or one star count with its decimal: `4.0 ★`. */
const starWords = (value: number, decimals: number): string => `${value.toFixed(decimals)} ★`;

/** `Quality 4.0 ★ · Timing 2.5 ★ · Dealing 4.5 ★`, averages to one decimal. */
export const averageWords = (ratings: Pick<SupplierRatings, "quality" | "timing" | "dealing">): string =>
  `Quality ${starWords(ratings.quality, 1)} · Timing ${starWords(ratings.timing, 1)} · Dealing ${starWords(ratings.dealing, 1)}`;

/** One order's own stars: `Quality 4 ★ · Timing 3 ★ · Dealing 5 ★`. */
export const starsWords = (rating: Pick<SupplierRatings, "quality" | "timing" | "dealing">): string =>
  `Quality ${starWords(rating.quality, 0)} · Timing ${starWords(rating.timing, 0)} · Dealing ${starWords(rating.dealing, 0)}`;

/** "usually on time", "usually 5 days late"; `null` while it is not known. */
export function usualWords(days: number | null | undefined): string | null {
  if (days === null || days === undefined) return null;
  return days > 0 ? `usually ${plural(days, "day")} late` : "usually on time";
}

/** The list's line under a supplier: the averages and the usual lateness, or "Not rated yet". */
export function ratingLine(row: Pick<SupplierRow, "ratings" | "usual_lateness_days">): string {
  const usual = usualWords(row.usual_lateness_days);
  const parts = [row.ratings ? averageWords(row.ratings) : "Not rated yet"];
  if (usual) parts.push(usual);
  return parts.join(" · ");
}

/** The supplier page's fourth figure: "5 days", "On time", or "Not known yet", and whether it is a bad one. */
export function usualFigure(days: number | null | undefined): { text: string; late: boolean } {
  if (days === null || days === undefined) return { text: "Not known yet", late: false };
  return days > 0 ? { text: plural(days, "day"), late: true } : { text: "On time", late: false };
}

/** An order's own lateness for a supplier: "6 days late", "on time", or nothing while it is not known. */
export function latenessWords(days: number | null | undefined): { text: string; late: boolean } | null {
  if (days === null || days === undefined) return null;
  return days > 0 ? { text: `${plural(days, "day")} late`, late: true } : { text: "on time", late: false };
}

export const RATING_ROLE_WORDS = { factory: "Factory", print: "Printing", materials: "Materials" } as const;
