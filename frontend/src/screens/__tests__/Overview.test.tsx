import { describe, expect, it } from "vitest";

import { progressLabel } from "../Overview";

/**
 * The approved Home shows content progress per model. The distinction below
 * is the whole reason the panel is a table rather than two counts: it has to
 * separate *HBA never asked her* from *she has produced nothing*, because the
 * first is HBA's own omission and the second is a fact about her month.
 */
describe("content progress in the owner's Home", () => {
  it("reads as done over asked-for", () => {
    expect(progressLabel(5, 6)).toBe("5 / 6");
  });

  it("counts nothing produced as zero, not as missing", () => {
    expect(progressLabel(0, 6)).toBe("0 / 6");
    expect(progressLabel(null, 6)).toBe("0 / 6");
  });

  it("has nothing to show when nobody asked her for anything", () => {
    expect(progressLabel(null, null)).toBeNull();
    expect(progressLabel(0, null)).toBeNull();
  });

  it("never presents an unasked month as a failed one", () => {
    // The bug this exists to prevent: `0 / 0` in front of the owner, reading
    // as a model who did nothing, when the gap is that nobody set a target.
    expect(progressLabel(0, null)).not.toBe("0 / 0");
  });
});
