import { useEffect } from "react";

import { api } from "../lib/api";
import { applyMaintainerChoice, storedMaintainerChoice, themePickedThisVisit } from "../lib/theme";
import type { ThemeChoice } from "../lib/theme";

/**
 * The staff tools' theme, for whichever shell is open - the affiliate
 * dashboard's or Operations' (ADR 0057).
 *
 * This device's copy paints the first frame; the account's choice, once it
 * answers, is the one that holds (Settings audit P1). *Match my device* keeps
 * following the device while the tool is open.
 */
export function useMaintainerTheme(): void {
  useEffect(() => {
    applyMaintainerChoice(storedMaintainerChoice());
    api
      .get<{ theme: ThemeChoice | null }>("/api/staff/me/preferences")
      .then((body) => {
        if (body.theme && !themePickedThisVisit()) applyMaintainerChoice(body.theme);
      })
      .catch(() => undefined);
    let media: MediaQueryList | null = null;
    try {
      media = window.matchMedia("(prefers-color-scheme: light)");
    } catch {
      media = null;
    }
    const follow = () => {
      if (storedMaintainerChoice() === "system") applyMaintainerChoice("system");
    };
    media?.addEventListener?.("change", follow);
    return () => media?.removeEventListener?.("change", follow);
  }, []);
}
