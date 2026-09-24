import { useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";

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
  platformMonths,
} from "../lib/money";
import { NO_DESTINATION_RECORDED, PAY_TYPE, describeDestination } from "../lib/payouts";
import type { DestinationCard } from "../lib/payouts";

// Re-exported where it has always been imported from, so this move is not a
// change to anybody else's imports.
export type { DestinationCard };
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
  /** Her arrangement for this month, as a type — the wording lives here. */
  terms?: string | null;
  /** Masked on the server. Enough to recognise, never the full number. */
  destination?: Record<string, string | null> | null;
  /**
   * The destination as the approved table writes it — `InstaPay · 010 7014
   * 2033`, in full. Present only for an account that may record payments;
   * `null` otherwise, and the masked sentence is used instead. ADR 0042.
   */
  destination_line?: string | null;
  /** The full details the approved payment card draws. ADR 0042. */
  destination_card?: DestinationCard | null;
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
  /** What is left of the month's whole difference, money or not. */
  outstanding_piastres: number;
  /** `no_transfer_recorded` where the difference is real and nothing moved. */
  review_reason: string | null;
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

/**
 * What the button in the last column says.
 *
 * Three of these are the export's own words. `Settle difference` is ours: an
 * overpaid month is a state the export never drew, and it needs an act of its
 * own rather than being folded into `Open`.
 */
type RowAction =
  | "Review"
  | "Record payment"
  | "Fix terms"
  | "Settle difference"
  | "Open";

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
  /*
   * **A model with no arrangement cannot be paid at all**, and the export
   * gives that its own red pill rather than letting it read as one more month
   * awaiting a look. It is the only state on this screen that is somebody's
   * mistake instead of somebody's turn.
   */
  if (row.terms === null && row.state === "not_approved") {
    return {
      label: "Terms missing",
      explanation: "Nothing can be calculated until an arrangement is set.",
      action: "Fix terms",
    };
  }
  if (row.state === "not_approved") {
    return {
      label: "Awaiting approval",
      explanation:
        row.forecast_blockers.length > 0
          ? row.forecast_blockers.map(describeBlocker).join(" · ")
          : "Review the moving figure before it becomes money HBA owes.",
      action: "Review",
    };
  }
  if (row.state === "partially_paid") {
    return { label: "Partly paid", explanation: null, action: "Record payment" };
  }
  if (row.state === "unpaid") {
    return {
      label: "Approved",
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
      action: "Open",
    };
  }
  if (row.credited_piastres > 0 && row.paid_piastres === 0) {
    return {
      label: "No transfer due",
      explanation: `${formatEgp(row.credited_piastres)} already sent in an earlier month covers this month, so it is not sent again.`,
      action: "Open",
    };
  }
  if (row.paid_piastres === 0) {
    return {
      label: "No transfer due",
      explanation:
        row.adjusted_piastres > 0
          ? "The recorded adjustment settles this month without a transfer."
          : "There is no money to send for this agreed month.",
      action: "Open",
    };
  }
  return { label: "Fully paid", explanation: null, action: "Open" };
}

/**
 * The colour of each state, measured off the export.
 *
 * Amber where somebody still has to act, the accent where money has been
 * released, its lifted step where a month is closed, red where an arrangement
 * is missing altogether. Anything this table does not name falls back to the
 * quiet tier rather than borrowing a meaning it has not earned.
 */
export const STATE_PILL: Record<string, string> = {
  "Awaiting approval": "payments__pill--owed",
  "Partly paid": "payments__pill--owed",
  Approved: "payments__pill--approved",
  "Fully paid": "payments__pill--settled",
  "Terms missing": "payments__pill--refused",
  "More sent than due": "payments__pill--refused",
};

type Filter = "all" | "review" | "unpaid" | "partial" | "paid" | "no_due";

const FILTERS: { value: Filter; label: string }[] = [
  { value: "all", label: "All" },
  { value: "review", label: "Awaiting approval" },
  { value: "unpaid", label: "Approved" },
  { value: "partial", label: "Partly paid" },
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
  const [query] = useSearchParams();
  const [month, setMonth] = useState(query.get("month")?.match(/^\d{4}-(0[1-9]|1[0-2])$/) ? query.get("month")! : session.platform.working_month);
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
        (!query.get("affiliate") || String(row.affiliate_id) === query.get("affiliate")) &&
        matchesFilter(row, filter) &&
        (term === "" || row.name.toLocaleLowerCase().includes(term)),
    );
  }, [filter, rows, search, query]);

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
          months={platformMonths(session.platform)}
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
            {/*
             * Three cards, three grounds, no sub-lines. Each used to carry a
             * sentence under the figure - how much of the total was approved,
             * that the second number came from the ledger, how many models
             * were waiting. All three were ours, none is in the export, and
             * together they turned a row somebody reads in one glance into
             * three paragraphs.
             */}
            <PaymentFigure
              label="Total required"
              piastres={data.totals.required_piastres}
              estimated={data.totals.forecast_piastres > 0}
            />
            <PaymentFigure
              label="Recorded so far"
              piastres={data.totals.recorded_piastres}
              settled
            />
            <PaymentFigure
              label="Remaining to send"
              piastres={data.totals.still_owed_piastres}
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
                  <h2 className="panel__title">Agreed months that have changed</h2>
                  <p className="payments__correction-lead">
                    {/*
                     * F09. Not every row here is money: a month whose transfer
                     * has not been recorded has a real difference and nothing
                     * to take back, and it belongs in the queue as much as the
                     * others. The figure beside the heading is only the part
                     * that was advanced.
                     */}
                    Look at each one before another transfer is made. Where
                    money was sent, decide whether it is carried forward or
                    absorbed; the total is what has been advanced.
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
                        {row.review_reason === "no_transfer_recorded" &&
                          " · nothing sent yet"}
                      </span>
                    </span>
                    <Money
                      piastres={row.outstanding_piastres}
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

          <section className="payments__desk" aria-label="Month-end payments">
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
                      filter === option.value ? "chip chip--on" : "chip"
                    }
                    aria-pressed={filter === option.value}
                    onClick={() => setFilter(option.value)}
                  >
                    {option.label}
                    {/* The count rides inside the label — *Approved 4* — as
                     *  the export writes it. A filter you cannot see the size
                     *  of is a filter you have to click to evaluate. */}
                    <span className="payments__filter-count">
                      {rows.filter((row) => matchesFilter(row, option.value)).length}
                    </span>
                  </button>
                ))}
              </div>
              <input
                className="input input--search"
                type="search"
                value={search}
                onChange={(event) => setSearch(event.target.value)}
                placeholder="Search model names"
                aria-label="Search model names"
              />
            </div>

            {rows.length === 0 ? (
              <div className="surface"><p className="empty">No models in this month-end run.</p></div>
            ) : visibleRows.length === 0 ? (
              /* **Two empty lists, two sentences.** An empty *filter* is
               *  often good news - nobody is in *No transfer due* means every
               *  month owes something - and telling somebody their search
               *  found nothing when they have not searched sends them looking
               *  for a search box they never used. */
              <div className="surface">
                <p className="empty">
                  {search.trim()
                    ? "No model matches that search."
                    : `Nothing in ${FILTERS.find((f) => f.value === filter)?.label.toLowerCase() ?? "this filter"} for this month.`}
                </p>
              </div>
            ) : (
              <div className="surface payments__table-wrap">
                <table className="table payments__table">
                  <thead>
                    <tr>
                      <th className="payments__who">Model</th>
                      <th className="payments__amount">To receive</th>
                      <th className="payments__destination">Destination</th>
                      <th className="payments__state">State</th>
                      <th className="payments__action">Next action</th>
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
  owed = false,
  settled = false,
  estimated = false,
}: {
  label: string;
  piastres: number;
  owed?: boolean;
  settled?: boolean;
  /** F14. A total that still contains a forecast is not a debt yet, and the
   *  export says so with a pill beside the label rather than in a sentence. */
  estimated?: boolean;
}) {
  return (
    <div className="payments__figure">
      <span className="payments__figure-head">
        <span className="payments__figure-label">{label}</span>
        {estimated && <span className="pill payments__estimated">Estimated</span>}
      </span>
      <Money
        piastres={piastres}
        kind="agreed"
        tone={owed && piastres > 0 ? "owed" : settled ? "settled" : "neutral"}
        className="payments__total"
      />
    </div>
  );
}

/**
 * What this row's headline figure is. A02.
 *
 * **It is the month's transfer, and it used to be `balance_piastres`.** That
 * is what is *left* to send, which is zero on an unapproved month by
 * construction and zero again once a month is fully paid - so the list showed
 * Boda EGP 0.00 for September while her own detail screen showed an estimated
 * EGP 14,224, and a settled row showed nothing where the export shows what was
 * sent.
 *
 * `required_piastres` is the figure the export's rows carry
 * (`egp(pay.total)`): the month's entitlement less any deduction landing on
 * it, before payments. The server computes it the same way on both sides of
 * the approved/forecast line, which is what stops one column meaning two
 * things depending on a state the reader cannot see. It is also what the
 * page's own "Funds required" total already adds up, so the row and the
 * header finally agree.
 *
 * Not "replace every zero with a forecast": a genuine zero - a model with no
 * sales, a month settled outside the platform - still reads zero, and the
 * *remaining* figure keeps its own place on the second line below.
 */
export function amountShown(row: Balance): number {
  return row.required_piastres;
}

/**
 * The one line under the figure, and only where it adds something.
 *
 * The export allows exactly one, and chooses the deduction over the receipt
 * when there is one: a month paying less than it earned because an earlier
 * overpayment is being recovered needs that said, or the headline looks like
 * a mistake. Otherwise it is what has already been sent, and where neither
 * applies there is no line at all.
 */
export function secondLine(row: Balance) {
  if (row.credited_piastres > 0) {
    return (
      <span className="payments__part">
        <Money piastres={row.credited_piastres} /> deducted
      </span>
    );
  }
  if (row.paid_piastres > 0) {
    return (
      <span className="payments__part">
        <Money piastres={row.paid_piastres} /> recorded
      </span>
    );
  }
  return null;
}

export function PaymentRow({
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
      <td className="payments__who">
        {/* The export opens the model's payment for this month from her name,
         *  not her profile - the profile is one link further, from there. */}
        <Link className="payments__name control-font" to={`/payments/${month}/${row.affiliate_id}`}>
          {row.name}
        </Link>
        {/* Her arrangement under her name, as the export writes it: the
         *  person about to send this money should not have to remember
         *  whether it is a salary, a commission or a floor. */}
        <span className="payments__terms">
          {row.terms ? PAY_TYPE[row.terms] ?? row.terms : "No terms set"}
          {row.status !== "active" && (
            <span className="payments__person-state">· {row.status}</span>
          )}
        </span>
      </td>
      <td className="payments__amount">
        {row.required_kind === "unavailable" ? (
          <span className="payments__unavailable">Unavailable</span>
        ) : (
          <>
            <Money
              piastres={amountShown(row)}
              kind={isForecast ? "provisional" : "agreed"}
            />
            {/* One figure, and a second line only where it is not the whole
             *  story - the export puts what has already been recorded there
             *  and nothing else. *forecast - not agreed* used to follow every
             *  unapproved figure, which is the third place on this screen
             *  saying the same thing: the total already wears an `Estimated`
             *  badge and the row already wears an `Awaiting approval` pill. */}
            {secondLine(row)}
          </>
        )}
      </td>
      <td className="payments__destination">
        {/* **The real destination, on the row.** The approved export writes
         *  `InstaPay · 010 7014 2033` here and the owner asked for exactly
         *  that: the person reading this list is about to type it into a
         *  banking app, and `…291` cannot be typed. The server sends it only
         *  to somebody who may record payments; anybody else still gets the
         *  masked sentence. ADR 0042. */}
        <span className="payments__where">
          <span>
            {/* **Three cases, not two.** `destination_line` is null both
                when there is no destination *and* when the reader may not
                send money (ADR 0042 gates it on `payments.record`), and
                collapsing those printed *No destination recorded* to
                marketing about a model who had submitted her details
                perfectly well. The masked sentence is what they saw before
                and what they see now. */}
            {row.destination_line ??
              (row.destination
                ? describeDestination(row.destination)
                : NO_DESTINATION_RECORDED)}
          </span>
          {row.destination_card && canRecord && (
            <CopyDestination card={row.destination_card} />
          )}
        </span>
      </td>
      {/*
       * **A pill, and nothing else.**
       *
       * This carried a second line of explanation - *Review the moving figure
       * before it becomes money HBA owes* on every unapproved row, twenty
       * times down a list. The export draws one outlined pill whose colour is
       * the explanation: amber is somebody's turn, green is settled, red is a
       * mistake. What the blockers actually are belongs on the model's own
       * payment view, which is where somebody acts on them, and
       * `view.explanation` still carries them there.
       */}
      <td className="payments__state">
        <span className={`pill ${STATE_PILL[view.label] ?? "payments__pill--quiet"}`}>
          {view.label}
        </span>
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

/**
 * *Copy* beside a destination, because the next thing that happens to it is
 * being typed into a banking app. Retyping an account number off a screen is
 * the step where a digit goes missing.
 */
export function CopyDestination({ card }: { card: DestinationCard }) {
  const [state, setState] = useState<"idle" | "copied" | "failed">("idle");
  // The number itself, not the sentence around it: what gets pasted into a
  // banking app has to be the value and nothing else. The row the design
  // marks `copy` is the one that carries it.
  const value =
    card.rows.find((entry) => entry.copy === "number" || entry.copy === "account")
      ?.value ?? card.rows[0]?.value ?? "";
  return (
    <button
      type="button"
      className="button button--quiet payments__copy"
      aria-label="Copy destination"
      onClick={async () => {
        try {
          await navigator.clipboard.writeText(value);
          setState("copied");
        } catch {
          setState("failed");
        }
        window.setTimeout(() => setState("idle"), 2000);
      }}
    >
      {state === "copied" ? "Copied" : state === "failed" ? "Not copied" : "Copy"}
    </button>
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
  /*
   * The export gives an act that moves money an accent outline and an act
   * that only looks at something a plain one. `Open` is the second kind, and
   * it is also the fallback for anybody without the permission to do the
   * first - which is why the label is computed above and the link below
   * decides nothing about wording.
   */
  // *Review* opens the month's payment view, which carries the approval -
  // the export approves one model's month there, beside what it adds up to.
  if (action === "Review") {
    return (
      <Link
        className={canApprove ? "button button--row button--primary" : "button button--row"}
        to={`/payments/${month}/${row.affiliate_id}`}
      >
        {action}
      </Link>
    );
  }
  if (action === "Fix terms") {
    return (
      <Link
        className="button button--row button--primary"
        to={`/affiliates/${row.affiliate_id}/compensation`}
      >
        {action}
      </Link>
    );
  }
  if (action === "Record payment" && canRecord) {
    return (
      <Link
        className="button button--row button--primary"
        to={`/payments/${month}/${row.affiliate_id}/record`}
      >
        {action}
      </Link>
    );
  }
  if (action === "Settle difference" && canRecord) {
    return (
      <Link
        className="button button--row"
        to={`/payments/${month}/${row.affiliate_id}/reconcile`}
      >
        {action}
      </Link>
    );
  }
  return (
    <Link
      className="button button--row"
      to={`/payments/${month}/${row.affiliate_id}`}
    >
      Open
    </Link>
  );
}
