import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";

import { Money } from "../components/Money";
import { MonthPicker } from "../components/MonthPicker";
import type { MonthLock } from "../components/MonthPicker";
import { api, can } from "../lib/api";
import type { Session } from "../lib/api";
import { currentMonth, describeBlocker, formatMonth } from "../lib/money";
import "./Payroll.css";

export type PayrollRow = {
  affiliate_id: number;
  name: string;
  month: string;
  calculation_state: "draft" | "approved" | "historical";
  orders: { earned: number; pending: number; void: number };
  /** What it would come to if calculated now. Free to move. */
  obligation_piastres: number;
  /** What was agreed, or null if nothing has been. Cannot move. */
  approved_obligation_piastres: number | null;
  carried_forward: { from_month: string; orders: number; piastres: number }[];
  blockers: string[];
  is_payable: boolean;
  version: number | null;
};

type HistoricalRow = {
  affiliate_id: number;
  name: string;
  month: string;
  calculation_state: "historical";
  orders: number;
  net_sales_piastres: number;
  label: string;
  is_payable: false;
};

export type PayrollMonth = {
  month: string;
  is_historical: boolean;
  affiliates: (PayrollRow | HistoricalRow)[];
  totals: {
    affiliates: number;
    payable_affiliates: number;
    blocked_affiliates: number;
    obligation_piastres: number;
  };
};

type Reopened = {
  left_reopened: { affiliate_id: number; name: string; month: string }[];
};

/**
 * Blockers that settle a row on their own.
 *
 * `blockers` is one flat list on the server because approval only cares
 * whether it is empty. A screen cannot use it that way, and the first version
 * of this page proved it: the house account arrived carrying *both*
 * `house_accounts_are_never_owed` **and** `no_compensation_terms_for_this
 * _month`, so a rule of "are they all harmless?" painted HBA's own code red
 * and told somebody to go and set pay terms for an account that must never
 * have any.
 *
 * These two answer the question by themselves. A house account is never owed
 * money whatever else is true of it, and a month settled before the platform
 * is not ours to agree. Nothing listed beside them is worth reading.
 */
const NEVER_OWED = "house_accounts_are_never_owed";
const BEFORE_THE_PLATFORM = "month_predates_the_platform";

/**
 * Blockers that are ordinary states rather than obstacles.
 *
 * Painting these the same red as a missing target would spend the one signal
 * the page has on rows that need nothing — the same mistake as warning about a
 * working discount code (docs/limits.md).
 */
const NOT_A_PROBLEM = new Set([
  NEVER_OWED,
  BEFORE_THE_PLATFORM,
  "month_is_already_approved",
]);

export type RowState = "ready" | "needs-you" | "approved" | "nothing-to-do";

export function rowState(row: PayrollRow): RowState {
  if (row.calculation_state === "approved") return "approved";
  if (row.blockers.includes(NEVER_OWED)) return "nothing-to-do";
  if (row.blockers.includes(BEFORE_THE_PLATFORM)) return "nothing-to-do";
  if (row.is_payable) return "ready";
  return row.blockers.every((key) => NOT_A_PROBLEM.has(key))
    ? "nothing-to-do"
    : "needs-you";
}

/** The blockers worth showing. The rest are states, not obstacles. */
export function actionable(row: PayrollRow): string[] {
  if (rowState(row) !== "needs-you") return [];
  return row.blockers.filter((key) => !NOT_A_PROBLEM.has(key));
}

/**
 * Why a settled row is settled — one line, not a list.
 *
 * A house account with no pay terms has two entries and only one of them is
 * the reason. Printing both invites somebody to go and fix the other.
 */
export function settledReason(row: PayrollRow): string | null {
  if (row.blockers.includes(NEVER_OWED)) return NEVER_OWED;
  if (row.blockers.includes(BEFORE_THE_PLATFORM)) return BEFORE_THE_PLATFORM;
  return row.blockers.find((key) => NOT_A_PROBLEM.has(key)) ?? null;
}

function isHistorical(
  row: PayrollRow | HistoricalRow,
): row is HistoricalRow {
  return row.calculation_state === "historical";
}

const STATE_LABEL: Record<RowState, string> = {
  ready: "Ready",
  "needs-you": "Needs you",
  approved: "Approved",
  "nothing-to-do": "Not paid",
};

/**
 * Month end.
 *
 * The decision here is *can I agree this month, and if not, what is stopping
 * me* — so the figures at the top are what it would cost and who is holding it
 * up, and every row says which of those it is.
 *
 * Nothing on this page commits anything. Approval is Pattern C (§12.2): its
 * own page, with a preview of exactly what is about to become an obligation.
 */
export function Payroll({ session }: { session: Session }) {
  const navigate = useNavigate();
  const [month, setMonth] = useState(session.platform.working_month);
  const [data, setData] = useState<PayrollMonth | null>(null);
  const [reopened, setReopened] = useState<Reopened | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [chosen, setChosen] = useState<Set<number>>(new Set());
  const [lockNote, setLockNote] = useState<string | null>(null);

  useEffect(() => {
    setError(null);
    setChosen(new Set());
    setLockNote(null);
    Promise.all([
      api.get<PayrollMonth>(`/api/payroll/${month}`),
      api.get<Reopened>(`/api/payroll/${month}/reopened`),
    ])
      .then(([body, stuck]) => {
        setData(body);
        setReopened(stuck);
      })
      .catch((caught) => setError(caught.message));
  }, [month]);

  const rows = data?.affiliates ?? [];
  const live = rows.filter((row): row is PayrollRow => !isHistorical(row));
  const ready = live.filter((row) => rowState(row) === "ready");
  const needsYou = live.filter((row) => rowState(row) === "needs-you");
  const approved = live.filter((row) => rowState(row) === "approved");
  const agreedTotal = approved.reduce(
    (sum, row) => sum + (row.approved_obligation_piastres ?? 0),
    0,
  );

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

  function toggle(id: number) {
    setChosen((was) => {
      const next = new Set(was);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  const allReadyChosen = ready.length > 0 && ready.every((r) => chosen.has(r.affiliate_id));

  return (
    <>
      <div className="page__head">
        <div className="page__title">
          <h1>Payroll</h1>
          <span className="page__subtitle">{formatMonth(month)}</span>
        </div>
        <MonthPicker
          value={month}
          onChange={setMonth}
          lockFor={lockFor}
          onLockedClick={(candidate, lock) =>
            setLockNote(
              lock === "historical"
                ? `${formatMonth(candidate)} was settled before the platform. It shows sales, and no commission figure — the rates that applied then live in the old system.`
                : `${formatMonth(candidate)} has not finished. Orders are still arriving, so anything here will move.`,
            )
          }
        />
      </div>

      {error && (
        <p className="notice notice--refused" role="alert">
          {error}
        </p>
      )}

      {lockNote && <p className="notice payroll__note">{lockNote}</p>}

      {/*
       * §11.5. The dangerous state is not reopening a month — it is forgetting
       * that you did. A month sitting in draft with payments already made
       * against a superseded version is a balance nobody is watching, and
       * nothing else on any screen would ever mention it.
       */}
      {reopened && reopened.left_reopened.length > 0 && (
        <p className="notice notice--refused payroll__note" role="alert">
          {reopened.left_reopened.length === 1
            ? "One month was reopened and never approved again:"
            : `${reopened.left_reopened.length} months were reopened and never approved again:`}{" "}
          {reopened.left_reopened
            .map((row) => `${row.name} — ${formatMonth(row.month)}`)
            .join(", ")}
          . Payments made against the old version still stand, so what is owed
          is unsettled until each one is approved again.
        </p>
      )}

      {data === null && !error && <p className="empty">Loading…</p>}

      {data?.is_historical && (
        <p className="notice payroll__note">
          Paid outside the platform, so this month shows sales and no commission
          figure. Applying today’s rates to a month settled under the old ones
          would be a guess presented as a fact.
        </p>
      )}

      {data && !data.is_historical && (
        <div className="payroll__figures">
          {/*
           * Two figures, and they are deliberately not added together. One is
           * an obligation and one is a working number, and ADR 0027 exists so
           * that the difference is visible before the digits are read — the
           * agreed total is set in mono, the projected one in prose.
           */}
          <div className="payroll__figure">
            <Money
              piastres={agreedTotal}
              kind="agreed"
              tone={agreedTotal > 0 ? "owed" : "neutral"}
              className="payroll__total"
            />
            <span className="payroll__figure-label">
              agreed so far for {formatMonth(month)}
            </span>
          </div>
          <div className="payroll__figure">
            <Money
              piastres={data.totals.obligation_piastres}
              className="payroll__total"
            />
            <span className="payroll__figure-label">
              {ready.length === 0
                ? "would be added — nobody is ready to approve"
                : ready.length === 1
                  ? "would be added by approving the one model ready"
                  : `would be added by approving the ${ready.length} models ready`}
            </span>
          </div>
          <div className="payroll__figure">
            <strong
              className={
                needsYou.length > 0
                  ? "payroll__count payroll__count--refused"
                  : "payroll__count"
              }
            >
              {needsYou.length}
            </strong>
            <span className="payroll__figure-label">need you</span>
          </div>
        </div>
      )}

      {data && rows.length === 0 && (
        <p className="empty">Nobody on the programme this month.</p>
      )}

      {data && rows.length > 0 && (
        <table className="table payroll__table">
          <thead>
            <tr>
              <th className="payroll__pick">
                {!data.is_historical && ready.length > 0 && (
                  <input
                    type="checkbox"
                    checked={allReadyChosen}
                    aria-label="Choose everyone ready"
                    onChange={(event) =>
                      setChosen(
                        event.target.checked
                          ? new Set(ready.map((r) => r.affiliate_id))
                          : new Set(),
                      )
                    }
                  />
                )}
              </th>
              <th>Name</th>
              <th>State</th>
              <th>Orders</th>
              <th className="payroll__amount">
                {data.is_historical ? "Net sales" : "Would be paid"}
              </th>
              <th>Carried forward</th>
              <th>Waiting on</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) =>
              isHistorical(row) ? (
                <tr key={row.affiliate_id} className="payroll__row--quiet">
                  <td />
                  <td>
                    <Link
                      className="payroll__name"
                      to={`/affiliates/${row.affiliate_id}`}
                    >
                      {row.name}
                    </Link>
                  </td>
                  <td className="payroll__state">Settled before</td>
                  <td className="code">{row.orders}</td>
                  <td className="payroll__amount">
                    <Money piastres={row.net_sales_piastres} />
                  </td>
                  <td />
                  <td />
                </tr>
              ) : (
                <PayrollTableRow
                  key={row.affiliate_id}
                  row={row}
                  chosen={chosen.has(row.affiliate_id)}
                  onToggle={() => toggle(row.affiliate_id)}
                />
              ),
            )}
          </tbody>
        </table>
      )}

      {/*
       * The button counts and prices what it will do. "Approve" alone leaves
       * the person to work out what they just agreed to, and the whole point
       * of §11.3 is that nobody should have to.
       */}
      {data && !data.is_historical && can(session, "payroll.approve") && (
        <div className="payroll__actions">
          <button
            type="button"
            className="button button--primary"
            disabled={chosen.size === 0}
            onClick={() =>
              navigate(`/payroll/${month}/approve`, {
                state: { affiliate_ids: [...chosen] },
              })
            }
          >
            {chosen.size === 0
              ? "Choose who to approve"
              : `Review ${chosen.size} for approval`}
          </button>
          {approved.length > 0 && can(session, "payroll.reopen") && (
            <Link className="button" to={`/payroll/${month}/reopen`}>
              Reopen an agreed month
            </Link>
          )}
        </div>
      )}
    </>
  );
}

function PayrollTableRow({
  row,
  chosen,
  onToggle,
}: {
  row: PayrollRow;
  chosen: boolean;
  onToggle: () => void;
}) {
  const state = rowState(row);
  const stopping = actionable(row);

  return (
    <tr className={state === "nothing-to-do" ? "payroll__row--quiet" : undefined}>
      <td className="payroll__pick">
        {state === "ready" && (
          <input
            type="checkbox"
            checked={chosen}
            onChange={onToggle}
            aria-label={`Include ${row.name}`}
          />
        )}
      </td>
      <td>
        <Link className="payroll__name" to={`/affiliates/${row.affiliate_id}`}>
          {row.name}
        </Link>
      </td>
      <td className={`payroll__state payroll__state--${state}`}>
        {STATE_LABEL[state]}
        {state === "approved" && row.version !== null && (
          <span className="payroll__version">v{row.version}</span>
        )}
      </td>
      <td className="payroll__orders">
        <span className="code">{row.orders.earned}</span> counted
        {row.orders.pending > 0 && (
          <span className="payroll__pending">
            {row.orders.pending} still travelling
          </span>
        )}
      </td>
      {/*
       * ADR 0027. An approved figure is set in the mono face because it is an
       * obligation and cannot change; a draft one is prose because it is still
       * being worked out. A blocked figure is neither owed nor coloured as if
       * it were.
       */}
      <td className="payroll__amount">
        <Money
          piastres={
            state === "approved" && row.approved_obligation_piastres !== null
              ? row.approved_obligation_piastres
              : row.obligation_piastres
          }
          kind={
            state === "approved"
              ? "agreed"
              : state === "ready"
                ? "provisional"
                : "blocked"
          }
          tone={state === "ready" && row.obligation_piastres > 0 ? "owed" : "neutral"}
        />
      </td>
      <td className="payroll__carried">
        {row.carried_forward.map((line) => (
          <span key={line.from_month} className="payroll__carried-line">
            {line.orders} order{line.orders === 1 ? "" : "s"} from{" "}
            {formatMonth(line.from_month)}
            {/*
             * Sales, not commission. `carry_forward_summary` sums
             * commission_base_piastres, and labelling that as a payout would
             * overstate what the line is worth by roughly ten times.
             */}
            <span className="payroll__carried-sales">
              <Money piastres={line.piastres} /> of sales
            </span>
          </span>
        ))}
      </td>
      <td>
        {stopping.map((key) => (
          <span key={key} className="blocker payroll__blocker">
            {describeBlocker(key)}
          </span>
        ))}
        {state === "nothing-to-do" && settledReason(row) && (
          <span className="payroll__quiet-reason">
            {describeBlocker(settledReason(row) as string)}
          </span>
        )}
      </td>
    </tr>
  );
}
