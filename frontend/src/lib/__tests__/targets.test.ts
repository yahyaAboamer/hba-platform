import { describe, expect, it } from "vitest";

import type { MonthTargets } from "../portal";
import {
  describeCurrentTargetPay,
  describeTargetPay,
  targetChip,
  targetCounts,
  targetOutcome,
  targetProgressNote,
} from "../targets";

/**
 * **What a model is told about her own targets.**
 *
 * These four functions are the entire vocabulary two screens use for a
 * subject where the wrong word is a false statement about somebody's work or
 * her pay. They are tested here rather than through the screens because the
 * failures worth guarding are semantic, not visual:
 *
 * 1. **Unrecorded must never read as missed.** §11.3 and A06. An unrecorded
 *    month blocks a guaranteed minimum; a screen calling it a miss tells her
 *    the month is lost when it is only waiting, and points her at the wrong
 *    question when she asks about it.
 * 2. **A month before the platform must never show invented counts.** ADR 0036
 *    and H02. The old dashboard kept the outcome and not the arithmetic;
 *    filling in numbers to match the outcome is fabricating the evidence for a
 *    figure that decided her pay.
 * 3. **A shortfall must not read as money gone where it is not.** §15. Targets
 *    decide pay only on a guaranteed minimum.
 * 4. **No zero-divided arithmetic reaches the screen.** AC30.
 */

function target(over: Partial<MonthTargets> = {}): MonthTargets {
  return {
    required_videos: 6,
    required_stories: 12,
    actual_videos: 6,
    actual_stories: 12,
    numbers_kept: true,
    achieved: true,
    determines_pay: true,
    recorded_at: "2026-09-01T00:00:00+00:00",
    ...over,
  };
}

describe("targetChip", () => {
  it("says not recorded, and never short, when nobody has counted", () => {
    const chip = targetChip(target({ achieved: null }))!;
    expect(chip.text).toBe("Not recorded yet");
    expect(chip.text.toLowerCase()).not.toContain("short");
    expect(chip.text.toLowerCase()).not.toContain("miss");
  });

  it("says a met month is met, with no wait for a confirmation (ADR 0081)", () => {
    expect(targetChip(target())!.text).toBe("targets met");
    expect(targetChip(target({ determines_pay: false }))!.text).toBe("targets met");
  });
});

describe("targetCounts", () => {
  it("says the numbers were not kept for a month before the platform", () => {
    expect(targetCounts(target({ numbers_kept: false }))).toBe("not kept");
  });

  it("never prints a zero where nothing was counted", () => {
    const said = targetCounts(
      target({ actual_videos: null, actual_stories: null }),
    );
    expect(said).toBe("—");
    expect(said).not.toContain("0");
  });

  it("omits the requirement rather than printing 'of 0'", () => {
    // AC30. A target of zero is a statement about HBA's month, not hers, and
    // "0 of 0" is arithmetic nobody wants to read.
    expect(
      targetCounts(
        target({
          required_videos: 0,
          required_stories: 0,
          actual_videos: 0,
          actual_stories: 0,
        }),
      ),
    ).toBe("0 videos, 0 stories");
  });

  it("shows both halves of a partly counted month", () => {
    expect(targetCounts(target({ actual_videos: 4, actual_stories: 0 }))).toBe(
      "4 of 6 videos, 0 of 12 stories",
    );
  });

  it("does not turn one missing count into zero", () => {
    expect(targetCounts(target({ actual_videos: null, actual_stories: 1 }))).toBe(
      "— of 6 videos, 1 of 12 stories",
    );
  });
});

describe("the visible current-month explanation", () => {
  it("names only recorded work still needed", () => {
    expect(targetProgressNote(target({ achieved: false, actual_videos: 4 }))).toBe(
      "2 videos left to reach this month’s target.",
    );
    expect(targetProgressNote(target({ achieved: false, actual_videos: 4, actual_stories: 9 }))).toBe(
      "2 videos and 3 stories left to reach this month’s target.",
    );
    expect(targetProgressNote(target({ achieved: null, actual_videos: null }))).toBeNull();
  });

  it("does not settle a current shortfall while the month runs", () => {
    const said = describeCurrentTargetPay(target({ achieved: false }));
    expect(said).toContain("applies if this month's targets are met");
    expect(said).toContain("commission still applies");
    expect(said).not.toContain("does not apply");
    expect(said).not.toContain("confirm");
  });

  it("distinguishes missing and met guarantee records", () => {
    expect(describeCurrentTargetPay(target({ achieved: null }))).toContain("not recorded");
    expect(describeCurrentTargetPay(target())).toBe("Met, so your guaranteed minimum applies.");
  });
});

describe("targetOutcome", () => {
  it("separates the three states, in the export's words where it has them", () => {
    expect(targetOutcome(target({ achieved: null }))).toBe("not recorded");
    expect(targetOutcome(target({ achieved: false }))).toBe("not met");
    expect(targetOutcome(target())).toBe("met");
  });

  it("never mentions a confirmation (ADR 0081)", () => {
    expect(targetOutcome(target({ determines_pay: false }))).toBe("met");
  });
});

describe("describeTargetPay", () => {
  it("tells a commission model her targets do not change her pay", () => {
    const said = describeTargetPay(target({ determines_pay: false }));
    expect(said).toContain("does not change what you are paid");
    // The reassurance must not be smuggled in beside a loss.
    expect(said.toLowerCase()).not.toContain("guaranteed minimum");
  });

  it("does not call an unrecorded month a miss", () => {
    const said = describeTargetPay(target({ achieved: null }));
    expect(said).toContain("Nobody has recorded");
    expect(said.toLowerCase()).not.toContain("short");
  });

  it("says a shortfall costs the guarantee and nothing else", () => {
    // §11.3: she is paid her commission, promptly, and the month closes.
    // Wording that reads as a penalty is wrong about the rule as well.
    const said = describeTargetPay(target({ achieved: false }));
    expect(said).toContain("paid your commission");
  });

  it("has a sentence for every combination and never an empty one", () => {
    for (const determines_pay of [true, false]) {
      for (const achieved of [null, false, true]) {
        const said = describeTargetPay(target({ determines_pay, achieved }));
        expect(said.length).toBeGreaterThan(20);
        expect(said.endsWith(".")).toBe(true);
      }
    }
  });
});
