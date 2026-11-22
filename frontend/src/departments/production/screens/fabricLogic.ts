/**
 * The words and checks of fabric storage (ADR 0089), kept apart so each can be tested on its own.
 * Kilos come from the server as strings with three decimals ("12.500"); nothing here adds up money.
 */
import { isBlank } from "./logic";
import { matches } from "./search";
import type { FabricMove, FabricRow, Kg } from "./types";

/** "12.5 kg", "1,250 kg", "0.125 kg": the server's kilos, without the trailing zeros. */
export function kgWords(kg: Kg | number): string {
  const value = typeof kg === "number" ? kg : Number(kg);
  if (!Number.isFinite(value)) return `${kg} kg`;
  return `${value.toLocaleString("en-GB", { maximumFractionDigits: 3 })} kg`;
}

/** The kilos typed, as a number above 0 with at most three decimals and at most a million; `null` when they are not. */
export function kgOf(text: string): number | null {
  const trimmed = text.trim().replace(",", ".");
  if (!/^\d{1,7}(\.\d{1,3})?$/.test(trimmed)) return null;
  const value = Number(trimmed);
  return value > 0 && value <= 1_000_000 ? value : null;
}

/** Like `kgOf`, but 0 is allowed: what a count of storage may say. */
export function countOf(text: string): number | null {
  if (/^\s*0+([.,]0{0,3})?\s*$/.test(text)) return 0;
  return kgOf(text);
}

export const KG_PROBLEM = "Give the kilos as a number, like 12.5.";

/** What the fabric search looks through. */
export const FABRIC_SEARCH_HINT = "name, type, colour, colour code, supplier";

export const fabricMatches = (row: FabricRow, query: string): boolean =>
  matches([row.name, row.fabric_type, row.colour, row.colour_code, row.supplier?.name], query);

/** "Black · Cotton fleece 320 gsm", or `null` when neither is known. */
export function fabricLine(row: Pick<FabricRow, "colour" | "fabric_type">): string | null {
  const parts = [row.colour, row.fabric_type].filter(Boolean);
  return parts.length ? parts.join(" · ") : null;
}

/** One line of a fabric's history, in words. */
export function moveWords(move: FabricMove): string {
  switch (move.kind) {
    case "purchase":
      return move.purchase ? `Bought from ${move.purchase.supplier.name}: ${move.purchase.item}` : "Bought";
    case "use":
      return move.order ? `Taken by ${move.order.code}${move.returned ? " (given back since)" : ""}` : "Taken by an order";
    case "return":
      return move.order ? `Given back by ${move.order.code}` : "Given back";
    case "count":
      return "Storage counted";
    case "void":
      return move.purchase ? `Purchase voided: ${move.purchase.item}` : "Purchase voided";
  }
}

/** "+12.5 kg" or "−3 kg". */
export function signedKg(kg: Kg): string {
  const value = Number(kg);
  return `${value > 0 ? "+" : "−"}${kgWords(Math.abs(value))}`;
}

// ── A fabric's details ───────────────────────────────────────────────────────

export type FabricDraft = { name: string; fabricType: string; colour: string; colourCode: string; note: string; inStorage: string };

export const blankFabric = (): FabricDraft => ({ name: "", fabricType: "", colour: "", colourCode: "", note: "", inStorage: "" });

export const fabricDraft = (row: FabricRow & { note: string | null }): FabricDraft => ({
  name: row.name,
  fabricType: row.fabric_type ?? "",
  colour: row.colour ?? "",
  colourCode: row.colour_code ?? "",
  note: row.note ?? "",
  inStorage: "",
});

export function fabricProblem(draft: FabricDraft, adding: boolean): string | null {
  if (isBlank(draft.name)) return "Give the fabric a name.";
  if (adding && !isBlank(draft.inStorage) && kgOf(draft.inStorage) === null) return KG_PROBLEM;
  return null;
}

/** What the add or edit panel sends; blank as `null`. The kilos already in storage only when adding. */
export function fabricBody(draft: FabricDraft, adding: boolean) {
  const text = (value: string) => (isBlank(value) ? null : value.trim());
  const body: Record<string, unknown> = {
    name: draft.name.trim(),
    fabric_type: text(draft.fabricType),
    colour: text(draft.colour),
    colour_code: text(draft.colourCode),
    note: text(draft.note),
  };
  if (adding && !isBlank(draft.inStorage)) body.in_storage_kg = kgOf(draft.inStorage);
  return body;
}
