import { useState } from "react";
import {
  Link,
  NavLink,
  Outlet,
  useLocation,
  useOutletContext,
} from "react-router-dom";

import { formatMonth } from "../lib/money";
import "./AffiliateLayout.css";

/**
 * §12.5: **the affiliate portal is phone-first.**
 *
 * A bottom tab bar rather than the maintainer's sidebar, because they are
 * holding the phone in one hand and their thumb does not reach the top of it.
 * The maintainer's `Layout` is the opposite instruction: seven sections down
 * the left, built for scanning twenty models at month end on a laptop.
 *
 * Earnings and Payments are separate tabs and stay separate. *What I have
 * earned* and *what has arrived* are different questions with different
 * answers for most of any month, and merging them is how a model ends up
 * believing they have been paid twice or not at all.
 *
 * ## Why "You" is not a tab any more
 *
 * It is reached from the avatar in the header instead. That is where a person
 * looks for their own account on every other application they use, and it
 * frees the fifth slot for **Grow** - the only tab that is about what they do
 * rather than what they are owed.
 */
const TABS = [
  { to: "/", label: "Month", end: true },
  { to: "/orders", label: "Orders" },
  { to: "/payments", label: "Payments" },
  { to: "/year", label: "Year" },
  { to: "/grow", label: "Grow" },
];

/** Tabs that are about one month. The rest are not, and get no month bar. */
const MONTH_SCOPED = new Set(["/", "/orders"]);

export type PortalContext = {
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
          <span className="months__current">{formatMonth(month)}</span>
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
