import { useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";

import { api } from "../lib/api";
import {
  egpPlain,
  formatEgp,
  formatMonth,
  parseEgp,
  shortMonth,
} from "../lib/money";
import {
  fromServer,
  outcomesFrom,
  periodsToWrite,
  runs,
  toBasisPoints,
  MISSING_REASON,
} from "../lib/payHistory";
import type {
  Arrangement,
  Kind,
  MonthRow,
  PayHistory,
  Readiness,
  Run,
} from "../lib/payHistory";
import "./Payroll.css";
import "./Compensation.css";
import "./PaymentDetail.css";

const KIND_LABEL: Record<Kind, string> = {
  commission: "Commission only",
  fixed_plus_commission: "Salary + commission",
  base_guarantee: "Guaranteed minimum",
};

const KINDS = Object.keys(KIND_LABEL) as Kind[];

/** The export's words for the three choices on the arrangement buttons. */
const OPTION_LABEL: Record<Kind, string> = {
  commission: "Commission only",
  fixed_plus_commission: "Fixed salary plus commission",
  base_guarantee: "Guaranteed minimum with commission",
};

/** The one word a month tile has room for. */
function tileWord(arrangement: Arrangement | undefined): string {
  if (!arrangement) return "Not set";
  if (arrangement.kind === "fixed_plus_commission") return "Salary";
  if (arrangement.kind === "base_guarantee") return "Guarantee";
  return `${arrangement.rateBp / 100}%`;
}

function describeRun(run: Run): string {
  const rate = `${run.rateBp / 100}% commission`;
  if (run.kind === "fixed_plus_commission") return `${formatEgp(run.amountPiastres)} salary plus ${rate}`;
  if (run.kind === "base_guarantee") return `${formatEgp(run.amountPiastres)} minimum, ${rate}`;
  return rate;
}

/**
 * *Compensation terms* — `vTerms` in the approved export.
 *
 * Left: her terms through the year, one line for each run of months that
 * share an arrangement, newest first. Right: choose months on a year's grid
 * of twelve, choose the arrangement, and apply it to exactly those months.
 *
 * This screen used to open on two questions - *is she new or was she with
 * HBA already*, then *was it the same the whole time* - before it showed a
 * month at all, and it saved the whole history in a separate step at the
 * bottom. The export has no fork and no second step: selecting months and
 * applying terms to them **is** the save, and months that were not selected
 * are left exactly as they were.
 *
 * What stays, because each is a rule rather than a layout:
 *
 * - **An approved month cannot change**, and there is no reopening (05B). Its
 *   tile is marked and cannot be selected.
 * - A month before her first sale is not hers to arrange. A model who has
 *   never sold starts at the working month.
 * - A guaranteed minimum in a month settled before the platform records
 *   whether she met her targets (ADR 0036); the export never drew such a
 *   month, so the question appears only when one is selected.
 * - The whole history is written in one transaction, so a failed apply leaves
 *   nothing half-changed.
 */
export function Compensation() {
  const { id = "" } = useParams();

  const [data, setData] = useState<PayHistory | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [set, setSet] = useState<Record<string, Arrangement>>({});
  const [sel, setSel] = useState<string[]>([]);
  const [draft, setDraft] = useState<Draft | null>(null);
  const [year, setYear] = useState<string | null>(null);

  useEffect(() => {
    api
      .get<PayHistory>(`/api/affiliates/${id}/pay-history`)
      .then((body) => {
        setData(body);
        setSet(fromServer(body));
        setYear(body.working_month.slice(0, 4));
      })
      .catch((caught) => setError(caught.message));
  }, [id]);

  /** Her first month, decided by the server: when she started with HBA, not
   *  when she first sold (A06). A model signed in January whose first sale was
   *  in March still has January and February to arrange — and a salary is
   *  exactly what those months need, because there are no commissions in them
   *  to stand in for one. */
  const startMonth = data ? data.arrangeable_from : "";
  const arrangeable = useMemo(
    () => (data?.months ?? []).filter((row) => row.month >= startMonth),
    [data, startMonth],
  );
  const history = useMemo(() => runs(arrangeable, set).reverse(), [arrangeable, set]);

  if (error && data === null) {
    return (
      <p className="notice notice--refused" role="alert">
        {error}
      </p>
    );
  }
  if (data === null || year === null) return <p className="empty">Loading…</p>;

  const years = [...new Set(data.months.map((row) => row.month.slice(0, 4)))];
  const monthsOfYear = data.months.filter((row) => row.month.startsWith(year));
  /*
   * The export draws a whole year of twelve. The server lists months only up
   * to the working month, so the rest of the year is drawn as tiles that
   * cannot be chosen yet - otherwise September sat alone on a second row,
   * stretched across the whole card.
   */
  const laterThisYear = Array.from({ length: 12 }, (_, index) => `${year}-${String(index + 1).padStart(2, "0")}`)
    .filter((month) => !monthsOfYear.some((row) => row.month === month));
  const editable = (row: MonthRow) => row.month >= startMonth && !row.approved;
  const ordered = [...sel].sort();
  const selectedTerms = ordered.map((month) => set[month]);
  const mixed =
    ordered.length > 1 &&
    !selectedTerms.every(
      (terms) =>
        terms?.kind === selectedTerms[0]?.kind &&
        terms?.rateBp === selectedTerms[0]?.rateBp &&
        terms?.amountPiastres === selectedTerms[0]?.amountPiastres,
    );
  const outcomeMonths =
    draft?.kind === "base_guarantee"
      ? ordered.filter((month) => data.months.find((row) => row.month === month)?.settled_outside)
      : [];
  const amountLabel =
    draft?.kind === "fixed_plus_commission"
      ? "Fixed monthly salary, EGP"
      : draft?.kind === "base_guarantee"
        ? "Guaranteed minimum, EGP"
        : null;

  function toggle(row: MonthRow) {
    if (!editable(row)) return;
    const next = sel.includes(row.month)
      ? sel.filter((month) => month !== row.month)
      : [...sel, row.month];
    setSel(next);
    setDraft(next.length > 0 ? draftFor([...next].sort(), set) : null);
    setSaved(null);
    setError(null);
  }

  function selectAll() {
    const next = monthsOfYear.filter(editable).map((row) => row.month);
    setSel(next);
    setDraft(next.length > 0 ? draftFor(next, set) : null);
    setSaved(null);
    setError(null);
  }

  function clear() {
    setSel([]);
    setDraft(null);
    setSaved(null);
    setError(null);
  }

  /*
   * **Apply is the save.** The new arrangement is laid over exactly the
   * selected months, and the whole history - every run, every recorded
   * outcome - is written in the one transaction the server already makes of
   * it. The screen only takes the new state once the server has accepted it,
   * so a refusal leaves both the page and the record as they were.
   */
  async function apply() {
    if (!data || !draft || ordered.length === 0) return;
    const parsed = readDraft(draft);
    if (parsed === null) {
      setError(
        draft.kind === "commission"
          ? "Enter a commission rate above zero."
          : `Enter a commission rate and ${draft.kind === "fixed_plus_commission" ? "the fixed monthly salary" : "the guaranteed minimum"}.`,
      );
      return;
    }
    const next = { ...set };
    for (const month of ordered) {
      const row = data.months.find((candidate) => candidate.month === month);
      next[month] = {
        ...parsed,
        met: parsed.kind === "base_guarantee" && row?.settled_outside ? draft.met[month] ?? null : null,
      };
    }
    setSaving(true);
    setError(null);
    try {
      // **Every month she has, not the ones this screen lets you edit** (A06).
      //
      // The route replaces her whole pay history in one act, so what is sent
      // is the history — anything left out of it is deleted. Sending only the
      // arrangeable slice therefore quietly dropped terms recorded before the
      // start month, while the message below promised the opposite: *unselected
      // months are unchanged*. It was true of unselected months inside the
      // slice and false of everything before it.
      //
      // `set` already holds every month the server sent, including those, so
      // handing the whole list to `periodsToWrite` re-states them exactly as
      // they were and the replacement keeps them.
      await api.put(`/api/affiliates/${id}/pay-history`, {
        periods: periodsToWrite(data.months, next).map((run) => ({
          start_month: run.from,
          end_month: run.to === data.working_month ? null : run.to,
          compensation_type: run.kind,
          commission_rate_bp: run.rateBp,
          fixed_amount_piastres: run.kind === "fixed_plus_commission" ? run.amountPiastres : null,
          base_amount_piastres: run.kind === "base_guarantee" ? run.amountPiastres : null,
        })),
        outcomes: outcomesFrom(data.months, next),
      });
      setSet(next);
      setSaved(
        `Applied to ${ordered.length} ${ordered.length === 1 ? "month" : "months"}. Unselected months are unchanged.`,
      );
      setSel([]);
      setDraft(null);
    } catch (caught) {
      setError((caught as Error).message);
    } finally {
      setSaving(false);
    }
  }

  return (
    <>
      <div className="page__head">
        <Link className="button pay__back" to={`/affiliates/${id}`}>
          ← {data.name}
        </Link>
        <div className="page__title">
          <h1>Compensation terms</h1>
          <span className="page__subtitle">{data.name}</span>
        </div>
      </div>

      <div className="terms">
        <div className="terms__left">
          <section className="terms__history">
            <h2 className="terms__title">Terms through the year</h2>
            {history.length === 0 ? (
              <p className="terms__none">No terms have been set yet.</p>
            ) : (
              <ul>
                {history.map((run) => {
                  const current = run.from <= data.working_month && run.to >= data.working_month;
                  return (
                    <li key={run.from}>
                      <span className="terms__run-head">
                        <span>{OPTION_LABEL[run.kind]}</span>
                        <span className={current ? "terms__current" : "terms__earlier"}>
                          {current ? "Current" : "Earlier"}
                        </span>
                      </span>
                      <span className="terms__run-detail">{describeRun(run)}</span>
                      <span className="terms__run-range">
                        {formatMonth(run.from)}
                        {run.from === run.to ? "" : ` – ${formatMonth(run.to)}`}
                      </span>
                    </li>
                  );
                })}
              </ul>
            )}
          </section>
          <SetupReadiness readiness={data.readiness} />
        </div>

        <section className="terms__editor">
          <div className="terms__editor-head">
            <h2 className="terms__title terms__title--bare">Choose months</h2>
            <span className="terms__years">
              {years.map((each) => (
                <button
                  key={each}
                  type="button"
                  className={each === year ? "chip chip--on terms__year" : "chip terms__year"}
                  aria-pressed={each === year}
                  onClick={() => setYear(each)}
                >
                  {each}
                </button>
              ))}
            </span>
          </div>

          <div className="terms__months">
            {monthsOfYear.map((row) => {
              const before = row.month < startMonth;
              const on = sel.includes(row.month);
              return (
                <button
                  key={row.month}
                  type="button"
                  className={[
                    "terms__month",
                    on ? "terms__month--on" : "",
                    row.approved ? "terms__month--locked" : "",
                  ].join(" ")}
                  aria-pressed={on}
                  disabled={!editable(row)}
                  onClick={() => toggle(row)}
                >
                  <span className="terms__month-name">{shortMonth(row.month)}</span>
                  <span className="terms__month-what">{before ? "Before start" : tileWord(set[row.month])}</span>
                  <span className={row.approved ? "terms__month-note terms__month-note--locked" : "terms__month-note"}>
                    {row.approved ? "Approved" : before ? "—" : ""}
                  </span>
                </button>
              );
            })}
            {laterThisYear.map((month) => (
              <button key={month} type="button" className="terms__month" disabled>
                <span className="terms__month-name">{shortMonth(month)}</span>
                <span className="terms__month-what">Not yet</span>
                <span className="terms__month-note">—</span>
              </button>
            ))}
          </div>

          <div className="terms__selection">
            <span>
              {ordered.length === 0
                ? "No month selected"
                : `${ordered.length} ${ordered.length === 1 ? "month" : "months"} selected`}
            </span>
            <span className="terms__selection-acts">
              <button type="button" className="button button--row" onClick={selectAll}>
                Select all editable months in {year}
              </button>
              <button type="button" className="button button--row terms__clear" onClick={clear}>
                Clear
              </button>
            </span>
          </div>

          <div className="terms__arrangement">
            <h2 className="terms__title terms__title--bare">Arrangement</h2>
            {mixed && (
              <p className="terms__mixed">
                The selected months use different arrangements. Entering values
                here replaces all of them.
              </p>
            )}
            <div className="terms__options">
              {KINDS.map((kind) => (
                <button
                  key={kind}
                  type="button"
                  className={draft?.kind === kind ? "terms__option terms__option--on" : "terms__option"}
                  aria-pressed={draft?.kind === kind}
                  disabled={ordered.length === 0}
                  onClick={() =>
                    draft && setDraft({ ...draft, kind, met: kind === "base_guarantee" ? draft.met : {} })
                  }
                >
                  {OPTION_LABEL[kind]}
                </button>
              ))}
            </div>

            <label className="terms__field">
              <span>Commission rate, %</span>
              <input
                className="input terms__input"
                inputMode="decimal"
                value={draft?.rate ?? ""}
                placeholder={mixed ? "Mixed" : "e.g. 12"}
                disabled={ordered.length === 0}
                onChange={(event) => draft && setDraft({ ...draft, rate: event.target.value })}
              />
            </label>
            {amountLabel && draft && (
              <label className="terms__field">
                <span>{amountLabel}</span>
                <input
                  className="input terms__input"
                  inputMode="decimal"
                  value={draft.amount}
                  onChange={(event) => setDraft({ ...draft, amount: event.target.value })}
                />
              </label>
            )}

            {draft && outcomeMonths.length > 0 && (
              <div className="terms__outcomes">
                <span className="terms__outcomes-lead">
                  Did she meet her targets? Before the platform the outcome is
                  the whole record, and it decides whether the minimum applied.
                </span>
                {outcomeMonths.map((month) => (
                  <span key={month} className="terms__outcome">
                    <span>{formatMonth(month)}</span>
                    <span className="seg">
                      <label className="seg-opt">
                        <input
                          type="radio"
                          name={`met-${month}`}
                          checked={draft.met[month] === true}
                          onChange={() => setDraft({ ...draft, met: { ...draft.met, [month]: true } })}
                        />
                        <span>Met</span>
                      </label>
                      <label className="seg-opt">
                        <input
                          type="radio"
                          name={`met-${month}`}
                          checked={draft.met[month] === false}
                          onChange={() => setDraft({ ...draft, met: { ...draft.met, [month]: false } })}
                        />
                        <span>Missed</span>
                      </label>
                    </span>
                  </span>
                ))}
              </div>
            )}

            {error && (
              <p className="terms__error" role="alert">
                {error}
              </p>
            )}
            {saved && <p className="terms__saved">{saved}</p>}

            <div className="terms__acts">
              <button
                type="button"
                className="button button--primary terms__big"
                disabled={ordered.length === 0 || saving}
                onClick={apply}
              >
                {saving
                  ? "Applying…"
                  : ordered.length === 0
                    ? "Select months first"
                    : `Apply to ${ordered.length} ${ordered.length === 1 ? "month" : "months"}`}
              </button>
              <Link className="button terms__big" to={`/affiliates/${id}`}>
                Done
              </Link>
            </div>
            <p className="terms__note">
              Approved months cannot change. There is no reopening action.
            </p>
          </div>
        </section>
      </div>
    </>
  );
}

function SetupReadiness({ readiness }: { readiness: Readiness }) {
  const blocking = readiness.months.filter((row) => !row.ready);
  if (blocking.length === 0) return null;

  return (
    <section className="terms__history terms__blocking">
      <h2 className="terms__title">Still needed before these months pay</h2>
      <ul>
        {blocking.map((row) => (
          <li key={row.month}>
            <span className="terms__run-head">
              <span>{formatMonth(row.month)}</span>
            </span>
            <span className="terms__run-detail">
              {row.missing.map((reason) => MISSING_REASON[reason]).join(" · ")}
            </span>
          </li>
        ))}
      </ul>
    </section>
  );
}

/* ── the editor panel ──────────────────────────────────────────────────────── */

type Draft = {
  kind: Kind;
  /** Held as typed, so a half-typed "1" is not read as 1%. */
  rate: string;
  amount: string;
  met: Record<string, boolean>;
};

function blankDraft(): Draft {
  return { kind: "commission", rate: "10", amount: "", met: {} };
}

function draftFor(months: string[], set: Record<string, Arrangement>): Draft {
  const existing = set[months[0]];
  if (!existing) return blankDraft();
  const met: Record<string, boolean> = {};
  for (const month of months) {
    const current = set[month];
    if (current?.met !== null && current?.met !== undefined) met[month] = current.met;
  }
  return {
    kind: existing.kind,
    rate: String(existing.rateBp / 100),
    amount: existing.kind === "commission" ? "" : egpPlain(existing.amountPiastres),
    met,
  };
}

/** The draft as numbers, or `null` while it is not yet a valid arrangement. */
function readDraft(draft: Draft): Omit<Arrangement, "met"> | null {
  const rateBp = toBasisPoints(draft.rate);
  if (rateBp === null || rateBp <= 0) return null;
  if (draft.kind === "commission") {
    return { kind: draft.kind, rateBp, amountPiastres: 0 };
  }
  const amountPiastres = parseEgp(draft.amount);
  if (amountPiastres === null || amountPiastres <= 0) return null;
  return { kind: draft.kind, rateBp, amountPiastres };
}
