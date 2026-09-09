/**
 * Which theme a device is in, remembered on that device.
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
 *
 * ## Two keys, not one
 *
 * The portal and the maintainer's tool remember separately, because they are
 * not the same decision. A model chooses how her phone looks at night; the
 * two people reconciling payroll choose how a laptop looks under an office
 * light, and one of them is often the same person in both roles. Sharing a
 * key would mean flipping the portal's theme by adjusting the tool's.
 *
 * The *values* are shared - ADR 0039 - so a theme means the same thing on
 * both. Only the preference is separate.
 */

export type Theme = "dark" | "light";

/** Which half is asking. */
export type Surface = "portal" | "maintainer";

const KEYS: Record<Surface, string> = {
  portal: "hba.portal.theme",
  maintainer: "hba.maintainer.theme",
};

/** What this device chose last for that half, or dark. */
export function storedTheme(surface: Surface = "portal"): Theme {
  try {
    const found = window.localStorage.getItem(KEYS[surface]);
    if (found === "dark" || found === "light") return found;
  } catch {
    // Private window, or a browser set to block site data. Not an error -
    // the default is a perfectly good answer.
  }
  return "dark";
}

/** Remember it. Silently does nothing where storage is unavailable. */
export function storeTheme(theme: Theme, surface: Surface = "portal"): void {
  try {
    window.localStorage.setItem(KEYS[surface], theme);
  } catch {
    // As above. The theme still applies for this visit; it just will not
    // survive a reload, which is better than refusing to switch at all.
  }
}

/**
 * Stamp the maintainer's theme on `<html>`.
 *
 * The portal puts `data-theme` on its own root element, because the screens a
 * model sees before the layout exists would otherwise paint in the wrong
 * theme for a frame. The maintainer's tool has no such approach screens, and
 * its sign-in and first-run pages sit outside the layout entirely - so the
 * document element is the one place that covers all of them.
 *
 * `tokens.css` matches `[data-theme="dark"]` unanchored, so the same block
 * serves both.
 */
export function applyMaintainerTheme(theme: Theme): void {
  document.documentElement.setAttribute("data-theme", theme);
}
