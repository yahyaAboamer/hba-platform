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

/**
 * §12.5: **the affiliate portal is phone-first.**
 *
 * A bottom tab bar rather than the maintainer's sidebar, because they are
 * holding the phone in one hand and their thumb does not reach the top of it.
 * The maintainer's `Layout` is the opposite instruction: seven sections down
 * the left, built for scanning twenty models at month end on a laptop.
 *
 * ## The five, from the approved design
 *
 * **Home · Orders · Wardrobe · Targets · Ranking** (rule S03,
 * `docs/redesign/designs/Affiliate Portal v3.dc.html`). Three of them are new
 * or renamed, so what happened to the old ones is worth writing down rather
 * than leaving somebody to diff it:
 *
 * - **Month → Home.** The same screen. The word "month" was the tool's word
 *   for it; "home" is where a person thinks they are.
 * - **Payments moved into You**, behind the avatar. It is a record of what
 *   has arrived rather than something checked weekly, and the slot was needed.
 *   The route is unchanged and the You screen links to it, so a bookmark and
 *   a receipt email both still land.
 * - **Year and Grow left the bar** and kept their routes. The design puts the
 *   year's performance on Home (rule M01) and the discount code in the header
 *   chip, which is where Grow's only real content already is. Folding them in
 *   properly is Phase 07A; until then Home links to both, because deleting a
 *   working screen to match a drawing is not a redesign.
 * - **Wardrobe, Targets and Ranking** have nothing behind them yet. They say
 *   so — see `NotBuiltYet`. They are here early because a tab bar that grows
 *   a slot every few weeks moves every other tab under her thumb each time.
 *
 * ## Why "You" is not a tab
 *
 * It is reached from the avatar in the header instead. That is where a person
 * looks for their own account on every other application they use, and it
 * leaves all five slots for what she came to find out.
 */
const TABS = [
  { to: "/", label: "Home", end: true },
  { to: "/orders", label: "Orders" },
  { to: "/wardrobe", label: "Wardrobe" },
  { to: "/targets", label: "Targets" },
  { to: "/ranking", label: "Ranking" },
];

/**
 * Tabs that are about one month. The rest are not, and get no month bar.
 *
 * Ranking is month-scoped in the design's proposal (D03) but has no screen to
 * scope yet, so it is left out until Phase 07B decides its period rather than
 * being given a bar it does not use.
 */
const MONTH_SCOPED = new Set(["/", "/orders"]);

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
}: {
  name: string;
  code: string | null;
  codePending: boolean;
}) {
  const { pathname } = useLocation();
  const [copied, setCopied] = useState(false);

  if (pathname === "/you") {
    return (
      <header className="phead phead--back">
        <Link to="/" className="phead__back">
          ← Back
        </Link>
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
          {codePending ? "code being checked" : "HBA affiliate"}
        </span>
      </div>
      {code && (
        <button type="button" className="phead__code" onClick={copy}>
          {copied ? "Copied" : code}
        </button>
      )}
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
  const { month, months, setMonth } = context;

  const index = months.indexOf(month);
  // Newest first, so "older" is forward through the list.
  const older = index >= 0 && index < months.length - 1 ? months[index + 1] : null;
  const newer = index > 0 ? months[index - 1] : null;

  return (
    <>
      {header}

      {MONTH_SCOPED.has(pathname) && (
        <nav className="months" aria-label="Which month">
          <button
            type="button"
            className="months__step"
            onClick={() => older && setMonth(older)}
            disabled={!older}
            aria-label="The month before"
          >
            ←
          </button>
          <span className="months__current">
            {formatMonth(month)}
            {context.monthState && (
              <span className="months__state">{context.monthState}</span>
            )}
          </span>
          <button
            type="button"
            className="months__step"
            onClick={() => newer && setMonth(newer)}
            disabled={!newer}
            aria-label="The month after"
          >
            →
          </button>
        </nav>
      )}

      <div className="portal__body">
        <Outlet context={context} />
      </div>

      {/*
       * Below the content and fixed to the bottom of the window. The safe-area
       * inset matters on an iPhone: without it the last tab sits under the
       * home indicator and takes two attempts to press.
       */}
      <nav className="tabs" aria-label="Sections">
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
      </nav>
    </>
  );
}
