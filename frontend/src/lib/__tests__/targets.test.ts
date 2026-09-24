import { describe, expect, it } from "vitest";

import type { MonthTargets } from "../portal";
import {
  describeTargetPay,
  targetChip,
  targetCounts,
  targetOutcome,
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
    verified: true,
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

  it("distinguishes met-and-confirmed from met-and-waiting where pay depends on it", () => {
    expect(targetChip(target({ verified: false }))!.text).toBe(
      "Waiting to be confirmed",
    );
    expect(targetChip(target())!.text).toBe("targets met");
  });

  it("does not raise confirmation where it decides nothing", () => {
    // On commission, whether HBA has countersigned a number is their
    // paperwork. Telling her it is outstanding invents a worry.
    expect(
      targetChip(target({ verified: false, determines_pay: false }))!.text,
    ).toBe("targets met");
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
    ).toBe("0 video, 0 story");
  });

  it("shows both halves of a partly counted month", () => {
    expect(targetCounts(target({ actual_videos: 4, actual_stories: 0 }))).toBe(
      "4 of 6 video, 0 of 12 story",
    );
  });
});

describe("targetOutcome", () => {
  it("separates the three states, in the export's words where it has them", () => {
    expect(targetOutcome(target({ achieved: null }))).toBe("not recorded");
    expect(targetOutcome(target({ achieved: false }))).toBe("not met");
    expect(targetOutcome(target())).toBe("met");
  });

  it("mentions confirmation only where it holds money up", () => {
    expect(targetOutcome(target({ verified: false }))).toBe("met — to confirm");
    expect(
      targetOutcome(target({ verified: false, determines_pay: false })),
    ).toBe("met");
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

  it("puts an unconfirmed month on HBA rather than on her", () => {
    expect(describeTargetPay(target({ verified: false }))).toContain(
      "as soon as HBA confirms",
    );
  });

  it("has a sentence for every combination and never an empty one", () => {
    for (const determines_pay of [true, false]) {
      for (const achieved of [null, false, true]) {
        for (const verified of [true, false]) {
          const said = describeTargetPay(
            target({ determines_pay, achieved, verified }),
          );
          expect(said.length).toBeGreaterThan(20);
          expect(said.endsWith(".")).toBe(true);
        }
      }
    }
  });
});
