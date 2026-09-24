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

/** The export's words and tones for each state in her month list. */
const LIST_WORD: Record<MonthListState, { word: string; tone: string }> = {
  open: { word: "in progress", tone: "pmonths__state--open" },
  approved: { word: "approved", tone: "pmonths__state--agreed" },
  paid: { word: "paid", tone: "pmonths__state--agreed" },
  settled: { word: "settled", tone: "pmonths__state--settled" },
};

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
    "/earnings": "How this adds up",
    /* The export titles this screen **Payments** and calls the row that
       opens it *Payment history* - the row says what she will find, the
       screen says where she is. Ours said *Payment history* twice. */
    "/payments": "Payments",
    "/you/payout": "Payment details",
    "/you/details": "Personal and contact details",
    "/you/sizes": "Height and weight",
    "/you/notifications": "Notifications",
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

  const monthly = Boolean(month && months && onMonth && ["/", "/orders", "/ranking"].includes(pathname));

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
            {codePending ? "Code being checked" : "HBA ambassador"}{code && <> · <button type="button" className="phead__inline-code" onClick={copy}>{copied ? "Copied" : code}</button></>}
          </span>
        </div>
        {monthly && (
          <button
            type="button"
            className="phead__month"
            aria-expanded={listOpen}
            aria-controls="portal-months"
            aria-label={`Month: ${formatMonth(month!)}`}
            onClick={() => setListOpen((was) => !was)}
          >
            <span>{shortMonth(month!)}</span>
            <span className="phead__caret" aria-hidden="true">▼</span>
          </button>
        )}
      </header>
      {monthly && listOpen && (
        <div className="pmonths" id="portal-months">
          {months!.map((value) => {
            const state = states?.[value];
            return (
              <button
                key={value}
                type="button"
                className={value === month ? "pmonths__month pmonths__month--on" : "pmonths__month"}
                aria-current={value === month ? "true" : undefined}
                onClick={() => { onMonth!(value); setListOpen(false); }}
              >
                <span>{formatMonth(value)}</span>
                {state && <span className={`pmonths__state ${LIST_WORD[state].tone}`}>{LIST_WORD[state].word}</span>}
              </button>
            );
          })}
        </div>
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
              {tab.label}
            </NavLink>
          ))}
        </div>
      </nav>}
    </>
  );
}
