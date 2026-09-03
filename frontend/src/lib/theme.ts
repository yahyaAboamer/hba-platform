/**
 * Which theme the portal is in, remembered on this device.
 *
 * **Dark is the default, and the operating system is not consulted.** The
 * business asked for dark by default with a toggle; following
 * `prefers-color-scheme` instead would quietly overrule that on every phone
 * set to light, which is most of them.
 *
 * The choice lives in `localStorage` and nowhere else - it is a per-device
 * preference about how a screen looks, not a fact about the account, so
 * putting it on the server would mean a write, a migration and a round trip
 * to answer a question the browser already knows.
 *
 * Every access is wrapped. `localStorage` does not merely return null in a
 * private window or with site data blocked - **it throws on access**, and an
 * exception here would take the whole portal down before it painted.
 */

export type Theme = "dark" | "light";

const KEY = "hba.portal.theme";

/** What this device chose last, or dark. */
export function storedTheme(): Theme {
  try {
    const found = window.localStorage.getItem(KEY);
    if (found === "dark" || found === "light") return found;
  } catch {
    // Private window, or a browser set to block site data. Not an error -
    // the default is a perfectly good answer.
  }
  return "dark";
}

/** Remember it. Silently does nothing where storage is unavailable. */
export function storeTheme(theme: Theme): void {
  try {
    window.localStorage.setItem(KEY, theme);
  } catch {
    // As above. The theme still applies for this visit; it just will not
    // survive a reload, which is better than refusing to switch at all.
  }
}
