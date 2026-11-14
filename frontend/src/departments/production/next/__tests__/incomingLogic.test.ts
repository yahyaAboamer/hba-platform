import { describe, expect, it } from "vitest";

import { arrivalDue, arrivalSizes, arrivalTitle, deliveryButton, deliveryPill, figures, recordLink, sizeLine, summaryLine } from "../incomingLogic";
import { panelFromOpen } from "../logic";
import type { Powers } from "../logic";
import type { Delivery, IncomingDelivery } from "../types";
import { counts, makeArrival, makeIncoming, makeIncomingDelivery, makeOrder } from "./fixtures";

const OWNER: Powers = { canEdit: true, isOwner: true };
const QC: Powers = { canEdit: true, isOwner: false };
const VIEWER: Powers = { canEdit: false, isOwner: false };

describe("The words on an arrival", () => {
  it("lists only the sizes that are not zero, in the screens' order", () => {
    expect(sizeLine({ XS: 0, S: 148, M: 296, L: 0, XXL: 69 })).toBe("S 148 · M 296 · XXL 69");
    expect(sizeLine({})).toBe("");
    expect(sizeLine({ XL: 1234 })).toBe("XL 1,234");
  });

  it("titles pieces by what is left and what the order was counted from", () => {
    const planned = makeArrival({ expected: counts({ S: 800 }), to_come: counts({ S: 800 }) });
    expect(arrivalTitle(planned)).toBe("Oversized hoodie · Black · 800 planned");
    const part = makeArrival({ basis: "cut", expected: counts({ S: 985 }), shipped: counts({ S: 300 }), to_come: counts({ S: 685 }) });
    expect(arrivalTitle(part)).toBe("Oversized hoodie · Black · 685 of 985 still to come");
    const whole = makeArrival({ basis: "passed", expected: counts({ S: 926 }), to_come: counts({ S: 926 }) });
    expect(arrivalTitle(whole)).toBe("Oversized hoodie · Black · 926 still to come");
    const fix = makeArrival({ kind: "fix", basis: null, expected: counts({ S: 1 }), to_come: counts({ S: 1 }) });
    expect(arrivalTitle(fix)).toBe("Oversized hoodie · Black · 1 fix piece");
  });

  it("says the numbers were taken from the cut, and what has already left", () => {
    expect(arrivalSizes(makeArrival())).toBe("S 8 · M 12");
    const cut = makeArrival({ basis: "cut", shipped: counts({ S: 300 }), to_come: counts({ M: 12 }) });
    expect(arrivalSizes(cut)).toBe("M 12 · as cut · 300 already shipped");
  });

  it("writes the date, and how late only when it is late", () => {
    expect(arrivalDue(makeArrival({ due: "2030-11-26" }))).toBe("26 Nov");
    expect(arrivalDue(makeArrival({ due: "2030-11-26", late_days: 1 }))).toBe("26 Nov · 1 day late");
    expect(arrivalDue(makeArrival({ due: "2030-11-26", late_days: 6 }))).toBe("26 Nov · 6 days late");
  });

  it("offers Record delivery only to somebody who may record, and only when the order would take one", () => {
    const ready = makeArrival({ can_record: true });
    expect(recordLink(ready, QC)).toBe("/production/next/orders/1?open=delivery");
    expect(recordLink(ready, OWNER)).toBe("/production/next/orders/1?open=delivery");
    expect(recordLink(ready, VIEWER)).toBeNull();
    expect(recordLink(makeArrival({ can_record: false }), OWNER)).toBeNull();
    expect(recordLink(makeArrival({ kind: "fix", can_record: true }), QC)).toBe("/production/next/orders/1?open=delivery:fix");
  });
});

describe("The header and the four figures", () => {
  it("says how much is still to leave the factory and what is waiting for a count", () => {
    const data = makeIncoming([makeArrival()], []);
    expect(summaryLine(data.totals)).toBe("20 pieces still to leave the factory · 0 shipped and waiting for Khazenly's count");
    expect(summaryLine({ ...data.totals, to_come_total: 1 })).toContain("1 piece still");
  });

  it("names the months and tones only what is owed", () => {
    const data = makeIncoming([makeArrival()], []);
    expect(figures(data.totals).map((figure) => [figure.label, figure.value, figure.tone])).toEqual([
      ["Arriving in November", "20", ""],
      ["Arriving in December", "0", ""],
      ["Waiting for Khazenly's count", "0", ""],
      ["Counts that do not match", "None", ""],
    ]);
    const owed = figures({ ...data.totals, waiting_for_count: 300, mismatch_pieces: 2 });
    expect([owed[2].tone, owed[3].tone, owed[3].value]).toEqual(["warn", "late", "2 pieces"]);
  });
});

describe("A delivery's pill and button", () => {
  const pill = (over: Partial<IncomingDelivery>) => deliveryPill(makeIncomingDelivery(over)).text;

  it("says each state in words", () => {
    expect(pill({})).toBe("Counts match");
    expect(pill({ state: "waiting_for_count" })).toBe("Waiting for count");
    expect(pill({ state: "explained", missing: 1 })).toBe("Explained");
    expect(pill({ state: "mismatch", missing: 1 })).toBe("1 piece missing");
    expect(pill({ state: "mismatch", missing: 3 })).toBe("3 pieces missing");
    expect(pill({ state: "mismatch", extra: 2 })).toBe("2 more than shipped");
    expect(pill({ state: "mismatch", missing: 1, extra: 2 })).toBe("1 piece missing, 2 more than shipped");
  });

  it("gives the count to enter or the reason to add, and nothing else", () => {
    const waiting = makeIncomingDelivery({ id: 7, state: "waiting_for_count" });
    const mismatch = makeIncomingDelivery({ id: 8, state: "mismatch", missing: 1 });
    expect(deliveryButton(waiting, QC)).toEqual({ label: "Enter Khazenly's count", to: "/production/next/orders/1?open=delivery:7" });
    expect(deliveryButton(mismatch, QC)).toEqual({ label: "Add reason", to: "/production/next/orders/1?open=delivery-reason:8" });
    expect(deliveryButton(makeIncomingDelivery({ state: "explained" }), OWNER)).toBeNull();
    expect(deliveryButton(makeIncomingDelivery(), OWNER)).toBeNull();
    expect(deliveryButton(waiting, VIEWER)).toBeNull();
    expect(deliveryButton(mismatch, VIEWER)).toBeNull();
  });
});

describe("The order page opens what Incoming asks for", () => {
  const delivery = (id: number, kind: "finished" | "fix"): Delivery => ({
    id, number: id, kind, shipped_on: "2030-11-01", counted_on: null, mismatch_reason: null, sizes: [],
    shipped_total: 10, counted_total: null, waiting_for_count: true, mismatch: false, needs_reason: false,
  });
  const both = makeOrder("warehouse", {
    deliveries: [delivery(7, "finished")],
    sizes: [{ passed: 10 }, { passed: 20 }],
    extra: { fix_not_returned: 4 },
  });

  it("opens a new fix delivery when fix pieces are asked for, even with finished pieces still to come", () => {
    expect(panelFromOpen("delivery", both, QC)).toEqual({ kind: "delivery", id: null, deliveryKind: "finished" });
    expect(panelFromOpen("delivery:fix", both, QC)).toEqual({ kind: "delivery", id: null, deliveryKind: "fix" });
    expect(panelFromOpen("delivery:finished", both, QC)).toEqual({ kind: "delivery", id: null, deliveryKind: "finished" });
  });

  it("opens nothing for a kind with nothing left, a closed order or somebody who cannot record", () => {
    const shipped = makeOrder("warehouse", { sizes: [{ passed: 10, shipped: 10 }, { passed: 20, shipped: 20 }], extra: { fix_not_returned: 0 } });
    expect(panelFromOpen("delivery:fix", shipped, QC)).toBeNull();
    expect(panelFromOpen("delivery:finished", shipped, QC)).toBeNull();
    expect(panelFromOpen("delivery:fix", both, VIEWER)).toBeNull();
    expect(panelFromOpen("delivery:fix", { ...both, status: "closed" }, QC)).toBeNull();
  });

  it("still opens a delivery by its number, for its count or its reason", () => {
    expect(panelFromOpen("delivery:7", both, QC)).toEqual({ kind: "delivery", id: 7, deliveryKind: "finished" });
    expect(panelFromOpen("delivery-reason:7", both, QC)).toEqual({ kind: "delivery", id: 7, deliveryKind: "finished" });
    expect(panelFromOpen("delivery:99", both, QC)).toBeNull();
    expect(panelFromOpen("delivery-reason:99", both, VIEWER)).toBeNull();
  });
});
