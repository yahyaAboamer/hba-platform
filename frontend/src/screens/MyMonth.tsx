import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { usePortal } from "../components/AffiliateLayout";
import { Money } from "../components/Money";
import { PortalYearChart } from "../components/PortalYearChart";
import { api } from "../lib/api";
import { formatDay, formatMonth } from "../lib/money";
import type { MyEarnings, MyPayments, Payment, PaymentMonth } from "../lib/portal";
import "./MyMonth.css";

/**
 * Her month, in the approved Home's hierarchy.
 *
 * ## Four words for where the month has got to
 *
 * The approved portal speaks in four: *in progress*, *approved*, *payment
 * recorded*, *settled*. We hold that in two separate facts — whether the month
 * is agreed, and what the ledger says was sent — and the pill has to say both
 * without ever promising the second because the first happened. **Approval is
 * not payment**, and a month agreed this morning says *approved*, not *paid*,
 * however certain the transfer is.
 */
/**
 * Where a month has got to — including *we could not find out*. A12.
 *
 * `unknown` exists because the settlement comes from a second request, and a
 * screen that could not read it used to show **approved**: the badge that
 * means *agreed and not yet paid*. That is a claim about her money inferred
 * from a failed network call, and it is the one reading nobody should take
 * from an error.
 */
export type HomeState = "open" | "approved" | "paid" | "settled" | "unknown";

/**
 * Lower case, as the export writes them.
 *
 * Exported because *How this adds up* is the same month under a different
 * heading, and two screens that disagreed about where one month had got to
 * would be the reason for the next support message.
 */
export const STATE_LABEL: Record<HomeState, string> = {
  open: "in progress",
  approved: "approved",
  paid: "payment recorded",
  settled: "settled",
  unknown: "payment status unavailable",
};

const HERO_LABEL: Record<HomeState, string> = {
  open: "Your earnings so far",
  approved: "Approved for payment",
  paid: "Recorded payment",
  settled: "Settled earnings",
  // The earnings read succeeded, so the figure is real and is still shown.
  // What could not be read is whether anything has been sent against it.
  unknown: "Approved earnings",
};

/** What the sum at the foot of the breakdown is called. */
export const TOTAL_LABEL: Record<HomeState, string> = {
  open: "Earnings so far",
  approved: "Approved for payment",
  paid: "Recorded payment",
  settled: "Settled",
  unknown: "Approved earnings",
};

export function homeState(
  body: MyEarnings,
  settlement?: PaymentMonth,
  /**
   * Whether the settlement read actually answered. A12.
   *
   * `settlement` being absent has two completely different causes - *the
   * ledger has nothing for this month* and *the request failed* - and the
   * second one used to be silently read as the first, producing **approved**
   * on a screen that had no idea. Defaulted to `true` so every existing
   * caller keeps its meaning, and passed explicitly by the screens that can
   * tell the difference.
   */
  settlementKnown = true,
): HomeState {
  // A month from before the platform is closed and has no figure to move
  // (ADR 0036), which is the export's *settled*. Neither it nor an open month
  // depends on the ledger, so a failed settlement read costs them nothing.
  if (body.state === "historical") return "settled";
  if (body.state === "open") return "open";
  if (!settlementKnown) return "unknown";
  // Agreed. Only the ledger may promote it to *payment recorded*, and only
  // once nothing is outstanding: a part payment is still money owed.
  const paid = settlement?.state === "settled" || settlement?.state === "overpaid";
  return paid ? "paid" : "approved";
}

export function MyMonth() {
  const { month, months } = usePortal();
  const [body, setBody] = useState<MyEarnings | null>(null);
  const [payments, setPayments] = useState<MyPayments | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [paymentError, setPaymentError] = useState<string | null>(null);
  const [retry, setRetry] = useState(0);

  useEffect(() => {
    let live = true;
    setBody(null); setError(null); setPayments(null); setPaymentError(null);
    api.get<MyEarnings>(`/api/me/earnings/${month}`)
      .then(value => { if (live) setBody(value); })
      .catch(e => { if (live) setError(e.message); });
    api.get<MyPayments>("/api/me/payments")
      .then(value => { if (live) setPayments(value); })
      .catch(e => { if (live) setPaymentError(e.message); });
    return () => { live = false; };
  }, [month, retry]);

  if (error) return <p className="notice notice--refused" role="alert">{error} <button className="button" onClick={() => setRetry(n => n + 1)}>Retry</button></p>;
  if (!body) return <p className="empty">Loading…</p>;

  const settlement = payments?.months.find(row => row.month === month);
  const state = homeState(body, settlement, paymentError === null);
  const transfer = payments?.payments.find(row => row.settles.some(part => part.month === month));

  return <div className="portal-home">
    <div className="portal-home__month">
      <h1>{formatMonth(month)}</h1>
      <span className={`portal-home__state portal-home__state--${state}`}>{STATE_LABEL[state]}</span>
    </div>

    <section className="portal-home__hero">
      <h2>{HERO_LABEL[state]}</h2>
      <div className="portal-home__amount">{body.amount_piastres === null ? "—" : <Money piastres={body.amount_piastres} />}</div>
      {body.amount_piastres === null && <p className="portal-home__note">Earnings are not available for this month yet.</p>}
      <div className="portal-home__metrics">
        {/* F02. What the month is paid on - delivered and pending together.
            It showed the delivered part while the figure above it was worked
            out on both, so the card disagreed with itself. */}
        <div><span>Net sales counted</span><strong><Money piastres={body.sales.counted_piastres} /></strong></div>
        <div><span>Code uses</span><strong>{body.orders.uses ?? "—"}</strong></div>
      </div>
      {/*
       * The export's three chips, in its words, and ours are links: the
       * question a chip raises is *which ones*, and the answer is one screen
       * away. The third counts only what the courier failed to deliver
       * (`failed_delivery`, decided by the order's own status on the server):
       * a cancelled order is void too, and is not a failed delivery.
       */}
      <div className="portal-home__states">
        <Link to="/orders?status=earned">{body.orders.earned} delivered</Link>
        <Link to="/orders?status=pending">{body.orders.pending} pending</Link>
        <Link to="/orders?status=void">{body.orders.failed_delivery} failed delivery</Link>
      </div>
    </section>

    <PortalYearChart month={month} eligible={months} />

    <Link className="portal-home__open control-font" to={`/earnings?month=${month}`}>How this adds up <span>→</span></Link>

    {/*
     * A month that moved after it was agreed, and the money carried out of an
     * earlier one. Both are the export's amber *something changed* button:
     * a line naming what happened, the server's own sentence under it, and a
     * way through to the detail. Neither is drawn unless it happened.
     */}
    {body.recalculated && (
      <Link className="portal-home__change" to={`/earnings?month=${month}`}>
        <span className="portal-home__change-kicker">Sales performance has changed since approval</span>
        <span>Agreed at <Money piastres={body.recalculated.was_piastres} />, now calculated as <Money piastres={body.recalculated.now_piastres} />.</span>
        <span className="portal-home__change-more">See the detail →</span>
      </Link>
    )}
    {(body.credited_from ?? []).map(row => (
      <Link className="portal-home__change" key={row.month} to={`/earnings?month=${month}`}>
        <span className="portal-home__change-kicker">Carried from {formatMonth(row.month)}</span>
        <span>{row.text}</span>
        <span className="portal-home__change-more">See the detail →</span>
      </Link>
    ))}
    {body.waiting_on?.length > 0 && <div className="portal-home__waiting">{body.waiting_on.map(row => <p key={row.text}>{row.text}</p>)}</div>}

    <PaymentCard state={state} settlement={settlement} transfer={transfer} loading={!payments && !paymentError} error={paymentError} onRetry={() => setRetry(n => n + 1)} />
  </div>;
}

/**
 * What the ledger says about this month, in the export's card.
 *
 * Every line is read from the ledger's own figures. **Nothing here predicts a
 * date**: the export writes "usually recorded" against a demo schedule, and we
 * have no such promise to make on HBA's behalf.
 */
function PaymentCard({ state, settlement, transfer, loading, error, onRetry }: {
  state: HomeState;
  settlement?: PaymentMonth;
  transfer?: Payment;
  loading: boolean;
  error: string | null;
  onRetry: () => void;
}) {
  const recorded = settlement && settlement.paid_piastres > 0;
  const part = recorded && settlement.state === "partially_paid";

  return <section className="portal-home__payment">
    <div className="portal-home__pay-title">{state === "open" ? "Expected payment" : "Payment"}</div>
    {error
      ? <p className="portal-home__pay-line" role="alert">Could not load payment status. <button className="button" onClick={onRetry}>Retry</button></p>
      : loading
        ? <p className="portal-home__pay-line">Loading payment status…</p>
        : <>
          <div className="portal-home__pay-line">
            {recorded
              ? part
                ? <><Money piastres={settlement.paid_piastres} /> recorded of <Money piastres={settlement.obligation_piastres} /></>
                : <><Money piastres={settlement.paid_piastres} /> recorded</>
              : state === "open" ? "After the month closes"
                : state === "approved" ? "Not yet recorded"
                  : "No payments recorded here for this month"}
          </div>
          <div className="portal-home__pay-note">
            {recorded
              // Sliced rather than parsed: a timestamp handed to `Date` shows
              // the day before to anybody west of Greenwich (see `formatDay`).
              ? `Recorded ${formatDay(transfer?.occurred_at.slice(0, 10) ?? "")}${transfer?.reference ? ` · ${transfer.reference}` : ""}`
              : state === "open" ? "Recorded here once the month has closed and been approved."
                : state === "approved" ? "Approved. The transfer appears here once it has been sent."
                  : "Your performance history for this month is unchanged."}
          </div>
        </>}
    <Link className="portal-home__pay-more control-font" to="/payments">Payment history →</Link>
  </section>;
}
