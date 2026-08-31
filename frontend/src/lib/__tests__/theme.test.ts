/*
 * The theme resolver, tested the way the money arithmetic is: pure functions
 * only, no DOM, so the suite runs anywhere.
 */
import { describe, expect, it } from "vitest";
import {
  parseThemePreference,
  resolveTheme,
  type ThemePreference,
} from "../theme";

describe("resolveTheme", () => {
  it("an explicit choice wins over the device", () => {
    expect(resolveTheme("light", true)).toBe("light");
    expect(resolveTheme("dark", false)).toBe("dark");
  });

  it("Auto defers to the device", () => {
    expect(resolveTheme("auto", true)).toBe("dark");
    expect(resolveTheme("auto", false)).toBe("light");
  });
});

describe("parseThemePreference", () => {
  it("reads the three states it knows", () => {
    const known: ThemePreference[] = ["light", "dark", "auto"];
    for (const preference of known) {
      expect(parseThemePreference(preference)).toBe(preference);
    }
  });

  it("anything unreadable is Auto, not an error", () => {
    expect(parseThemePreference(null)).toBe("auto");
    expect(parseThemePreference("")).toBe("auto");
    // A value from another lifetime of this key, or a typed-over one.
    expect(parseThemePreference("system")).toBe("auto");
    expect(parseThemePreference("DARK")).toBe("auto");
  });
});
