import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { api, can } from "../lib/api";
import type { Session } from "../lib/api";
import { formatMonth } from "../lib/money";

/**
 * A09. Finishing the months that happened before the platform, for everybody
 * at once.
 *
 * The approved export puts a **Review months from January 2026** button under
 * the Historical setup table, with a line under it afterwards saying what
 * happened. That entry was missing entirely: the per-model readiness existed
 * and the only way to act on it was to open twenty profiles.
 *
 * The two halves are deliberately separate calls. The review is a **dry run**
 * that writes nothing, because A09 is as much about what is still missing as
 * about what can be finished, and a screen that could only find that out by
 * doing something is a screen nobody presses.
 */
export type HistoricalMonth = {
  affiliate_id: number;
  name: string;
  month: string;
  missing?: string[];
  obligation_piastres?: number;
};

export type HistoricalReviewBody = {
  working_month: string;
  from_month: string | null;
  ready: HistoricalMonth[];
  blocked: HistoricalMonth[];
  already_finalised: HistoricalMonth[];
  approved?: HistoricalMonth[];
  refused?: (HistoricalMonth & { reason: string })[];
  summary: string;
  approved_total: string;
  totals: {
    models?: number;
    ready?: number;
    approved?: number;
    refused?: number;
    blocked: number;
    already_finalised: number;
  };
};

/** What a month is waiting for, in the words the person who must supply it uses. */
export const MISSING_TEXT: Record<string, string> = {
  no_terms: "no terms recorded",
  no_target_outcome: "guaranteed minimum with no met/missed recorded",
  target_not_verified: "targets not confirmed",
};

/**
 * The blocked months gathered per model, because that is how somebody fixes
 * them — one profile, all of her gaps — rather than one line per month.
 */
export function blockedByModel(rows: HistoricalMonth[]) {
  const out = new Map<number, { name: string; months: string[]; missing: Set<string> }>();
  for (const row of rows) {
    const found = out.get(row.affiliate_id) ?? {
      name: row.name,
      months: [],
      missing: new Set<string>(),
    };
    found.months.push(row.month);
    for (const reason of row.missing ?? []) found.missing.add(reason);
    out.set(row.affiliate_id, found);
  }
  return [...out.entries()].map(([id, row]) => ({ id, ...row }));
}

export function HistoricalReview({ session }: { session: Session }) {
  const [body, setBody] = useState<HistoricalReviewBody | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [working, setWorking] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const allowed = can(session, "payroll.approve");

  useEffect(() => {
    let live = true;
    setError(null);
    api
      .get<HistoricalReviewBody>("/api/payroll/historical/review")
      .then((found) => { if (live) setBody(found); })
      .catch((caught) => { if (live) setError(caught.message); });
    return () => { live = false; };
  }, [attempt]);

  async function finalise() {
    setWorking(true);
    setError(null);
    try {
      setBody(await api.post<HistoricalReviewBody>("/api/payroll/historical/finalise", {}));
    } catch (caught) {
      setError((caught as Error).message);
    } finally {
      setWorking(false);
    }
  }

  if (error) {
    return (
      <div className="settings__historical">
        <p className="notice notice--refused" role="alert">
          {error}{" "}
          <button type="button" className="button" onClick={() => setAttempt((n) => n + 1)}>
            Try again
          </button>
        </p>
      </div>
    );
  }
  if (!body) return null;

  const ready = body.totals.ready ?? 0;
  const done = body.totals.approved;
  const blocked = blockedByModel(body.blocked);

  return (
    <div className="settings__historical">
      {/* The button the approved export puts here, in its words. It is only
          drawn when there is something to do: an entry that does nothing is
          worse than no entry, because somebody presses it. */}
      {done === undefined && ready > 0 && allowed && (
        <button
          type="button"
          className="button button--primary"
          disabled={working}
          onClick={finalise}
        >
          {working
            ? "Finalising…"
            : `Review months from ${formatMonth(body.from_month ?? body.working_month)}`}
        </button>
      )}
      {/* The result line, written by the server - it says what was done to
          somebody's money, so it is not restated here. The export shows it in
          a bordered accent box once the review has run; before that it is the
          quiet sentence explaining why the button is or is not there. */}
      <p
        className={done === undefined ? "settings__note" : "settings__result"}
        role="status"
      >
        {body.summary}
      </p>

      {done !== undefined && (
        // Running it again is the repair for a run that stopped halfway, so
        // the way to do that stays on the screen.
        <button type="button" className="button" onClick={() => setAttempt((n) => n + 1)}>
          Check again
        </button>
      )}

      {blocked.length > 0 && (
        <>
          <h3 className="settings__subtitle">
            Waiting on information HBA holds
          </h3>
          {/* Named per model rather than per month, because that is how one
              person fixes them: one profile, all of her gaps. Nothing here can
              be filled in by the software — that is the whole point of the
              separation. */}
          <ul className="settings__gaps">
            {blocked.map((row) => (
              <li key={row.id}>
                <Link to={`/affiliates/${row.id}/compensation`}>{row.name}</Link>
                {" — "}
                {row.months.length} month{row.months.length === 1 ? "" : "s"}
                {" from "}{formatMonth(row.months[0])}
                {": "}
                {[...row.missing].map((reason) => MISSING_TEXT[reason] ?? reason).join(", ")}
              </li>
            ))}
          </ul>
        </>
      )}

      {body.refused && body.refused.length > 0 && (
        <>
          <h3 className="settings__subtitle">Refused</h3>
          <ul className="settings__gaps">
            {body.refused.map((row) => (
              <li key={`${row.affiliate_id}-${row.month}`}>
                {row.name} · {formatMonth(row.month)} — {row.reason}
              </li>
            ))}
          </ul>
        </>
      )}

      {!allowed && ready > 0 && (
        <p className="settings__note">Only somebody who approves payroll can finalise these.</p>
      )}
    </div>
  );
}
