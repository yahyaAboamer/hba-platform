import { NavLink, Outlet, useLocation, useOutletContext } from "react-router-dom";

import { formatMonth } from "../lib/money";
import "./AffiliateLayout.css";

/**
 * §12.5: **the affiliate portal is phone-first.**
 *
 * A bottom tab bar rather than the maintainer's sidebar, because she is
 * holding the phone in one hand and her thumb does not reach the top of it.
 * The maintainer's `Layout` is the opposite instruction: seven sections down
 * the left, built for scanning twenty models at month end on a laptop.
 *
 * Earnings and Payments are separate tabs and stay separate. *What I have
 * earned* and *what has arrived* are different questions with different
 * answers for most of any month, and merging them is how a model ends up
 * believing she has been paid twice or not at all.
 */
const TABS = [
  { to: "/", label: "Earnings", end: true },
  { to: "/orders", label: "Orders" },
  { to: "/you", label: "You" },
];

/** Tabs that are about one month. The rest are not, and get no month bar. */
const MONTH_SCOPED = new Set(["/", "/orders"]);

export type PortalContext = {
  month: string;
  months: string[];
  setMonth: (month: string) => void;
  /** Re-read her record after something changes. */
  reload: () => void;
};

export function usePortal(): PortalContext {
  return useOutletContext<PortalContext>();
}

export function AffiliateLayout({ context }: { context: PortalContext }) {
  const { pathname } = useLocation();
  const { month, months, setMonth } = context;

  const index = months.indexOf(month);
  // Newest first, so "older" is forward through the list.
  const older = index >= 0 && index < months.length - 1 ? months[index + 1] : null;
  const newer = index > 0 ? months[index - 1] : null;

  return (
    <>
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
