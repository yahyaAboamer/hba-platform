import { useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";

import { Money } from "../../components/Money";
import { MonthPicker } from "../../components/MonthPicker";
import type { MonthLock } from "../../components/MonthPicker";
import { api, can } from "../../lib/api";
import type { Session } from "../../lib/api";
import {
  currentMonth,
  describeBlocker,
  formatEgp,
  formatMonth,
  platformMonths,
} from "../../lib/money";
import { NO_DESTINATION_RECORDED, PAY_TYPE, describeDestination } from "../../lib/payouts";
import type { DestinationCard } from "../../lib/payouts";

// Re-exported where it has always been imported from, so this move is not a
// change to anybody else's imports.
export type { DestinationCard };
import { useHistoryState } from "./HistoricalSetup";
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

type Outstanding = {
  month: string;
  affiliates: Balance[];
  totals: {
    affiliates: number;
    required_piastres: number;
    forecast_piastres: number;
    approved_piastres: number;
    recorded_piastres: number;
    still_owed_affiliates: number;
    still_owed_piastres: number;
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
    /* *Approved* alone was ambiguous: a part-paid and a fully paid month
     * are approved too. The state is "agreed, nothing sent yet", and the
     * payer's next act is the label (refinement F-L4). */
    return {
      label: "Ready to send",
      explanation: null,
      action: "Record payment",
    };
  }
  if (row.state === "overpaid") {
    return {
      label: "Overpaid",
      explanation: "More was sent than this month was approved at. Decide what happens to the difference.",
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
  "Ready to send": "payments__pill--approved",
  "Fully paid": "payments__pill--settled",
  "Terms missing": "payments__pill--refused",
  Overpaid: "payments__pill--refused",
};

type Filter = "all" | "review" | "unpaid" | "partial" | "paid" | "no_due";

const FILTERS: { value: Filter; label: string }[] = [
  { value: "all", label: "All" },
  { value: "review", label: "Awaiting approval" },
  { value: "unpaid", label: "Ready to send" },
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
  const mayOpenHistorical = can(session, "compensation.manage");
  // Asked only of somebody who will see the link.
  const history = useHistoryState(session, mayOpenHistorical);
  const [query] = useSearchParams();
  const [month, setMonth] = useState(query.get("month")?.match(/^\d{4}-(0[1-9]|1[0-2])$/) ? query.get("month")! : session.platform.working_month);
  const [data, setData] = useState<Outstanding | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [lockNote, setLockNote] = useState<string | null>(null);
  const [filter, setFilter] = useState<Filter>("all");
  const [search, setSearch] = useState("");

  // Bumped by *Try again*: a failed load is a dead end without it.
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    setError(null);
    setLockNote(null);
    api
      .get<Outstanding>(`/api/payments/${month}`)
      .then(setData)
      .catch((caught) => setError(caught.message));
  }, [month, attempt]);

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
      <div className="page__head payments__head">
        <div className="page__title">
          <h1>Payments</h1>
          <span className="page__subtitle">{formatMonth(month)}</span>
          {/* Off the sidebar since Batch 2.3; it leaves once every month before go-live is final (as before, it stays where that cannot be read). */}
          {mayOpenHistorical && history.state !== "complete" && (
            <Link className="control-font" to="/affiliates/historical">Historical setup →</Link>
          )}
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
        <div className="notice notice--refused payments__error" role="alert">
          <span>{error}</span>
          <button type="button" className="button button--row" onClick={() => setAttempt((n) => n + 1)}>
            Try again
          </button>
        </div>
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
             * **Two cash figures, nothing that has to be reconciled**
             * (refinement F-L1, then F2-1). A third card, *Total to send*,
             * summed the server's `required_piastres`, which is what was sent
             * plus what is left: on an overpaid month that counted money
             * already transferred - more than the month was approved at - as
             * still to send. *Left to send* is the act, so it comes first;
             * *Recorded* is what has already left the bank, overpayments
             * included, because that is what happened. Neither is the
             * approved total, and neither claims to be.
             */}
            <PaymentFigure
              label="Left to send"
              piastres={data.totals.still_owed_piastres}
              owed
            />
            <PaymentFigure
              label="Recorded"
              piastres={data.totals.recorded_piastres}
              settled
            />
          </section>
          <SummaryNotes rows={rows} forecast={data.totals.forecast_piastres} />


          {/*
           * No corrections panel here. The export puts an open correction on
           * Home, as a notice with *Open correction* (built from the same
           * `open_corrections` on the server), and on the model's own
           * payment review; the desk is the month's transfers only.
           */}
          <section className="payments__desk" aria-label="Month-end payments">
            <div className="payments__tools">
              <div
                className="payments__filters"
                role="group"
                aria-label="Filter payment states"
              >
                {/* A filter with nothing in it is hidden (F-L5), unless it is
                 *  the one selected: six chips, four of them reading 0, made
                 *  the row of choices harder to read than the list. */}
                {FILTERS.filter(
                  (option) =>
                    option.value === "all" ||
                    option.value === filter ||
                    rows.some((row) => matchesFilter(row, option.value)),
                ).map((option) => (
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
              <div className="surface payments__none">
                <p className="empty">
                  {search.trim()
                    ? "No model matches that search."
                    : `Nothing in ${FILTERS.find((f) => f.value === filter)?.label.toLowerCase() ?? "this filter"} for this month.`}
                </p>
                <button
                  type="button"
                  className="button button--row"
                  onClick={() => {
                    setSearch("");
                    setFilter("all");
                  }}
                >
                  Show all models
                </button>
              </div>
            ) : (
              <div className="surface payments__table-wrap">
                {/* Explicit roles: below 640px the rows are laid out as a list
                 *  of two-line rows, and a table whose CSS display changes
                 *  loses its semantics in Chromium unless they are stated. */}
                <table className="table payments__table" role="table">
                  <thead role="rowgroup">
                    <tr role="row">
                      <th role="columnheader" className="payments__who">Model</th>
                      <th role="columnheader" className="payments__amount">To receive</th>
                      <th role="columnheader" className="payments__destination">Destination</th>
                      <th role="columnheader" className="payments__state">State</th>
                      <th role="columnheader" className="payments__action">Next action</th>
                    </tr>
                  </thead>
                  <tbody role="rowgroup">
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

/**
 * What the two cards leave out, said once and only when it applies.
 *
 * Months not approved yet are an estimate (F14) and stay out of the cards;
 * somebody asking finance for the month's cash still needs the figure, so it
 * is here. An overpayment is in *Recorded* as what was actually sent, so the
 * line names who, and by how much.
 */
function SummaryNotes({ rows, forecast }: { rows: Balance[]; forecast: number }) {
  const waiting = rows.filter((row) => row.state === "not_approved").length;
  const overpaid = rows.filter((row) => row.state === "overpaid");
  if (waiting === 0 && overpaid.length === 0) return null;
  return (
    <p className="payments__summary-note">
      {waiting > 0 && (
        <span>
          Not approved yet: {waiting} {waiting === 1 ? "model" : "models"}
          {forecast > 0 && (
            <>
              , about <Money piastres={forecast} kind="provisional" />
            </>
          )}
        </span>
      )}
      {overpaid.length > 0 && (
        <span>
          Overpaid:{" "}
          {overpaid.map((row, index) => (
            <span key={row.affiliate_id}>
              {index > 0 && ", "}
              {row.name} by <Money piastres={-row.balance_piastres} />
            </span>
          ))}
        </span>
      )}
    </p>
  );
}

function PaymentFigure({
  label,
  piastres,
  owed = false,
  settled = false,
}: {
  label: string;
  piastres: number;
  owed?: boolean;
  settled?: boolean;
}) {
  return (
    <div className="payments__figure">
      <span className="payments__figure-head">
        <span className="payments__figure-label">{label}</span>
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
  /* **Except an overpaid month** (F2-1). There the server's figure is what
   * was sent - paid plus nothing left - which put EGP 8,500 under *To
   * receive* for a month approved at EGP 8,000. What she is due is the
   * approved amount; the excess is said on the line below. */
  if (row.state === "overpaid") return row.obligation_piastres;
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
  if (row.state === "overpaid") {
    return (
      <span className="payments__part payments__part--over">
        {/* The open excess, not what was sent: after part of it is settled,
         *  or when a credit landed, the two differ (review, round 2). */}
        <Money piastres={-row.balance_piastres} /> to settle
      </span>
    );
  }
  if (row.credited_piastres > 0) {
    return (
      <span className="payments__part">
        <Money piastres={row.credited_piastres} /> from credit
      </span>
    );
  }
  /* A fully paid row's *X recorded* only repeated its own headline beside a
   * *Fully paid* pill (F2-4). The line is for a month that is not the whole
   * story: what is left on a part-paid one. */
  if (row.state === "partially_paid" && row.balance_piastres > 0) {
    return (
      <span className="payments__part">
        <Money piastres={row.paid_piastres} /> recorded
        <span className="payments__left">
          <Money piastres={row.balance_piastres} /> left
        </span>
      </span>
    );
  }
  return null;
}

/** Whether this row's next act is sending money, so where it goes matters now. */
function sendsMoney(row: Balance): boolean {
  return row.required_kind === "approved" && row.balance_piastres > 0;
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
    <tr role="row">
      <td role="cell" className="payments__who">
        {/* The export opens the model's payment for this month from her name,
         *  not her profile - the profile is one link further, from there. */}
        <Link className="payments__name control-font" to={`/affiliates/payments/${month}/${row.affiliate_id}`}>
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
      <td role="cell" className="payments__amount">
        {row.required_kind === "unavailable" ? (
          /* *Unavailable* said nothing about why, while her own page showed
           * the blocker (F-L3). The reason is short, and it is the act. */
          <>
            <span className="payments__unavailable">Not worked out yet</span>
            <span className="payments__part payments__part--quiet">
              {row.terms === null
                ? "No pay terms"
                : row.forecast_blockers.length > 0
                  ? row.forecast_blockers.map(describeBlocker).join(" · ")
                  : "Missing information"}
            </span>
          </>
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
      <td
        role="cell"
        className={
          sendsMoney(row) || !row.destination
            ? "payments__destination"
            : "payments__destination payments__destination--idle"
        }
      >
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
          {/* Copy only where the next act is a transfer (F2-4): on a paid,
           *  credited or unapproved row it was eight more buttons for a
           *  number nobody was about to type. */}
          {row.destination_card && canRecord && sendsMoney(row) && (
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
      <td role="cell" className="payments__state">
        <span className={`pill ${STATE_PILL[view.label] ?? "payments__pill--quiet"}`}>
          {view.label}
        </span>
      </td>
      <td role="cell" className="payments__action">
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
        to={`/affiliates/payments/${month}/${row.affiliate_id}`}
      >
        {action}
      </Link>
    );
  }
  if (action === "Fix terms") {
    return (
      <Link
        className="button button--row button--primary"
        to={`/affiliates/models/${row.affiliate_id}/compensation`}
      >
        {action}
      </Link>
    );
  }
  if (action === "Record payment" && canRecord) {
    return (
      <Link
        className="button button--row button--primary"
        to={`/affiliates/payments/${month}/${row.affiliate_id}/record`}
      >
        {action}
      </Link>
    );
  }
  if (action === "Settle difference" && canRecord) {
    return (
      <Link
        className="button button--row"
        to={`/affiliates/payments/${month}/${row.affiliate_id}/reconcile`}
      >
        {action}
      </Link>
    );
  }
  return (
    <Link
      className="button button--row"
      to={`/affiliates/payments/${month}/${row.affiliate_id}`}
    >
      Open
    </Link>
  );
}
