import { describe, expect, it } from "vitest";

import { coverageLabel, featureLabel } from "../Products";

describe("model coverage in the catalogue", () => {
  it("counts models, and says so", () => {
    expect(coverageLabel(4)).toBe("4 models");
    expect(coverageLabel(1)).toBe("1 model");
  });

  it("writes nobody out rather than printing a nought", () => {
    // A 0 in a column of counts reads as a measurement that came back empty.
    // "Nobody yet" is the thing HBA would act on.
    expect(coverageLabel(0)).toBe("Nobody yet");
  });
});

describe("the feature request column", () => {
  it("has three states, not two", () => {
    expect(featureLabel(true)).toBe("Showing to models");
    expect(featureLabel(false)).toBe("Hidden");
    expect(featureLabel(null)).toBe("—");
  });

  it("never calls a hidden request an absent one", () => {
    // Somebody wrote that wording and took it down; it is still there to put
    // back. Collapsing hidden into none is how a paragraph gets retyped.
    expect(featureLabel(false)).not.toBe(featureLabel(null));
  });
});
