import { describe, expect, it } from "vitest";
import { chartPoints } from "../PortalYearChart";

describe("approved Home chart boundary cases", () => {
  it("has no coordinates when no months exist", () => {
    expect(chartPoints([])).toEqual([]);
  });
  it("centres a new model's only month within the plot", () => {
    const [point] = chartPoints([3200000]);
    expect(point).toEqual({x:180,y:30});
  });
  it("keeps a zero-sales history on a finite baseline", () => {
    const points = chartPoints([0,0,0]);
    expect(points.every(point => point !== null && Number.isFinite(point.x) && point.y === 132)).toBe(true);
  });
  it("leaves missing and invalid values as gaps, rather than zero earnings", () => {
    const points = chartPoints([100000,null,Number.NaN,200000]);
    expect(points[1]).toBeNull();
    expect(points[2]).toBeNull();
    expect(points[0]!.y).toBeGreaterThan(points[3]!.y);
  });
});
