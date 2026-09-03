/*
 * The portal's theme preference.
 *
 * Three states, not two: light, dark, or Auto — which follows the
 * dark-or-light setting already chosen on this device. The preference is the
 * model's own decision and lives in localStorage under one key; the resolved
 * theme is what the paint actually is. Default is Auto, because somebody who
 * never asked for a choice should get the one the device already made.
 *
 * The inline script in index.html repeats resolveTheme's one rule before the
 * bundle loads, so the first paint is already right. Where the two disagree,
 * this module is the source of truth.
 */

export type ThemePreference = "light" | "dark" | "auto";
export type ResolvedTheme = "light" | "dark";

/** One key, one meaning. Renaming it silently drops every saved choice. */
export const THEME_STORAGE_KEY = "hba-theme";

/** Anything unreadable is Auto, never an error. */
export function parseThemePreference(value: string | null): ThemePreference {
  return value === "light" || value === "dark" || value === "auto"
    ? value
    : "auto";
}

/** The whole decision, in one pure function. */
export function resolveTheme(
  preference: ThemePreference,
  systemPrefersDark: boolean,
): ResolvedTheme {
  if (preference === "auto") return systemPrefersDark ? "dark" : "light";
  return preference;
}

function systemPrefersDark(): boolean {
  return (
    typeof window !== "undefined" &&
    window.matchMedia("(prefers-color-scheme: dark)").matches
  );
}

export function readThemePreference(): ThemePreference {
  try {
    return parseThemePreference(localStorage.getItem(THEME_STORAGE_KEY));
  } catch {
    // Storage can refuse (private modes, embedded browsers). Auto is the
    // honest answer, not a failure.
    return "auto";
  }
}

export function storeThemePreference(preference: ThemePreference): void {
  try {
    localStorage.setItem(THEME_STORAGE_KEY, preference);
  } catch {
    // Nothing to recover: the choice just does not survive a reload.
  }
}

/** Paints the resolved theme onto <html>. Idempotent. */
export function applyTheme(preference: ThemePreference): ResolvedTheme {
  const resolved = resolveTheme(preference, systemPrefersDark());
  document.documentElement.dataset.theme = resolved;
  return resolved;
}

/*
 * Applies the stored preference and keeps Auto honest: while the preference is
 * Auto, a change to the device's own setting re-paints. Called once from
 * main.tsx — the inline script has already painted, so this only catches up on
 * anything that changed while the bundle was loading.
 */
export function initTheme(): void {
  applyTheme(readThemePreference());
  window
    .matchMedia("(prefers-color-scheme: dark)")
    .addEventListener("change", () => {
      if (readThemePreference() === "auto") applyTheme("auto");
    });
}
