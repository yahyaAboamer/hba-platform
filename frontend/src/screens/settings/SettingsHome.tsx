import { Navigate, useLocation } from "react-router-dom";

import { can } from "../../lib/api";
import type { Session } from "../../lib/api";
import { isOwner } from "../../frame/where";

/**
 * Where an old `/settings?section=…` link lands now (Batch 2.3, contract §5).
 * Somebody who may not open the new home goes to *Me*, which every member of
 * staff has, rather than to a page that refuses them.
 */
export function settingsHome(session: Session, section: string | null): string {
  const me = "/settings/me";
  const owner = isOwner(session);
  switch (section) {
    case "team":
      return owner ? "/settings/team" : me;
    case "shopify":
      return owner ? "/settings/integrations" : me;
    case "historical":
      return can(session, "compensation.manage") ? "/affiliates/historical" : me;
    case "codes":
      return can(session, "affiliates.view") ? "/affiliates/brand-codes" : me;
    case "policy":
    case "advanced":
      return owner ? "/settings/company" : me;
    case "activity":
      if (owner) return "/settings/company";
      return can(session, "audit.view") && can(session, "affiliates.view") ? "/affiliates/activity" : me;
    default:
      return me;
  }
}

/** `/settings`: goes on to the new home of the section it names, or to *Me*. Keeps the other query keys. */
export function SettingsHome({ session }: { session: Session }) {
  const { search, hash, state } = useLocation();
  const query = new URLSearchParams(search);
  const section = query.get("section");
  query.delete("section");
  const rest = query.toString();
  return (
    <Navigate
      to={{ pathname: settingsHome(session, section), search: rest ? `?${rest}` : "", hash }}
      state={state}
      replace
    />
  );
}
