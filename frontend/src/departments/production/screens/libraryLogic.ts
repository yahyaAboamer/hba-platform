/**
 * The words and checks of the Library (ADR 0087), kept apart so each can be tested on its own. The
 * server adds up the cost of goods; nothing here does sums of money it then sends.
 */
import { formatEgp, parseEgp } from "../../../lib/money";
import { COST_PARTS, blankCost, isBlank } from "./logic";
import type { CostPartKey, CostText } from "./logic";
import { productBody, productProblem } from "./productLogic";
import { matches } from "./search";
import type { LibraryCogs, LibraryItem, LibraryRow, ProductStatus } from "./types";

export const STATUS_WORDS: Record<ProductStatus, string> = { active: "Active", draft: "Draft", archived: "Archived" };

/** What the Library's search looks through. */
export const LIBRARY_SEARCH_HINT = "name, size, SKU, colour code, fabric";

export function libraryMatches(row: LibraryRow, query: string): boolean {
  return matches([row.title, ...row.sizes, ...row.skus, row.colour_code, row.fabric_type], query);
}

/** What HBA has not added to a product yet, in words: "COGS, size chart"; `null` when nothing is missing. */
export function missingWords(row: LibraryRow, withMoney: boolean): string | null {
  const missing: string[] = [];
  if (!row.filled.details) missing.push("details");
  if (withMoney && !row.filled.cogs) missing.push("COGS");
  if (!row.filled.design) missing.push("design");
  if (!row.filled.size_chart) missing.push("size chart");
  return missing.length ? missing.join(", ") : null;
}

/** "5 sizes · XS to XL", "1 size · One size", or "No sizes". */
export function sizesWords(sizes: readonly string[]): string {
  if (sizes.length === 0) return "No sizes";
  if (sizes.length === 1) return `1 size · ${sizes[0]}`;
  return `${sizes.length} sizes · ${sizes[0]} to ${sizes[sizes.length - 1]}`;
}

// ── Details ──────────────────────────────────────────────────────────────────

export type DetailsDraft = { colourCode: string; fabricType: string; decorationType: string; width: string; notes: string };

export const detailsDraft = (item: LibraryItem): DetailsDraft => ({
  colourCode: item.details.colour_code ?? "",
  fabricType: item.details.fabric_type ?? "",
  decorationType: item.details.decoration_type ?? "",
  width: item.details.decoration_width_cm ?? "",
  notes: item.details.notes ?? "",
});

/** The same width rule as an order's Product card. */
export const detailsProblem = (draft: DetailsDraft): string | null => productProblem(draft);

/** What the Edit details panel sends: every field, blank as `null`. */
export function detailsBody(draft: DetailsDraft) {
  return { ...productBody(draft), notes: isBlank(draft.notes) ? null : draft.notes.trim() };
}

// ── COGS ─────────────────────────────────────────────────────────────────────

const cogsKey = (part: CostPartKey) => `${part}_piastres` as const;

/** Piastres as pounds to type: 12500 is "125", 12550 is "125.50"; `null` is blank. */
export function poundsText(piastres: number | null): string {
  if (piastres === null) return "";
  const pounds = Math.trunc(piastres / 100);
  const rest = piastres % 100;
  return rest === 0 ? String(pounds) : `${pounds}.${String(rest).padStart(2, "0")}`;
}

/** The COGS as the five boxes of a form start: blank where a part is not set. */
export function cogsText(cogs: LibraryCogs | undefined): CostText {
  const text = blankCost();
  if (!cogs) return text;
  for (const part of COST_PARTS) text[part] = poundsText(cogs[cogsKey(part)]);
  return text;
}

/** Whether any part of the COGS is set. */
export const hasCogs = (cogs: LibraryCogs | undefined): cogs is LibraryCogs =>
  !!cogs && COST_PARTS.some((part) => cogs[cogsKey(part)] !== null);

/** The first part that is not an amount of pounds, as a sentence; `null` when every part reads. */
export function cogsProblem(text: CostText, labels: Record<CostPartKey, string>): string | null {
  for (const part of COST_PARTS) {
    if (isBlank(text[part])) continue;
    const found = parseEgp(text[part]);
    if (found === null || found < 0) return `Check ${labels[part].toLocaleLowerCase()}: an amount in pounds, like 85 or 85.50.`;
  }
  return null;
}

/** What the COGS panel sends: each part in piastres, blank as `null` (not set, which is not the same as 0). */
export function cogsBody(text: CostText) {
  return Object.fromEntries(
    COST_PARTS.map((part) => [`cogs_${part}_piastres`, isBlank(text[part]) ? null : parseEgp(text[part])]),
  );
}

/** "EGP 0.00" for a set part, "Not set" for one that is not. */
export const partWords = (piastres: number | null): string => (piastres === null ? "Not set" : formatEgp(piastres));
