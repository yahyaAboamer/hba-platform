import { useEffect, useState } from "react";
import {
  Link,
  NavLink,
  Outlet,
  useLocation,
  useNavigate,
  useOutletContext,
} from "react-router-dom";

import { api } from "../lib/api";
import { formatMonth, shortMonth } from "../lib/money";
import { monthListStates } from "../lib/portal";
import type { MonthListState, MyPayments } from "../lib/portal";
import type { Me } from "../screens/MyDetails";
import { MonthSheet } from "./MonthSheet";
import "./AffiliateLayout.css";

/** Stroke icons for the tab bar, in the portal's weight - never emoji. */
function TabIcon({ name }: { name: string }) {
  const paths: Record<string, React.ReactNode> = {
    home: <><path d="M4 10.5 12 4l8 6.5V20H4v-9.5Z" /><path d="M10 20v-6h4v6" /></>,
    orders: <><path d="M6 3h12v18l-3-2-3 2-3-2-3 2V3Z" /><path d="M9 8h6M9 12h6" /></>,
    wardrobe: <path d="M8 4 4 6.5l2 4 2-1V20h8V9.5l2 1 2-4L16 4a4 4 0 0 1-8 0Z" />,
    targets: <><circle cx="12" cy="12" r="8.5" /><circle cx="12" cy="12" r="4.5" /><circle cx="12" cy="12" r="1" /></>,
    ranking: <path d="M5 20V12M12 20V5M19 20v-5" />,
  };
  return (
    <svg className="tabs__icon" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      {paths[name]}
    </svg>
  );
}

/**
 * Approved mobile navigation; account and detail views sit outside the tab bar.
 * Icons since batch L: five words in a row are read one by one, five shapes
 * are recognised at a glance.
 */
const TABS = [
  { to: "/", label: "Home", icon: "home", end: true },
  { to: "/orders", label: "Orders", icon: "orders" },
  { to: "/wardrobe", label: "Wardrobe", icon: "wardrobe" },
  { to: "/targets", label: "Targets", icon: "targets" },
  { to: "/ranking", label: "Ranking", icon: "ranking" },
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
 * Their name, their code, and the way in to their own details - and on Home,
 * Orders and Ranking, the month.
 *
 * **The code is here rather than on one screen**, because it is the thing
 * they give out, the thing customers type, and the reason every figure in
 * this portal exists. It used to live three taps away.
 *
 * **The month is the export's compact control**: the short month and a caret
 * (*Nov ▼*), opening a list under the header of every month she can see, each
 * with where it has got to. It was a native select reading *September 2026*,
 * wide enough to cut her own code off the line beside it.
 *
 * On a view that is not one of the five, the whole thing collapses to a way
 * back: their name is already the heading there, and an avatar linking to the
 * page you are on is a control that does nothing.
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
  const navigate = useNavigate();
  const [copied, setCopied] = useState(false);
  const [listOpen, setListOpen] = useState(false);
  const [states, setStates] = useState<Record<string, MonthListState> | null>(null);

  // The list belongs to the screen it was opened on. Moving to another tab
  // or view closes it, as the export's tab and view changes do.
  useEffect(() => setListOpen(false), [pathname]);

  // Read each time it opens, so a month approved or paid since she last
  // looked says so. A failed read leaves the months without words.
  useEffect(() => {
    if (!listOpen || !months) return;
    let live = true;
    api.get<MyPayments>("/api/me/payments")
      .then((body) => { if (live) setStates(monthListStates(months, body)); })
      .catch(() => { if (live) setStates(null); });
    return () => { live = false; };
  }, [listOpen, months]);

  const secondaryTitles: Record<string,string> = {
    "/you": "You",
    "/you/terms": "Your terms",
    "/earnings": "How this adds up",
    /* The export titles this screen **Payments** and calls the row that
       opens it *Payment history* - the row says what she will find, the
       screen says where she is. Ours said *Payment history* twice. */
    "/payments": "Payments",
    "/you/payout": "Where you are paid",
    "/you/details": "Contact & delivery",
    "/you/sizes": "Height and weight",
    "/you/notifications": "Notifications",
    "/you/guide": "Dashboard guide",
    "/glossary": "Help",
    "/best": "All products sold",
  };
  const isPrimary = TABS.some(tab => tab.to === pathname);
  if (!isPrimary) {
    return (
      <div className="phead-bar">
        <header className="phead phead--back">
          {/*
           * Back to wherever she came from, not to Home. *All products sold* is
           * reached from the wardrobe and the payment detail from the payment
           * list, and a Back that always went Home would throw away her place
           * both times. Home is the fallback for somebody who arrived on a link.
           */}
          <button
            type="button"
            className="phead__back"
            onClick={() => (window.history.length > 1 ? navigate(-1) : navigate("/"))}
          >
            ← Back
          </button>
          <span className="phead__title">{secondaryTitles[pathname] ?? "Details"}</span>
        </header>
      </div>
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

  // Home carries its own month control since batch L - one line, in the
  // page - so the header's is only for Orders and Ranking.
  const monthly = Boolean(month && months && onMonth && ["/orders", "/ranking"].includes(pathname));

  return (
    <div className="phead-bar">
      <header className="phead">
        <Link to="/you" className="phead__avatar" aria-label="Your details">
          {/* Their initial. `name` is never empty - the application requires it -
              but a fallback costs nothing and avoids an empty circle. */}
          {name.trim().charAt(0).toUpperCase() || "·"}
        </Link>
        <div className="phead__who">
          <span className="phead__name">{name}</span>
          <span className="phead__since">
            {codePending ? "Code being checked" : "HBA ambassador"}
            {monthly && code && <> · <button type="button" className="phead__inline-code" onClick={copy}>{copied ? "Copied" : code}</button></>}
          </span>
        </div>
        {monthly ? (
          <button
            type="button"
            className="phead__month"
            aria-haspopup="dialog"
            aria-expanded={listOpen}
            aria-label={`Month: ${formatMonth(month!)}`}
            onClick={() => setListOpen(true)}
          >
            <span>{shortMonth(month!)}</span>
            <span className="phead__caret" aria-hidden="true">▼</span>
          </button>
        ) : (
          code && (
            /* The thing she gives out, as a button that copies it (batch L).
               It was a word in the grey line under her name. */
            <button
              type="button"
              className="phead__code"
              onClick={copy}
              aria-label={copied ? "Code copied" : `Copy your code ${code}`}
            >
              {copied ? "Copied" : code}
              <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                <rect x="8" y="8" width="12" height="12" rx="2.5" />
                <path d="M16 8V6a2 2 0 0 0-2-2H6a2 2 0 0 0-2 2v8a2 2 0 0 0 2 2h2" />
              </svg>
            </button>
          )
        )}
      </header>
      {monthly && listOpen && (
        <MonthSheet
          months={months!}
          current={month!}
          states={states}
          onPick={(value) => { onMonth!(value); setListOpen(false); }}
          onClose={() => setListOpen(false)}
        />
      )}
    </div>
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
              <span className="tabs__glyph"><TabIcon name={tab.icon} /></span>
              <span className="tabs__label">{tab.label}</span>
            </NavLink>
          ))}
        </div>
      </nav>}
    </>
  );
}
