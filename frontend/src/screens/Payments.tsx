import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";

import { Money } from "../components/Money";
import { MonthPicker } from "../components/MonthPicker";
import type { MonthLock } from "../components/MonthPicker";
import { api, can } from "../lib/api";
import type { Session } from "../lib/api";
import {
  currentMonth,
  describeBlocker,
  formatEgp,
  formatMonth,
} from "../lib/money";
import "./Payments.css";

export type SettlementState =
  | "unpaid"
  | "partially_paid"
  | "settled"
  | "overpaid"
  | "not_approved"
  | "settled_externally";

export type RequiredKind =
  | "approved"
  | "forecast"
  | "unavailable"
  | "settled_externally";

export type Balance = {
  affiliate_id: number;
  name: string;
  status: "pending" | "active" | "inactive" | "archived";
  month: string;
  state: SettlementState;
  payroll_snapshot_id?: number;
  version?: number;
  obligation_piastres: number;
  /** What left the bank for this month, across every version of it. */
  paid_piastres: number;
  /** Of that, what settled the version currently in force. */
  paid_this_version_piastres?: number;
  /** And what settled a version that has since been superseded. */
  paid_earlier_versions_piastres?: number;
  versions?: {
    version: number;
    obligation_piastres: number;
    paid_piastres: number;
    approved_at: string | null;
    is_current: boolean;
  }[];
  adjusted_piastres: number;
  credited_piastres: number;
  balance_piastres: number;
  forecast_piastres: number | null;
  forecast_blockers: string[];
  required_kind: RequiredKind;
  required_piastres: number;
  destination_changed_at?: string | null;
};

type OpenCorrection = {
  affiliate_id: number;
  name: string;
  status: Balance["status"];
  month: string;
  recoverable_piastres: number;
};

type Outstanding = {
  month: string;
  affiliates: Balance[];
  open_corrections: OpenCorrection[];
  totals: {
    affiliates: number;
    required_piastres: number;
    forecast_piastres: number;
    approved_piastres: number;
    recorded_piastres: number;
    still_owed_affiliates: number;
    still_owed_piastres: number;
    open_corrections: number;
    open_corrections_piastres: number;
  };
};

export const STATE_LABEL: Record<SettlementState, string> = {
  unpaid: "Not paid yet",
  partially_paid: "Part paid",
  settled: "Settled",
  overpaid: "Overpaid",
  not_approved: "Nothing agreed yet",
  settled_externally: "Paid outside the platform",
};

export function toneFor(state: SettlementState): "owed" | "settled" | "neutral" {
  if (state === "unpaid" || state === "partially_paid") return "owed";
  if (state === "settled") return "settled";
  return "neutral";
}

type RowAction =
  | "Review and agree"
  | "Record payment"
  | "Settle difference"
  | "Open history";

type RowPresentation = {
  label: string;
  explanation: string | null;
  action: RowAction;
};

/**
 * Translate ledger facts into the one next act a payer needs.
 *
 * A zero balance has more than one cause. In particular, D04 permits a model
 * to earn money and receive no new transfer because an earlier overpayment
 * already covers it. Calling that “paid” would invent a transfer; calling it
 * an error would contradict the approved recovery rule.
 */
export function paymentRowPresentation(row: Balance): RowPresentation {
  if (row.state === "not_approved") {
    return {
      label:
        row.required_kind === "forecast"
          ? "Forecast — not agreed"
          : "Needs attention before approval",
      explanation:
        row.forecast_blockers.length > 0
          ? row.forecast_blockers.map(describeBlocker).join(" · ")
          : "Review the moving figure before it becomes money HBA owes.",
      action: "Review and agree",
    };
  }
  if (row.state === "partially_paid") {
    return { label: "Part paid", explanation: null, action: "Record payment" };
  }
  if (row.state === "unpaid") {
    return {
      label: "Ready to send",
      explanation: null,
      action: "Record payment",
    };
  }
  if (row.state === "overpaid") {
    return {
      label: "More sent than due",
      explanation: "Review the recorded transfers before deciding the difference.",
      action: "Settle difference",
    };
  }
  if (row.state === "settled_externally") {
    return {
      label: "Paid outside the platform",
      explanation: "No transfer is recorded or repeated here.",
      action: "Open history",
    };
  }
  if (row.credited_piastres > 0 && row.paid_piastres === 0) {
    return {
      label: "No transfer due",
      explanation: `${formatEgp(row.credited_piastres)} already sent in an earlier month covers this month, so it is not sent again.`,
      action: "Open history",
    };
  }
  if (row.paid_piastres === 0) {
    return {
      label: "No transfer due",
      explanation:
        row.adjusted_piastres > 0
          ? "The recorded adjustment settles this month without a transfer."
          : "There is no money to send for this agreed month.",
      action: "Open history",
    };
  }
  return { label: "Fully paid", explanation: null, action: "Open history" };
}

type Filter = "all" | "review" | "unpaid" | "partial" | "paid" | "no_due";

const FILTERS: { value: Filter; label: string }[] = [
  { value: "all", label: "All" },
  { value: "review", label: "Awaiting approval" },
  { value: "unpaid", label: "Not paid" },
  { value: "partial", label: "Part paid" },
  { value: "paid", label: "Fully paid" },
  { value: "no_due", label: "No transfer due" },
];

function matchesFilter(row: Balance, filter: Filter): boolean {
  const view = paymentRowPresentation(row);
  if (filter === "all") return true;
  if (filter === "review") return row.state === "not_approved";
  if (filter === "unpaid") return row.state === "unpaid";
  if (filter === "partial") return row.state === "partially_paid";
  if (filter === "paid") return view.label === "Fully paid";
  return view.label === "No transfer due";
}

/**
 * The admin month-end control desk.
 *
 * The three headline figures intentionally remain separate: a forecast helps
 * request cash, an approved obligation is fixed, and remaining is the money
 * still to transfer. Adding or relabelling them would turn a moving estimate
 * into a debt or make an approval look like payment (F14).
 */
export function Payments({ session }: { session: Session }) {
  const [month, setMonth] = useState(session.platform.working_month);
  const [data, setData] = useState<Outstanding | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [lockNote, setLockNote] = useState<string | null>(null);
  const [filter, setFilter] = useState<Filter>("all");
  const [search, setSearch] = useState("");

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
  const visibleRows = useMemo(() => {
    const term = search.trim().toLocaleLowerCase();
    return rows.filter(
      (row) =>
        matchesFilter(row, filter) &&
        (term === "" || row.name.toLocaleLowerCase().includes(term)),
    );
  }, [filter, rows, search]);

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
                ? `${formatMonth(candidate)} was paid outside the platform. No payment is recorded or repeated here.`
                : `${formatMonth(candidate)} has not finished, so there is no month-end payment run yet.`,
            )
          }
        />
      </div>

      {error && (
        <p
          className="notice notice--refused"
          role="alert"
        >
          {error}
        </p>
      )}

      {lockNote && <p className="notice payments__note">{lockNote}</p>}
      {data === null && !error && <p className="empty">Loading…</p>}

      {data && (
        <>
          <section
            className="payments__summary"
            aria-label="Month-end payment totals"
          >
            <PaymentFigure
              label="Total funds required"
              piastres={data.totals.required_piastres}
              provisional={data.totals.forecast_piastres > 0}
              detail={
                data.totals.forecast_piastres > 0
                  ? `${formatEgp(data.totals.approved_piastres)} approved · ${formatEgp(data.totals.forecast_piastres)} forecast.`
                  : `${formatEgp(data.totals.approved_piastres)} is approved.`
              }
            />
            <PaymentFigure
              label="Recorded as sent"
              piastres={data.totals.recorded_piastres}
              detail="Actual transfers in this month’s ledger."
            />
            <PaymentFigure
              label="Still to transfer"
              piastres={data.totals.still_owed_piastres}
              detail={
                data.totals.still_owed_affiliates === 1
                  ? "One model is waiting."
                  : `${data.totals.still_owed_affiliates} models are waiting.`
              }
              owed
            />
          </section>

          {/*
           * 05C made each correction visible on one model. That is not enough
           * at month end: nobody can remember to open every profile. This one
           * cross-model queue is deliberately above the payment table so
           * already-advanced money is considered before another transfer.
           */}
          {data.open_corrections.length > 0 && (
            <section className="panel payments__corrections">
              <div className="panel__head payments__correction-head">
                <div>
                  <h2 className="panel__title">Unresolved earlier payments</h2>
                  <p className="payments__correction-lead">
                    Decide whether each amount is carried forward or absorbed
                    before it is forgotten at month end.
                  </p>
                </div>
                <Money
                  piastres={data.totals.open_corrections_piastres}
                  kind="agreed"
                  tone="owed"
                />
              </div>
              <ul className="payments__correction-list">
                {data.open_corrections.map((row) => (
                  <li
                    key={`${row.affiliate_id}-${row.month}`}
                    className="payments__correction"
                  >
                    <span>
                      <strong>{row.name}</strong>
                      {row.status !== "active" && (
                        <span className="payments__person-state">{row.status}</span>
                      )}
                      <span className="payments__correction-month">
                        {formatMonth(row.month)}
                      </span>
                    </span>
                    <Money
                      piastres={row.recoverable_piastres}
                      kind="agreed"
                      tone="owed"
                    />
                    <Link
                      className="button"
                      to={`/affiliates/${row.affiliate_id}#corrections`}
                    >
                      Review correction
                    </Link>
                  </li>
                ))}
              </ul>
            </section>
          )}

          <section className="panel payments__desk">
            <div className="payments__tools">
              <div
                className="payments__filters"
                role="group"
                aria-label="Filter payment states"
              >
                {FILTERS.map((option) => (
                  <button
                    key={option.value}
                    type="button"
                    className={
                      filter === option.value
                        ? "payments__filter payments__filter--active"
                        : "payments__filter"
                    }
                    aria-pressed={filter === option.value}
                    onClick={() => setFilter(option.value)}
                  >
                    {option.label}
                  </button>
                ))}
              </div>
              <label className="payments__search">
                <span className="sr-only">Find a model</span>
                <input
                  className="input"
                  type="search"
                  value={search}
                  onChange={(event) => setSearch(event.target.value)}
                  placeholder="Find a model"
                />
              </label>
            </div>

            {rows.length === 0 ? (
              <p className="empty">No models in this month-end run.</p>
            ) : visibleRows.length === 0 ? (
              <p className="empty">No models match this view.</p>
            ) : (
              <div className="payments__table-wrap">
                <table className="table payments__table">
                  <thead>
                    <tr>
                      <th>Model</th>
                      <th>Payment state</th>
                      <th className="payments__amount">Funds required</th>
                      <th className="payments__amount">Recorded</th>
                      <th className="payments__amount">Remaining</th>
                      <th />
                    </tr>
                  </thead>
                  <tbody>
                    {visibleRows.map((row) => (
                      <PaymentRow
                        key={row.affiliate_id}
                        row={row}
                        month={month}
                        canRecord={can(session, "payments.record")}
                        canApprove={can(session, "payroll.approve")}
                      />
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>
        </>
      )}
    </>
  );
}

function PaymentFigure({
  label,
  piastres,
  detail,
  owed = false,
  provisional = false,
}: {
  label: string;
  piastres: number;
  detail: string;
  owed?: boolean;
  provisional?: boolean;
}) {
  return (
    <div className="payments__figure">
      <span className="payments__figure-label">{label}</span>
      <Money
        piastres={piastres}
        kind={provisional ? "provisional" : "agreed"}
        tone={owed && piastres > 0 ? "owed" : "neutral"}
        className="payments__total"
      />
      <span className="payments__figure-detail">{detail}</span>
    </div>
  );
}

function PaymentRow({
  row,
  month,
  canRecord,
  canApprove,
}: {
  row: Balance;
  month: string;
  canRecord: boolean;
  canApprove: boolean;
}) {
  const view = paymentRowPresentation(row);
  const isForecast = row.required_kind === "forecast";

  return (
    <tr>
      <td>
        <Link
          className="payments__name"
          to={`/affiliates/${row.affiliate_id}`}
        >
          {row.name}
        </Link>
        {row.status !== "active" && (
          <span className="payments__person-state">{row.status}</span>
        )}
      </td>
      <td className="payments__state">
        <span>{view.label}</span>
        {view.explanation && (
          <span className="payments__state-note">{view.explanation}</span>
        )}
      </td>
      <td className="payments__amount">
        {row.required_kind === "unavailable" ? (
          <span className="payments__unavailable">Unavailable</span>
        ) : (
          <>
            <Money
              piastres={row.required_piastres}
              kind={isForecast ? "provisional" : "agreed"}
            />
            <span className="payments__part">
              {isForecast ? (
                "forecast — not agreed"
              ) : row.required_piastres === row.obligation_piastres ? (
                "approved"
              ) : (
                <>
                  <Money
                    piastres={row.obligation_piastres}
                    kind="agreed"
                  />{" "}
                  approved
                </>
              )}
            </span>
          </>
        )}
      </td>
      <td className="payments__amount">
        <Money
          piastres={row.paid_piastres}
          kind="agreed"
        />
      </td>
      <td className="payments__amount">
        <Money
          piastres={row.balance_piastres}
          kind="agreed"
          tone={toneFor(row.state)}
        />
        {row.credited_piastres > 0 && (
          <span className="payments__part">
            <Money piastres={row.credited_piastres} /> from earlier payment
          </span>
        )}
      </td>
      <td className="payments__action">
        <PaymentAction
          row={row}
          month={month}
          action={view.action}
          canRecord={canRecord}
          canApprove={canApprove}
        />
      </td>
    </tr>
  );
}

function PaymentAction({
  row,
  month,
  action,
  canRecord,
  canApprove,
}: {
  row: Balance;
  month: string;
  action: RowAction;
  canRecord: boolean;
  canApprove: boolean;
}) {
  if (action === "Review and agree" && canApprove) {
    return (
      <Link
        className="button"
        to={`/payroll/${month}/approve`}
        state={{
          affiliate_ids: [row.affiliate_id],
          return_to: "/payments",
        }}
      >
        {action}
      </Link>
    );
  }
  if (action === "Record payment" && canRecord) {
    return (
      <Link
        className="button button--primary"
        to={`/payments/${month}/${row.affiliate_id}`}
      >
        {action}
      </Link>
    );
  }
  if (action === "Settle difference" && canRecord) {
    return (
      <Link
        className="button"
        to={`/payments/${month}/${row.affiliate_id}/reconcile`}
      >
        {action}
      </Link>
    );
  }
  return (
    <Link
      className="button"
      to={`/affiliates/${row.affiliate_id}/payments`}
    >
      Open history
    </Link>
  );
}
