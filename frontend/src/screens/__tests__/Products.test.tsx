import { describe, expect, it } from "vitest";

import { coverageLabel, coverageWidth, featureLabel } from "../Products";

describe("model coverage in the catalogue", () => {
  it("says how many of the working models have it, as the export does", () => {
    expect(coverageLabel(3, 12)).toBe("3 of 12 received");
  });

  it("keeps the denominator on a product nobody has", () => {
    // *0 of 12 received* is something HBA can act on; a bare nought reads as
    // a measurement that came back empty.
    expect(coverageLabel(0, 12)).toBe("0 of 12 received");
  });

  it("draws the bar in proportion, and never past full", () => {
    expect(coverageWidth(3, 12)).toBe("25%");
    expect(coverageWidth(14, 12)).toBe("100%");
    expect(coverageWidth(0, 0)).toBe("0%");
  });
});

describe("the feature request column", () => {
  it("says Active while a request is showing to models", () => {
    expect(featureLabel(true)).toBe("Active");
  });

  it("draws nothing for a hidden request or none at all, as the export does", () => {
    expect(featureLabel(false)).toBeNull();
    expect(featureLabel(null)).toBeNull();
  });
});
