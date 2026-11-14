import { describe, expect, it } from "vitest";

import {
  afterLineSentence,
  afterPaymentSentence,
  canHaveReceipt,
  canReverse,
  chipCount,
  hasMoney,
  lineProblem,
  listSentence,
  openWords,
  orderPieces,
  owedWords,
  panelFromSupplierOpen,
  parseQuantity,
  paymentProblem,
  perPiece,
  perPieceSentence,
  purchaseBody,
  purchaseDates,
  purchaseProblem,
  purchaseSentence,
  purchaseSums,
  purchaseTotal,
  quantityString,
  quantityWords,
  removable,
  signedPiastres,
  visibleSuppliers,
} from "../supplierLogic";
import type { PurchaseDraft } from "../supplierLogic";
import type { AccountLine } from "../types";
import { makeLine, makePurchase, makeSupplierPage, makeSupplierRow, SECTIONS } from "./supplierFixtures";
import { makeRow } from "./fixtures";

const TODAY = "2030-11-13";

const draft = (over: Partial<PurchaseDraft> = {}): PurchaseDraft => ({
  supplierId: "fac",
  orderId: "",
  item: "Heavy fleece, black",
  part: "fabric",
  quantity: "1,075",
  unit: "kg",
  price: "160",
  boughtOn: TODAY,
  expectedOn: "",
  deposit: "",
  depositMethod: "bank_transfer",
  note: "",
  ...over,
});

describe("A purchase's total, as the server works it out", () => {
  it("reads a quantity as exact thousandths, with at most three decimals", () => {
    expect(parseQuantity("1,075")).toBe(1075000n);
    expect(parseQuantity("12.5")).toBe(12500n);
    expect(parseQuantity(" .25 ")).toBe(250n);
    expect(parseQuantity("1.005")).toBe(1005n);
    expect(parseQuantity("1.0005")).toBeNull();
    expect(parseQuantity("")).toBeNull();
    expect(parseQuantity("1e3")).toBeNull();
    expect(parseQuantity("-2")).toBeNull();
    expect(quantityString(1075000n)).toBe("1075");
    expect(quantityString(12500n)).toBe("12.5");
    expect(quantityString(1005n)).toBe("1.005");
  });

  it("multiplies quantity by unit price and rounds half up to a whole piastre", () => {
    expect(purchaseTotal(1075000n, 16000)).toBe(17_200_000); // 1,075 kg at EGP 160
    expect(purchaseTotal(12500n, 4000)).toBe(50_000);
    // 1.005 at EGP 1.00 is 100.5 piastres: half up is 101, not the 100 that banker's rounding or a float gives.
    expect(purchaseTotal(1005n, 100)).toBe(101);
    // 0.333 at EGP 1.00 is 33.3 piastres: down.
    expect(purchaseTotal(333n, 100)).toBe(33);
    // 0.0005 would be a half piastre; the quantity has three decimals, so the smallest is 0.001 x 500 = 0.5.
    expect(purchaseTotal(1n, 500)).toBe(1);
    expect(purchaseTotal(1n, 499)).toBe(0);
  });

  it("stays in whole numbers up to the largest the server allows", () => {
    // 1,000,000 units at EGP 999,999.99 is 99,999,999,000,000 piastres.
    expect(purchaseTotal(1_000_000_000n, 99_999_999)).toBe(99_999_999_000_000);
    expect(purchaseSums({ quantity: "0.1", price: "0.30", deposit: "" }).total).toBe(3);
  });

  it("works the figures the form shows from what is typed", () => {
    expect(purchaseSums({ quantity: "1,075", price: "160", deposit: "40,000" })).toEqual({
      quantity: 1075000n,
      price: 16000,
      total: 17_200_000,
      deposit: 4_000_000,
    });
    expect(purchaseSums({ quantity: "", price: "160", deposit: "" }).total).toBeNull();
    expect(purchaseSums({ quantity: "5", price: "abc", deposit: "" }).total).toBeNull();
  });

  it("says the total, and what stays owed after the deposit", () => {
    const sums = purchaseSums({ quantity: "1,075", price: "160", deposit: "40,000" });
    expect(purchaseSentence(sums)).toBe(
      "Total EGP 172,000.00. After the deposit, EGP 132,000.00 of it is still owed, and stays on this supplier's balance until you pay it.",
    );
    expect(purchaseSentence(purchaseSums({ quantity: "1,075", price: "160", deposit: "" }))).toBe(
      "Total EGP 172,000.00. All of it goes on this supplier's balance until you pay it.",
    );
    expect(purchaseSentence(purchaseSums({ quantity: "1", price: "10", deposit: "10" }))).toContain("nothing is left owed");
    expect(purchaseSentence(purchaseSums({ quantity: "", price: "", deposit: "" }))).toBeNull();
  });

  it("works the per-piece figure of the order the way the server does, over pieces cut else planned", () => {
    expect(perPiece(17_200_000, 972)).toBe(17_695);
    expect(perPiece(300_000, 972)).toBe(309);
    expect(perPiece(1, 2)).toBe(1); // half a piastre rounds up
    expect(perPiece(100, 0)).toBeNull();
    expect(orderPieces({ cut_total: null, planned_total: 1000 })).toEqual({ pieces: 1000, basis: "planned" });
    expect(orderPieces({ cut_total: 972, planned_total: 1000 })).toEqual({ pieces: 972, basis: "cut" });
    const order = makeRow({ id: 2, style_name: "Oversized hoodie", planned_total: 1000, cut_total: null });
    expect(perPieceSentence(17_200_000, "fabric", order)).toBe(
      "For PO-2611-02 that adds EGP 172.00 per piece to its fabric cost, over 1,000 planned pieces.",
    );
    expect(perPieceSentence(17_200_000, "other", order)).toBeNull();
    expect(perPieceSentence(17_200_000, "fabric", undefined)).toBeNull();
  });
});

describe("What a purchase needs before it is sent", () => {
  it("passes a good one and builds the body: pounds in, piastres out, no total", () => {
    expect(purchaseProblem(draft(), TODAY)).toBeNull();
    expect(purchaseBody(draft({ orderId: "2", expectedOn: "2030-11-20", deposit: "40,000", note: " Pick up " }))).toEqual({
      item: "Heavy fleece, black",
      quantity: "1075",
      unit: "kg",
      unit_price_piastres: 16000,
      part: "fabric",
      order_id: 2,
      bought_on: TODAY,
      expected_on: "2030-11-20",
      note: "Pick up",
      deposit_piastres: 4_000_000,
      deposit_method: "bank_transfer",
    });
    // No deposit: neither key is sent.
    const plain = purchaseBody(draft());
    expect(plain).not.toHaveProperty("deposit_piastres");
    expect(plain).not.toHaveProperty("deposit_method");
    expect(plain).not.toHaveProperty("total_piastres");
    // A deposit typed as 0 is no deposit.
    expect(purchaseBody(draft({ deposit: "0" }))).not.toHaveProperty("deposit_piastres");
  });

  it("refuses each thing the server refuses, in words, before sending", () => {
    expect(purchaseProblem(draft({ supplierId: "" }), TODAY)).toBe("Choose the supplier.");
    expect(purchaseProblem(draft({ item: "  " }), TODAY)).toBe("Say what was bought.");
    expect(purchaseProblem(draft({ quantity: "abc" }), TODAY)).toContain("at most three decimal places");
    expect(purchaseProblem(draft({ quantity: "0" }), TODAY)).toBe("The quantity must be more than 0.");
    expect(purchaseProblem(draft({ quantity: "1,000,001" }), TODAY)).toBe("That quantity is too large. Check the number.");
    expect(purchaseProblem(draft({ price: "" }), TODAY)).toContain("Give the price per kilogram");
    expect(purchaseProblem(draft({ unit: "m", price: "" }), TODAY)).toContain("per metre");
    expect(purchaseProblem(draft({ price: "0" }), TODAY)).toBe("The price must be more than 0.");
    expect(purchaseProblem(draft({ quantity: "0.001", price: "0.10" }), TODAY)).toBe(
      "That comes to less than a piastre. Check the quantity and the price.",
    );
    expect(purchaseProblem(draft({ boughtOn: "" }), TODAY)).toBe("Give the date it was bought.");
    expect(purchaseProblem(draft({ boughtOn: "2030-11-14" }), TODAY)).toBe("The purchase date can't be in the future.");
  });

  it("holds the deposit to the total", () => {
    expect(purchaseProblem(draft({ deposit: "172,000" }), TODAY)).toBeNull(); // all of it is allowed
    expect(purchaseProblem(draft({ deposit: "172,000.01" }), TODAY)).toBe("The deposit can't be more than the total.");
    expect(purchaseProblem(draft({ deposit: "-5" }), TODAY)).toBe("The deposit must be more than 0, or left empty.");
    expect(purchaseProblem(draft({ deposit: "lots" }), TODAY)).toContain("Check the deposit");
  });
});

describe("A payment, and what the balance will be after it", () => {
  it("says what you will owe, that nothing is owed, or how much the factory is overpaid", () => {
    expect(afterPaymentSentence(275_000, 100_000, "Main factory")).toBe("After this payment you will owe EGP 1,750.00.");
    expect(afterPaymentSentence(275_000, 275_000, "Main factory")).toBe("After this payment you will owe nothing.");
    expect(afterPaymentSentence(275_000, 3_000_000, "Main factory")).toBe(
      "After this payment Main factory will be overpaid by EGP 27,250.00, which comes off what you owe them next.",
    );
    // Already overpaid: a further payment deepens it.
    expect(afterPaymentSentence(-50_000, 10_000, "Main factory")).toContain("overpaid by EGP 600.00");
    expect(afterPaymentSentence(275_000, null, "Main factory")).toBeNull();
    expect(afterPaymentSentence(275_000, 0, "Main factory")).toBeNull();
  });

  it("checks an amount above zero, a date not in the future, in pounds", () => {
    const pay = { amount: "30,000", date: TODAY, method: "cash", kind: "weekly", note: "" } as const;
    expect(paymentProblem(pay, TODAY)).toBeNull();
    expect(paymentProblem({ ...pay, amount: "" }, TODAY)).toBe("Give the amount.");
    expect(paymentProblem({ ...pay, amount: "0" }, TODAY)).toBe("The amount must be more than 0.");
    expect(paymentProblem({ ...pay, amount: "-5" }, TODAY)).toBe("The amount must be more than 0.");
    expect(paymentProblem({ ...pay, amount: "12.345" }, TODAY)).toContain("Check the amount");
    expect(paymentProblem({ ...pay, date: "" }, TODAY)).toBe("Give the date it was paid.");
    expect(paymentProblem({ ...pay, date: "2030-11-14" }, TODAY)).toBe("The payment date can't be in the future.");
  });

  it("keeps the direction of an opening balance or a correction out of a minus sign", () => {
    expect(signedPiastres({ amount: "2,500", direction: "more" })).toBe(250_000);
    expect(signedPiastres({ amount: "2,500", direction: "less" })).toBe(-250_000);
    expect(signedPiastres({ amount: "", direction: "more" })).toBeNull();
    expect(signedPiastres({ amount: "-5", direction: "more" })).toBeNull();
    expect(afterLineSentence(275_000, 250_000)).toBe("After this you will owe EGP 5,250.00.");
    expect(afterLineSentence(275_000, -275_000)).toBe("After this you will owe nothing.");
    expect(afterLineSentence(275_000, -300_000)).toBe("After this you will have overpaid by EGP 250.00.");
    expect(afterLineSentence(275_000, null)).toBeNull();
  });

  it("requires the note on a correction and a date not in the future", () => {
    const line = { amount: "100", direction: "more", date: TODAY, note: "" } as const;
    expect(lineProblem(line, TODAY, false)).toBeNull();
    expect(lineProblem(line, TODAY, true)).toBe("Say why: the note is kept with the line.");
    expect(lineProblem({ ...line, note: "Missed invoice" }, TODAY, true)).toBeNull();
    expect(lineProblem({ ...line, amount: "0" }, TODAY, false)).toContain("more than 0");
    expect(lineProblem({ ...line, date: "2030-12-01" }, TODAY, false)).toBe("The date can't be in the future.");
  });
});

describe("The words of the list and the account", () => {
  it("says what is owed in words, never by a sign alone", () => {
    expect(owedWords(275_000)).toBe("You owe EGP 2,750.00");
    expect(owedWords(-7_374_000)).toBe("Overpaid EGP 73,740.00");
    expect(owedWords(0)).toBe("Nothing owed");
    expect(listSentence(14, 14_315_000)).toBe("14 suppliers · you owe EGP 143,150.00 in total");
    expect(listSentence(1, 0)).toBe("1 supplier · nothing owed");
    expect(listSentence(3, undefined)).toBe("3 suppliers");
    expect(listSentence(0, undefined)).toBe("No suppliers");
  });

  it("says what is open, and a quantity with its unit", () => {
    expect(openWords({ open_orders: 1, open_purchases: 2 })).toBe("1 order open · 2 purchases not received");
    expect(openWords({ open_orders: 0, open_purchases: 0 })).toBe("nothing open");
    expect(quantityWords("1075", "kg")).toBe("1,075 kg");
    expect(quantityWords("12.5", "m")).toBe("12.5 m");
    expect(quantityWords("1", "piece")).toBe("1 piece");
    expect(quantityWords("1000", "piece")).toBe("1,000 pieces");
  });

  it("puts a purchase's dates in words, and says how late it is", () => {
    expect(purchaseDates(makePurchase(), TODAY)).toEqual({ text: "Bought 9 Nov · expected 12 Nov, 1 day late · not received yet", late: true });
    expect(purchaseDates(makePurchase({ expected_on: "2030-11-19" }), TODAY)).toEqual({ text: "Bought 9 Nov · expected 19 Nov · not received yet", late: false });
    expect(purchaseDates(makePurchase({ received_on: "2030-11-12" }), TODAY).text).toBe("Bought 9 Nov · received 12 Nov · expected 12 Nov");
    expect(purchaseDates(makePurchase({ expected_on: null }), TODAY).text).toBe("Bought 9 Nov · no date expected · not received yet");
  });

  it("offers Reverse only on a payment, a balance or a correction that still stands", () => {
    const line = (over: Partial<AccountLine>) => makeLine({ what: "x", amount_piastres: 1, ...over });
    expect(canReverse(line({ kind: "payment" }))).toBe(true);
    expect(canReverse(line({ kind: "opening" }))).toBe(true);
    expect(canReverse(line({ kind: "adjustment" }))).toBe(true);
    expect(canReverse(line({ kind: "work" }))).toBe(false);
    expect(canReverse(line({ kind: "purchase" }))).toBe(false);
    expect(canReverse(line({ kind: "payment", reversed: true }))).toBe(false);
    expect(canReverse(line({ kind: "payment", reversal: true }))).toBe(false);
    expect(canReverse(line({ kind: "work", id: null, not_settled: true }))).toBe(false);
    expect(canHaveReceipt(line({ kind: "payment" }))).toBe(true);
    expect(canHaveReceipt(line({ kind: "adjustment" }))).toBe(false);
    expect(canHaveReceipt(line({ kind: "payment", reversed: true }))).toBe(false);
  });
});

describe("The list, by section", () => {
  const rows = [
    makeSupplierRow({ id: "fac", name: "Main factory", sections: [{ id: 6, name: "Manufacturers" }] }),
    makeSupplierRow({ id: "fab", name: "Fabric A", sections: [{ id: 7, name: "Fabric" }, { id: 6, name: "Manufacturers" }] }),
    makeSupplierRow({ id: "old", name: "Closed mill", active: false, sections: [{ id: 7, name: "Fabric" }] }),
    makeSupplierRow({ id: "x", name: "Nobody's" }),
  ];

  it("leaves out inactive suppliers unless asked, and counts what it shows", () => {
    expect(visibleSuppliers(rows, "all", false).map((row) => row.id)).toEqual(["fac", "fab", "x"]);
    expect(visibleSuppliers(rows, "all", true)).toHaveLength(4);
    expect(visibleSuppliers(rows, 7, false).map((row) => row.id)).toEqual(["fab"]);
    expect(visibleSuppliers(rows, 7, true).map((row) => row.id)).toEqual(["fab", "old"]);
    expect(visibleSuppliers(rows, "none", false).map((row) => row.id)).toEqual(["x"]);
    expect(chipCount(rows, 6, false)).toBe(2);
  });

  it("lets a section be removed only when no supplier is in it", () => {
    expect(removable(SECTIONS[0])).toBe(false);
    expect(removable(SECTIONS[2])).toBe(true);
  });
});

describe("What a page carries, and `?open=`", () => {
  const owner = { canEdit: true, isOwner: true, canManage: true };
  const viewer = { canEdit: false, isOwner: false, canManage: false };

  it("has money only when its keys are there", () => {
    expect(hasMoney(makeSupplierPage())).toBe(true);
    expect(hasMoney(makeSupplierPage({}, false))).toBe(false);
  });

  it("opens Mark received for a purchase that is still to arrive, for somebody who may mark it", () => {
    const page = makeSupplierPage();
    expect(panelFromSupplierOpen("purchase:1", page, owner)).toEqual({ kind: "receive", id: 1 });
    expect(panelFromSupplierOpen("purchase:1", page, viewer)).toBeNull();
    // Voided, unknown, or something else entirely.
    expect(panelFromSupplierOpen("purchase:3", page, owner)).toBeNull();
    expect(panelFromSupplierOpen("purchase:99", page, owner)).toBeNull();
    expect(panelFromSupplierOpen("settle", page, owner)).toBeNull();
    expect(panelFromSupplierOpen(null, page, owner)).toBeNull();
    const received = makeSupplierPage({ purchases: [makePurchase({ id: 1, received_on: "2030-11-12" })] });
    expect(panelFromSupplierOpen("purchase:1", received, owner)).toBeNull();
  });
});
