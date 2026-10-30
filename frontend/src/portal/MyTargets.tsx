import { useEffect, useState } from "react";

import { TargetBars } from "../components/TargetProgress";
import { PortalSkeleton } from "../components/PortalSkeleton";
import { api } from "../lib/api";
import type { MonthTargets } from "../lib/portal";
import { formatDay, formatMonth } from "../lib/money";
import {
  describeCurrentTargetPay,
  describeTargetPay,
  targetChip,
  targetCounts,
  targetOutcome,
  targetProgressNote,
} from "../lib/targets";
import "./MyTargets.css";

type Row = MonthTargets & { month: string };

/**
 * What HBA has asked of her, this month and every month before it.
 *
 * UI24, and `onTargets` in the approved portal (lines 328–376), which calls it
 * *Content record* — the right name: it is a record somebody else keeps, and
 * the heading says so before the screen has to.
 *
 * ## Nothing here is editable, and that is the design
 *
 * There is no route to change any of it (§6.5) — not a disabled field, not a
 * permission check. On a guaranteed minimum these numbers decide money, and
 * the person being measured is not the person who records the measurement.
 *
 * ## Three states, not two
 *
 * A month nobody has counted yet is **not** a month she missed (§11.3), and
 * the difference matters most in exactly the case where it is easiest to get
 * wrong: an unrecorded month blocks a guaranteed minimum, so she sees "not
 * recorded yet" against the month that is holding up her pay and can ask
 * about the right thing. The export has two words for a month, *met* and *not
 * met*; we keep the third.
 *
 * ## A month from before the platform
 *
 * ADR 0036: the old dashboard kept whether the target was met and not what was
 * counted to decide it. Those months say the numbers were not kept. Inventing
 * counts to match the outcome would be fabricating the evidence for a figure
 * that decided her pay.
 */
export function MyTargets() {
  const [rows, setRows] = useState<Row[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    api
      .get<{ months: Row[] }>("/api/me/targets")
      .then((body) => {
        if (live) setRows(body.months);
      })
      .catch((caught) => {
        // Never rendered as "nothing has been asked of you" (§S06). A failed
        // request and an empty history are different facts, and being told the
        // second one wrongly is alarming on a screen about her pay.
        if (live) setError(caught.message);
      });
    return () => {
      live = false;
    };
  }, []);

  if (error) {
    return (
      <p className="notice notice--refused" role="alert">
        {error}
      </p>
    );
  }

  if (rows === null) return <PortalSkeleton screen="targets" />;

  // Defensive rather than expected: `months_for` always offers at least the
  // month she is in, so this is what stops an empty payload becoming a white
  // screen on the line below rather than a state anybody should reach.
  if (rows.length === 0) {
    return (
      <p className="empty">
        Nothing has been asked of you yet. When HBA sets a target it appears
        here, with what has been counted against it.
      </p>
    );
  }

  // Newest first, from the server. The first row is the month she is in.
  const [current, ...history] = rows;
  const chip = targetChip(current);
  const progress = targetProgressNote(current);

  return (
    <div className="mytargets">
      <h1 className="mytargets__heading">Targets</h1>
      <p className="mytargets__kept">
        HBA records these
        {current.recorded_at
          ? ` · updated ${formatDay(current.recorded_at.slice(0, 10))}`
          : " · nothing recorded this month yet"}
      </p>

      <section className="mytargets__now">
        <div className="mytargets__now-head">
          <span className="mytargets__now-month">{formatMonth(current.month)}</span>
          {chip && (
            <span className={chip.className}>
              {chip.text}
            </span>
          )}
        </div>
        {current.achieved === null &&
        current.required_videos === null &&
        current.required_stories === null ? (
          <p className="mytargets__none">
            Nothing has been set for this month yet.
          </p>
        ) : (
          <TargetBars target={current} />
        )}
        {progress && <p className="mytargets__progress">{progress}</p>}
      </section>

      {current.determines_pay ? (
        <aside className={current.achieved && current.verified ? "mytargets__pay-note mytargets__pay-note--met" : "mytargets__pay-note"}>
          <h2>How this affects your pay</h2>
          <p>{describeCurrentTargetPay(current)}</p>
        </aside>
      ) : (
        <p className="mytargets__informational">{describeTargetPay(current)}</p>
      )}

      {history.length > 0 && (
        <>
          <div className="mytargets__history-head">
            <h2 className="mytargets__title">Earlier months</h2>
            <span>Most recent first</span>
          </div>
          <ul className="mytargets__history">
            {history.map((row) => (
              <li key={row.month} className="mytargets__month">
                <span className="mytargets__label">
                  {formatMonth(row.month)}
                  <span className="mytargets__detail">
                    {targetCounts(row)}
                    {row.recorded_at && ` · updated ${formatDay(row.recorded_at.slice(0, 10))}`}
                  </span>
                </span>
                <span
                  className={
                    row.achieved
                      ? "mytargets__state mytargets__state--met"
                      : "mytargets__state"
                  }
                >
                  {targetOutcome(row)}
                </span>
              </li>
            ))}
          </ul>
          {/*
           * One sentence under the list rather than a marker on every row that
           * decided pay. Most models are on one arrangement throughout, and a
           * badge repeated down every line teaches nothing.
           */}
          <p className="mytargets__foot">
            HBA records these. If something here looks wrong, tell them — there
            is nothing on this screen for you to change.
          </p>
        </>
      )}
    </div>
  );
}
