import { describe, expect, it } from "vitest";

import { expectedRecording } from "../portal";

describe("the usual recording date on Home (decision g)", () => {
  it("is around the 3rd of the following month", () => {
    expect(expectedRecording("2026-09", "open", "2026-09-25")).toEqual({ date: "2026-10-03", label: "3 October 2026", passed: false });
    expect(expectedRecording("2026-12", "approved", "2026-12-20")!.label).toBe("3 January 2027");
  });

  it("is not offered once money is recorded, or for a month settled outside the dashboard", () => {
    expect(expectedRecording("2026-08", "paid", "2026-09-01")).toBeNull();
    expect(expectedRecording("2026-03", "settled", "2026-09-01")).toBeNull();
    expect(expectedRecording("2026-08", "unknown", "2026-09-01")).toBeNull();
  });

  it("keeps its date once it has passed, and says so, rather than moving forward", () => {
    const late = expectedRecording("2026-08", "approved", "2026-09-10")!;
    expect(late.date).toBe("2026-09-03");
    expect(late.passed).toBe(true);
    // On the day itself it is still the expected day, not a missed one.
    expect(expectedRecording("2026-08", "approved", "2026-09-03")!.passed).toBe(false);
  });
});
