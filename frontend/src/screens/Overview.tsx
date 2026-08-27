import { useEffect, useState } from "react";

import { Money } from "../components/Money";
import { MonthPicker } from "../components/MonthPicker";
import type { MonthLock } from "../components/MonthPicker";
import { api } from "../lib/api";
import type { Session } from "../lib/api";
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

/** §16's in-platform notifications. Empty on a healthy platform. */
type Attention = {
  items: {
    key: string;
    severity: "blocking" | "attention";
    text: string;
    detail: string;
    where: string;
  }[];
  blocking: number;
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
export function Overview({ session }: { session: Session }) {
  // Opens on the working month, which before go-live is the month the
  // platform starts in rather than an August it holds nothing for.
  const [month, setMonth] = useState(session.platform.working_month);
  const [payroll, setPayroll] = useState<PayrollMonth | null>(null);
  const [sync, setSync] = useState<SyncStatus | null>(null);
  const [attention, setAttention] = useState<Attention | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [lockNote, setLockNote] = useState<string | null>(null);

  useEffect(() => {
    setError(null);
    Promise.all([
      api.get<PayrollMonth>(`/api/payroll/${month}`),
      api.get<SyncStatus>("/api/operations/sync"),
      api.get<Attention>("/api/operations/attention"),
    ])
      .then(([months, status, needing]) => {
        setPayroll(months);
        setSync(status);
        setAttention(needing);
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
       * §16's in-platform notifications, where somebody lands rather than
       * behind a tab they have to think to open. Every item is conditional on
       * something genuinely true and genuinely actionable, and the whole panel
       * disappears on a healthy platform - which is what makes it worth
       * reading when it does not.
       *
       * The go-live warning used to be a bespoke banner here. It is one of
       * these now: the judgement about what deserves attention belongs on the
       * server, in one place, rather than being spread across screens that ask
       * the same question differently.
       */}
      {attention && attention.items.length > 0 && (
        <section className="attention">
          {attention.items.map((item) => (
            <div
              key={item.key}
              className={
                item.severity === "blocking"
                  ? "attention__item attention__item--blocking"
                  : "attention__item"
              }
            >
              <p className="attention__text">{item.text}</p>
              <p className="attention__detail">{item.detail}</p>
            </div>
          ))}
        </section>
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
