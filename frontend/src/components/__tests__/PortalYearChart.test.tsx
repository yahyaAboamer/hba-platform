import { describe, expect, it } from "vitest";
import { chartPoints, chartScale } from "../PortalYearChart";

describe("approved Home chart boundary cases", () => {
  it("has no coordinates when no months exist", () => {
    expect(chartPoints([])).toEqual([]);
  });
  it("centres a new model's only month within the export's plot", () => {
    const [point] = chartPoints([3200000]);
    expect(point!.x).toBe(150);
    // The highest month sits under the export's 15% headroom, not on the top rule.
    expect(point!.y).toBeCloseTo(102 - 88 / 1.15, 5);
  });
  it("keeps a zero-sales history on a finite baseline", () => {
    const points = chartPoints([0, 0, 0]);
    expect(points.every((point) => point !== null && Number.isFinite(point.x) && point.y === 102)).toBe(true);
    expect(chartScale([0, 0, 0], 1.15)).toBe(0);
  });
  it("leaves missing and invalid values as gaps, rather than zero earnings", () => {
    const points = chartPoints([100000, null, Number.NaN, 200000]);
    expect(points[1]).toBeNull();
    expect(points[2]).toBeNull();
    expect(points[0]!.y).toBeGreaterThan(points[3]!.y);
  });
  it("spreads months from x 8 to 292, as the export does", () => {
    const points = chartPoints([1, 2, 3]);
    expect(points.map((p) => p!.x)).toEqual([8, 150, 292]);
  });
});

describe("the chart's scale, from real values", () => {
  it("puts the highest month under the export's 15% sales headroom", () => {
    expect(chartScale([1271000, 500000], 1.15)).toBeCloseTo(1461650, 5);
  });
  it("gives uses the export's 35% headroom", () => {
    expect(chartScale([2, 4], 1.35)).toBeCloseTo(5.4, 5);
  });
});
