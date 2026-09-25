import { describe, expect, it } from "vitest";

import { outcomeWord } from "../Targets";

// The export's `tgRows.state` and `mTargetHistory` (Admin lines 2765-2767, 2970).
const row = (achieved: boolean | null, v: number | null, s: number | null) =>
  ({ achieved, actual_videos: v, actual_stories: s });

describe("Admin Targets: the export's words for the month's record (item 9)", () => {
  it("says there is no record, never a zero or a miss", () => {
    expect(outcomeWord(row(null, null, null), "2026-09", "2026-09")).toBe("No record yet");
  });
  it("says a recorded zero before anything else", () => {
    expect(outcomeWord(row(false, 0, 0), "2026-08", "2026-09")).toBe("Recorded zero");
  });
  it("says Target met", () => {
    expect(outcomeWord(row(true, 6, 12), "2026-08", "2026-09")).toBe("Target met");
  });
  it("says In progress for the running month and Below target once it has ended", () => {
    expect(outcomeWord(row(false, 3, 5), "2026-09", "2026-09")).toBe("In progress");
    expect(outcomeWord(row(false, 3, 5), "2026-08", "2026-09")).toBe("Below target");
  });
});
