import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { HistoricalReview } from "./HistoricalReview";
import type { HistoricalReviewBody } from "./HistoricalReview";
import { api, can } from "../../lib/api";
import type { Session } from "../../lib/api";
import { formatMonth } from "../../lib/money";
import "./ModelLifecycle.css";
import "../../screens/Settings.css";


/**
 * Whether the months before go-live are all final (D3). Asked only of
 * somebody who may see the review; for anybody else the section stays.
 */
export function useHistoryState(session: Session) {
  const [state, setState] = useState<"unknown" | "open" | "complete">("unknown");
  const allowed = can(session, "payroll.approve");
  useEffect(() => {
    if (!allowed) return;
    let live = true;
    api.get<HistoricalReviewBody>("/api/payroll/historical/review")
      .then((body) => {
        if (!live) return;
        const waiting = (body.totals.ready ?? 0) + body.totals.blocked + (body.totals.unknown_start ?? 0);
        setState(waiting === 0 ? "complete" : "open");
      })
      .catch(() => undefined);
    return () => { live = false; };
  }, [allowed]);
  return { state, goLive: session.platform.go_live_month };
}

export type SetupRow = {
  id: number;
  name: string;
  account_kind: string;
  code?: string;
  status: string;
  uses?: number;
  collaboration_start_month?: string | null;
  /** The first month her terms cover. `null` means none were ever written. */
  earliest_terms_month?: string | null;
  /**
   * A09. How many of her eligible months can actually be calculated, counted
   * on the server with the same per-month rule the profile uses.
   */
  historical_setup?: {
    eligible: number;
    ready: number;
    blocking: number;
    /** Of `blocking`, the months before go-live - what the review counts. */
    blocking_before_go_live?: number;
    /** The earliest month that cannot be calculated, to link straight to. */
    first_gap: string | null;
    start_is_recorded: boolean;
  } | null;
};

/** Whether her row asks anything of anybody (H2). */
function needsSomething(row: SetupRow) {
  const setup = row.historical_setup;
  return !setup || setup.blocking > 0 || setup.eligible === 0;
}

/**
 * Whether her months can be worked out, and what to do where not (H3, H5).
 *
 * The count is split at go-live, so the row and the review under the table
 * agree on the page: it used to say *9 of 9* above *5 months* for one model.
 */
export function historicalState(row: SetupRow) {
  const setup = row.historical_setup;
  if (!setup) return <span className="settings__gap">Not known</span>;
  if (setup.eligible === 0) {
    return <>
      <span className="pill settings__pill--owed">No start month</span>
      <Link className="settings__fix" to={`/affiliates/models/${row.id}`}>Record her start month →</Link>
    </>;
  }
  if (setup.blocking === 0) return <span className="pill settings__pill--ok">Ready</span>;
  const before = setup.blocking_before_go_live ?? 0;
  const after = setup.blocking - before;
  const parts = [
    before > 0 && `${before} ${before === 1 ? "month" : "months"} before go-live`,
    after > 0 && `${after} after`,
  ].filter(Boolean).join(" · ");
  return <>
    <span className="pill settings__pill--owed">{parts || `${setup.blocking} months`} cannot be calculated</span>
    <Link className="settings__fix" to={`/affiliates/models/${row.id}/compensation`}>
      {/* Only a model with no terms at all is known to need terms; a gap
          later on may be a guarantee outcome or unconfirmed targets instead. */}
      {!setup.first_gap
        ? "Set the months →"
        : row.earliest_terms_month
          ? `Fix from ${formatMonth(setup.first_gap)} →`
          : `Write her terms from ${formatMonth(setup.first_gap)} →`}
    </Link>
  </>;
}

/** The export's Historical setup opens on eight and expands to the whole list. */
const HISTORICAL_PREVIEW = 8;

function SetupRoster({ session }: { session: Session }) {
  const [rows, setRows] = useState<SetupRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [expanded, setExpanded] = useState(false);
  useEffect(() => {
    let live = true;
    api.get<{ affiliates: SetupRow[] }>("/api/affiliates?include_archived=true")
      // H1: models who have started. An applicant has no history to work out,
      // and listing her as *No month can be worked out* padded the list.
      .then((body) => { if (live) setRows(body.affiliates.filter((row) =>
        row.account_kind === "model" && row.status !== "pending" && row.status !== "declined")); })
      .catch((caught) => { if (live) setError(caught.message); });
    return () => { live = false; };
  }, []);
  if (error) return <p className="notice notice--refused" role="alert">{error}</p>;
  if (!rows) return <p className="empty">Loading…</p>;

  // H2: whoever needs something first, so nobody hides behind *Show all*.
  const sorted = [...rows].sort((a, b) =>
    Number(needsSomething(b)) - Number(needsSomething(a)) || a.name.localeCompare(b.name));
  const waiting = sorted.filter(needsSomething).length;
  const shownRows = expanded ? sorted : sorted.slice(0, Math.max(HISTORICAL_PREVIEW, waiting));

  return <section className="panel">
    <div className="panel__head">
      <h2 className="panel__title">Historical setup</h2>
      <span className="settings__head-note">
        {rows.length - waiting} ready · {waiting} {waiting === 1 ? "needs" : "need"} something
      </span>
    </div>
    <table className="table settings__table settings__hist">
      <thead><tr>
        <th>Model</th><th>Started</th><th>Terms from</th><th>What is needed</th>
      </tr></thead>
      <tbody>{shownRows.map((row) => <tr key={row.id}>
        <td><Link to={`/affiliates/models/${row.id}`}>{row.name}</Link></td>
        <td>{row.collaboration_start_month ? formatMonth(row.collaboration_start_month) : <span className="settings__gap">Not recorded</span>}</td>
        <td>{row.earliest_terms_month ? formatMonth(row.earliest_terms_month) : <span className="settings__gap">None written</span>}</td>
        <td className="settings__need">{historicalState(row)}</td>
      </tr>)}</tbody>
    </table>
    {rows.length === 0 && <p className="empty">No model has started yet.</p>}
    {!expanded && sorted.length > shownRows.length && (
      <div className="settings__pad settings__rule">
        <button type="button" className="button" onClick={() => setExpanded(true)}>Show all {rows.length} models</button>
      </div>
    )}
    <div className="settings__pad settings__rule"><HistoricalReview session={session} /></div>
  </section>;
}


/** `/affiliates/historical`: the months before go-live, worked out model by model. */
export function HistoricalSetup({ session }: { session: Session }) {
  const history = useHistoryState(session);
  return <>
    <div className="page__head"><div className="page__title"><h1>Historical setup</h1></div></div>
    <div className="settings__sections">
      {history.state === "complete"
        ? <section className="panel"><p className="settings__pad settings__done">
            History is complete: every month before {history.goLive ? formatMonth(history.goLive) : "go-live"} is final.
          </p></section>
        : <SetupRoster session={session} />}
    </div>
  </>;
}
