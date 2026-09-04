import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import { Money } from "../components/Money";
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
} from "../lib/payHistory";
import type {
  Arrangement,
  Kind,
  MonthRow,
  PayHistory,
} from "../lib/payHistory";
import "./Payroll.css";
import "./Compensation.css";

const KIND_LABEL: Record<Kind, string> = {
  commission: "Commission only",
  fixed_plus_commission: "Salary + commission",
  base_guarantee: "Guaranteed minimum",
};

const KIND_NOTE: Record<Kind, string> = {
  commission: "Paid a percentage of what her code sold. Nothing else.",
  fixed_plus_commission:
    "Both. The salary is paid on top of the commission, never instead of it.",
  base_guarantee:
    "Whichever is larger — her commission, or the floor — and only in a month where she met her targets.",
};

/** The short word used on a strip tile, where "+ commission" will not fit. */
const KIND_SHORT: Record<Kind, string> = {
  commission: "Commission",
  fixed_plus_commission: "Salary +",
  base_guarantee: "Guaranteed",
};

/** Which money field each arrangement carries, and what to call it. */
const AMOUNT_LABEL: Partial<Record<Kind, string>> = {
  fixed_plus_commission: "Monthly salary",
  base_guarantee: "Guaranteed minimum",
};

const KINDS = Object.keys(KIND_LABEL) as Kind[];

/**
 * Setting up what a model is paid on, for every month she has sold in.
 *
 * ADR 0036 and task #17. **This replaced a form that could record one
 * arrangement from one month**, which was the whole of what the platform could
 * express and nothing like what actually happened: a model can have been on
 * commission in January, on a salary from April, and on a guaranteed minimum
 * from June, and every one of those months has to be calculable or her
 * dashboard shows a hole where her year should be.
 *
 * The old form could technically write that history — three saves, each
 * naming a start and an end month by hand, each refused if the months
 * overlapped by one. The strip is the same information asked for in the shape
 * the answer already has.
 *
 * ## What it will not let somebody do
 *
 * **Arrange a month she did not sell in.** Those are hatched. Offering them
 * invites a year of arrangements for months that never existed.
 *
 * **Touch an approved month.** §11.1: changing what it was calculated from
 * after the money moved would leave the frozen snapshot disagreeing with the
 * data it came from. The server refuses it; this marks it before it is
 * clicked, which is the difference between a rule and a surprise.
 *
 * **Assert a target for a month that can still be paid.** The met/missed
 * toggle appears only on a guaranteed minimum *before go-live*, where the
 * outcome is the whole of what the old dashboard kept. Later months record
 * what was produced, on the Targets screen, and are counted rather than
 * asserted.
 *
 * ## Consecutive identical months collapse
 *
 * Because that is what gets written: `set_terms` records a run, not a month.
 * Showing nine rows for one decision would misrepresent the record somebody is
 * about to agree to.
 */
export function Compensation() {
  const { id = "" } = useParams();
  const navigate = useNavigate();

  const [data, setData] = useState<PayHistory | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  const [who, setWho] = useState<"new" | "old" | null>(null);
  const [same, setSame] = useState<"yes" | "no" | null>(null);
  const [set, setSet] = useState<Record<string, Arrangement>>({});
  const [sel, setSel] = useState<string[]>([]);
  const [anchor, setAnchor] = useState<string | null>(null);
  const [draft, setDraft] = useState<Draft | null>(null);

  useEffect(() => {
    api
      .get<PayHistory>(`/api/affiliates/${id}/pay-history`)
      .then((body) => {
        setData(body);
        setSet(fromServer(body));
        // **A model who already has a history opens straight on the strip.**
        //
        // The fork asks a question her record has already answered, and
        // making somebody answer it again before they can correct one month
        // is the difference between a screen you edit and a wizard you
        // endure.
        if (body.periods.length > 0) {
          setWho("old");
          setSame("no");
        }
      })
      .catch((caught) => setError(caught.message));
  }, [id]);

  /** The months she may be arranged in: from her first sale to this month. */
  const arrangeable = useMemo(
    () =>
      (data?.months ?? []).filter(
        (row) => data?.joined_month !== null && row.month >= (data?.joined_month ?? ""),
      ),
    [data],
  );

  const open = arrangeable.filter((row) => !row.approved);
  const missing = open.filter((row) => !set[row.month]);
  // Two collapses of the same months, and they are not the same list. `rows`
  // splits June-met from July-missed because a single row could not say which
  // month was paid the floor; `periods` does not, because the arrangement is
  // identical and the outcome lives on the target. Only `periods` is written,
  // and only `periods` is counted in the save note.
  const rows = useMemo(() => runs(arrangeable, set), [arrangeable, set]);
  const periods = useMemo(
    () => periodsToWrite(arrangeable, set),
    [arrangeable, set],
  );

  function choose(month: string, withShift: boolean) {
    const row = arrangeable.find((candidate) => candidate.month === month);
    if (!row || row.approved) return;

    let next: string[];
    if (withShift && anchor !== null) {
      const [first, last] = [anchor, month].sort();
      next = open
        .filter((candidate) => candidate.month >= first && candidate.month <= last)
        .map((candidate) => candidate.month);
    } else if (sel.length === 1 && sel[0] === month) {
      setSel([]);
      setAnchor(null);
      setDraft(null);
      return;
    } else {
      next = [month];
      setAnchor(month);
    }

    setSel(next);
    // Opening on what the first selected month already says means correcting
    // one month is a change to one field, not a re-entry of the arrangement.
    setDraft(draftFor(next, set));
  }

  function apply() {
    if (!draft) return;
    const parsed = readDraft(draft);
    if (parsed === null) return;

    setSet((was) => {
      const next = { ...was };
      for (const month of sel) {
        const row = arrangeable.find((candidate) => candidate.month === month);
        next[month] = {
          ...parsed,
          met:
            parsed.kind === "base_guarantee" && row?.settled_outside
              ? draft.met[month] ?? null
              : null,
        };
      }
      return next;
    });
    setSel([]);
    setAnchor(null);
    setDraft(null);
  }

  function clearRun(from: string, to: string) {
    setSet((was) => {
      const next = { ...was };
      for (const row of arrangeable) {
        if (row.month >= from && row.month <= to && !row.approved) {
          delete next[row.month];
        }
      }
      return next;
    });
  }

  async function save() {
    if (!data) return;
    setSaving(true);
    setError(null);
    try {
      await api.put(`/api/affiliates/${id}/pay-history`, {
        periods: periods.map((run) => ({
          start_month: run.from,
          // The last run reaches this month and is left open: "from here on,
          // until further notice", which is what an arrangement still in
          // force means. Closing it at this month would silently end her pay
          // at the end of it.
          end_month: run.to === data.working_month ? null : run.to,
          compensation_type: run.kind,
          commission_rate_bp: run.rateBp,
          fixed_amount_piastres:
            run.kind === "fixed_plus_commission" ? run.amountPiastres : null,
          base_amount_piastres:
            run.kind === "base_guarantee" ? run.amountPiastres : null,
        })),
        outcomes: outcomesFrom(arrangeable, set),
      });
      navigate(`/affiliates/${id}`);
    } catch (caught) {
      setError((caught as Error).message);
      setSaving(false);
    }
  }

  if (error && data === null) {
    return (
      <p className="notice notice--refused" role="alert">
        {error}
      </p>
    );
  }
  if (data === null) return <p className="empty">Loading…</p>;

  const neverSold = data.joined_month === null;

  return (
    // The arrangement tints are defined on this wrapper, not on `:root`. They
    // are the one place this codebase spends colour on something other than
    // money state (ADR 0027), and scoping them here is what keeps that bend
    // confined to the screen that argued for it.
    <div className="comp">
      {/*
       * Above the heading, not inside `page__title` — which is a flex row, so
       * a crumb placed in it sits *beside* the h1 on the same baseline and
       * reads as part of the title. Caught by looking at the screen.
       */}
      <p className="crumb">
        <Link to="/affiliates">Affiliates</Link> ·{" "}
        <Link to={`/affiliates/${id}`}>{data.name}</Link>
      </p>
      <div className="page__head">
        <div className="page__title">
          <h1>Set up {data.name}’s pay</h1>
        </div>
      </div>

      <p className="comp__lede">
        What she is paid on, and from when. A model who was with HBA before the
        platform needs every month she sold in to have an arrangement, or those
        months cannot be calculated.
      </p>

      {error && (
        <p className="notice notice--refused" role="alert">
          {error}
        </p>
      )}

      {/*
       * Skipped for a model with no sales at all. There is nothing to fork
       * about — she has no history to backfill, and asking would be asking
       * about months that do not exist.
       */}
      {who === null && !neverSold && (
        <section className="panel comp__card">
          <h2 className="comp__cardtitle">
            Is she new, or was she with HBA already?
          </h2>
          <div className="fork">
            <button type="button" onClick={() => setWho("new")}>
              <b>New model</b>
              <span>Starts now. One arrangement, from this month onwards.</span>
            </button>
            <button type="button" onClick={() => setWho("old")}>
              <b>Already with HBA</b>
              <span>
                Has sales before the platform. Every one of those months needs an
                arrangement.
              </span>
            </button>
          </div>
        </section>
      )}

      {(who === "new" || neverSold) && (
        <NewModel
          working={data.working_month}
          saving={saving}
          onSave={async (arrangement) => {
            setSaving(true);
            setError(null);
            try {
              await api.put(`/api/affiliates/${id}/pay-history`, {
                periods: [
                  {
                    start_month: data.working_month,
                    end_month: null,
                    compensation_type: arrangement.kind,
                    commission_rate_bp: arrangement.rateBp,
                    fixed_amount_piastres:
                      arrangement.kind === "fixed_plus_commission"
                        ? arrangement.amountPiastres
                        : null,
                    base_amount_piastres:
                      arrangement.kind === "base_guarantee"
                        ? arrangement.amountPiastres
                        : null,
                  },
                ],
                outcomes: {},
              });
              navigate(`/affiliates/${id}`);
            } catch (caught) {
              setError((caught as Error).message);
              setSaving(false);
            }
          }}
        />
      )}

      {who === "old" && same === null && (
        <section className="panel comp__card">
          <h2 className="comp__cardtitle">Was it the same the whole time?</h2>
          <div className="fork">
            <button
              type="button"
              onClick={() => {
                setSame("yes");
                // "Same throughout" is one arrangement over every month she
                // has. Making somebody select them by hand would be asking
                // for work the answer already contains.
                setSel(open.map((row) => row.month));
                setDraft(blankDraft());
              }}
            >
              <b>The same throughout</b>
              <span>
                One arrangement covers every month from when she started until
                now.
              </span>
            </button>
            <button type="button" onClick={() => setSame("no")}>
              <b>It changed</b>
              <span>
                Her salary, her guarantee, or the way she was paid was not the
                same all year.
              </span>
            </button>
          </div>
        </section>
      )}

      {who === "old" && same !== null && (
        <>
          <section className="panel comp__card">
            <div className="striphead">
              <h2 className="comp__cardtitle">Her months</h2>
              <p className="hint">
                {same === "yes"
                  ? "Every month is selected. Set the arrangement once and it applies to all of them."
                  : "Click a month. Shift-click another to take everything between them."}
              </p>
            </div>

            <div className="strip">
              {data.months.map((row) => (
                <MonthTile
                  key={row.month}
                  row={row}
                  before={
                    data.joined_month === null || row.month < data.joined_month
                  }
                  arrangement={set[row.month]}
                  selected={sel.includes(row.month)}
                  onChoose={(withShift) => choose(row.month, withShift)}
                />
              ))}
            </div>

            <div className="legend">
              <span>
                <i className="legend--commission" />
                Commission only
              </span>
              <span>
                <i className="legend--salary" />
                Salary + commission
              </span>
              <span>
                <i className="legend--guarantee" />
                Guaranteed minimum
              </span>
              <span className="legend__quiet">
                Hatched months are before she joined, or already approved
              </span>
            </div>

            {draft && sel.length > 0 && (
              <Panel
                draft={draft}
                months={sel}
                rows={arrangeable}
                onChange={setDraft}
                onApply={apply}
                onCancel={() => {
                  setSel([]);
                  setAnchor(null);
                  setDraft(null);
                }}
              />
            )}
          </section>

          <section className="panel comp__card">
            <h2 className="comp__cardtitle">What will be recorded</h2>
            {rows.length === 0 ? (
              <p className="empty">Nothing set yet.</p>
            ) : (
              <div className="comp__scroll">
                <table className="table">
                  <thead>
                    <tr>
                      <th>Months</th>
                      <th>Arrangement</th>
                      <th>Rate</th>
                      <th>Amount</th>
                      <th>Targets</th>
                      <th />
                    </tr>
                  </thead>
                  <tbody>
                    {rows.map((run) => (
                      <tr key={run.from}>
                        <td className="code">
                          {shortMonth(run.from)}
                          {run.from === run.to ? "" : ` – ${shortMonth(run.to)}`}
                        </td>
                        <td>
                          <span className={`pill pill--${run.kind}`}>
                            {KIND_LABEL[run.kind]}
                          </span>
                        </td>
                        <td className="code">{run.rateBp / 100}%</td>
                        <td className="code">
                          {run.kind === "commission" ? (
                            "—"
                          ) : (
                            <Money piastres={run.amountPiastres} />
                          )}
                        </td>
                        <td>
                          {run.met === null
                            ? "—"
                            : run.met
                              ? "met"
                              : "missed"}
                        </td>
                        <td>
                          <button
                            type="button"
                            className="comp__clear"
                            onClick={() => clearRun(run.from, run.to)}
                          >
                            Clear
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>

          <div className="comp__save">
            <p className={missing.length === 0 ? "comp__ready" : undefined}>
              {missing.length === 0
                ? `Every month from ${formatMonth(open[0]?.month ?? data.working_month)} is covered. ${periods.length} arrangement${periods.length === 1 ? "" : "s"} will be recorded.`
                : `${missing.length} month${missing.length === 1 ? "" : "s"} still without an arrangement: ${missing.map((row) => shortMonth(row.month)).join(", ")}. A month with no arrangement cannot be calculated.`}
            </p>
            <button
              type="button"
              className="button button--primary"
              disabled={missing.length > 0 || saving}
              onClick={save}
            >
              {saving ? "Saving…" : "Save her pay history"}
            </button>
          </div>
        </>
      )}
    </div>
  );
}

/* ── the strip ─────────────────────────────────────────────────────────────── */

function MonthTile({
  row,
  before,
  arrangement,
  selected,
  onChoose,
}: {
  row: MonthRow;
  before: boolean;
  arrangement: Arrangement | undefined;
  selected: boolean;
  onChoose: (withShift: boolean) => void;
}) {
  const locked = before || row.approved;
  return (
    <button
      type="button"
      className="mo"
      data-set={locked ? "off" : (arrangement?.kind ?? "none")}
      aria-pressed={selected}
      disabled={locked}
      title={
        before
          ? "Before she sold anything"
          : row.approved
            ? `${formatMonth(row.month)} is approved. Reopen it before changing what it was calculated from.`
            : formatMonth(row.month)
      }
      onClick={(event) => onChoose(event.shiftKey)}
    >
      <span className="mo__name">{shortMonth(row.month)}</span>
      <span className="mo__what">
        {before ? "—" : row.approved ? "approved" : arrangement ? KIND_SHORT[arrangement.kind] : "not set"}
      </span>
      {/*
       * Formatted, not plain. `egpPlain` is for filling an input, where a
       * currency mark and thousands separators would have to be stripped
       * again; on a tile "5000.00" beside a percentage is a figure whose
       * unit somebody has to guess.
       */}
      <span className="mo__amt">
        {arrangement && arrangement.kind !== "commission" && !locked
          ? formatEgp(arrangement.amountPiastres)
          : ""}
      </span>
      {arrangement?.met !== null && arrangement?.met !== undefined && (
        <span className={`mo__met mo__met--${arrangement.met ? "yes" : "no"}`}>
          {arrangement.met ? "target met" : "target missed"}
        </span>
      )}
    </button>
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

function Panel({
  draft,
  months,
  rows,
  onChange,
  onApply,
  onCancel,
}: {
  draft: Draft;
  months: string[];
  rows: MonthRow[];
  onChange: (draft: Draft) => void;
  onApply: () => void;
  onCancel: () => void;
}) {
  const ordered = [...months].sort();
  const label =
    ordered.length === 1
      ? formatMonth(ordered[0])
      : `${formatMonth(ordered[0])} – ${formatMonth(ordered[ordered.length - 1])} · ${ordered.length} months`;

  const amountLabel = AMOUNT_LABEL[draft.kind];
  // Only where the old dashboard is the only record. A guaranteed minimum in a
  // month the platform pays for records what was produced, on the Targets
  // screen, and is counted rather than asserted (ADR 0036).
  const outcomeMonths =
    draft.kind === "base_guarantee"
      ? ordered.filter(
          (month) => rows.find((row) => row.month === month)?.settled_outside,
        )
      : [];
  const laterGuaranteeMonths =
    draft.kind === "base_guarantee"
      ? ordered.filter(
          (month) => !rows.find((row) => row.month === month)?.settled_outside,
        )
      : [];

  const ready = readDraft(draft) !== null;

  return (
    <div className="cpanel">
      <h3>{label}</h3>
      <p className="cpanel__for">{KIND_NOTE[draft.kind]}</p>

      <div className="kinds">
        {KINDS.map((kind) => (
          <button
            key={kind}
            type="button"
            aria-pressed={draft.kind === kind}
            onClick={() =>
              onChange({
                ...draft,
                kind,
                met: kind === "base_guarantee" ? draft.met : {},
              })
            }
          >
            {KIND_LABEL[kind]}
          </button>
        ))}
      </div>

      <div className="fields">
        <label className="field">
          Commission rate
          <div className="comp__suffixed">
            <input
              className="input"
              inputMode="decimal"
              value={draft.rate}
              aria-label="Commission rate, percent"
              onChange={(event) =>
                onChange({ ...draft, rate: event.target.value })
              }
            />
            <span className="comp__suffix">%</span>
          </div>
        </label>
        {amountLabel && (
          <label className="field">
            {amountLabel}
            <input
              className="input"
              inputMode="decimal"
              value={draft.amount}
              placeholder="0.00"
              onChange={(event) =>
                onChange({ ...draft, amount: event.target.value })
              }
            />
          </label>
        )}
      </div>

      {outcomeMonths.length > 0 && (
        <div className="targets">
          <p>
            <b>Did she meet her targets?</b> The guarantee only applies in a
            month where she did — so this decides, month by month, whether she
            was paid the floor or her commission. The video and story counts
            were not kept on the old dashboard, so the outcome is the whole
            record.
          </p>
          {outcomeMonths.map((month) => (
            <div key={month} className="trow">
              <span className="code">{formatMonth(month)}</span>
              <span className="seg">
                <button
                  type="button"
                  aria-pressed={draft.met[month] === true}
                  data-value="met"
                  onClick={() =>
                    onChange({ ...draft, met: { ...draft.met, [month]: true } })
                  }
                >
                  Met
                </button>
                <button
                  type="button"
                  aria-pressed={draft.met[month] === false}
                  onClick={() =>
                    onChange({ ...draft, met: { ...draft.met, [month]: false } })
                  }
                >
                  Missed
                </button>
              </span>
            </div>
          ))}
        </div>
      )}

      {laterGuaranteeMonths.length > 0 && (
        <p className="cpanel__elsewhere">
          {laterGuaranteeMonths.map(formatMonth).join(", ")}{" "}
          {laterGuaranteeMonths.length === 1 ? "is" : "are"} paid through this
          platform, so {laterGuaranteeMonths.length === 1 ? "its" : "their"}{" "}
          targets are recorded and confirmed on the{" "}
          <Link to="/targets">Targets screen</Link> rather than set here.
        </p>
      )}

      <div className="acts">
        <button
          type="button"
          className="button button--primary"
          disabled={!ready}
          onClick={onApply}
        >
          Apply to{" "}
          {ordered.length === 1 ? "this month" : `these ${ordered.length} months`}
        </button>
        <button type="button" className="button" onClick={onCancel}>
          Cancel
        </button>
      </div>
    </div>
  );
}

/* ── the new-model form ────────────────────────────────────────────────────── */

function NewModel({
  working,
  saving,
  onSave,
}: {
  working: string;
  saving: boolean;
  onSave: (arrangement: Omit<Arrangement, "met">) => void;
}) {
  const [draft, setDraft] = useState<Draft>(blankDraft);
  const parsed = readDraft(draft);
  const amountLabel = AMOUNT_LABEL[draft.kind];

  return (
    <section className="panel comp__card">
      <h2 className="comp__cardtitle">Her arrangement</h2>
      <p className="hint">
        One arrangement, starting {formatMonth(working)}. Nothing before it
        exists for her, so there is nothing to backfill.
      </p>

      <div className="kinds">
        {KINDS.map((kind) => (
          <button
            key={kind}
            type="button"
            aria-pressed={draft.kind === kind}
            onClick={() => setDraft({ ...draft, kind })}
          >
            {KIND_LABEL[kind]}
          </button>
        ))}
      </div>
      <p className="cpanel__for">{KIND_NOTE[draft.kind]}</p>

      <div className="fields">
        <label className="field">
          Commission rate
          <div className="comp__suffixed">
            <input
              className="input"
              inputMode="decimal"
              value={draft.rate}
              aria-label="Commission rate, percent"
              onChange={(event) => setDraft({ ...draft, rate: event.target.value })}
            />
            <span className="comp__suffix">%</span>
          </div>
        </label>
        {amountLabel && (
          <label className="field">
            {amountLabel}
            <input
              className="input"
              inputMode="decimal"
              value={draft.amount}
              placeholder="0.00"
              onChange={(event) => setDraft({ ...draft, amount: event.target.value })}
            />
          </label>
        )}
      </div>

      <div className="acts">
        <button
          type="button"
          className="button button--primary"
          disabled={parsed === null || saving}
          onClick={() => parsed && onSave(parsed)}
        >
          {saving ? "Saving…" : "Save her arrangement"}
        </button>
      </div>
    </section>
  );
}
