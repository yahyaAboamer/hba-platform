import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";

import { usePortal } from "../components/AffiliateLayout";
import { Money } from "../components/Money";
import { api } from "../lib/api";
import { formatMonth } from "../lib/money";
import type { MyEarnings, MyPayments } from "../lib/portal";
import { STATE_LABEL, TOTAL_LABEL, homeState } from "./MyMonth";
import "./MyMonth.css";

/**
 * *How this adds up* — `vEarnings` in the approved portal, lines 468–511.
 *
 * The same month as Home, under its arithmetic: every line the server sent,
 * the total at the foot of the same card, and the rule the whole thing was
 * worked out under.
 *
 * **Every figure is the server's.** The lines are rendered as they arrive and
 * nothing here adds them up — §11.1's rule about a second implementation is at
 * its sharpest on the screen whose whole job is to show the sum.
 *
 * It loads her payment history for one reason: so the word at the top of this
 * screen is the same word as at the top of Home. A month that says *payment
 * recorded* there and *approved* here reads as two systems disagreeing.
 */
export function MyCalculation() {
  const { month: selectedMonth, months } = usePortal();
  const [query] = useSearchParams();
  const month = query.get("month") ?? selectedMonth;
  const eligible = months.includes(month);
  const [body, setBody] = useState<MyEarnings | null>(null);
  const [payments, setPayments] = useState<MyPayments | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [retry, setRetry] = useState(0);

  useEffect(() => {
    let live = true;
    setBody(null);
    setError(null);
    if (!eligible) {
      setError("This month is not available in your history.");
      return;
    }
    api.get<MyEarnings>(`/api/me/earnings/${month}`)
      .then(value => { if (live) setBody(value); })
      .catch(e => { if (live) setError(e.message); });
    // Quietly: the breakdown is the screen, and a failure here costs it one
    // word at the top rather than its contents.
    api.get<MyPayments>("/api/me/payments")
      .then(value => { if (live) setPayments(value); })
      .catch(() => { if (live) setPayments(null); });
    return () => { live = false; };
  }, [month, retry, eligible]);

  if (error) return <p role="alert">{error} <button className="button" onClick={() => setRetry(n => n + 1)}>Retry</button></p>;
  if (!body) return <p className="empty">Loading…</p>;

  const state = homeState(body, payments?.months.find(row => row.month === month));

  return <div className="portal-home">
    <div className="portal-home__month">
      <h1>{formatMonth(month)}</h1>
      <span className={`portal-home__state portal-home__state--${state}`}>{STATE_LABEL[state]}</span>
    </div>

    <dl className="portal-calculation">
      {body.makeup.map((line, index) => (
        <div key={index}>
          <dt>{line.label}{line.detail && <small>{line.detail}</small>}</dt>
          <dd><Money piastres={line.piastres} /></dd>
        </div>
      ))}
      {/* The total belongs to the same card as the lines it sums, which is
          what says it is their sum rather than a second figure. */}
      <div className="portal-calculation__total">
        <dt>{TOTAL_LABEL[state]}</dt>
        <dd>{body.amount_piastres === null ? "Not available" : <Money piastres={body.amount_piastres} />}</dd>
      </div>
    </dl>

    {/*
     * Why this month reads differently from what was agreed. The export puts
     * it in an amber card with the long sentence and then what is being
     * recovered; ours says the same from the server's own figures.
     */}
    {body.recalculated && (
      <section className="portal-calc__changed">
        <h2>Why this month differs from the approved calculation</h2>
        <p>
          {formatMonth(month)} was agreed at <Money piastres={body.recalculated.was_piastres} /> and now
          calculates as <Money piastres={body.recalculated.now_piastres} />. What was agreed, and any
          payment recorded against it, have not changed.
        </p>
      </section>
    )}
    {(body.credited_from ?? []).map(row => (
      <section className="portal-calc__changed" key={row.month}>
        <h2>Carried from {formatMonth(row.month)}</h2>
        <p>{row.text}</p>
      </section>
    ))}

    {body.waiting_on?.map(row => <p className="portal-home__waiting" key={row.text}>{row.text}</p>)}
    {body.note && <p className="portal-home__note">{body.note}</p>}

    {/*
     * The rule the month was worked out under, at the foot of the screen.
     *
     * **Delivered only.** The export's line counts pending orders too; that is
     * 05A's preview and not what she is paid on, and a sentence promising it
     * would be promising money that is not owed yet.
     *
     * The rate is the server's own field, shown as a percentage. That is the
     * one arithmetic the browser does here, and it is a rate rather than an
     * amount.
     */}
    {body.commission_rate_bp !== null && (
      <p className="portal-calc__rule">
        Commission is {percent(body.commission_rate_bp)} of net sales on delivered orders.
        An order on its way counts the day it arrives; one that fails is excluded.
      </p>
    )}

    {body.policy_version && (
      <a className="portal-calc__rules-link" href={`/policy/${body.policy_version.id}`}>
        The rules this month was calculated under →
      </a>
    )}
  </div>;
}

/** Basis points as somebody reads them: 1000 → "10%", 1250 → "12.5%". */
function percent(bp: number): string {
  const whole = bp / 100;
  return `${Number.isInteger(whole) ? whole : whole.toFixed(2).replace(/0$/, "")}%`;
}
