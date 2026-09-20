import { useEffect, useState } from "react";

import { Link } from "react-router-dom";

import { usePortal } from "../components/AffiliateLayout";
import { Money } from "../components/Money";
import { api } from "../lib/api";
import { formatMonth } from "../lib/money";
import { describeDestination } from "../lib/payouts";
import type { MyPayments as Body, Payment } from "../lib/portal";
import "./MyPayments.css";

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
  const { me } = usePortal();
  const [body, setBody] = useState<Body | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .get<Body>("/api/me/payments")
      .then(setBody)
      .catch((caught) => setError(caught.message));
  }, []);

  if (error) {
    return (
      <p className="notice notice--refused" role="alert">
        {error}
      </p>
    );
  }

  if (body === null) return <p className="empty">Loading…</p>;

  if (body.months.length === 0 && body.payments.length === 0) {
    // A12. **"Nothing has been paid yet" was a claim this screen cannot
    // make.** It reads the platform's ledger, which begins at go-live - and
    // HBA paid models before it existed (ADR 0036). An empty ledger therefore
    // means there is no record *here*, which is a fact, rather than that she
    // has never been paid, which is not one and which is a worse thing to
    // read on your own payments page.
    return (
      <p className="empty">
        No payment is recorded here yet. A month appears once HBA closes it.
      </p>
    );
  }

  const owed = body.outstanding_piastres > 0;

  return (
    <>
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
            : "Every month HBA has closed has been paid in full."}
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
      <section className="panel destination">
        <div className="destination__row">
          <span className="destination__label">Going to</span>
          <span className="destination__value">
            {describeDestination(me.payout_destination)}
          </span>
        </div>
        <Link to="/you" className="destination__change">
          Change where I am paid
        </Link>
      </section>

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
                src={`/api/me/payments/${payment.id}/proof`}
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
