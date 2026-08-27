import { useEffect, useState } from "react";

import { Money } from "../components/Money";
import { api } from "../lib/api";
import { formatMonth } from "../lib/money";
import type { MyPayments as Body, Payment } from "../lib/portal";
import "./MyPayments.css";

/** The settlement states, in her words rather than the ledger's. */
const STATE_TEXT: Record<string, string> = {
  unpaid: "Not paid yet",
  partially_paid: "Part paid",
  settled: "Paid",
  overpaid: "Overpaid",
};

/**
 * What has arrived, and what is still outstanding.
 *
 * §14, and **a separate screen from her earnings on purpose.** *What I have
 * earned* and *what has arrived* have different answers for most of any month,
 * and merging them is how a model ends up believing she has been paid twice,
 * or not at all.
 *
 * This is the one screen in the portal where colour is spent (ADR 0027). Money
 * state is the only thing it is ever spent on, and here the platform actually
 * knows: outstanding is `owed`, settled is `settled`. Her earnings screen
 * paints nothing, because a figure still being worked out is not a debt.
 *
 * Not month-scoped. Her earnings are a question about one month; *where is my
 * money* is a question about all of them at once.
 */
export function MyPayments() {
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
    return (
      <p className="empty">
        Nothing has been paid yet. A month appears here once HBA closes it.
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

      <section className="panel settle">
        <div className="panel__head">
          <h2 className="panel__title">Month by month</h2>
        </div>
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
               * The line that makes her own arithmetic close. A month agreed
               * at 2,400 pounds and settled by a transfer of 2,340 reads as
               * sixty pounds short - the write-off is in a panel further down,
               * and she will not connect the two to each other on her own.
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
                  Includes <Money piastres={row.credited_piastres} /> carried in
                  from an earlier month.
                </p>
              )}
            </li>
          ))}
        </ul>
      </section>

      {body.payments.length > 0 && (
        <section className="panel settle">
          <div className="panel__head">
            <h2 className="panel__title">Every transfer</h2>
          </div>
          <ul className="settle__list">
            {body.payments.map((payment) => (
              <PaymentRow key={payment.id} payment={payment} />
            ))}
          </ul>
        </section>
      )}

      {/*
       * §11.5 requires these to be visible to her, with the reason written at
       * the time: a credit she cannot see is a credit she cannot check. They
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

function PaymentRow({ payment }: { payment: Payment }) {
  const [showing, setShowing] = useState(false);
  const [broken, setBroken] = useState(false);

  return (
    <li className="settle__row">
      <div className="settle__head">
        <span className="settle__when">{onlyTheDate(payment.occurred_at)}</span>
        <Money piastres={payment.amount_piastres} kind="agreed" tone="settled" />
      </div>
      <div className="settle__foot">
        <span className="settle__for">
          {payment.settles.length === 0
            ? "Not yet put against a month"
            : `For ${payment.settles.map((line) => formatMonth(line.month)).join(", ")}`}
        </span>
        {payment.reference && (
          <span className="code settle__reference">{payment.reference}</span>
        )}
      </div>

      {/*
       * §14 and ADR 0017. Visible proof removes an entire category of *did you
       * send it?* messages, which is the whole reason the screenshot is kept.
       *
       * Behind a press rather than always open: twelve months of transfers is
       * twelve full-width images to scroll past on a phone before reaching the
       * one she came for.
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
               * A screenshot that will not load is not a reason to show her a
               * broken-image icon and nothing else. The payment is real either
               * way, and the sentence she needs is what to do about it.
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
