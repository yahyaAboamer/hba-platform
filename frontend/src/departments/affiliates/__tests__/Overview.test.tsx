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

import { toReview } from "../Overview";

const row = (over: Partial<Parameters<typeof toReview>[0][0]> = {}) => ({
  required_videos: 6,
  required_stories: 12,
  actual_videos: 6,
  actual_stories: 12,
  ...over,
});

describe("which models the content panel shows", () => {
  it("leaves out a model who has produced everything asked of her", () => {
    // The panel is called "to review". A model who is done is not something
    // to review, and listing her pushes somebody who needs chasing off the
    // bottom of a six-row panel.
    expect(toReview([row()])).toHaveLength(0);
  });

  it("keeps a model who is short", () => {
    expect(toReview([row({ actual_videos: 1 })])).toHaveLength(1);
  });

  it("puts nothing-recorded above any shortfall", () => {
    const nothing = row({ actual_videos: null, actual_stories: null });
    const short = row({ actual_videos: 0, actual_stories: 0 });
    const order = toReview([short, nothing]);
    expect(order[0]).toBe(nothing);
  });

  it("keeps a model nobody asked anything of", () => {
    // That gap is HBA's own, and it is exactly what this panel is for.
    expect(toReview([row({ required_videos: null, required_stories: null,
      actual_videos: null, actual_stories: null })])).toHaveLength(1);
  });

  it("sorts the furthest behind first", () => {
    const barely = row({ actual_videos: 5, actual_stories: 12 });
    const badly = row({ actual_videos: 0, actual_stories: 0 });
    expect(toReview([barely, badly])[0]).toBe(badly);
  });

  it("shows at most six, because the whole table is one click away", () => {
    expect(toReview(Array.from({ length: 12 }, () =>
      row({ actual_videos: 0, actual_stories: 0 })))).toHaveLength(6);
  });
});
