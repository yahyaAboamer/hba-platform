import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";

import { Money } from "../components/Money";
import { api } from "../lib/api";
import { formatMonth } from "../lib/money";
import "./Payroll.css";
import "./AffiliatePayments.css";

type Payment = {
  id: number;
  amount_piastres: number;
  amount: string;
  occurred_at: string;
  reference: string | null;
  note: string | null;
  has_proof: boolean;
  /** Already masked when it was written (§6.4.4). Never the raw account. */
  destination: Record<string, string | null> | null;
  allocated_piastres: number;
  unallocated_piastres: number;
};

type Adjustment = {
  id: number;
  type: string;
  amount_piastres: number;
  amount: string;
  from_month: string;
  to_month: string | null;
  reason: string;
};

type History = {
  affiliate_id: number;
  name: string;
  payments: Payment[];
  adjustments: Adjustment[];
};

const ADJUSTMENT_WORD: Record<string, string> = {
  credit: "Carried to a later month",
  writeoff: "Absorbed by HBA",
};

/**
 * Everything one model has been paid, and every adjustment touching them.
 *
 * **The maintainer's side of a screen the model already had.** §11.5 requires
 * adjustments to be visible to the model - a credit they cannot see is a credit
 * they cannot check - and Phase 9 built that. This is the same facts from the
 * other side, and until now the maintainer had no way to see them at all: the
 * Payments screen answers *who is owed what this month*, which is a different
 * question from *what have we ever sent this person*.
 *
 * It is the question asked when somebody says the money never arrived.
 *
 * Its own page rather than another panel on the affiliate's record, because
 * that record answers "is this person set up and earning" and this answers
 * "what has moved". Different questions, different lengths, and the record was
 * already long.
 */
export function AffiliatePayments() {
  const { id = "" } = useParams();
  const [history, setHistory] = useState<History | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [showing, setShowing] = useState<number | null>(null);

  useEffect(() => {
    api
      .get<History>(`/api/affiliates/${id}/payments`)
      .then(setHistory)
      .catch((caught) => setError(caught.message));
  }, [id]);

  if (error) {
    return (
      <p className="notice notice--refused" role="alert">
        {error}
      </p>
    );
  }
  if (history === null) return <p className="empty">Loading…</p>;

  const total = history.payments.reduce(
    (sum, payment) => sum + payment.amount_piastres,
    0,
  );

  return (
    <>
      <div className="page__head">
        <div className="page__title">
          <Link to={`/affiliates/${id}`} className="detail__back">
            {history.name}
          </Link>
          <h1>What {history.name} has been paid</h1>
        </div>
      </div>

      <section className="panel">
        <div className="panel__head">
          <h2 className="panel__title">Payments</h2>
          {history.payments.length > 0 && (
            <span className="chip chip--quiet">
              <Money piastres={total} kind="agreed" /> in total
            </span>
          )}
        </div>

        {history.payments.length === 0 ? (
          <p className="empty">Nothing has been sent yet.</p>
        ) : (
          <ul className="paid">
            {history.payments.map((payment) => (
              <li key={payment.id} className="paid__row">
                <div className="paid__head">
                  <Money piastres={payment.amount_piastres} kind="agreed" />
                  <span className="paid__when">
                    {new Date(payment.occurred_at).toLocaleDateString("en-GB", {
                      day: "numeric",
                      month: "long",
                      year: "numeric",
                    })}
                  </span>
                </div>

                <dl className="paid__facts">
                  {payment.reference && (
                    <div>
                      <dt>Reference</dt>
                      <dd className="code">{payment.reference}</dd>
                    </div>
                  )}
                  {payment.destination && (
                    <div>
                      <dt>Sent to</dt>
                      {/*
                       * The masked snapshot as it was **at the time of
                       * paying**, not what is on file now. If a destination
                       * changed since, this is the only record of where the
                       * money actually went.
                       */}
                      <dd className="code">
                        {payment.destination.instapay_address_url ??
                          payment.destination.bank_account_number ??
                          payment.destination.wallet_phone ??
                          "—"}
                      </dd>
                    </div>
                  )}
                  {payment.unallocated_piastres > 0 && (
                    <div>
                      <dt>Not yet against a month</dt>
                      <dd>
                        <Money
                          piastres={payment.unallocated_piastres}
                          kind="agreed"
                          tone="owed"
                        />
                      </dd>
                    </div>
                  )}
                </dl>

                {payment.note && <p className="paid__note">{payment.note}</p>}

                {/*
                 * ADR 0017. The model can already see this; so should the
                 * person being asked "are you sure you sent it?".
                 */}
                {payment.has_proof && (
                  <>
                    <button
                      type="button"
                      className="button settle__proof-toggle"
                      onClick={() =>
                        setShowing(showing === payment.id ? null : payment.id)
                      }
                    >
                      {showing === payment.id ? "Hide the screenshot" : "Show the screenshot"}
                    </button>
                    {showing === payment.id && (
                      <img
                        className="settle__proof"
                        src={`/api/payments/${payment.id}/proof`}
                        alt={`Screenshot of the ${payment.amount} payment`}
                      />
                    )}
                  </>
                )}
              </li>
            ))}
          </ul>
        )}
      </section>

      {/*
       * §11.5. Adjustments are not payments and are not shown as though they
       * were: nothing moved. They explain why a month settles at a figure the
       * payments alone do not add up to.
       */}
      <section className="panel">
        <div className="panel__head">
          <h2 className="panel__title">Adjustments</h2>
        </div>
        {history.adjustments.length === 0 ? (
          <p className="empty">
            None. Every month has settled on what was actually sent.
          </p>
        ) : (
          <ul className="paid">
            {history.adjustments.map((row) => (
              <li key={row.id} className="paid__row">
                <div className="paid__head">
                  <Money piastres={row.amount_piastres} kind="agreed" />
                  <span className="paid__when">
                    {ADJUSTMENT_WORD[row.type] ?? row.type}
                  </span>
                </div>
                <dl className="paid__facts">
                  <div>
                    <dt>From</dt>
                    <dd>{formatMonth(row.from_month)}</dd>
                  </div>
                  {row.to_month && (
                    <div>
                      <dt>Against</dt>
                      <dd>{formatMonth(row.to_month)}</dd>
                    </div>
                  )}
                </dl>
                <p className="paid__note">{row.reason}</p>
              </li>
            ))}
          </ul>
        )}
      </section>
    </>
  );
}
