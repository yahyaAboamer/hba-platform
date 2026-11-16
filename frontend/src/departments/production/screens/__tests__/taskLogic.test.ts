import { describe, expect, it } from "vitest";

import { panelFromOpen } from "../logic";
import type { Powers } from "../logic";
import { detailLine, dueWords, groupTasks, matchesFilter, summarySentence, taskLink, waitingWords } from "../taskLogic";
import type { Delivery } from "../types";
import { makeManual, makeOrder, makeTask, makeTaskList, TODAY } from "./fixtures";

const OWNER: Powers = { canEdit: true, isOwner: true };
const QC: Powers = { canEdit: true, isOwner: false };
const VIEWER: Powers = { canEdit: false, isOwner: false };

const overdue = makeTask({ key: "a", title: "Approve the sample", who: "owner", group: "overdue", overdue_days: 3, due: "2030-11-10" });
const today = makeManual({ id: 5, title: "Visit the print house", group: "today", due: TODAY });
const factory = makeTask({ key: "c", title: "Receive 30 fix pieces", who: "factory", waiting_on: "Main factory", since: "2030-11-10" });
const later = makeTask({ key: "d", title: "Final inspection", group: "later", stage: "making", due: "2030-11-26" });

describe("Filters and groups", () => {
  const tasks = [overdue, today, factory, later];

  it("keeps the server's groups in order and drops an empty one", () => {
    expect(groupTasks(tasks, "all").map((entry) => [entry.group, entry.tasks.length])).toEqual([
      ["overdue", 1], ["today", 1], ["week", 1], ["later", 1],
    ]);
    expect(groupTasks([today], "all").map((entry) => entry.group)).toEqual(["today"]);
  });

  it("filters by overdue, by who it is for and by waiting on suppliers", () => {
    expect(groupTasks(tasks, "overdue").flatMap((entry) => entry.tasks)).toEqual([overdue]);
    expect(groupTasks(tasks, "owner").flatMap((entry) => entry.tasks)).toEqual([overdue]);
    expect(groupTasks(tasks, "qc").flatMap((entry) => entry.tasks)).toEqual([today, later]);
    expect(groupTasks(tasks, "factory").flatMap((entry) => entry.tasks)).toEqual([factory]);
    expect(matchesFilter(today, "overdue")).toBe(false);
  });

  it("puts done tasks last, in a group of their own", () => {
    const done = makeManual({ id: 9, title: "Old", done: true, done_at: "2030-11-12T10:00:00Z", group: "done" });
    expect(groupTasks([done, overdue], "all").map((entry) => entry.group)).toEqual(["overdue", "done"]);
  });

  it("says how many are open, overdue and for today, with today's weekday", () => {
    expect(summarySentence(makeTaskList(tasks).counts, tasks, TODAY)).toBe("4 open · 1 overdue · 1 for today, Wednesday 13 Nov");
    const quiet = makeTaskList([later]);
    expect(summarySentence(quiet.counts, quiet.tasks, TODAY)).toBe("1 open · 0 for today, Wednesday 13 Nov");
  });
});

describe("The words on a row", () => {
  it("gives the date, and how many days when overdue", () => {
    expect(dueWords(overdue)).toBe("10 Nov · 3 days");
    expect(dueWords({ ...overdue, overdue_days: 1 })).toBe("10 Nov · 1 day");
    expect(dueWords(today)).toBe("13 Nov");
    expect(dueWords(makeManual({ id: 1, title: "x" }))).toBe("No date");
    // The factory finishes making around its promised date.
    expect(dueWords(later)).toBe("around 26 Nov");
    expect(dueWords(makeManual({ id: 2, title: "x", done: true, done_at: "2030-11-12T22:30:00Z", group: "done" }))).toBe("Done 13 Nov");
  });

  it("says who it waits on, and for how long", () => {
    expect(waitingWords(factory, TODAY)).toBe("waiting on Main factory for 3 days");
    expect(waitingWords({ ...factory, since: TODAY }, TODAY)).toBe("waiting on Main factory");
    expect(waitingWords({ ...overdue, since: "2030-11-10" }, TODAY)).toBe("waiting 3 days");
    expect(waitingWords(makeTask({ key: "q", title: "x", who: "qc", since: "2030-11-01" }), TODAY)).toBeNull();
    expect(waitingWords(today, TODAY)).toBeNull();
  });

  it("names the order, or says it was added by hand", () => {
    expect(detailLine(factory, TODAY)).toBe("Oversized hoodie · Black · PO-2610-01 · waiting on Main factory for 3 days");
    expect(detailLine(today, TODAY)).toBe("Added by hand · no order");
    const onOrder = makeManual({ id: 3, title: "x", order: { id: 2, code: "PO-2611-02", style_name: "Boxy tee", colour: "Black" } });
    expect(detailLine(onOrder, TODAY)).toBe("Boxy tee · Black · PO-2611-02 · Added by hand");
  });
});

describe("Which button a generated task gets", () => {
  const forms = (open: string | null, who: "owner" | "qc" | "factory" = "qc") => makeTask({ key: "k", title: "t", who, open });

  it("goes to the order with its form open, in the form's own words", () => {
    const link = (open: string, powers = QC) => taskLink(forms(open), powers);
    expect(link("cut")).toEqual({ label: "Enter counts", to: "/production/orders/1?open=cut", opens: true });
    expect(link("stage:fabric_check")?.label).toBe("Record check");
    expect(link("stage:materials")?.label).toBe("Mark arrived");
    expect(link("stage:making")?.label).toBe("Mark finished");
    expect(link("inspection")?.label).toBe("Record inspection");
    expect(link("delivery")?.label).toBe("Record delivery");
    expect(link("delivery:fix")?.label).toBe("Record delivery");
    expect(link("delivery:7")).toEqual({ label: "Enter counts", to: "/production/orders/1?open=delivery:7", opens: true });
    expect(link("delivery-reason:7")?.label).toBe("Add reason");
    expect(link("sample", OWNER)?.label).toBe("Review sample");
    expect(link("settle", OWNER)?.label).toBe("Settle");
  });

  it("gives the QC manager the order, not the owner's forms", () => {
    expect(taskLink(forms("sample", "owner"), QC)).toEqual({ label: "Open order", to: "/production/orders/1", opens: false });
    expect(taskLink(forms("settle", "owner"), QC)?.opens).toBe(false);
  });

  it("gives somebody who can only read the order for every task", () => {
    for (const open of ["cut", "sample", "delivery", "delivery-reason:7", "stage:making", null]) {
      expect(taskLink(forms(open), VIEWER)).toEqual({ label: "Open order", to: "/production/orders/1", opens: false });
    }
  });

  it("gives work with nothing to fill in the order", () => {
    expect(taskLink(forms(null, "factory"), OWNER)).toEqual({ label: "Open order", to: "/production/orders/1", opens: false });
    expect(taskLink(forms("something-new"), OWNER)?.opens).toBe(false);
  });
});

describe("A purchase's task (batch 4)", () => {
  const purchase = (key: string, title: string, who: "qc" | "factory", order: boolean = true) =>
    makeTask({ key, title, who, open: "purchase:1", ...(order ? {} : { order: null }), supplier: { id: "fac", name: "Main factory" } });

  it("is Mark received, on the supplier's page with that purchase open, for both of its tasks", () => {
    const to = "/production/suppliers/fac?open=purchase:1";
    expect(taskLink(purchase("purchase:1:arrival", "Check Heavy fleece, black on arrival", "qc"), QC)).toEqual({ label: "Mark received", to, opens: true });
    expect(taskLink(purchase("purchase:1:chase", "Chase the Heavy fleece, black delivery", "factory"), QC)).toEqual({ label: "Mark received", to, opens: true });
    expect(taskLink(purchase("purchase:1:chase", "x", "factory"), OWNER)?.label).toBe("Mark received");
  });

  it("goes to the supplier even when the purchase is for no order", () => {
    expect(taskLink(purchase("purchase:1:arrival", "x", "qc", false), QC)?.to).toBe("/production/suppliers/fac?open=purchase:1");
  });

  it("gives somebody who can only read the supplier's page, not a button that writes", () => {
    expect(taskLink(purchase("purchase:1:arrival", "x", "qc"), VIEWER)).toEqual({ label: "Open supplier", to: "/production/suppliers/fac", opens: false });
  });
});

/** The fixture skips the sample (a repeat run); this order is waiting for it. */
function waitingForSample() {
  const order = makeOrder("sample");
  order.stages = order.stages.map((stage) => (stage.key === "sample" ? { ...stage, status: "todo", done_on: null } : stage));
  return order;
}

describe("The form a task asks the order page to open", () => {
  const delivery = (id: number, kind: "finished" | "fix"): Delivery => ({
    id, number: id, kind, shipped_on: "2030-11-01", counted_on: null, mismatch_reason: null, sizes: [],
    shipped_total: 10, counted_total: null, waiting_for_count: true, mismatch: false, needs_reason: false,
  });

  it("opens the stage's own form for somebody who may use it", () => {
    expect(panelFromOpen("cut", makeOrder("cutting"), QC)).toEqual({ kind: "cut" });
    expect(panelFromOpen("inspection", makeOrder("final_inspection"), QC)).toEqual({ kind: "inspection" });
    expect(panelFromOpen("stage:materials", makeOrder("materials"), QC)).toEqual({ kind: "complete", stage: "materials" });
    expect(panelFromOpen("stage:pattern_check", makeOrder("pattern_check"), QC)).toEqual({ kind: "complete", stage: "pattern_check" });
    expect(panelFromOpen("stage:making", makeOrder("making"), QC)).toEqual({ kind: "complete", stage: "making" });
    expect(panelFromOpen("stage:fabric_check", makeOrder("fabric_check"), QC)).toEqual({ kind: "fabric" });
    expect(panelFromOpen("settle", makeOrder("settle"), OWNER)).toEqual({ kind: "settle" });
    expect(panelFromOpen("sample", waitingForSample(), OWNER)).toEqual({ kind: "sample" });
  });

  it("opens nothing when the person may not use the form", () => {
    expect(panelFromOpen("settle", makeOrder("settle"), QC)).toBeNull();
    expect(panelFromOpen("sample", waitingForSample(), QC)).toBeNull();
    expect(panelFromOpen("cut", makeOrder("cutting"), VIEWER)).toBeNull();
    expect(panelFromOpen("delivery", makeOrder("warehouse"), VIEWER)).toBeNull();
  });

  it("opens nothing for work the order has moved past, or an order that is not open", () => {
    expect(panelFromOpen("cut", makeOrder("final_inspection"), QC)).toBeNull();
    expect(panelFromOpen("stage:making", makeOrder("warehouse"), QC)).toBeNull();
    expect(panelFromOpen("cut", makeOrder("cutting", { extra: { status: "cancelled" } }), QC)).toBeNull();
  });

  it("opens a delivery's own form for its count or its reason, and a new one for pieces to come", () => {
    const order = makeOrder("warehouse", { deliveries: [delivery(7, "finished"), delivery(8, "fix")], sizes: [{ passed: 10 }, { passed: 20 }] });
    expect(panelFromOpen("delivery:8", order, QC)).toEqual({ kind: "delivery", id: 8, deliveryKind: "fix" });
    expect(panelFromOpen("delivery-reason:7", order, QC)).toEqual({ kind: "delivery", id: 7, deliveryKind: "finished" });
    expect(panelFromOpen("delivery:99", order, QC)).toBeNull();
    // 30 passed, none shipped: finished pieces are still to come.
    expect(panelFromOpen("delivery", order, QC)).toEqual({ kind: "delivery", id: null, deliveryKind: "finished" });
    // Everything shipped and fix pieces still out: a fix delivery. Nothing to come at all: nothing opens.
    const shipped = makeOrder("warehouse", { sizes: [{ passed: 10, shipped: 10 }, { passed: 20, shipped: 20 }], extra: { fix_not_returned: 4 } });
    expect(panelFromOpen("delivery", shipped, QC)).toEqual({ kind: "delivery", id: null, deliveryKind: "fix" });
    expect(panelFromOpen("delivery", { ...shipped, fix_not_returned: 0 }, QC)).toBeNull();
  });

  it("opens nothing for a value it does not know", () => {
    for (const value of [null, "", "nonsense", "stage:plan", "stage:", "stage:cutting", "delivery-reason"]) {
      expect(panelFromOpen(value, makeOrder("cutting"), OWNER)).toBeNull();
    }
  });
});
