/**
 * The words of an order's Product card and the checks of its "Edit details" panel, kept apart so each
 * can be tested on its own. The server computes the cost of goods; nothing here does sums of money.
 */
import { formatEgp } from "../../../lib/money";
import { pieces } from "./format";
import { isBlank } from "./logic";
import type { Cogs, ProductDetails } from "./types";

/** The words for an empty detail. */
export const NOT_SET = "Not set";

/** The code itself when it is a `#rrggbb` colour, for the small swatch beside it; otherwise `null`. */
export function hexOf(code: string | null): string | null {
  if (!code) return null;
  const trimmed = code.trim();
  return /^#[0-9a-f]{6}$/i.test(trimmed) ? trimmed : null;
}

/** "DTF print · 12.5 cm wide", "DTF print", "12.5 cm wide", or `null` when neither is set. */
export function decorationWords(product: Pick<ProductDetails, "decoration_type" | "decoration_width_cm">): string | null {
  const parts: string[] = [];
  if (product.decoration_type) parts.push(product.decoration_type);
  if (product.decoration_width_cm) parts.push(`${product.decoration_width_cm} cm wide`);
  return parts.length ? parts.join(" · ") : null;
}

const BASIS_WORDS: Record<Cogs["pieces_basis"], string> = { passed: "passed", cut: "cut", planned: "planned" };

/** "EGP 185.00 a piece · EGP 88,800.00 for 480 passed pieces". */
export function cogsWords(cogs: Cogs): string {
  const noun = cogs.pieces === 1 ? "piece" : "pieces";
  return `${formatEgp(cogs.per_piece_piastres)} a piece · ${formatEgp(cogs.total_piastres)} for ${pieces(cogs.pieces)} ${BASIS_WORDS[cogs.pieces_basis]} ${noun}`;
}

/** The roles a supplier has on the product, in words: "Printing, Accessories". */
export const rolesWords = (roles: readonly string[]): string => roles.join(", ");

export type ProductDraft = { colourCode: string; fabricType: string; decorationType: string; width: string };

export const productDraft = (product: ProductDetails): ProductDraft => ({
  colourCode: product.colour_code ?? "",
  fabricType: product.fabric_type ?? "",
  decorationType: product.decoration_type ?? "",
  width: product.decoration_width_cm ?? "",
});

/** The width typed, as a number with at most one decimal, above 0 and at most 999.9; `null` when blank. */
function widthOf(text: string): number | null | undefined {
  if (isBlank(text)) return null;
  const trimmed = text.trim().replace(",", ".");
  if (!/^\d{1,3}(\.\d)?$/.test(trimmed)) return undefined;
  const value = Number(trimmed);
  return value > 0 && value <= 999.9 ? value : undefined;
}

/** The first thing wrong with the details, or `null`. */
export function productProblem(draft: ProductDraft): string | null {
  if (widthOf(draft.width) === undefined) return "Check the width: a number of cm above 0, like 12 or 12.5.";
  return null;
}

/** The PATCH body: blank text is sent as `null` (the server stores it so). */
export function productBody(draft: ProductDraft) {
  const text = (value: string) => (isBlank(value) ? null : value.trim());
  return {
    colour_code: text(draft.colourCode),
    fabric_type: text(draft.fabricType),
    decoration_type: text(draft.decorationType),
    decoration_width_cm: widthOf(draft.width) ?? null,
  };
}
