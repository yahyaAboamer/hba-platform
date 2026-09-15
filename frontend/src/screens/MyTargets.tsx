import { useEffect, useState } from "react";

import { TargetBars } from "../components/TargetProgress";
import { api } from "../lib/api";
import type { MonthTargets } from "../lib/portal";
import { formatDay, formatMonth } from "../lib/money";
import {
  describeTargetPay,
  targetChip,
  targetCounts,
  targetOutcome,
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

  if (rows === null) return <p className="empty">Loading…</p>;

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

  return (
    <div className="mytargets">
      <h1 className="mytargets__heading">Content record</h1>
      {/* Who keeps it and when they last touched it. The export prints the
          date flatly; where nobody has recorded anything yet there is no date
          to print, and saying so is the whole of §11.3 in one line. */}
      <p className="mytargets__kept">
        Recorded by HBA
        {current.recorded_at
          ? ` · updated ${formatDay(current.recorded_at.slice(0, 10))}`
          : " · nothing recorded for this month yet"}
      </p>

      <section className="mytargets__now">
        <div className="mytargets__now-head">
          <span className="mytargets__now-month">{formatMonth(current.month)}</span>
          {targetChip(current) && (
            <span className={targetChip(current)!.className}>
              {targetChip(current)!.text}
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
        {/*
         * The export folds this sentence behind an ⓘ. It stays in the open
         * here: on a guaranteed minimum it is the sentence that says whether
         * these two numbers are about to decide her pay, and that is not
         * something to make somebody press for.
         */}
        <p className="mytargets__pay">{describeTargetPay(current)}</p>
      </section>

      {history.length > 0 && (
        <>
          <h2 className="mytargets__title">Earlier months</h2>
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
