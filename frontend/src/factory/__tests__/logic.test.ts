import { describe, expect, it } from "vitest";

import { cutWords, dayWords, reportBody, reportProblem, typedFrom, unwrap } from "../logic";

describe("what is sent as the cut", () => {
  it("counts a blank size as none and trims the note", () => {
    expect(reportBody({ S: "118", M: "", L: " 236 " }, "  short  ")).toEqual({ sizes: { S: 118, M: 0, L: 236 }, note: "short" });
    expect(reportBody({ S: "1" }, "   ").note).toBeNull();
  });

  it("refuses nothing cut, a number that is not whole, and one too large", () => {
    expect(reportProblem({ S: "", M: "" })).toMatch(/at least one size/);
    expect(reportProblem({ S: "1.5" })).toMatch(/whole numbers/);
    expect(reportProblem({ S: "-3" })).toMatch(/whole numbers/);
    expect(reportProblem({ S: "100001" })).toMatch(/at most 100,000/);
    expect(reportProblem({ S: "100000", M: "" })).toBeNull();
  });

  it("starts a correction from the sizes sent, and a first report blank", () => {
    const lines = [
      { size: "S", planned: 10, reported: 8, confirmed: null },
      { size: "M", planned: 10, reported: null, confirmed: null },
    ];
    expect(typedFrom(lines, "reported")).toEqual({ S: "8", M: "" });
    expect(typedFrom(lines, "blank")).toEqual({ S: "", M: "" });
  });
});

describe("words", () => {
  it("says the figure that stands: confirmed, then reported, then planned", () => {
    const pieces = (n: number) => String(n);
    expect(cutWords({ planned_total: 800, cut: { reported_total: null, confirmed_total: null } }, pieces)).toBe("800 planned");
    expect(cutWords({ planned_total: 800, cut: { reported_total: 792, confirmed_total: null } }, pieces)).toBe("792 reported cut");
    expect(cutWords({ planned_total: 800, cut: { reported_total: 792, confirmed_total: 790 } }, pieces)).toBe("790 cut");
  });

  it("reads a day or a stamped instant", () => {
    expect(dayWords("2030-11-16")).toBe("16 Nov");
    expect(dayWords("2030-11-16T10:00:00Z")).toBe("16 Nov");
    expect(dayWords(null)).toBe("—");
  });

  it("takes an answer as the object itself or under its key", () => {
    expect(unwrap<number[]>({ orders: [1] }, "orders")).toEqual([1]);
    expect(unwrap<number[]>([1], "orders")).toEqual([1]);
  });
});
