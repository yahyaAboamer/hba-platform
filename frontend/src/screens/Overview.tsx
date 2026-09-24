import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { Money } from "../components/Money";
import { SalesByMonth } from "../components/SalesByMonth";
import { MonthPicker } from "../components/MonthPicker";
import type { MonthLock } from "../components/MonthPicker";
import { api } from "../lib/api";
import type { Session } from "../lib/api";
import { currentMonth, formatMonth, platformMonths } from "../lib/money";

type PayrollRow = {
  affiliate_id: number;
  name: string;
  calculation_state?: string;
  obligation_piastres?: number;
  blockers?: string[];
  is_payable?: boolean;
  /* Historical months carry sales and no commission figure (ADR 0014). */
  net_sales_piastres?: number;
  orders?: number | { earned: number; pending: number; void: number };
};

type PayrollMonth = {
  month: string;
  is_historical: boolean;
  affiliates: PayrollRow[];
  totals: {
    affiliates: number;
    payable_affiliates: number;
    blocked_affiliates: number;
    obligation_piastres: number;
  };
};

/** §16's in-platform notifications. Empty on a healthy platform. */
type Attention = {
  items: {
    key: string;
    severity: "blocking" | "attention";
    text: string;
    /** The export's second line, naming which model or which order. */
    detail: string | null;
    where: string;
    /** The words on the button — *Open correction*, not *Open*. */
    action: string;
  }[];
  blocking: number;
  /** Still true, still unresolved, and somebody chose to stop seeing it. */
  muted: {
    key: string;
    severity: "blocking" | "attention";
    text: string;
    where: string;
  }[];
};

type SyncStatus = {
  orders_indexed: number;
  go_live_month: string | null;
  payroll_can_be_approved: boolean;
  jobs: { failed: number };
};

/**
 * Where a month stands.
 *
 * §12.3's noted tension applies here: a page carries summary figures only where
 * they support the decision made on that page. The decision on this page is
 * *can I run payroll for this month, and if not, what is stopping me* — so the
 * figures are what is owed, who is blocked, and why.
 *
 * Nothing here is a chart. Twenty rows is not a dataset.
 */
/**
 * The owner's month, in the parts a payroll decision is made from. A01.
 *
 * **Every figure arrives computed.** The parts of an expected payout are
 * carved out of the one rounded total on the server, so this renders them and
 * never sums them — three components added in a browser would disagree with
 * the payroll screen the first time one of them rounded, on the screen whose
 * only job is to say how much money to find.
 */
type Summary = {
  active_models: number;
  sales_piastres: number;
  ready: number;
  blocked: number;
  expected: {
    payout_piastres: number;
    commission_piastres: number;
    fixed_piastres: number;
    guarantee_top_up_piastres: number;
  };
  /** Keyed by why: `no_target`, `not_recorded_this_week`, `behind`. */
  selling_models: number;
  needs_review: Record<string, number>;
  /** A row per model — what was asked for, what she made, when it was
   *  last written down. The counts above say how many; this says who. */
  content: {
    affiliate_id: number;
    name: string;
    required_videos: number | null;
    required_stories: number | null;
    actual_videos: number | null;
    actual_stories: number | null;
    last_update: string | null;
  }[];
  top: {
    affiliate_id: number;
    name: string;
    code: string | null;
    rank: number;
    sales_piastres: number;
    uses: number;
  }[];
  /** January to this month, one figure each, for the chart at the foot of
   *  the approved Home. */
  year: { month: string; sales_piastres: number; sales: string }[];
};

/**
 * *5 / 6*, or an em dash where the question was never asked.
 *
 * **A missing requirement is not zero.** Nobody asked her for anything is
 * HBA's own omission; she has produced nothing is a fact about her month, and
 * a table that printed `0 / 0` for the first would put a model in front of the
 * owner as behind when the gap is HBA's.
 */
export function progressLabel(
  done: number | null,
  required: number | null,
): string | null {
  if (required === null) return null;
  return `${done ?? 0} / ${required}`;
}

/** *Sep*, as the export abbreviates it on the count card. */
function shortMonth(month: string): string {
  return new Date(`${month}-01T00:00:00`).toLocaleDateString("en-GB", {
    month: "short",
  });
}

/**
 * **Only the models needing review**, worst first, at most six.
 *
 * The panel is called *Content progress to review* and the export means it:
 * a model who has produced everything asked of her is not something to
 * review, and listing her pushes the one who has produced nothing off the
 * bottom. Nothing recorded at all sorts above any shortfall, because it is
 * the case somebody has to chase rather than measure.
 *
 * Six, because this is a panel beside another panel and not a screen. The
 * whole table is one click away under *Targets →*.
 */
export function toReview<T extends {
  required_videos: number | null;
  required_stories: number | null;
  actual_videos: number | null;
  actual_stories: number | null;
}>(rows: T[]): T[] {
  const shortfall = (row: T) => {
    if (row.required_videos === null) return null; // nobody asked
    if (row.actual_videos === null && row.actual_stories === null) return null;
    return (
      Math.max((row.required_videos ?? 0) - (row.actual_videos ?? 0), 0) +
      Math.max((row.required_stories ?? 0) - (row.actual_stories ?? 0), 0)
    );
  };
  return rows
    .map((row) => ({ row, short: shortfall(row) }))
    // `null` is *nothing recorded* — which includes nobody having asked. Both
    // need a person; neither can be measured.
    .filter((x) => x.short === null || x.short > 0)
    .sort((a, b) => (b.short ?? Infinity) - (a.short ?? Infinity))
    .slice(0, 6)
    .map((x) => x.row);
}

/** The day it was written down. The time of day decides nothing here. */
function formatDay(iso: string) {
  return new Date(iso).toLocaleDateString("en-GB", {
    day: "numeric", month: "long", year: "numeric",
  });
}

export function Overview({ session }: { session: Session }) {
  // Opens on the working month, which before go-live is the month the
  // platform starts in rather than an August it holds nothing for.
  const [noticeMenu, setNoticeMenu] = useState<string | null>(null);
  const [month, setMonth] = useState(session.platform.working_month);
  const [payroll, setPayroll] = useState<PayrollMonth | null>(null);
  const [sync, setSync] = useState<SyncStatus | null>(null);
  const [attention, setAttention] = useState<Attention | null>(null);
  const [summary, setSummary] = useState<Summary | null>(null);
  /**
   * Notices hidden for this browsing session only (A10's *temporary hide*).
   *
   * `sessionStorage`, so it comes back next time - which is the whole
   * difference from a mute. Wrapped, because a private window or blocked site
   * data makes the accessor itself throw, and a panel of notices is not worth
   * a blank screen.
   */
  const [hidden, setHidden] = useState<string[]>(() => {
    try {
      return JSON.parse(sessionStorage.getItem("hidden-notices") ?? "[]");
    } catch {
      return [];
    }
  });

  function hide(key: string) {
    setHidden((was) => {
      const next = [...was, key];
      try {
        sessionStorage.setItem("hidden-notices", JSON.stringify(next));
      } catch {
        // Hiding is a convenience. If it cannot be remembered it still works
        // for this view, which is most of the value.
      }
      return next;
    });
  }

  function reloadNotices() {
    api
      .get<Attention>("/api/operations/attention")
      .then(setAttention)
      .catch(() => undefined);
  }

  function mute(key: string) {
    api
      .post("/api/operations/notices/mute", { key })
      .then(reloadNotices)
      .catch((caught) => setError(caught.message));
  }

  function unmute(key: string) {
    api
      .del(`/api/operations/notices/mute/${key}`)
      .then(reloadNotices)
      .catch((caught) => setError(caught.message));
  }
  const [error, setError] = useState<string | null>(null);
  const [lockNote, setLockNote] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    setError(null);
    setSummary(null);
    setPayroll(null);
    Promise.all([
      api.get<PayrollMonth>(`/api/payroll/${month}`),
      api.get<SyncStatus>("/api/operations/sync"),
      api.get<Attention>("/api/operations/attention"),
      api.get<Summary>(`/api/payroll/${month}/summary`),
    ])
      .then(([months, status, needing, month_summary]) => {
        if (!live) return;
        setPayroll(months);
        setSync(status);
        setAttention(needing);
        setSummary(month_summary);
      })
      .catch((caught) => { if (live) setError(caught.message); });
    setLockNote(null);
    return () => { live = false; };
  }, [month]);

  function lockFor(candidate: string): MonthLock {
    if (sync?.go_live_month && candidate < sync.go_live_month) return "historical";
    if (candidate > currentMonth()) return "future";
    return null;
  }



  return (
    <>
      <div className="page__head">
        <div className="page__title"><h1>Home</h1><span className="page__subtitle">{formatMonth(month)}</span></div>
        <MonthPicker value={month} onChange={setMonth} months={platformMonths(session.platform)} lockFor={lockFor}
          onLockedClick={(candidate, lock) => setLockNote(lock === "historical"
            ? `${formatMonth(candidate)} was settled outside this dashboard.`
            : `${formatMonth(candidate)} is still in progress.`)} />
      </div>
      {lockNote && <p className="notice">{lockNote}</p>}
      {error && <p className="notice notice--refused" role="alert">{error}</p>}
      {hidden.length > 0 && <div className="overview__hidden">
        <span>{hidden.length} notices hidden for now</span>
        <button className="button" onClick={() => { setHidden([]); try { sessionStorage.removeItem("hidden-notices"); } catch { /* optional persistence */ } }}>Show again</button>
      </div>}
      {attention && <section className="overview__notices" aria-label="Notifications">
        {attention.items.filter(item => !hidden.includes(item.key)).map(item => <div key={item.key}
          className={`overview__notice ${item.severity === "blocking" ? "overview__notice--blocking" : ""}`}>
          <span className="overview__notice-dot" aria-hidden="true" />
          <div className="overview__notice-copy">
            <span>{item.text}</span>
            {item.detail && <small>{item.detail}</small>}
          </div>
          <Link className="button" to={item.where}>{item.action}</Link>
          <button className="button overview__notice-icon" aria-label={`Options for ${item.text}`} aria-expanded={noticeMenu === item.key}
            onClick={() => setNoticeMenu(noticeMenu === item.key ? null : item.key)}>⋯</button>
          <button className="button overview__notice-icon" aria-label={`Dismiss ${item.text}`} onClick={() => hide(item.key)}>✕</button>
          {noticeMenu === item.key && <div className="overview__notice-menu">
            <button className="button" onClick={() => hide(item.key)}>Hide for now</button>
            {item.severity !== "blocking" && <button className="button" onClick={() => mute(item.key)}>Don't remind me about this item</button>}
          </div>}
        </div>)}
      </section>}
      {attention && attention.muted.length > 0 && <details className="attention__muted">
        <summary>{attention.muted.length} muted notices</summary>
        <ul>{attention.muted.map(item => <li key={item.key}><Link to={item.where}>{item.text}</Link>
          <button className="button" onClick={() => unmute(item.key)}>Show again</button></li>)}</ul>
      </details>}
      {!summary && !error && <p className="empty">Loading…</p>}
      {summary && <>
        <div className="overview__cards">
          <section className="overview__card">
            <h2>Sales generated by models</h2>
            <div className="overview__hero-value"><Money piastres={summary.sales_piastres} /></div>
            {/* Which models the figure came from, as the export says it. A
             *  total with no denominator cannot tell a quiet month from a
             *  broken feed. */}
            <p className="overview__card-note">
              {summary.selling_models} {summary.selling_models === 1 ? "model" : "models"} with
              {" "}attributed orders in {formatMonth(month)}
            </p>
            <Link className="control-font" to={`/orders?month=${month}`}>All attributed orders →</Link>
          </section>
          <section className="overview__card overview__card--payout">
            <h2>{payroll?.is_historical
              ? `Historical earnings for ${formatMonth(month)}`
              : `Expected payment for ${formatMonth(month)}`}
              {!payroll?.is_historical && <span className="state">Estimated</span>}</h2>
            {payroll?.is_historical ? <p className="overview__note">Settled outside this dashboard. Review historical terms in Settings.</p> : <>
              <div className="overview__hero-value"><Money piastres={summary.expected.payout_piastres} /></div>
              <dl className="overview__parts">
                <div><dt>Fixed salary</dt><dd><Money piastres={summary.expected.fixed_piastres} /></dd></div>
                <div><dt>Commission</dt><dd><Money piastres={summary.expected.commission_piastres} /></dd></div>
                {summary.expected.guarantee_top_up_piastres > 0 && <div className="overview__parts--lift"><dt>Guarantee top-ups</dt><dd><Money piastres={summary.expected.guarantee_top_up_piastres} /></dd></div>}
              </dl>
            </>}
            <Link className="control-font" to={`/payments?month=${month}`}>Open {formatMonth(month)} in Payments →</Link>
          </section>
          <section className="overview__card overview__card--count">
            <h2>Active models</h2><div className="overview__hero-value overview__hero-value--count">{summary.active_models}</div>
            <p className="overview__card-note">
              {summary.active_models} collaborating in {shortMonth(month)}
            </p>
            <Link className="control-font" to="/affiliates">Open roster →</Link>
          </section>
        </div>
        <div className="overview__lower">
          <section className="panel">
            <div className="panel__head"><h2 className="panel__title">Top three by generated sales</h2></div>
            {summary.top.length === 0 ? <p className="empty">No attributed sales in {formatMonth(month)} yet.</p> :
              <ol className="overview__top">{summary.top.map(row => <li key={row.affiliate_id}>
                <span className="overview__place">{row.rank}</span>
                <span className="layout__avatar" aria-hidden="true">{row.name.charAt(0)}</span>
                <span className="overview__top-who">
                  <Link to={`/affiliates/${row.affiliate_id}?section=performance&month=${month}`}>{row.name}</Link>
                  {row.code && <small>{row.code}</small>}
                </span>
                <Money piastres={row.sales_piastres} />
              </li>)}</ol>}
          </section>
          <section className="panel">
            <div className="panel__head">
              <h2 className="panel__title">Content progress to review</h2>
              <Link className="control-font" to={`/targets?month=${month}`}>Targets →</Link>
            </div>
            {toReview(summary.content).length === 0 ? <p className="empty">Every model's record is up to date for {formatMonth(month)}.</p> : <>
              <table className="table overview__content">
                <thead><tr><th>Model</th><th>Videos</th><th>Stories</th><th>Last update</th></tr></thead>
                <tbody>
                  {toReview(summary.content).map(row => <tr key={row.affiliate_id}>
                    <td>
                      <Link
                        className="overview__content-name"
                        to={`/affiliates/${row.affiliate_id}?section=targets&month=${month}`}
                      >
                        {row.name}
                      </Link>
                    </td>
                    <td>{progressLabel(row.actual_videos, row.required_videos)
                      ?? <span className="overview__unrecorded">—</span>}</td>
                    <td>{progressLabel(row.actual_stories, row.required_stories)
                      ?? <span className="overview__unrecorded">—</span>}</td>
                    <td>{row.last_update
                      ? formatDay(row.last_update)
                      : row.required_videos === null
                        ? <span className="overview__unrecorded">Nothing asked for</span>
                        : <span className="overview__stale">No update yet</span>}</td>
                  </tr>)}
                </tbody>
              </table>
            </>}
          </section>
        </div>

        <SalesByMonth year={summary.year ?? []} month={month} onPick={setMonth} />
      </>}
    </>
  );
}
