/**
 * The fields an order is made of, shared by the New order screen and the
 * owner's Edit order panel: style, colour, factory, who buys the fabric,
 * pieces per size, the target date, printing and the target cost per piece.
 */
import { useId } from "react";

import { formatEgp } from "../../../lib/money";
import { cairoToday } from "./format";
import { COST_LABELS, COST_PARTS, blankCost, blankCounts, costTotal, countsFrom, isBlank, partPiastres, sizesBody, totalOf, unreadable, NOT_WHOLE } from "./logic";
import type { Counts, CostText } from "./logic";
import type { Choices, FabricBuyer, OrderView, Printing } from "./types";
import { SIZES } from "./types";
import { DateBox, SizeInputs, TextBox } from "./ui";

/** The product select's value for "a style that is not on Shopify yet". */
export const NEW_STYLE = "__new";

export type OrderDraft = {
  /** A Shopify product id, `NEW_STYLE`, or `""` for not chosen yet. */
  productId: string;
  styleName: string;
  colour: string;
  factoryId: string;
  fabricBy: FabricBuyer;
  printing: Printing;
  printSupplierId: string;
  planned: Counts;
  target: CostText;
  targetDate: string;
  notes: string;
};

export const emptyDraft = (): OrderDraft => ({
  productId: "",
  styleName: "",
  colour: "",
  factoryId: "",
  fabricBy: "hba",
  printing: "factory",
  printSupplierId: "",
  planned: blankCounts(),
  target: blankCost(),
  targetDate: "",
  notes: "",
});

/** An existing order's fields, as the Edit panel starts from them (money in pounds). */
export function draftFromOrder(order: OrderView): OrderDraft {
  const target = blankCost();
  for (const part of order.cost?.parts ?? []) {
    const pounds = Math.trunc(part.target_piastres / 100);
    const piastres = part.target_piastres % 100;
    target[part.part] = piastres === 0 ? String(pounds) : `${pounds}.${String(piastres).padStart(2, "0")}`;
  }
  return {
    productId: order.shopify_product_id ?? NEW_STYLE,
    styleName: order.style_name,
    colour: order.colour,
    factoryId: order.factory.id,
    fabricBy: order.fabric_bought_by,
    printing: order.printing,
    printSupplierId: order.print_supplier?.id ?? "",
    planned: countsFrom(Object.fromEntries(order.sizes.map((line) => [line.size, line.planned || null]))),
    target,
    targetDate: order.target_date,
    notes: order.notes ?? "",
  };
}

/** The first thing wrong with the fields, or `null`. `creating` also refuses a target date in the past. */
export function draftProblem(draft: OrderDraft, creating: boolean, lockPlanned = false): string | null {
  if (isBlank(draft.styleName)) return "Choose the style, or type a new name.";
  if (isBlank(draft.colour)) return "Give the colour.";
  if (!draft.factoryId) return "Choose the factory.";
  if (draft.printing === "outside" && !draft.printSupplierId) return "Choose the print house.";
  if (!lockPlanned) {
    if (unreadable(draft.planned).length) return NOT_WHOLE;
    if (totalOf(draft.planned) <= 0) return "Plan at least one piece.";
  }
  if (isBlank(draft.targetDate)) return "Give the target date.";
  if (creating && draft.targetDate < cairoToday()) return "The target date can't be in the past.";
  if (costTotal(draft.target) === null) return "Check the target cost: use amounts like 165 or 165.50.";
  return null;
}

/** The request body's shared part. */
export function draftBody(draft: OrderDraft, lockPlanned = false) {
  const piastres = Object.fromEntries(COST_PARTS.map((part) => [`target_${part}_piastres`, partPiastres(draft.target[part]) ?? 0]));
  const planned = sizesBody(draft.planned, () => false);
  for (const size of SIZES) if (planned[size] === 0) delete planned[size];
  return {
    style_name: draft.styleName.trim(),
    colour: draft.colour.trim(),
    shopify_product_id: draft.productId && draft.productId !== NEW_STYLE ? draft.productId : null,
    factory_id: draft.factoryId,
    fabric_bought_by: draft.fabricBy,
    printing: draft.printing,
    print_supplier_id: draft.printing === "outside" ? draft.printSupplierId : null,
    target_date: draft.targetDate,
    notes: draft.notes.trim() || null,
    ...(lockPlanned ? {} : { planned }),
    ...piastres,
  };
}

/** What the server says when who buys the fabric, or printing, is changed after cutting. */
export const FABRIC_LOCKED = "Who buys the fabric cannot change after cutting. Reopen cutting first.";
export const PRINTING_LOCKED = "Printing cannot change after cutting. Reopen cutting first.";

/** The supplier an order already has, which may since have been deactivated. */
type HeldSupplier = { id: string; name: string | null } | null | undefined;

/**
 * The supplier options: the active ones, plus the one the order already has even when it is no
 * longer active (the server lets it stay), so a stale supplier does not hide the select's value.
 */
function SupplierOptions({ suppliers, held }: { suppliers: Choices["suppliers"]; held: HeldSupplier }) {
  return (
    <>
      {suppliers.map((supplier) => (
        <option key={supplier.id} value={supplier.id}>
          {supplier.name}
          {supplier.category ? ` · ${supplier.category}` : ""}
        </option>
      ))}
      {held && !suppliers.some((supplier) => supplier.id === held.id) && (
        <option value={held.id}>{held.name ?? held.id} (no longer active)</option>
      )}
    </>
  );
}

export function OrderFields({
  draft,
  onChange,
  choices,
  lockPlanned,
  lockBuyerAndPrinting,
  held,
}: {
  draft: OrderDraft;
  onChange: (draft: OrderDraft) => void;
  choices: Choices;
  /** Cutting is done: the plan stays as it was. */
  lockPlanned?: boolean;
  /** Cutting is done: who buys the fabric and how it is printed stay as they were (shown, not editable). */
  lockBuyerAndPrinting?: boolean;
  /** The factory and print house the order has now, kept in the lists even if no longer active. */
  held?: { factory: HeldSupplier; printSupplier: HeldSupplier };
}) {
  const id = useId();
  const set = <K extends keyof OrderDraft>(key: K, value: OrderDraft[K]) => onChange({ ...draft, [key]: value });
  const total = totalOf(draft.planned);
  const perPiece = costTotal(draft.target);
  const known = choices.products.some((product) => product.id === draft.productId);

  return (
    <>
      <div className="prod-field">
        <label className="field__label" htmlFor={`${id}-style`}>
          Style, from the product list
        </label>
        <select
          id={`${id}-style`}
          className="input"
          value={draft.productId}
          onChange={(event) => {
            const picked = event.target.value;
            const product = choices.products.find((candidate) => candidate.id === picked);
            onChange({
              ...draft,
              productId: picked,
              styleName: product ? product.title : picked === NEW_STYLE ? (draft.productId === NEW_STYLE ? draft.styleName : "") : "",
            });
          }}
        >
          <option value="">Choose a style…</option>
          {choices.products.map((product) => (
            <option key={product.id} value={product.id}>
              {product.title}
            </option>
          ))}
          {draft.productId && draft.productId !== NEW_STYLE && !known && <option value={draft.productId}>{draft.styleName}</option>}
          <option value={NEW_STYLE}>A new style, not on Shopify yet</option>
        </select>
      </div>
      {draft.productId === NEW_STYLE && (
        <TextBox label="Style name" value={draft.styleName} onChange={(value) => set("styleName", value)} max={180} />
      )}
      <TextBox label="Colour" value={draft.colour} onChange={(value) => set("colour", value)} max={80} />

      <div className="prod-field">
        <label className="field__label" htmlFor={`${id}-factory`}>
          Factory
        </label>
        <select id={`${id}-factory`} className="input" value={draft.factoryId} onChange={(event) => set("factoryId", event.target.value)}>
          <option value="">Choose the factory…</option>
          <SupplierOptions suppliers={choices.suppliers} held={held?.factory} />
        </select>
      </div>
      <div className="prod-field">
        <label className="field__label" htmlFor={`${id}-buyer`}>
          Who buys the fabric
        </label>
        <select
          id={`${id}-buyer`}
          className="input"
          value={draft.fabricBy}
          disabled={lockBuyerAndPrinting}
          aria-describedby={lockBuyerAndPrinting ? `${id}-buyer-locked` : undefined}
          onChange={(event) => set("fabricBy", event.target.value as FabricBuyer)}
        >
          <option value="hba">HBA</option>
          <option value="factory">The factory</option>
        </select>
        {lockBuyerAndPrinting && (
          <span id={`${id}-buyer-locked`} className="field__hint">
            {FABRIC_LOCKED}
          </span>
        )}
      </div>

      <SizeInputs
        legend="Pieces per size"
        counts={draft.planned}
        onChange={(size, value) => set("planned", { ...draft.planned, [size]: value })}
        total={lockPlanned ? "Cutting is done, so the plan stays as it was." : `Total ${total.toLocaleString("en-GB")} pieces`}
        disabled={lockPlanned}
      />

      <DateBox label="Target date" value={draft.targetDate} onChange={(value) => set("targetDate", value)} />
      <div className="prod-field">
        <label className="field__label" htmlFor={`${id}-printing`}>
          Printing
        </label>
        <select
          id={`${id}-printing`}
          className="input"
          value={draft.printing}
          disabled={lockBuyerAndPrinting}
          aria-describedby={lockBuyerAndPrinting ? `${id}-printing-locked` : undefined}
          onChange={(event) => set("printing", event.target.value as Printing)}
        >
          <option value="factory">At the factory</option>
          <option value="outside">Outside print house</option>
          <option value="none">No printing</option>
        </select>
        {lockBuyerAndPrinting && (
          <span id={`${id}-printing-locked`} className="field__hint">
            {PRINTING_LOCKED}
          </span>
        )}
      </div>
      {draft.printing === "outside" && (
        <div className="prod-field">
          <label className="field__label" htmlFor={`${id}-printer`}>
            Print house
          </label>
          <select
            id={`${id}-printer`}
            className="input"
            value={draft.printSupplierId}
            disabled={lockBuyerAndPrinting}
            aria-describedby={lockBuyerAndPrinting ? `${id}-printing-locked` : undefined}
            onChange={(event) => set("printSupplierId", event.target.value)}
          >
            <option value="">Choose the print house…</option>
            <SupplierOptions suppliers={choices.suppliers} held={held?.printSupplier} />
          </select>
        </div>
      )}

      <fieldset className="prod-fieldset prod-wide">
        <legend className="field__label">Target cost per piece, EGP</legend>
        <div className="prod-sizes prod-sizes--five">
          {COST_PARTS.map((part) => (
            <div key={part} className="prod-size">
              <label htmlFor={`${id}-cost-${part}`}>{part === "packaging" ? "Packaging" : COST_LABELS[part]}</label>
              <input
                id={`${id}-cost-${part}`}
                className="input"
                inputMode="decimal"
                autoComplete="off"
                aria-label={`${part === "packaging" ? "Packaging" : COST_LABELS[part]}, target cost`}
                value={draft.target[part]}
                onChange={(event) => set("target", { ...draft.target, [part]: event.target.value })}
              />
            </div>
          ))}
        </div>
        <p className="prod-total" aria-live="polite">
          {perPiece === null
            ? "Check the amounts: use figures like 165 or 165.50."
            : `Total ${formatEgp(perPiece)} per piece · ${formatEgp(perPiece * total)} for the order`}
        </p>
      </fieldset>

      <TextBox label="Notes, optional" value={draft.notes} onChange={(value) => set("notes", value)} area wide max={2000} />
    </>
  );
}

