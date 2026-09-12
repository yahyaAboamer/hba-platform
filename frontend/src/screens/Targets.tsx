import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";

import { MonthPicker } from "../components/MonthPicker";
import type { MonthLock } from "../components/MonthPicker";
import { api, can } from "../lib/api";
import type { Session } from "../lib/api";
import { currentMonth, formatMonth } from "../lib/money";
import "./Targets.css";

type Row = {
  affiliate_id: number;
  name: string;
  account_kind: "model" | "house";
  determines_pay: boolean;
  required_videos: number | null;
  required_stories: number | null;
  actual_videos: number | null;
  actual_stories: number | null;
  /** `null` means nobody has recorded what they did — which is not a miss. */
  achieved: boolean | null;
  verified: boolean;
  verified_at: string | null;
  recorded_at: string | null;
  /** D08. HBA only — nothing about pace reaches a model's own screens. */
  pace: {
    state: string;
    week: number;
    required: number;
    expected_by_now: number;
    done: number;
    week_started: string;
  };
};

type Grid = {
  month: string;
  /**
   * What the month looked like when it was handed out.
   *
   * Sent back on save so the server can refuse a save built on figures
   * somebody else has already changed. Two people run payroll and both open
   * this screen at month end.
   */
  revision: string;
  rows: Row[];
};

/** What is in each of the four boxes, as text, so a half-typed cell survives. */
type Draft = Record<number, {
  required_videos: string;
  required_stories: string;
  actual_videos: string;
  actual_stories: string;
}>;

function draftFrom(rows: Row[]): Draft {
  const draft: Draft = {};
  for (const row of rows) {
    draft[row.affiliate_id] = {
      required_videos: row.required_videos?.toString() ?? "",
      required_stories: row.required_stories?.toString() ?? "",
      actual_videos: row.actual_videos?.toString() ?? "",
      actual_stories: row.actual_stories?.toString() ?? "",
    };
  }
  return draft;
}

/** A whole number, or null for an empty box. `undefined` means "not a number". */
function count(text: string): number | null | undefined {
  const trimmed = text.trim();
  if (trimmed === "") return null;
  if (!/^\d+$/.test(trimmed)) return undefined;
  return Number(trimmed);
}

/**
 * What each row is waiting for, in the words §11.3 uses.
 *
 * Three answers, not two. Nothing recorded **blocks** their month; a recorded
 * miss does not — the block is on missing information, never on a quiet month.
 */
/**
 * Targets. §15, and the one screen §12.2 asks to be built as a grid rather
 * than a form: every model down the side, one month across, tab straight
 * through, single save.
 *
 * Sara records these from their own tracking; the platform collects no evidence.
 * What it does is make the consequence visible — for a model on a guaranteed
 * minimum these numbers decide what they are paid, and for everybody else they
 * are worth knowing and decide nothing.
 */
export function Targets({ session, affiliateId, initialMonth, embedded = false }: { session: Session; affiliateId?: number; initialMonth?: string; embedded?: boolean }) {
  const [query] = useSearchParams();
  const [month, setMonth] = useState(initialMonth ?? (query.get("month")?.match(/^\d{4}-(0[1-9]|1[0-2])$/) ? query.get("month")! : session.platform.working_month));
  const [grid, setGrid] = useState<Grid | null>(null);
  const [draft, setDraft] = useState<Draft>({});
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState<string | null>(null);
  const [working, setWorking] = useState(false);
  const [chosen, setChosen] = useState<Set<number>>(new Set());
  /**
   * Write these requirements to every month of the year (owner, 11 September
   * 2026): a model's targets are fixed across a year, and varying one month is
   * the exception.
   *
   * **Off by default and reset after every save.** It rewrites twelve months
   * at once, including ones already gone, so it is a deliberate act each time
   * rather than a setting that stays on.
   */
  const [wholeYear, setWholeYear] = useState(false);
  /**
   * **One set of numbers at a time**, the way the approved screen works.
   *
   * Ours showed *asked for* and *produced* side by side — four inputs a row,
   * twenty rows, eighty boxes on screen, and no way to tell at a glance which
   * half you were editing. The export switches: you are either recording what
   * happened or setting what is being asked for, and the column headings say
   * which.
   */
  const [mode, setMode] = useState<"achieved" | "required">("achieved");
  const [search, setSearch] = useState("");
  //: Undoing is its own selection and its own reason. Sharing `chosen`
  //: with confirming would let one button act on rows picked for the
  //: other, which on a screen that releases guarantees is not a mistake
  //: worth risking to save a state variable.
  const [undoing, setUndoing] = useState(false);
  const [takingBack, setTakingBack] = useState<Set<number>>(new Set());
  const [why, setWhy] = useState("");

  /**
   * Load the month, and **ignore an answer that is no longer the question.**
   *
   * Two requests in flight for two months can return in either order, and the
   * slower one arriving second would paint August's numbers under a September
   * heading. The month is captured when the request goes out and checked when
   * it comes back.
   */
  function load() {
    setError(null);
    const asked = month;
    api
      .get<Grid>(`/api/targets/${asked}`)
      .then((body) => {
        if (body.month !== asked) return;
        setGrid(body);
        setDraft(draftFrom(body.rows));
        setChosen(new Set());
      })
      .catch((caught) => {
        if (asked === month) setError(caught.message);
      });
  }

  useEffect(load, [month]);

  function edit(id: number, field: keyof Draft[number], value: string) {
    setSaved(null);
    setDraft((was) => ({ ...was, [id]: { ...was[id], [field]: value } }));
  }

  async function save() {
    if (grid === null) return;

    /*
     * **The numbers on screen belong to the month that loaded them.**
     *
     * `month` and `grid` are two pieces of state that change at different
     * times: the picker moves first, the rows arrive later. Between those two
     * moments the screen shows one month's figures under another month's
     * heading, and a save there would write August's requirements into
     * September - silently, into the data that decides whether a guaranteed
     * minimum applies.
     *
     * Refused rather than reconciled. There is no correct guess about which
     * month somebody meant.
     */
    if (grid.month !== month) {
      setError("That month is still loading. Nothing was saved — try again.");
      return;
    }

    setWorking(true);
    setError(null);
    setSaved(null);
    try {
      const rows = [];
      for (const row of grid.rows.filter((r) => r.account_kind !== "house" && (!affiliateId || r.affiliate_id === affiliateId))) {
        const cells = draft[row.affiliate_id];
        const required_videos = count(cells.required_videos);
        const required_stories = count(cells.required_stories);
        const actual_videos = count(cells.actual_videos);
        const actual_stories = count(cells.actual_stories);

        if (
          [required_videos, required_stories, actual_videos, actual_stories].includes(
            undefined,
          )
        ) {
          throw new Error(
            `${row.name}: those need to be whole numbers. Nothing saved.`,
          );
        }

        // A row nobody has touched is left alone. Sending zeros for it would
        // set a requirement of nothing for every model on the programme.
        if (required_videos === null && required_stories === null) continue;

        // **Emptying both count boxes means "take them off"**, not "leave
        // them", and only where something was actually recorded before.
        // A06: unrecorded and zero are different facts, and until this the
        // only way to undo a mistyped count was to set it to zero - which
        // claims she produced nothing.
        const wasRecorded = row.actual_videos !== null;
        const clearing =
          wasRecorded && actual_videos === null && actual_stories === null;

        rows.push({
          affiliate_id: row.affiliate_id,
          required_videos: required_videos ?? 0,
          required_stories: required_stories ?? 0,
          actual_videos: clearing ? null : actual_videos,
          actual_stories: clearing ? null : actual_stories,
          clear_actuals: clearing,
        });
      }

      const result = await api.put<{
        saved: number;
        revision: string;
        applied_to_year: {
          name: string;
          applied: string[];
          skipped: { month: string; why: string }[];
        }[];
      }>(`/api/targets/${month}`, {
        rows,
        revision: grid.revision,
        apply_to_year: wholeYear,
      });
      // Carried forward, so saving twice in a row does not need a reload
      // between them.
      setGrid({ ...grid, revision: result.revision });
      setSaved(describeSave(result.saved, result.applied_to_year));
      // Off again after every save. It rewrites twelve months, so leaving it
      // armed for the next save is how somebody changes a year by accident.
      setWholeYear(false);
      load();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Nothing saved.");
    } finally {
      setWorking(false);
    }
  }

  async function confirm() {
    setWorking(true);
    setError(null);
    try {
      await api.post(`/api/targets/${month}/verify`, {
        affiliate_ids: [...chosen],
      });
      load();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Nothing verified.");
    } finally {
      setWorking(false);
    }
  }

  async function takeBack() {
    setWorking(true);
    setError(null);
    try {
      await api.post(`/api/targets/${month}/unverify`, {
        affiliate_ids: [...takingBack],
        reason: why.trim(),
      });
      setTakingBack(new Set());
      setWhy("");
      setUndoing(false);
      load();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Nothing changed.");
    } finally {
      setWorking(false);
    }
  }

  /**
   * How many boxes differ from what is stored — the export's *N unsaved
   * changes*, with a Discard beside it.
   *
   * Counted against the loaded grid rather than tracked as a flag, so typing
   * a value and typing it back reports nothing to save, which is the truth.
   */
  const dirtyCount = grid
    ? grid.rows.reduce((total, row) => {
        const cells = draft[row.affiliate_id];
        if (!cells) return total;
        const stored = draftFrom([row])[row.affiliate_id];
        return total + (Object.keys(cells) as (keyof typeof cells)[])
          .filter((field) => cells[field] !== stored[field]).length;
      }, 0)
    : 0;

  function discard() {
    if (grid) setDraft(draftFrom(grid.rows));
    setSaved(null);
  }

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

  // A house code publishes nothing, so a row of empty boxes beside it is
  // four things nobody will ever type into.
  const needle = search.trim().toLowerCase();
  const rows = (grid?.rows ?? []).filter(row =>
    row.account_kind !== "house"
    && (!affiliateId || row.affiliate_id === affiliateId)
    && (!query.get("pace") || row.pace?.state === query.get("pace"))
    && (!needle || row.name.toLowerCase().includes(needle)));
  const confirmable = rows.filter(
    (row) => row.achieved !== null && !row.verified,
  );
  const confirmed = rows.filter((row) => row.verified);

  return (
    <>
      {!embedded && <div className="page__head">
        <div className="page__title">
          <h1>Targets</h1>
          <span className="page__subtitle">{formatMonth(month)} · recorded weekly</span>
        </div>
        <MonthPicker value={month} onChange={setMonth} lockFor={lockFor} />
      </div>}

      {error && (
        <p className="notice notice--refused" role="alert">
          {error}
        </p>
      )}

      {saved && <p className="notice notice--settled targets__note">{saved}</p>}

      {grid === null && !error && <p className="empty">Loading…</p>}

      {grid && !embedded && (
        <div className="targets__bar">
          <div className="targets__bar-left">
            <input
              type="search"
              className="input input--search"
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              placeholder="Search model names"
              aria-label="Search model names"
            />
            {/*
             * Which set of numbers this screen is editing. The export switches
             * between them rather than showing both, and the column headings
             * follow the switch — so there is never a question about which of
             * four boxes in a row you are typing into.
             *
             * Two radios rather than two buttons: they are one choice, and a
             * radio group is what says so to somebody arriving by keyboard.
             */}
            <div className="seg">
              <label className="seg-opt">
                <input type="radio" name="targets-mode" checked={mode === "achieved"}
                  onChange={() => setMode("achieved")} />
                <span>Record achieved</span>
              </label>
              <label className="seg-opt">
                <input type="radio" name="targets-mode" checked={mode === "required"}
                  onChange={() => setMode("required")} />
                <span>Set requirements</span>
              </label>
            </div>
          </div>

          {/*
           * The export's right-hand group: what is unsaved, the way back from
           * it, and the save. Everything that acts on the whole grid lives
           * here, which is why nothing sits under the table any more.
           */}
          <div className="targets__bar-right">
            {dirtyCount > 0 && (
              <>
                <span className="targets__dirty">
                  {dirtyCount} unsaved {dirtyCount === 1 ? "change" : "changes"}
                </span>
                <button type="button" className="button" onClick={discard}>Discard</button>
              </>
            )}
            {saved && dirtyCount === 0 && (
              <span className="targets__saved">{saved}</span>
            )}
            {/*
             * A model's targets are fixed across a year (owner, 11 September
             * 2026), so this is the ordinary way to set them and a
             * single-month edit is the exception you opt out into. It changes
             * what the save does, so it stands next to it — the export has no
             * equivalent control, and this is the nearest place that does not
             * invent a second row of furniture for it.
             */}
            {can(session, "targets.record") && mode === "required" && (
              <label className="targets__year">
                <input
                  type="checkbox"
                  checked={wholeYear}
                  onChange={(event) => setWholeYear(event.target.checked)}
                />
                Whole year
              </label>
            )}
            {can(session, "targets.verify") && confirmable.length > 0 && (
              <button
                type="button"
                className="button"
                onClick={confirm}
                disabled={working || chosen.size === 0}
              >
                {chosen.size === 0
                  ? "Confirm"
                  : `Confirm ${chosen.size} ${chosen.size === 1 ? "model" : "models"}`}
              </button>
            )}
            {can(session, "targets.record") && (
              <button
                type="button"
                className="button button--primary"
                onClick={save}
                disabled={working || dirtyCount === 0}
              >
                {working ? "Saving…" : wholeYear ? "Save the year" : "Save changes"}
              </button>
            )}
          </div>
        </div>
      )}

      {grid && rows.length > 0 && (
        <>
          <div className="surface">
          <table className="table targets__grid">
            <thead>
              <tr>
                <th className="targets__model">Model</th>
                <th className="targets__number">
                  {mode === "achieved" ? "Videos achieved" : "Videos required"}
                </th>
                <th className="targets__number">
                  {mode === "achieved" ? "Stories achieved" : "Stories required"}
                </th>
                <th className="targets__outcome">Recorded</th>
                <th className="targets__updated">Last updated</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => {
                const cells = draft[row.affiliate_id];
                if (!cells) return null;
                return (
                  <tr key={row.affiliate_id}>
                    {/*
                     * Name, and beside it what the record decides - the export
                     * lays the Model column out as one flex line with a 10px
                     * gap, so the confirmation tick joins that line rather
                     * than claiming a column of its own. A sixth column that
                     * is empty in most rows is a column of white space.
                     */}
                    <td className="targets__model">
                      {can(session, "targets.verify") &&
                        row.achieved !== null &&
                        !row.verified && (
                          <input
                            type="checkbox"
                            aria-label={`Confirm ${row.name}'s numbers`}
                            checked={chosen.has(row.affiliate_id)}
                            onChange={() =>
                              setChosen((was) => {
                                const next = new Set(was);
                                if (next.has(row.affiliate_id)) {
                                  next.delete(row.affiliate_id);
                                } else {
                                  next.add(row.affiliate_id);
                                }
                                return next;
                              })
                            }
                          />
                        )}
                      <Link
                        className="targets__name"
                        to={`/affiliates/${row.affiliate_id}`}
                      >
                        {row.name}
                      </Link>
                      {row.determines_pay && (
                        <span className="targets__arrangement">
                          Guarantee needs this record
                        </span>
                      )}
                    </td>
                    <Cell
                      value={mode === "achieved" ? cells.actual_videos : cells.required_videos}
                      label={`${row.name} videos ${mode === "achieved" ? "achieved" : "required"}`}
                      suffix={mode === "achieved"
                        ? `of ${row.required_videos ?? 0}`
                        : "required"}
                      onChange={(v) => edit(row.affiliate_id,
                        mode === "achieved" ? "actual_videos" : "required_videos", v)}
                    />
                    <Cell
                      value={mode === "achieved" ? cells.actual_stories : cells.required_stories}
                      label={`${row.name} stories ${mode === "achieved" ? "achieved" : "required"}`}
                      suffix={mode === "achieved"
                        ? `of ${row.required_stories ?? 0}`
                        : "required"}
                      onChange={(v) => edit(row.affiliate_id,
                        mode === "achieved" ? "actual_stories" : "required_stories", v)}
                    />
                    {/*
                     * The export draws one line here, toned by what it says.
                     * D08's weekly pace was asked for after the export was
                     * drawn and answers the same question a week at a time, so
                     * it follows as a second, quieter line.
                     */}
                    <td className="targets__outcome">
                      <Outcome row={row} />
                      <PaceCell row={row} />
                    </td>
                    <td className="targets__updated">
                      {row.recorded_at
                        ? new Date(row.recorded_at).toLocaleDateString("en-GB",
                            { day: "numeric", month: "long", year: "numeric" })
                        : <span className="targets__never">—</span>}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          </div>

          {/*
           * **The way back, and it looks like one.**
           *
           * A confirmation released a guaranteed minimum. Taking it back is
           * rare, deliberate, and worth a written reason — so it is folded
           * away rather than sitting beside *Confirm* as though the two were
           * a pair. Somebody reaching for it has decided to.
           *
           * The reason is not paperwork. A verification undone leaves no other
           * trace anybody would ever meet: the row simply reads unconfirmed
           * again, exactly as though nobody had looked yet.
           */}
          {can(session, "targets.verify") && confirmed.length > 0 && (
            <section className="panel targets__undo">
              {!undoing ? (
                <button
                  type="button"
                  className="button"
                  onClick={() => setUndoing(true)}
                >
                  Take a confirmation back
                </button>
              ) : (
                <>
                  <div className="panel__head">
                    <h2 className="panel__title">Take a confirmation back</h2>
                  </div>
                  <p className="targets__lead">
                    The month reads as unconfirmed again, and a guaranteed
                    minimum it had released stops applying until somebody
                    confirms it once more.
                  </p>

                  <ul className="targets__undo-list">
                    {confirmed.map((row) => (
                      <li key={row.affiliate_id}>
                        <label className="pay__option">
                          <input
                            type="checkbox"
                            checked={takingBack.has(row.affiliate_id)}
                            onChange={(event) => {
                              const next = new Set(takingBack);
                              if (event.target.checked) next.add(row.affiliate_id);
                              else next.delete(row.affiliate_id);
                              setTakingBack(next);
                            }}
                          />
                          <span className="pay__option-body">
                            <strong>{row.name}</strong>
                            {row.determines_pay && (
                              <span className="detail__note">
                                a guaranteed minimum depends on this
                              </span>
                            )}
                          </span>
                        </label>
                      </li>
                    ))}
                  </ul>

                  <label className="field comp__field">
                    <span className="field__label">Why?</span>
                    <textarea
                      className="input reopen__textarea"
                      rows={2}
                      maxLength={500}
                      required
                      value={why}
                      onChange={(event) => setWhy(event.target.value)}
                      placeholder="Confirmed against the wrong month's posts."
                    />
                    <span className="detail__note">
                      Kept in the record. Without it there is nothing anywhere
                      to say a confirmation was ever made.
                    </span>
                  </label>

                  <div className="payroll__actions">
                    <button
                      type="button"
                      className="button"
                      onClick={() => {
                        setUndoing(false);
                        setTakingBack(new Set());
                        setWhy("");
                      }}
                      disabled={working}
                    >
                      Cancel
                    </button>
                    <button
                      type="button"
                      className="button button--primary"
                      onClick={takeBack}
                      disabled={
                        working || takingBack.size === 0 || why.trim() === ""
                      }
                    >
                      {working
                        ? "Saving…"
                        : `Take back ${takingBack.size} ${
                            takingBack.size === 1 ? "confirmation" : "confirmations"
                          }`}
                    </button>
                  </div>
                </>
              )}
            </section>
          )}
        </>
      )}

      {grid && rows.length === 0 && (
        <p className="empty">Nobody on the programme this month.</p>
      )}
    </>
  );
}

function Cell({
  value,
  label,
  suffix,
  onChange,
}: {
  value: string;
  label: string;
  /** *of 6*, or *required* — what the box beside it is measured against. */
  suffix?: string;
  onChange: (value: string) => void;
}) {
  return (
    <td className="targets__number">
      <span className="targets__cell">
        <input
          className="targets__input"
          inputMode="numeric"
          aria-label={label}
          value={value}
          onChange={(event) => onChange(event.target.value)}
        />
        {suffix && <span className="targets__of">{suffix}</span>}
      </span>
    </td>
  );
}

/**
 * Whether she is keeping up with the month, week by week. D08.
 *
 * **This screen and nowhere else.** The owner was asked and chose to keep it
 * internal, so nothing about being behind appears in the portal in any
 * wording. The consequence he accepted knowingly: a model cannot catch up on a
 * warning she never sees, so this is a prompt for the conversation rather than
 * a substitute for it.
 *
 * ## Not recorded is not behind
 *
 * The platform keeps one cumulative pair of counts a month and no weekly
 * history, so a figure last typed in week one cannot answer a question about
 * week three. Where nothing has been recorded since the week began it says so
 * — otherwise this column would quietly report how often HBA types rather
 * than how she is doing.
 */
/**
 * What a save actually did, when it was a year-wide one.
 *
 * A year-wide change writes twelve months and **silently cannot touch an
 * agreed one** — that refusal is 05B and it is not negotiable. It also
 * rewrites months already gone, which the owner chose knowingly on 11
 * September 2026 and which can turn a month that was achieved into one that
 * was missed.
 *
 * So it says what it reached and what it refused. "12 rows saved" would be
 * true and would hide both.
 */
function describeSave(
  saved: number,
  spread: { name: string; applied: string[]; skipped: { month: string }[] }[],
): string {
  const rows = saved === 1 ? "One row saved." : `${saved} rows saved.`;
  if (!spread?.length) return rows;

  const reached = spread.reduce((count, row) => count + row.applied.length, 0);
  const refused = spread.reduce((count, row) => count + row.skipped.length, 0);
  const months = `${reached} ${reached === 1 ? "month" : "months"} across the year`;
  return refused === 0
    ? `${rows} Applied to ${months}.`
    : `${rows} Applied to ${months}. ${refused} left alone — already agreed, ` +
      `or from before the platform.`;
}


function PaceCell({ row }: { row: Row }) {
  const pace = row.pace;
  if (!pace || pace.state === "not_started") return null;

  /*
   * **Nothing, when the line above already says it.** Where nothing has been
   * recorded at all, *Not recorded* has answered the question and a second
   * line saying nothing arrived this week either is the same fact twice - in
   * a 140px column, wrapped, which is what took the export's 56px row to 80.
   */
  if (row.achieved === null) return null;

  // **A month nobody has asked anything of is a gap, not a blank** (owner, 11
  // September 2026). It was rendering as nothing at all, which is exactly how
  // it stays unnoticed until payroll cannot close on it.
  if (pace.state === "no_target") {
    return <span className="targets__pace">Nothing asked for yet</span>;
  }
  /*
   * The wording is short because the column is 140px wide and the export
   * writes one line in it. *Nothing recorded in week 2* wrapped to two lines
   * and every row that carried it stood 24px taller than the design.
   */
  if (pace.state === "not_recorded_this_week") {
    return <span className="targets__pace">None in week {pace.week}</span>;
  }
  if (pace.state === "behind") {
    return (
      <span className="targets__behind">
        Behind · {pace.done} of {pace.expected_by_now}
      </span>
    );
  }
  return (
    <span className="targets__pace">
      On pace · {pace.done} of {pace.expected_by_now}
    </span>
  );
}


function Outcome({ row }: { row: Row }) {
  // **The outcome, not the counts**, though on this screen they agree: the
  // picker locks every month before go-live (`lockFor`), so the one row shape
  // where they differ — an outcome kept without counts, ADR 0036 — cannot be
  // reached here. Said in terms of the outcome anyway, because that is what
  // the column is for and the next person to widen the picker will not read
  // this file first.
  if (row.achieved === null) {
    return <span className="targets__unknown">Not recorded</span>;
  }
  if (row.achieved) {
    return (
      <span className="targets__met">
        Met{" "}
        {row.verified ? (
          <span className="targets__confirmed">· confirmed</span>
        ) : (
          <span className="targets__unconfirmed">· not confirmed</span>
        )}
      </span>
    );
  }
  return (
    <span className="targets__missed">
      Missed{" "}
      {row.verified && <span className="targets__confirmed">· confirmed</span>}
    </span>
  );
}
