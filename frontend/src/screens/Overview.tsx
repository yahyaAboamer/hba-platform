import { useEffect, useState } from "react";

import { Money } from "../components/Money";
import { MonthPicker } from "../components/MonthPicker";
import type { MonthLock } from "../components/MonthPicker";
import { api } from "../lib/api";
import { currentMonth, describeBlocker, formatMonth } from "../lib/money";

type PayrollRow = {
  affiliate_id: number;
  name: string;
  calculation_state?: string;
  obligation_piastres?: number;
  blockers?: string[];
  is_payable?: boolean;
  /* Historical months carry sales and no commission figure (ADR 0014). */
  net_sales_piastres?: number;
  orders?: number | { earned: number; pending: number; void: number };
};

type PayrollMonth = {
  month: string;
  is_historical: boolean;
  affiliates: PayrollRow[];
  totals: {
    affiliates: number;
    payable_affiliates: number;
    blocked_affiliates: number;
    obligation_piastres: number;
  };
};

type SyncStatus = {
  orders_indexed: number;
  go_live_month: string | null;
  payroll_can_be_approved: boolean;
  jobs: { failed: number };
};

/**
 * Where a month stands.
 *
 * §12.3's noted tension applies here: a page carries summary figures only where
 * they support the decision made on that page. The decision on this page is
 * *can I run payroll for this month, and if not, what is stopping me* — so the
 * figures are what is owed, who is blocked, and why.
 *
 * Nothing here is a chart. Twenty rows is not a dataset.
 */
export function Overview() {
  const [month, setMonth] = useState(currentMonth);
  const [payroll, setPayroll] = useState<PayrollMonth | null>(null);
  const [sync, setSync] = useState<SyncStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [lockNote, setLockNote] = useState<string | null>(null);

  useEffect(() => {
    setError(null);
    Promise.all([
      api.get<PayrollMonth>(`/api/payroll/${month}`),
      api.get<SyncStatus>("/api/operations/sync"),
    ])
      .then(([months, status]) => {
        setPayroll(months);
        setSync(status);
      })
      .catch((caught) => setError(caught.message));
    setLockNote(null);
  }, [month]);

  function lockFor(candidate: string): MonthLock {
    if (sync?.go_live_month && candidate < sync.go_live_month) return "historical";
    if (candidate > currentMonth()) return "future";
    return null;
  }

  const blocked = payroll?.affiliates.filter((row) => row.blockers?.length) ?? [];

  return (
    <>
      <div className="page__head">
        <div className="page__title">
          <h1>Overview</h1>
          <span className="page__subtitle">{formatMonth(month)}</span>
        </div>
        <MonthPicker
          value={month}
          onChange={setMonth}
          lockFor={lockFor}
          onLockedClick={(candidate, lock) =>
            setLockNote(
              lock === "historical"
                ? `${formatMonth(candidate)} was settled before the platform, so it shows sales and no commission figure.`
                : `${formatMonth(candidate)} has not finished. Orders are still arriving, so the figures will move.`,
            )
          }
        />
      </div>

      {lockNote && (
        <p className="notice" style={{ marginBottom: "var(--space-4)" }}>
          {lockNote}
        </p>
      )}

      {error && (
        <p className="notice notice--refused" role="alert">
          {error}
        </p>
      )}

      {/*
       * The one thing that stops everything. GO_LIVE_MONTH blank blocks every
       * approval by design, and a person who does not know that will read a
       * screen full of blocked months as a bug.
       */}
      {sync && !sync.payroll_can_be_approved && (
        <p className="notice notice--refused" style={{ marginBottom: "var(--space-5)" }}>
          No go-live month is set, so no month can be approved. Set{" "}
          <code className="code">GO_LIVE_MONTH</code> to the first month the
          platform is responsible for paying.
        </p>
      )}

      {/*
        * A month before go-live is a different page, not the same page with
        * zeroes in it. §11.2: those months were settled outside the platform,
        * so "owed" and "blocked" are not questions about them - and answering
        * them with 0 and 5 at the same time, which an earlier version did, is
        * worse than not answering at all.
        */}
      {payroll?.is_historical && (
        <section className="panel">
          <div className="panel__head">
            <h2 className="panel__title">{formatMonth(month)}</h2>
            <span className="state">settled before the platform</span>
          </div>
          <p className="empty">
            Paid outside the platform, so it shows sales and no commission
            figure. The rates that applied then live in the old system and in
            somebody's memory; applying today's would be misleading.
          </p>
          <table className="table">
            <thead>
              <tr>
                <th>Model</th>
                <th className="numeric">Net sales</th>
              </tr>
            </thead>
            <tbody>
              {payroll.affiliates.map((row) => (
                <tr key={row.affiliate_id}>
                  <td>{row.name}</td>
                  <td className="numeric">
                    <Money piastres={row.net_sales_piastres ?? 0} kind="blocked" />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}

      {payroll && !payroll.is_historical && (
        <>
          <div className="overview__figures">
            {/*
              * "Ready to approve", not "owed". Nothing is owed until a month is
              * approved - that is the distinction seven phases exist to keep,
              * and the label was quietly breaking it.
              */}
            <Figure
              label="Ready to approve"
              value={
                <Money
                  piastres={payroll.totals.obligation_piastres}
                  tone={payroll.totals.obligation_piastres > 0 ? "owed" : "neutral"}
                />
              }
              note={`${payroll.totals.payable_affiliates} of ${payroll.totals.affiliates} models`}
            />
            <Figure
              label="Blocked"
              value={
                <span className="overview__count">
                  {payroll.totals.blocked_affiliates}
                </span>
              }
              note={
                payroll.totals.blocked_affiliates
                  ? "Something is missing, not something is wrong"
                  : "Nothing waiting"
              }
            />
            <Figure
              label="Orders indexed"
              value={
                <span className="overview__count">{sync?.orders_indexed ?? "—"}</span>
              }
              note={sync?.jobs.failed ? `${sync.jobs.failed} failed jobs` : "Sync healthy"}
            />
          </div>

          <section className="panel">
            <div className="panel__head">
              <h2 className="panel__title">What is stopping {formatMonth(month)}</h2>
            </div>
            {blocked.length === 0 ? (
              <p className="empty">
                Nothing. Every model on the programme is ready to approve.
              </p>
            ) : (
              <table className="table">
                <thead>
                  <tr>
                    <th>Model</th>
                    <th>Waiting on</th>
                    <th className="numeric">Would be</th>
                  </tr>
                </thead>
                <tbody>
                  {blocked.map((row) => (
                    <tr key={row.affiliate_id}>
                      <td>{row.name}</td>
                      <td>
                        <ul className="overview__blockers">
                          {row.blockers!.map((key) => (
                            <li key={key} className="blocker">
                              {describeBlocker(key)}
                            </li>
                          ))}
                        </ul>
                      </td>
                      <td className="numeric">
                        {/*
                         * ADR 0027. Set in the prose face, because it is not an
                         * obligation - it is what the figure would be if the
                         * missing thing arrived.
                         */}
                        <Money
                          piastres={row.obligation_piastres ?? 0}
                          kind="blocked"
                        />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </section>
        </>
      )}
    </>
  );
}

function Figure({
  label,
  value,
  note,
}: {
  label: string;
  value: React.ReactNode;
  note: string;
}) {
  return (
    <div className="overview__figure">
      <span className="overview__label">{label}</span>
      <span className="overview__value">{value}</span>
      <span className="overview__note">{note}</span>
    </div>
  );
}
