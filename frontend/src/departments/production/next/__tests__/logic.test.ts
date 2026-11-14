import { describe, expect, it } from "vitest";

import { addDays, daysBetween, lateWords, shortDay, stagePhrase } from "../format";
import {
  blankCounts,
  costTotal,
  countDifferences,
  countsFrom,
  cutProblem,
  deliveryProblem,
  fillDates,
  inspectionProblem,
  nextButton,
} from "../logic";
import type { InspectionLine } from "../logic";
import { makeOrder } from "./fixtures";

const DAYS = { sample: 7, materials: 7, fabric_check: 2, pattern_check: 3, cutting: 2, making: 17, final_inspection: 1, warehouse: 3, settle: 7 };

describe("dates, without Date for display", () => {
  it("counts and adds days on the calendar", () => {
    expect(addDays("2030-10-31", 1)).toBe("2030-11-01");
    expect(addDays("2030-03-01", -1)).toBe("2030-02-28");
    expect(daysBetween("2030-11-03", "2030-11-09")).toBe(6);
    expect(shortDay("2030-11-03")).toBe("3 Nov");
  });

  it("says lateness in words", () => {
    const row = { status: "open" as const, lateness_days: 6, finished_on: null, delivery_date: "2030-11-26", target_date: "2030-11-20" };
    expect(lateWords(row).text).toBe("Now due 26 Nov · 6 days late");
    expect(lateWords({ ...row, finished_on: "2030-11-26", delivery_date: "2030-11-20" }).text).toBe("Finished 6 days late");
    expect(lateWords({ ...row, lateness_days: 0, delivery_date: "2030-11-20" })).toEqual({ text: "On time", tone: "ok" });
  });
});

describe("the stage, in words", () => {
  const stage = { key: "cutting" as const, label: "Cutting", position: 6 };
  it("says the status, not the stage, for an order that is no longer open", () => {
    expect(stagePhrase({ status: "open", stage })).toBe("6 of 10 · Cutting");
    // A cancelled order still has the stage it never got past.
    expect(stagePhrase({ status: "cancelled", stage })).toBe("Cancelled");
    expect(stagePhrase({ status: "closed", stage: null })).toBe("Settled and closed");
  });
});

describe("the dates filled backwards (the server's fill_dates)", () => {
  it("counts back from the target date with each next stage's days", () => {
    const dates = fillDates("2030-11-03", DAYS, new Set(["sample"]));
    expect(dates.warehouse).toBe("2030-11-03");
    expect(dates.final_inspection).toBe("2030-10-31");
    expect(dates.making).toBe("2030-10-30");
    expect(dates.cutting).toBe("2030-10-13");
    expect(dates.pattern_check).toBe("2030-10-11");
    expect(dates.fabric_check).toBe("2030-10-08");
    expect(dates.materials).toBe("2030-10-06");
    // A skipped sample has no date and takes no days: the plan counts back from materials.
    expect(dates.sample).toBeNull();
    expect(dates.plan).toBe("2030-09-29");
    expect(dates.settle).toBe("2030-11-10");
  });

  it("gives the sample its days when it is not skipped", () => {
    expect(fillDates("2030-11-03", DAYS).sample).toBe("2030-09-29");
  });
});

describe("cutting", () => {
  const base = { cut: countsFrom({ S: 7, M: 20 }), planned: 30, reasons: [], promised: "2030-11-03", today: "2030-10-01" };

  it("refuses until the reasons add up to the shortfall", () => {
    expect(cutProblem(base)).toMatch(/3 pieces fewer were cut than planned; the reasons account for 0\. Make them add up to 3\./);
    expect(cutProblem({ ...base, reasons: [{ reason: "Defects", quantity: "2" }] })).toMatch(/account for 2/);
    expect(cutProblem({ ...base, reasons: [{ reason: "Defects", quantity: "3" }] })).toBeNull();
  });

  it("needs no reasons when nothing is short, and some pieces and a date", () => {
    expect(cutProblem({ ...base, cut: countsFrom({ S: 10, M: 20 }) })).toBeNull();
    expect(cutProblem({ ...base, cut: blankCounts() })).toMatch(/at least one size/);
    expect(cutProblem({ ...base, cut: countsFrom({ S: 10, M: 20 }), promised: "" })).toMatch(/date the factory promised/);
  });
});

describe("inspection", () => {
  const lines = (s: [string, string, string], m: [string, string, string]): InspectionLine[] => [
    { size: "S", cut: 10, passed: s[0], to_fix: s[1], rejected: s[2] },
    { size: "M", cut: 20, passed: m[0], to_fix: m[1], rejected: m[2] },
  ];
  const none = { rejectedReasons: [], toFixReasons: [] };

  it("completes only when every size adds up to its cut", () => {
    expect(inspectionProblem({ lines: lines(["8", "1", "0"], ["20", "0", "0"]), ...none }, true)).toMatch(/Size S: 9 inspected of 10 cut/);
    expect(inspectionProblem({ lines: lines(["10", "0", "0"], ["20", "0", "0"]), ...none }, true)).toBeNull();
  });

  it("lets counts be saved in batches, but never above the cut", () => {
    expect(inspectionProblem({ lines: lines(["8", "1", "0"], ["", "", ""]), ...none }, false)).toBeNull();
    expect(inspectionProblem({ lines: lines(["10", "1", "0"], ["", "", ""]), ...none }, false)).toMatch(/Size S: 11 inspected, more than the 10 cut/);
  });

  it("asks for reasons that add up to the rejected and to-fix totals", () => {
    const draft = { lines: lines(["8", "1", "1"], ["20", "0", "0"]), rejectedReasons: [], toFixReasons: [{ reason: "Label", quantity: "1" }] };
    expect(inspectionProblem(draft, true)).toMatch(/1 rejected, and the reasons account for 0/);
    expect(inspectionProblem({ ...draft, rejectedReasons: [{ reason: "Stain", quantity: "1" }] }, true)).toBeNull();
    expect(inspectionProblem({ ...draft, rejectedReasons: [{ reason: "Stain", quantity: "2" }] }, false)).toMatch(/more than the 1 counted/);
  });
});

describe("deliveries", () => {
  const draft = {
    kind: "finished" as const,
    shippedOn: "2030-10-01",
    shipped: countsFrom({ S: 10, M: 20 }),
    countedOn: "",
    counted: blankCounts(),
    room: 30,
    today: "2030-10-02",
  };

  it("never ships more than has passed", () => {
    expect(deliveryProblem(draft)).toBeNull();
    expect(deliveryProblem({ ...draft, shipped: countsFrom({ S: 11, M: 20 }) })).toMatch(/31 finished pieces shipped, more than the 30/);
  });

  it("needs a count date and every size once a count is started, and a count not before shipping", () => {
    expect(deliveryProblem({ ...draft, counted: countsFrom({ S: 10 }) })).toMatch(/date Khazenly counted/);
    expect(deliveryProblem({ ...draft, countedOn: "2030-10-02", counted: countsFrom({ S: 10 }) })).toMatch(/each size that shipped/);
    expect(deliveryProblem({ ...draft, countedOn: "2030-09-30", counted: countsFrom({ S: 10, M: 20 }) })).toMatch(/before it left the factory/);
    expect(deliveryProblem({ ...draft, countedOn: "2030-10-02", counted: countsFrom({ S: 10, M: 20 }) })).toBeNull();
  });

  it("finds the sizes where the counts differ", () => {
    expect(countDifferences({ shipped: draft.shipped, counted: countsFrom({ S: 10, M: 19 }) })).toEqual([{ size: "M", shipped: 20, counted: 19 }]);
    expect(countDifferences({ shipped: draft.shipped, counted: blankCounts() })).toEqual([]);
  });
});

describe("cost typed in pounds", () => {
  it("adds the five parts in piastres and refuses what is not a figure", () => {
    const parts = { fabric: "165", manufacturing: "85", printing: "30", accessories: "12.50", packaging: "8" };
    expect(costTotal(parts)).toBe(30050);
    expect(costTotal({ ...parts, fabric: "abc" })).toBeNull();
    expect(costTotal({ ...parts, printing: "" })).toBe(27050);
  });
});

describe("what the next-action button opens", () => {
  it("is the right form for the stage, and nothing for somebody who may not act", () => {
    const qc = { canEdit: true, isOwner: false };
    expect(nextButton(makeOrder("cutting"), qc)?.panel).toEqual({ kind: "cut" });
    expect(nextButton(makeOrder("final_inspection"), qc)?.panel).toEqual({ kind: "inspection" });
    expect(nextButton(makeOrder("settle"), qc)).toBeNull();
    expect(nextButton(makeOrder("settle"), { canEdit: true, isOwner: true })?.panel).toEqual({ kind: "settle" });
    expect(nextButton(makeOrder("cutting"), { canEdit: false, isOwner: false })).toBeNull();
  });
});
