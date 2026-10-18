import { useEffect, useState } from "react";

import { Link } from "react-router-dom";

import { usePortal } from "../components/AffiliateLayout";
import { Money } from "../components/Money";
import { api, portalPath } from "../lib/api";
import { formatMonth } from "../lib/money";
import { describeDestination } from "../lib/payouts";
import type { MyHome, MyPayments as Body, Payment } from "../lib/portal";
import { cairoToday, expectedRecording } from "../lib/portal";
import { readHome } from "./MyMonth";
import "./MyPayments.css";

const SHORT = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/**
 * The month she is still earning, and how it becomes money (batch L).
 *
 * It was nowhere on this screen: an empty ledger showed one grey sentence,
 * though Home already knew the amount so far and when HBA usually pays. Three
 * steps say where it has got to - earning, approved, paid - and the date is
 * HBA's usual timing, said as *around*, never as a promise.
 */
function ComingUp({ home, destination }: { home: MyHome; destination: string }) {
  const body = home.earnings;
  const expected = expectedRecording(home.month, "open", cairoToday());
  const closes = body.window.closes.slice(0, 10).split("-").map(Number);
  const when = expected ? expected.label.split(" ").slice(0, 2).join(" ") : null;

  return (
    <>
      <span className="pay-eyebrow">Coming up</span>
      <section className="pay-coming">
        <div className="pay-coming__head">
          <strong>{formatMonth(home.month)}</strong>
          <span className="pay-coming__pill">
            <span aria-hidden="true" />
            In progress
          </span>
        </div>
        <div className="pay-coming__figure">
          <span className="pay-coming__amount">
            {body.amount_piastres === null ? "—" : <Money piastres={body.amount_piastres} />}
          </span>
          <span className="pay-coming__note">so far — final once HBA closes the month</span>
        </div>
        <ol className="pay-steps">
          <li className="pay-steps__step pay-steps__step--now">
            <span className="pay-steps__bar" />
            <strong>Earning</strong>
            <span>until {closes[2]} {SHORT[closes[1] - 1]}</span>
          </li>
          <li className="pay-steps__step">
            <span className="pay-steps__bar" />
            <strong>Approved</strong>
            <span>by HBA</span>
          </li>
          <li className="pay-steps__step">
            <span className="pay-steps__bar" />
            <strong>Paid</strong>
            <span>{when ? `around ${when}` : "after approval"}</span>
          </li>
        </ol>
        <div className="pay-coming__rule" />
        <div className="pay-coming__to">
          <span>
            <span className="pay-coming__label">Paid to</span>
            <strong>{destination}</strong>
          </span>
          <Link className="pay-coming__change" to="/you/payout">
            Change
          </Link>
        </div>
      </section>
    </>
  );
}

/** The settlement states, in their words rather than the ledger's. */
const STATE_TEXT: Record<string, string> = {
  unpaid: "Not paid yet",
  partially_paid: "Part paid",
  settled: "Paid",
  overpaid: "Overpaid",
};

/**
 * What has arrived, and what is still outstanding.
 *
 * §14, and **a separate screen from their earnings on purpose.** *What I have
 * earned* and *what has arrived* have different answers for most of any month,
 * and merging them is how a model ends up believing they have been paid twice,
 * or not at all.
 *
 * This is the one screen in the portal where colour is spent (ADR 0027). Money
 * state is the only thing it is ever spent on, and here the platform actually
 * knows: outstanding is `owed`, settled is `settled`. Their earnings screen
 * paints nothing, because a figure still being worked out is not a debt.
 *
 * Not month-scoped. Their earnings are a question about one month; *where is my
 * money* is a question about all of them at once.
 */
export function MyPayments() {
  const { me, months } = usePortal();
  const [body, setBody] = useState<Body | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [running, setRunning] = useState<MyHome | null>(null);
  const [retry, setRetry] = useState(0);

  useEffect(() => {
    setError(null);
    setBody(null);
    api
      .get<Body>("/api/me/payments")
      .then(setBody)
      .catch((caught) => setError(caught.message));
    // The month still being earned, for *Coming up* (batch L). Optional: if
    // it cannot be read, the screen is exactly what it was without it.
    if (months?.[0]) {
      readHome(months[0]).then(setRunning).catch(() => setRunning(null));
    }
  }, [months, retry]);

  if (error) {
    return (
      <section className="pay-load-error" role="alert">
        <strong>Payment history could not load</strong>
        <p>{error}</p>
        <button type="button" className="button" onClick={() => setRetry((was) => was + 1)}>Try again</button>
      </section>
    );
  }

  if (body === null) return <PaymentSkeleton />;

  const destination = me.payout_abroad && !me.payout_destination
    ? "HBA arranges your payment directly"
    : describeDestination(me.payout_destination);
  const coming = running && running.earnings.state === "open" ? (
    <ComingUp home={running} destination={destination} />
  ) : null;

  if (body.months.length === 0 && body.payments.length === 0) {
    // A12. **"Nothing has been paid yet" was a claim this screen cannot
    // make.** It reads the platform's ledger, which begins at go-live - and
    // HBA paid models before it existed (ADR 0036). An empty ledger therefore
    // means there is no record *here*, which is a fact, rather than that she
    // has never been paid. Batch L keeps the claim and gives it a shape: what
    // is coming, then an empty history that says what will fill it.
    return (
      <div className="pay-screen">
        {coming}
        <span className="pay-eyebrow">History</span>
        <section className="pay-empty">
          <span className="pay-empty__icon" aria-hidden="true">
            <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
              <path d="M6 3h12v18l-3-2-3 2-3-2-3 2V3Z" />
              <path d="M9 8h6M9 12h6" />
            </svg>
          </span>
          <strong>No payments recorded here yet</strong>
          <span>Each transfer HBA records shows up here, with its date and reference.</span>
        </section>
      </div>
    );
  }

  const owed = body.outstanding_piastres > 0;

  return (
    <>
      {coming}
      <section className="figure">
        <p className="figure__state">
          {owed ? "Waiting to be paid" : "Nothing outstanding"}
        </p>
        <Money
          piastres={body.outstanding_piastres}
          kind="agreed"
          tone={owed ? "owed" : "settled"}
          className="figure__amount"
        />
        <p className="figure__note">
          {owed
            ? "Agreed and not yet transferred. Months still being worked out are not counted here."
            : "No agreed amount remains to send."}
        </p>
      </section>

      {/*
       * **Where it goes**, on the screen that is about money arriving.
       *
       * It only ever lived on the You screen, which is the wrong place for
       * it: somebody checking on a payment is right there, already thinking
       * about the account it lands in, and making them go and find it
       * elsewhere is what turns a glance into a message to HBA.
       *
       * Deliberately *not* an editable field here. Changing where money goes
       * is a decision, and a decision belongs on the screen built for it with
       * its own confirmation - not one press away from a balance.
       */}
      {/* Batch L: *Coming up* already says where it goes, with its own
          Change - one place for it, not two on one screen. */}
      {!coming && <section className="panel destination">
        <div className="destination__row">
          <span className="destination__label">Going to</span>
          <span className="destination__value">
            {destination}
          </span>
        </div>
        <Link to="/you" className="destination__change">
          Change where I am paid
        </Link>
      </section>}

      {/*
       * Agreed and not yet sent, at the top — the export leads with it, and it
       * is the question somebody opens this screen to ask. One card per month,
       * because two unpaid months are two separate answers.
       *
       * The figure is the month's own balance, not the total above it: the
       * total answers *how much am I owed altogether* and this answers *for
       * which month*.
       */}
      {body.months
        .filter((row) => row.balance_piastres > 0)
        .map((row) => (
          <section className="pay-await" key={row.month}>
            <div className="pay-await__label">Approved, payment not yet recorded</div>
            <div className="pay-await__row">
              <span>{formatMonth(row.month)}</span>
              <Money piastres={row.balance_piastres} kind="agreed" />
            </div>
          </section>
        ))}

      <section className="panel settle">
        <div className="panel__head">
          <h2 className="panel__title">Month by month</h2>
        </div>
        {/*
         * ADR 0036. One line, and only for somebody who has such a month.
         *
         * The list below starts at go-live, because those are the months this
         * platform has a transfer to show. Without a word it reads as *my
         * earlier months are missing*; with a banner it reads as an apology
         * for records nobody had reason to doubt. So: one sentence, saying
         * where the money went and where the months themselves are.
         */}
        {body.settled_outside && (
          <p className="settle__before">{body.settled_outside.text}</p>
        )}
        <ul className="settle__list">
          {body.months.map((row) => (
            <li key={row.month} className="settle__row">
              <div className="settle__head">
                <span className="code settle__month">
                  {formatMonth(row.month)}
                </span>
                <Money
                  piastres={row.obligation_piastres}
                  kind="agreed"
                  tone={row.balance_piastres > 0 ? "owed" : "settled"}
                />
              </div>
              <div className="settle__foot">
                <span className={`state state--${row.state}`}>
                  {STATE_TEXT[row.state] ?? row.state}
                </span>
                {row.balance_piastres > 0 && (
                  <span className="settle__balance">
                    <Money piastres={row.balance_piastres} tone="owed" /> still to
                    come
                  </span>
                )}
              </div>
              {/*
               * The line that makes their own arithmetic close. A month agreed
               * at 2,400 pounds and settled by a transfer of 2,340 reads as
               * sixty pounds short - the write-off is in a panel further down,
               * and they will not connect the two to each other on their own.
               */}
              {row.adjusted_piastres > 0 && (
                <p className="settle__reconcile">
                  <Money piastres={row.paid_piastres} /> transferred, and{" "}
                  <Money piastres={row.adjusted_piastres} /> settled without a
                  transfer. See below for why.
                </p>
              )}
              {row.credited_piastres > 0 && (
                <p className="settle__reconcile">
                  {/*
                    * **Not "includes"** (05C). A credit is an earlier month's
                    * overpayment being recovered, so it makes this month pay
                    * *less* - and under D04 it can take all of it. The old
                    * wording read as money added, which is the opposite.
                    */}
                  <Money piastres={row.credited_piastres} /> of this month
                  repaid an earlier one you had already been sent.
                </p>
              )}
            </li>
          ))}
        </ul>
      </section>

      {body.payments.length > 0 && (
        <section className="panel settle">
          <div className="panel__head">
            <h2 className="panel__title">Recorded payments</h2>
          </div>
          <ul className="settle__list">
            {body.payments.map((payment) => (
              <PaymentRow key={payment.id} payment={payment} />
            ))}
          </ul>
        </section>
      )}

      {/*
       * §11.5 requires these to be visible to them, with the reason written at
       * the time: a credit they cannot see is a credit they cannot check. They
       * are also the only place a figure moves without a transfer, which is
       * exactly the kind of thing that looks like an error when unexplained.
       */}
      {body.adjustments.length > 0 && (
        <section className="panel settle">
          <div className="panel__head">
            <h2 className="panel__title">Changes without a transfer</h2>
          </div>
          <ul className="settle__list">
            {body.adjustments.map((adjustment, index) => (
              <li key={index} className="settle__row">
                <div className="settle__head">
                  <span className="settle__kind">{adjustment.kind_text}</span>
                  <Money piastres={adjustment.amount_piastres} />
                </div>
                <p className="settle__reason">{adjustment.reason}</p>
                <p className="settle__when">
                  {adjustment.to_month
                    ? `From ${formatMonth(adjustment.from_month ?? "")} into ${formatMonth(adjustment.to_month)}`
                    : `Against ${formatMonth(adjustment.from_month ?? "")}`}
                </p>
              </li>
            ))}
          </ul>
        </section>
      )}
    </>
  );
}

function PaymentSkeleton() {
  return <div className="pay-skeleton" role="status" aria-label="Loading payment history">
    <div className="pay-skeleton__card pay-skeleton__card--figure"><span /><span /><span /></div>
    <div className="pay-skeleton__card"><span /><span /></div>
    <div className="pay-skeleton__card"><span /><span /><span /></div>
  </div>;
}

export function PaymentRow({ payment }: { payment: Payment }) {
  const [showing, setShowing] = useState(false);
  const [broken, setBroken] = useState(false);

  return (
    <li className="settle__row">
      {/*
       * The month it paid is the title and the date is underneath it, which is
       * the export's order and the way somebody looks a transfer up: they know
       * which month they are asking about, not which day it was sent.
       *
       * A transfer that has not been put against a month says so in the same
       * place rather than going untitled — money can arrive before anybody
       * decides what it settles.
       */}
      <div className="settle__head">
        <span className="settle__month">
          {payment.settles.length === 0
            ? "Not yet put against a month"
            : payment.settles.map((line) => formatMonth(line.month)).join(", ")}
        </span>
        <Money piastres={payment.amount_piastres} kind="agreed" tone="settled" />
      </div>
      <div className="settle__foot">
        <span className="settle__when">
          Recorded {onlyTheDate(payment.occurred_at)}
          {payment.reference && ` · ${payment.reference}`}
        </span>
      </div>

      {/*
       * **Where it actually went, not where money goes now** (§6.4.4, AC40).
       *
       * The destination is masked and frozen on the transaction at the moment
       * it was paid. The panel at the top of this screen says where her money
       * goes *today*, and after she changes it those two are different facts —
       * so a receipt that borrowed the current one would quietly claim an old
       * transfer went somewhere it never went.
       *
       * Shown on every transfer rather than only where they differ: a receipt
       * that names its destination sometimes is one nobody can trust the rest
       * of the time.
       */}
      {payment.destination && (
        <p className="settle__went">
          Sent to {describeDestination(payment.destination)}
        </p>
      )}

      {/*
       * AC41. A transfer answers *what arrived*; the month answers *why that
       * much*. Linking them is the difference between a receipt she can check
       * and one she has to take on trust — and the month picker is at the top
       * of the portal, so without this she has to remember which month a
       * transfer was for and go and find it.
       *
       * One link per month the transfer settled, because a single transfer can
       * cover two of them and "View calculation" would then be ambiguous.
       */}
      {payment.settles.length > 0 && (
        <p className="settle__why">
          {payment.settles.map((line) => (
            <Link
              key={line.month}
              className="settle__link"
              to={`/earnings?month=${line.month}`}
            >
              Why {formatMonth(line.month)} came to {line.amount}
            </Link>
          ))}
        </p>
      )}

      {/*
       * §14 and ADR 0017. Visible proof removes an entire category of *did you
       * send it?* messages, which is the whole reason the screenshot is kept.
       *
       * Behind a press rather than always open: twelve months of transfers is
       * twelve full-width images to scroll past on a phone before reaching the
       * one they came for.
       */}
      {payment.has_proof && (
        <>
          <button
            type="button"
            className="settle__proof-toggle"
            onClick={() => setShowing((was) => !was)}
            aria-expanded={showing}
          >
            {showing ? "Hide the transfer" : "See the transfer"}
          </button>
          {showing &&
            (broken ? (
              /*
               * A screenshot that will not load is not a reason to show them a
               * broken-image icon and nothing else. The payment is real either
               * way, and the sentence they need is what to do about it.
               */
              <p className="settle__reconcile">
                The screenshot would not load. The transfer above is still
                recorded — ask HBA if you need to see it.
              </p>
            ) : (
              <img
                className="settle__proof"
                src={portalPath(`/api/me/payments/${payment.id}/proof`)}
                alt={`Confirmation of the transfer on ${onlyTheDate(payment.occurred_at)}`}
                onError={() => setBroken(true)}
              />
            ))}
        </>
      )}
    </li>
  );
}

function onlyTheDate(iso: string): string {
  return new Date(iso).toLocaleDateString("en-GB", {
    day: "numeric",
    month: "long",
    year: "numeric",
  });
}
