/**
 * What the Suppliers tests share: suppliers and their pages as `GET /api/prod/suppliers` and
 * `GET /api/prod/suppliers/{id}` answer them. Not a test file itself.
 *
 * Money keys are **absent, not null**, for anybody without `production.owner`; `money: false` builds what
 * that person is sent.
 */
import type { AccountLine, PurchaseView, Section, SupplierList, SupplierRow, SupplierView } from "../types";

const MONEY_ROW = ["owed_piastres", "held_piastres"] as const;
const MONEY_PAGE = ["owed_piastres", "held_piastres", "paid_piastres", "paid_year", "has_opening", "account"] as const;
const MONEY_PURCHASE = ["unit_price_piastres", "total_piastres", "deposit_piastres", "void_reason"] as const;

function withoutKeys<T extends object>(value: T, keys: readonly string[]): T {
  const copy = { ...value } as Record<string, unknown>;
  for (const key of keys) delete copy[key];
  return copy as T;
}

export const SECTIONS: Section[] = [
  { id: 6, name: "Manufacturers", position: 1, supplier_count: 1 },
  { id: 7, name: "Fabric", position: 2, supplier_count: 1 },
  { id: 8, name: "Packaging", position: 3, supplier_count: 0 },
];

/** A supplier's line on the list, as the owner sees it; `money: false` is what everybody else gets. */
export function makeSupplierRow(over: Partial<SupplierRow> & { id: string; name: string }, money = true): SupplierRow {
  const row: SupplierRow = {
    code: over.id.toUpperCase(),
    contact_person: null,
    phone: null,
    whatsapp: null,
    city: null,
    notes: null,
    active: true,
    sections: [],
    open_orders: 0,
    open_purchases: 0,
    owed_piastres: 0,
    held_piastres: 0,
    ...over,
  };
  return money ? row : withoutKeys(row, MONEY_ROW);
}

export function makeSupplierList(rows: SupplierRow[], money = true, sections: Section[] = SECTIONS): SupplierList {
  const owed = rows.reduce((sum, row) => sum + Math.max(0, row.owed_piastres ?? 0), 0);
  const list: SupplierList = {
    sections,
    suppliers: rows,
    unsectioned: rows.filter((row) => row.sections.length === 0).length,
    owed_total_piastres: owed,
  };
  return money ? list : withoutKeys(list, ["owed_total_piastres"]);
}

/** Main factory: Manufacturers, one open order, two purchases not in, owing EGP 2,750.00. */
export const factoryRow = (money = true): SupplierRow =>
  makeSupplierRow(
    { id: "fac", name: "Main factory", sections: [{ id: 6, name: "Manufacturers" }], open_orders: 1, open_purchases: 2, owed_piastres: 275000, held_piastres: 345000, city: "Cairo" },
    money,
  );

export function makePurchase(over: Partial<PurchaseView> = {}, money = true): PurchaseView {
  const purchase: PurchaseView = {
    id: 1,
    supplier_id: "fac",
    item: "Heavy fleece, black",
    quantity: "1075",
    unit: "kg",
    part: "fabric",
    order: { id: 2, code: "PO-2611-02", style_name: "Oversized hoodie", colour: "Black", status: "open" },
    bought_on: "2030-11-09",
    expected_on: "2030-11-12",
    received_on: null,
    note: "Pick up from the mill",
    voided: false,
    voided_at: null,
    unit_price_piastres: 16000,
    total_piastres: 17200000,
    deposit_piastres: 4000000,
    void_reason: null,
    ...over,
  };
  return money ? purchase : withoutKeys(purchase, MONEY_PURCHASE);
}

export function makeLine(over: Partial<AccountLine> & { what: string; amount_piastres: number }): AccountLine {
  return {
    id: 1,
    kind: "payment",
    balance_after_piastres: 275000,
    happened_on: "2030-11-12",
    order: null,
    purchase: null,
    method: null,
    payment_kind: null,
    note: null,
    reversal: false,
    reverses_id: null,
    reversed: false,
    reversed_by_id: null,
    not_settled: false,
    receipt: null,
    created_by: "Owner",
    created_at: "2030-11-12T10:00:00Z",
    ...over,
  };
}

/** Newest first: work not yet settled, a payment with a receipt, a reversed correction and its reversal, work, the opening. */
export function factoryAccount(): AccountLine[] {
  return [
    makeLine({ id: null, kind: "work", what: "Work on PO-2611-02 so far, not settled", amount_piastres: 1064900, balance_after_piastres: 1339900, happened_on: null, not_settled: true, order: { id: 2, code: "PO-2611-02" } }),
    makeLine({ id: 6, what: "Weekly payment · InstaPay", amount_piastres: -3000000, balance_after_piastres: 275000, method: "instapay", payment_kind: "weekly", note: "Week 46", receipt: { url: "/api/prod/entries/6/receipt", mime_type: "image/png", size_bytes: 48 } }),
    makeLine({ id: 8, kind: "adjustment", what: "Reversal · Adjustment", amount_piastres: -250000, balance_after_piastres: 3275000, reversal: true, reverses_id: 7, note: "Counted twice" }),
    makeLine({ id: 7, kind: "adjustment", what: "Adjustment", amount_piastres: 250000, balance_after_piastres: 3525000, happened_on: "2030-11-10", reversed: true, reversed_by_id: 8, note: "Missed invoice" }),
    makeLine({ id: 5, kind: "work", what: "Work on PO-2611-01", amount_piastres: 1099400, balance_after_piastres: 3275000, order: { id: 1, code: "PO-2611-01" }, happened_on: "2030-11-08" }),
    makeLine({ id: 2, kind: "opening", what: "Balance brought forward", amount_piastres: 4200000, balance_after_piastres: 4200000, happened_on: "2030-10-06", note: "From the notebook" }),
  ];
}

/** `GET /suppliers/{id}` for Main factory. Money only when `money` (the owner). */
export function makeSupplierPage(over: Partial<SupplierView> = {}, money = true): SupplierView {
  const page: SupplierView = {
    id: "fac",
    code: "FAC",
    name: "Main factory",
    contact_person: "Karim",
    phone: "0100 111 2222",
    whatsapp: null,
    city: "Cairo",
    notes: "Pays by InstaPay",
    active: true,
    sections: [{ id: 6, name: "Manufacturers" }],
    open_orders: 1,
    open_purchases: 2,
    purchases: [
      makePurchase({ id: 3, item: "Wrong thread", quantity: "12.5", unit: "kg", part: "accessories", order: null, expected_on: null, note: null, voided: true, voided_at: "2030-11-12T09:00:00Z", unit_price_piastres: 4000, total_piastres: 50000, deposit_piastres: 0, void_reason: "Wrong supplier" }),
      makePurchase({ id: 2, item: "Zips", quantity: "1000", unit: "piece", part: "accessories", expected_on: "2030-11-19", note: null, unit_price_piastres: 300, total_piastres: 300000, deposit_piastres: 0 }),
      makePurchase({ id: 1 }),
    ],
    orders: [
      { id: 2, code: "PO-2611-02", style_name: "Oversized hoodie", colour: "Black", status: "open", role: "factory", stage: { key: "warehouse", label: "Warehouse receipt", position: 9 } },
      { id: 1, code: "PO-2611-01", style_name: "Oversized hoodie", colour: "Black", status: "closed", role: "factory", stage: null },
    ],
    owed_piastres: 1339900,
    held_piastres: 345000,
    paid_piastres: 3000000,
    paid_year: 2030,
    has_opening: true,
    account: factoryAccount(),
    ...over,
  };
  if (money) return page;
  const viewer = withoutKeys(page, MONEY_PAGE);
  viewer.purchases = viewer.purchases.map((purchase) => withoutKeys(purchase, MONEY_PURCHASE));
  return viewer;
}

/** Every key that carries money, anywhere in a value (to say nothing of it reaches the page of somebody else). */
export function moneyKeysIn(value: unknown, found: string[] = []): string[] {
  if (Array.isArray(value)) value.forEach((item) => moneyKeysIn(item, found));
  else if (value && typeof value === "object") {
    for (const [key, inner] of Object.entries(value)) {
      if (key.endsWith("_piastres")) found.push(key);
      moneyKeysIn(inner, found);
    }
  }
  return found;
}
