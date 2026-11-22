/**
 * What the Billing screen decides (ADR 0089), kept apart so each rule can be tested on its own: the
 * list's address, the search, the words, and the fabric-storage choice on a purchase. The server lists
 * and totals; nothing here adds money up.
 */
import { formatEgp } from "../../../lib/money";
import { plural } from "./format";
import type { PayRange } from "./paymentLogic";
import type { Bill, ChoiceFabric, FabricRow, PurchasePart, PurchaseUnit } from "./types";

/** The part chips: "" is all of them. */
export const BILL_PARTS: readonly { value: "" | PurchasePart; label: string }[] = [
  { value: "", label: "All" },
  { value: "fabric", label: "Fabric" },
  { value: "printing", label: "Printing" },
  { value: "accessories", label: "Accessories" },
  { value: "packaging", label: "Packaging" },
  { value: "other", label: "Other" },
];

export const BILL_SEARCH_HINT = "the item, the supplier, the order code, the note and the fabric name";

/** `from=…&to=…&supplier=…&part=…`, leaving out what is not set. */
export function billingQuery(range: PayRange, supplier: string, part: string): string {
  const query = new URLSearchParams();
  if (range.from) query.set("from", range.from);
  if (range.to) query.set("to", range.to);
  if (supplier) query.set("supplier", supplier);
  if (part) query.set("part", part);
  return query.toString();
}

/** Whether a bill matches what was typed: every word must be found in one of the places it is kept. */
export function billMatches(bill: Bill, text: string): boolean {
  const words = text.toLowerCase().split(/\s+/).filter(Boolean);
  if (words.length === 0) return true;
  const hay = [bill.item, bill.supplier.name, bill.order?.code, bill.note, bill.fabric?.name]
    .filter(Boolean)
    .join(" ")
    .toLowerCase();
  return words.every((word) => hay.includes(word));
}

const UNIT_WORDS: Record<PurchaseUnit, string> = { kg: "kg", m: "m", piece: "pieces" };

/** "12.500" becomes "12.5": the server writes three decimals, a person reads what matters. */
export function quantityWords(quantity: string): string {
  return quantity.includes(".") ? quantity.replace(/0+$/, "").replace(/\.$/, "") : quantity;
}

/** "12.5 kg at EGP 85.00". */
export function quantityLine(bill: Pick<Bill, "quantity" | "unit" | "unit_price_piastres">): string {
  return `${quantityWords(bill.quantity)} ${UNIT_WORDS[bill.unit]} at ${formatEgp(bill.unit_price_piastres)}`;
}

/** The small line under the item: the order it is for and where the fabric went. */
export function billDetail(bill: Pick<Bill, "order" | "fabric">): string {
  const parts: string[] = [];
  if (bill.order) parts.push(`order ${bill.order.code}`);
  if (bill.fabric) parts.push(`into storage: ${bill.fabric.name}`);
  return parts.join(" · ");
}

/** "4 bills · EGP 12,340.00": the ones not voided, as the server totals them. */
export function billingSentence(bills: readonly Bill[], totalPiastres: number): string {
  return `${plural(bills.filter((bill) => !bill.voided).length, "bill")} · ${formatEgp(totalPiastres)}`;
}

/** What one bill is called for a screen reader. */
export const billName = (bill: Pick<Bill, "item" | "supplier">): string => `${bill.item} from ${bill.supplier.name}`;

// ── Fabric storage on a purchase ─────────────────────────────────────────────

/** `pick` is "" (not into storage), "new" (a new fabric) or a fabric's id. */
export type FabricChoice = { pick: string; name: string; colour: string };

export const NO_FABRIC: FabricChoice = { pick: "", name: "", colour: "" };

/** Storage is offered only for fabric bought by the kilo. */
export const offersStorage = (part: PurchasePart, unit: PurchaseUnit): boolean => part === "fabric" && unit === "kg";

/** The fabrics worth choosing: the active ones. */
export const storageChoices = (fabrics: readonly FabricRow[]): ChoiceFabric[] =>
  fabrics.filter((row) => row.active).map((row) => ({ id: row.id, name: row.name, colour: row.colour, in_stock_kg: row.in_stock_kg }));

export function fabricLabel(fabric: Pick<ChoiceFabric, "name" | "colour" | "in_stock_kg">): string {
  return `${fabric.name}${fabric.colour ? ` · ${fabric.colour}` : ""} · ${quantityWords(fabric.in_stock_kg)} kg in storage`;
}

/** The refusal for a new fabric with no name; `null` when it reads. */
export function fabricProblem(part: PurchasePart, unit: PurchaseUnit, choice: FabricChoice): string | null {
  if (!offersStorage(part, unit)) return null;
  return choice.pick === "new" && !choice.name.trim() ? "Give the new fabric a name, or choose Not into storage." : null;
}

/** What is added to the purchase body: nothing unless storage was chosen and the part and unit allow it. */
export function fabricBody(part: PurchasePart, unit: PurchaseUnit, choice: FabricChoice): Record<string, unknown> {
  if (!offersStorage(part, unit) || choice.pick === "") return {};
  if (choice.pick === "new") {
    const colour = choice.colour.trim();
    return { new_fabric: { name: choice.name.trim(), ...(colour ? { colour } : {}) } };
  }
  return { fabric_id: Number(choice.pick) };
}
