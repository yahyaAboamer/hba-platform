import { useState } from "react";
import {
  Link,
  NavLink,
  Outlet,
  useLocation,
  useOutletContext,
} from "react-router-dom";

import { formatMonth } from "../lib/money";
import type { Me } from "../screens/MyDetails";
import "./AffiliateLayout.css";

/** Approved mobile navigation; account and detail views sit outside the tab bar. */
const TABS = [
  { to: "/", label: "Home", end: true },
  { to: "/orders", label: "Orders" },
  { to: "/wardrobe", label: "Wardrobe" },
  { to: "/targets", label: "Targets" },
  { to: "/ranking", label: "Ranking" },
];

export type PortalContext = {
  /**
   * What the month on screen is, in a word. Set by whichever screen loaded
   * it, because only the screen has the figure — the bar sits above them all
   * and has no data of its own.
   *
   * `null` until something says, so the bar never guesses.
   */
  monthState?: string | null;
  setMonthState?: (state: string | null) => void;
  /**
   * Their record, already loaded by `AffiliatePortal`.
   *
   * Passed down rather than fetched again: two screens want the payout
   * destination, and a second request for it would be a second answer that
   * goes stale the moment the first one changes.
   */
  me: Me;
  month: string;
  months: string[];
  setMonth: (month: string) => void;
  /** Re-read their record after something changes. */
  reload: () => void;
};

export function usePortal(): PortalContext {
  return useOutletContext<PortalContext>();
}

/**
 * Their name, their code, and the way in to their own details.
 *
 * **The code is here rather than on one screen**, because it is the thing
 * they give out, the thing customers type, and the reason every figure in
 * this portal exists. It used to live three taps away.
 *
 * On the You screen the whole thing collapses to a way back: their name is
 * already the heading there, and an avatar linking to the page you are on is
 * a control that does nothing.
 */
export function PortalHeader({
  name,
  code,
  codePending,
  month, months, onMonth,
}: {
  name: string;
  code: string | null;
  codePending: boolean;
  month?: string; months?: string[]; onMonth?: (month: string) => void;
}) {
  const { pathname } = useLocation();
  const [copied, setCopied] = useState(false);

  const secondaryTitles: Record<string,string> = {"/you":"You", "/earnings":"How this adds up", "/payments":"Payment history", "/you/payout":"Payment details", "/glossary":"Help"};
  const isPrimary = TABS.some(tab => tab.to === pathname);
  if (!isPrimary) {
    return (
      <header className="phead phead--back">
        <Link to="/" className="phead__back">
          ← Back
        </Link>
        <span>{secondaryTitles[pathname] ?? "Details"}</span>
      </header>
    );
  }

  async function copy() {
    if (!code) return;
    try {
      await navigator.clipboard.writeText(code);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1400);
    } catch {
      // Denied, or an insecure context. The code is on screen and readable,
      // so the button quietly does nothing rather than raising an error about
      // a convenience.
    }
  }

  return (
    <header className="phead">
      <Link to="/you" className="phead__avatar" aria-label="Your details">
        {/* Their initial. `name` is never empty - the application requires it -
            but a fallback costs nothing and avoids an empty circle. */}
        {name.trim().charAt(0).toUpperCase() || "·"}
      </Link>
      <div className="phead__who">
        <span className="phead__name">{name}</span>
        <span className="phead__since">
          {codePending ? "Code being checked" : "HBA ambassador"}{code && <> · <button type="button" className="phead__inline-code" onClick={copy}>{copied ? "Copied" : code}</button></>}
        </span>
      </div>
      {month && months && onMonth && ["/", "/orders", "/ranking"].includes(pathname) &&
        <select className="phead__month" aria-label="Month" value={month} onChange={event => onMonth(event.target.value)}>
          {months.map(value => <option key={value} value={value}>{formatMonth(value)}</option>)}
        </select>}

    </header>
  );
}

export function AffiliateLayout({
  context,
  header,
}: {
  context: PortalContext;
  header: React.ReactNode;
}) {
  const { pathname } = useLocation();
  return (
    <>
      {header}

      <div className="portal__body">
        <Outlet context={context} />
      </div>

      {/*
       * Below the content and fixed to the bottom of the window. The safe-area
       * inset matters on an iPhone: without it the last tab sits under the
       * home indicator and takes two attempts to press.
       */}
      {TABS.some(tab => tab.to === pathname) && <nav className="tabs" aria-label="Sections">
        <div className="tabs__inner">
          {TABS.map((tab) => (
            <NavLink
              key={tab.to}
              to={tab.to}
              end={tab.end}
              className={({ isActive }) =>
                isActive ? "tabs__tab tabs__tab--on" : "tabs__tab"
              }
            >
              {tab.label}
            </NavLink>
          ))}
        </div>
      </nav>}
    </>
  );
}
