import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { Money } from "../components/Money";
import { MonthPicker } from "../components/MonthPicker";
import type { MonthLock } from "../components/MonthPicker";
import { api, can } from "../lib/api";
import type { Session } from "../lib/api";
import { currentMonth, formatMonth } from "../lib/money";
import "./Payments.css";

export type SettlementState =
  | "unpaid"
  | "partially_paid"
  | "settled"
  | "overpaid"
  | "not_approved";

export type Balance = {
  affiliate_id: number;
  name: string;
  month: string;
  state: SettlementState;
  payroll_snapshot_id?: number;
  version?: number;
  obligation_piastres: number;
  paid_piastres: number;
  adjusted_piastres: number;
  credited_piastres: number;
  balance_piastres: number;
  /** Only on a month with no active snapshot: was there ever one? */
  reopened?: boolean;
};

type Outstanding = {
  month: string;
  affiliates: Balance[];
  totals: {
    affiliates: number;
    still_owed_affiliates: number;
    still_owed_piastres: number;
  };
};

/**
 * What each state means to somebody about to send money.
 *
 * `not_approved` is the one worth spelling out. It is **not** "owes nothing" —
 * it means there is no agreed figure to settle against, either because payroll
 * has not been run or because the month was reopened. Saying "nothing
 * outstanding" about a month that may have been paid in full against a
 * superseded version is the most misleading answer available (§11.1).
 */
export const STATE_LABEL: Record<SettlementState, string> = {
  unpaid: "Not paid yet",
  partially_paid: "Part paid",
  settled: "Settled",
  overpaid: "Overpaid",
  not_approved: "Nothing agreed yet",
};

/** Money and money alone carries colour (ADR 0027). */
export function toneFor(state: SettlementState): "owed" | "settled" | "neutral" {
  if (state === "unpaid" || state === "partially_paid") return "owed";
  if (state === "settled") return "settled";
  return "neutral";
}

/**
 * Paying what payroll agreed.
 *
 * The decision is *who is still waiting for money* — so the figure at the top
 * is what is still outstanding, and the table is sorted by nothing clever:
 * every row is here because somebody may need to be paid, and the ones who do
 * are the ones with a balance.
 *
 * Nothing on this page moves money. Recording a payment is Pattern C (§12.2):
 * its own page, per model, with the destination revealed there and not here.
 */
export function Payments({ session }: { session: Session }) {
  const [month, setMonth] = useState(session.platform.working_month);
  const [data, setData] = useState<Outstanding | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [lockNote, setLockNote] = useState<string | null>(null);

  useEffect(() => {
    setError(null);
    setLockNote(null);
    api
      .get<Outstanding>(`/api/payments/${month}`)
      .then(setData)
      .catch((caught) => setError(caught.message));
  }, [month]);

  function lockFor(candidate: string): MonthLock {
    if (
      session.platform.go_live_month &&
      candidate < session.platform.go_live_month
    ) {
      return "historical";
    }
    if (candidate > currentMonth()) return "future";
    return null;
  }

  const rows = data?.affiliates ?? [];
  const owing = rows.filter((row) => row.balance_piastres > 0);
  const overpaid = rows.filter((row) => row.state === "overpaid");
  const reopened = rows.filter((row) => row.reopened);

  return (
    <>
      <div className="page__head">
        <div className="page__title">
          <h1>Payments</h1>
          <span className="page__subtitle">{formatMonth(month)}</span>
        </div>
        <MonthPicker
          value={month}
          onChange={setMonth}
          lockFor={lockFor}
          onLockedClick={(candidate, lock) =>
            setLockNote(
              lock === "historical"
                ? `${formatMonth(candidate)} was settled before the platform, so nothing here was paid through it.`
                : `${formatMonth(candidate)} has not finished, so nothing has been agreed to pay yet.`,
            )
          }
        />
      </div>

      {error && (
        <p className="notice notice--refused" role="alert">
          {error}
        </p>
      )}

      {lockNote && <p className="notice payments__note">{lockNote}</p>}

      {/*
       * §11.5. A month reopened has no agreed figure, but may already have been
       * paid in full against the version that was withdrawn. The row would
       * otherwise read a flat "Nothing agreed yet" and look like a month
       * nobody had touched.
       */}
      {reopened.length > 0 && (
        <p className="notice notice--refused payments__note" role="alert">
          {reopened.map((row) => row.name).join(", ")}{" "}
          {reopened.length === 1 ? "has a month" : "have months"} that
          {reopened.length === 1 ? " was" : " were"} reopened and not agreed
          again. Money already sent stays attached to the version it settled,
          but until payroll is approved again there is no figure to measure it
          against.
        </p>
      )}

      {data === null && !error && <p className="empty">Loading…</p>}

      {data && (
        <div className="payments__figures">
          <div className="payments__figure">
            <Money
              piastres={data.totals.still_owed_piastres}
              kind="agreed"
              tone={data.totals.still_owed_piastres > 0 ? "owed" : "settled"}
              className="payments__total"
            />
            <span className="payments__figure-label">
              {owing.length === 0
                ? `nothing outstanding for ${formatMonth(month)}`
                : `still to send to ${owing.length} ${
                    owing.length === 1 ? "model" : "models"
                  }`}
            </span>
          </div>
          {overpaid.length > 0 && (
            <div className="payments__figure">
              <strong className="payments__count">{overpaid.length}</strong>
              <span className="payments__figure-label">
                overpaid — needs a decision
              </span>
            </div>
          )}
        </div>
      )}

      {data && rows.length === 0 && (
        <p className="empty">Nobody on the programme this month.</p>
      )}

      {data && rows.length > 0 && (
        <table className="table payments__table">
          <thead>
            <tr>
              <th>Name</th>
              <th>State</th>
              <th className="payments__amount">Agreed</th>
              <th className="payments__amount">Paid</th>
              <th className="payments__amount">Still owed</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr
                key={row.affiliate_id}
                className={
                  row.state === "not_approved" && !row.reopened
                    ? "payments__row--quiet"
                    : undefined
                }
              >
                <td>
                  <Link
                    className="payments__name"
                    to={`/affiliates/${row.affiliate_id}`}
                  >
                    {row.name}
                  </Link>
                </td>
                <td className={`payments__state payments__state--${row.state}`}>
                  {STATE_LABEL[row.state]}
                  {row.version !== undefined && (
                    <span className="payments__version">v{row.version}</span>
                  )}
                </td>
                {/* Everything in these three columns is settled money, so all
                    of it is set in the mono face (ADR 0027). */}
                <td className="payments__amount">
                  <Money piastres={row.obligation_piastres} kind="agreed" />
                  {row.credited_piastres > 0 && (
                    <span className="payments__part">
                      + <Money piastres={row.credited_piastres} /> carried in
                    </span>
                  )}
                </td>
                <td className="payments__amount">
                  <Money piastres={row.paid_piastres} kind="agreed" />
                  {row.adjusted_piastres > 0 && (
                    <span className="payments__part">
                      + <Money piastres={row.adjusted_piastres} /> written off
                      or credited
                    </span>
                  )}
                </td>
                <td className="payments__amount">
                  <Money
                    piastres={row.balance_piastres}
                    kind="agreed"
                    tone={toneFor(row.state)}
                  />
                </td>
                <td className="payments__action">
                  {can(session, "payments.record") &&
                    row.payroll_snapshot_id !== undefined &&
                    row.balance_piastres > 0 && (
                      <Link
                        className="button"
                        to={`/payments/${month}/${row.affiliate_id}`}
                      >
                        Pay
                      </Link>
                    )}
                  {can(session, "payments.record") &&
                    row.state === "overpaid" && (
                      <Link
                        className="button"
                        to={`/payments/${month}/${row.affiliate_id}/reconcile`}
                      >
                        Settle the difference
                      </Link>
                    )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </>
  );
}
