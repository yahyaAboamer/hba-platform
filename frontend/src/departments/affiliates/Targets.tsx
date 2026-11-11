import { useEffect, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";

import { MonthPicker } from "../../components/MonthPicker";
import type { MonthLock } from "../../components/MonthPicker";
import { api, can } from "../../lib/api";
import type { Session } from "../../lib/api";
import { currentMonth, formatMonth, platformMonths } from "../../lib/money";
import { PAY_TYPE } from "../../lib/payouts";
import "./ModelLifecycle.css";
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
  /** The raw compensation type she was on that month, or `null` for nobody.
   *  Labelled here rather than on the server, so one screen cannot start
   *  calling an arrangement something the next screen does not. */
  arrangement: string | null;
  recorded_at: string | null;
  /** The month she started with HBA, where it is known (ADR 0053, 0055). */
  start_month?: string | null;
  /** This month is before it, so it has no targets (ADR 0056). */
  before_start?: boolean;
  /** Her month is approved in payroll, so the server refuses any change to
   *  this row (`assert_recordable`). Said up front so the row can be locked
   *  with its reason instead of the whole save being refused afterwards. */
  agreed?: boolean;
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

type Field = "required_videos" | "required_stories" | "actual_videos" | "actual_stories";

/** What is in each of the four boxes, as text, so a half-typed cell survives. */
type Draft = Record<number, Record<Field, string>>;

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

/** The one problem that is shown while typing, as the export marks it. */
export const WHOLE = "Whole numbers only";

/**
 * Every box that would make the save wrong, keyed `id:field`, in words that
 * say what to do. Checked here so the box itself is marked; the server still
 * refuses all of it on its own.
 *
 * **All four boxes, whichever mode is showing.** A save sends both pairs, so a
 * box mistyped in the other mode was sent as 0 - over a stored requirement,
 * on the data that decides a guarantee (review, 10 November 2026).
 *
 * `rows` are the rows a save would send; locked rows never reach this.
 */
export function problems(
  rows: Pick<Row, "affiliate_id" | "required_videos" | "required_stories">[],
  draft: Draft,
): Record<string, string> {
  const found: Record<string, string> = {};
  for (const row of rows) {
    const cells = draft[row.affiliate_id];
    if (!cells) continue;
    const key = (field: Field) => `${row.affiliate_id}:${field}`;
    const value = (field: Field) => count(cells[field]);
    const fields: Field[] = ["required_videos", "required_stories", "actual_videos", "actual_stories"];
    for (const field of fields) if (value(field) === undefined) found[key(field)] = WHOLE;

    const [rv, rs, av, as] = fields.map(value);
    if (rv !== undefined && rs !== undefined) {
      const had = row.required_videos !== null || row.required_stories !== null;
      // A requirement cannot be taken off from here: emptying both boxes used
      // to be skipped in silence and the old figures came back after the save.
      if (had && rv === null && rs === null) {
        found[key("required_videos")] = "Type 0 for nothing asked";
      } else if ((rv === null) !== (rs === null)) {
        found[key(rv === null ? "required_videos" : "required_stories")] = "Type a number, 0 for none";
      }
    }
    if (av !== undefined && as !== undefined && (av === null) !== (as === null)) {
      // Half a month cannot say whether the target was met; the server
      // refuses it too, but only after the whole save has gone.
      found[key(av === null ? "actual_videos" : "actual_stories")] = "Type both, or clear both";
    }
  }
  return found;
}

const FIELD_WORDS: Record<Field, string> = {
  required_videos: "Videos required",
  required_stories: "Stories required",
  actual_videos: "Videos achieved",
  actual_stories: "Stories achieved",
};

export type Change = {
  id: number;
  name: string;
  /** *Videos achieved 3 → 5*, one per box that changes. */
  lines: string[];
  /** *Below target → Target met*, where the month's record turns. */
  turn: string | null;
};

/**
 * What a save will change, model by model, and what each change does.
 *
 * **Recording is the confirmation** (ADR 0081, owner, 11 November 2026), so
 * nothing checks the counts after they are saved. This list, read before
 * anything is written, is the check: a stray keystroke in an old month shows
 * up here as a change nobody meant, and a month that turns from met to missed
 * says so — with what it does to a guaranteed minimum.
 *
 * Mirrors what `save` sends: a row with no requirement is not sent, and
 * emptying both counts on a recorded row clears them.
 */
export function changesFor(rows: Row[], draft: Draft, month: string, current: string): Change[] {
  const out: Change[] = [];
  for (const row of rows) {
    const cells = draft[row.affiliate_id];
    if (!cells) continue;
    const next: Record<Field, number | null> = {
      required_videos: count(cells.required_videos) ?? null,
      required_stories: count(cells.required_stories) ?? null,
      actual_videos: count(cells.actual_videos) ?? null,
      actual_stories: count(cells.actual_stories) ?? null,
    };
    if (next.required_videos === null && next.required_stories === null) continue;
    const fields = Object.keys(FIELD_WORDS) as Field[];
    const show = (value: number | null) => (value === null ? "—" : String(value));
    const lines = fields
      .filter((field) => next[field] !== row[field])
      .map((field) => `${FIELD_WORDS[field]} ${show(row[field])} → ${show(next[field])}`);
    if (lines.length === 0) continue;

    const recorded = next.actual_videos !== null && next.actual_stories !== null;
    const achieved = recorded
      ? next.actual_videos! >= (next.required_videos ?? 0)
        && next.actual_stories! >= (next.required_stories ?? 0)
      : null;
    const before = outcomeWord(row, month, current);
    const after = outcomeWord(
      { achieved, actual_videos: next.actual_videos, actual_stories: next.actual_stories },
      month,
      current,
    );
    let turn: string | null = before === after ? null : `${before} → ${after}`;
    if (turn && row.determines_pay && (row.achieved === true) !== (achieved === true)) {
      turn += achieved === true
        ? " · her guaranteed minimum applies"
        : " · her guaranteed minimum no longer applies";
    }
    out.push({ id: row.affiliate_id, name: row.name, lines, turn });
  }
  return out;
}

/**
 * Targets. §15, and the one screen §12.2 asks to be built as a grid rather
 * than a form: every model down the side, one month across, tab straight
 * through, single save.
 *
 * Sara records these from their own tracking; the platform collects no evidence.
 * What it does is make the consequence visible — for a model on a guaranteed
 * minimum these numbers decide what they are paid, and for everybody else they
 * are worth knowing and decide nothing.
 *
 * Refined on 10 November 2026 (`docs/design-refinement/targets/JOURNAL.md`):
 * a box is only offered where a save could keep what is typed in it.
 */
export function Targets({ session, affiliateId, initialMonth, embedded = false }: { session: Session; affiliateId?: number; initialMonth?: string; embedded?: boolean }) {
  const [query] = useSearchParams();
  const [month, setMonth] = useState(initialMonth ?? (query.get("month")?.match(/^\d{4}-(0[1-9]|1[0-2])$/) ? query.get("month")! : session.platform.working_month));
  const [grid, setGrid] = useState<Grid | null>(null);
  const [draft, setDraft] = useState<Draft>({});
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState<string | null>(null);
  /** The longer report of a year-wide save: what it reached and what it left. */
  const [spread, setSpread] = useState<string | null>(null);
  const [working, setWorking] = useState(false);
  /** The changes a save is about to write, while they are being read. */
  const [review, setReview] = useState<Change[] | null>(null);
  /** Where focus goes back to when the change list is closed. */
  const saveButton = useRef<HTMLButtonElement>(null);
  /** Whether a save has been tried since the last load, so a box left empty
   *  is only called out once somebody has asked to save it. */
  const [tried, setTried] = useState(false);
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
   * **One set of numbers at a time**, the way the approved screen works: you
   * are either recording what happened or setting what is being asked for,
   * and the column headings say which.
   */
  const [mode, setMode] = useState<"achieved" | "required">("achieved");
  const [search, setSearch] = useState("");

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
        setTried(false);
      })
      .catch((caught) => {
        if (asked === month) setError(caught.message);
      });
  }

  useEffect(load, [month]);

  const current = currentMonth();
  const goLive = session.platform.go_live_month;
  /** Carried over from before the platform: outcomes only, kept as they were. */
  const beforePlatform = Boolean(goLive && month < goLive);
  const notStarted = month > current;
  const running = month === current;
  const year = month.slice(0, 4);
  /** Nothing on this month can be typed in this mode. */
  const monthLocked = beforePlatform || (mode === "achieved" && notStarted);

  /**
   * Why this row's boxes are not offered, or null when they are.
   *
   * Each is a save the server would refuse, or one that would keep nothing:
   * an agreed month (`assert_recordable`), a month before her start (ADR 0056),
   * and counts for a model nobody has asked anything of — those were skipped in
   * silence and the typed figures vanished after *0 rows saved*.
   */
  function rowLock(row: Row): "before_start" | "agreed" | "no_requirement" | null {
    if (row.before_start) return "before_start";
    if (row.agreed) return "agreed";
    if (mode === "achieved" && row.required_videos === null && row.required_stories === null) {
      return "no_requirement";
    }
    return null;
  }

  function edit(id: number, field: Field, value: string) {
    setSaved(null);
    setSpread(null);
    setDraft((was) => ({ ...was, [id]: { ...was[id], [field]: value } }));
  }

  // A house code publishes nothing, so a row of empty boxes beside it is
  // four things nobody will ever type into.
  const needle = search.trim().toLowerCase();
  const listed = (grid?.rows ?? []).filter(row =>
    row.account_kind !== "house"
    && (!affiliateId || row.affiliate_id === affiliateId));
  const rows = listed.filter(row =>
    (!query.get("pace") || row.pace?.state === query.get("pace"))
    && (!needle || row.name.toLowerCase().includes(needle)));
  /**
   * The rows a save sends: every row a save can keep, searched for or not and
   * in either mode - figures typed under *Set requirements* are still sent
   * after switching to *Record achieved*. Achieved boxes are never offered
   * where they could not be kept (`rowLock`), so they cannot hold edits.
   */
  const open = beforePlatform
    ? []
    : listed.filter((row) => !row.before_start && !row.agreed);
  const found = grid ? problems(open, draft) : {};
  const shown = tried
    ? found
    : Object.fromEntries(Object.entries(found).filter(([, why]) => why === WHOLE));

  /** *Save*: check the boxes, then list what would change before writing. */
  function save() {
    if (grid === null) return;

    /*
     * **The numbers on screen belong to the month that loaded them.**
     *
     * `month` and `grid` are two pieces of state that change at different
     * times: the picker moves first, the rows arrive later. A save between
     * the two would write one month's requirements into another - silently,
     * into the data that decides whether a guaranteed minimum applies.
     * Refused rather than reconciled.
     */
    if (grid.month !== month) {
      setError("That month is still loading. Nothing was saved — try again.");
      return;
    }

    setTried(true);
    if (Object.keys(found).length > 0) {
      // Take the reader to the first marked box: it may be twenty rows down,
      // behind the search, or in the other mode.
      const [first] = Object.keys(found);
      const [id, field] = first.split(":") as [string, Field];
      const who = listed.find((row) => String(row.affiliate_id) === id);
      setError(`Nothing saved. ${who?.name ?? "A row"}: ${found[first].toLowerCase()}.`);
      setMode(field.startsWith("required") ? "required" : "achieved");
      if (who && !rows.includes(who)) setSearch("");
      requestAnimationFrame(() => requestAnimationFrame(() =>
        document.getElementById(`targets-box-${id}-${field}`)?.focus()));
      return;
    }

    setError(null);
    const changes = changesFor(open, draft, month, current);
    // A box typed back to what it was (`07` for `7`) changes nothing.
    if (changes.length === 0 && !wholeYear) {
      setDraft(draftFrom(grid.rows));
      return;
    }
    setReview(changes);
  }

  async function commit() {
    if (grid === null) return;
    setReview(null);
    setWorking(true);
    setError(null);
    setSaved(null);
    setSpread(null);
    try {
      const body = [];
      for (const row of open) {
        const cells = draft[row.affiliate_id];
        const required_videos = count(cells.required_videos);
        const required_stories = count(cells.required_stories);
        const actual_videos = count(cells.actual_videos);
        const actual_stories = count(cells.actual_stories);

        // A row nobody has asked anything of, and nobody is asking now, is
        // left alone. Sending zeros for it would set a requirement of nothing
        // for every model on the list.
        if (required_videos === null && required_stories === null) continue;

        // **Emptying both count boxes means "take them off"**, not "leave
        // them", and only where something was actually recorded before.
        // A06: unrecorded and zero are different facts.
        const wasRecorded = row.actual_videos !== null;
        const clearing =
          wasRecorded && actual_videos === null && actual_stories === null;

        body.push({
          affiliate_id: row.affiliate_id,
          required_videos: required_videos ?? 0,
          required_stories: required_stories ?? 0,
          actual_videos: clearing ? null : actual_videos ?? null,
          actual_stories: clearing ? null : actual_stories ?? null,
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
        rows: body,
        revision: grid.revision,
        apply_to_year: wholeYear,
      });
      // Carried forward, so saving twice in a row does not need a reload
      // between them.
      setGrid({ ...grid, revision: result.revision });
      setSaved(savedLine(mode, month));
      setSpread(describeYear(year, result.applied_to_year));
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

  /**
   * How many boxes differ from what is stored — the export's *N unsaved
   * changes*, with a Discard beside it. Counted against the loaded grid, so
   * typing a value and typing it back reports nothing to save.
   */
  const dirtyCount = grid
    ? grid.rows.reduce((total, row) => {
        const cells = draft[row.affiliate_id];
        if (!cells) return total;
        const stored = draftFrom([row])[row.affiliate_id];
        return total + (Object.keys(cells) as Field[])
          .filter((field) => cells[field] !== stored[field]).length;
      }, 0)
    : 0;

  // A month or a tab left with unsaved figures loses them without a word;
  // the browser asks first, as it does for any form.
  const unsaved = dirtyCount > 0;
  useEffect(() => {
    if (!unsaved) return;
    const hold = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      event.returnValue = "";
    };
    window.addEventListener("beforeunload", hold);
    return () => window.removeEventListener("beforeunload", hold);
  }, [unsaved]);

  /** Another month, but not over unsaved figures: they would be dropped. */
  function pickMonth(next: string) {
    if (next === month) return;
    if (unsaved) {
      setError(
        `${dirtyCount} unsaved ${dirtyCount === 1 ? "change" : "changes"} on ` +
        `${formatMonth(month)}. Save or discard ${dirtyCount === 1 ? "it" : "them"} first.`,
      );
      return;
    }
    setMonth(next);
  }

  function discard() {
    if (grid) setDraft(draftFrom(grid.rows));
    setSaved(null);
    setSpread(null);
    setTried(false);
    setError(null);
  }

  function lockFor(candidate: string): MonthLock {
    if (goLive && candidate < goLive) return "historical";
    if (candidate > currentMonth()) return "future";
    return null;
  }

  const canRecord = can(session, "targets.record");

  return (
    <>
      {!embedded && <div className="page__head">
        <div className="page__title">
          <h1>Targets</h1>
          <span className="page__subtitle">
            {formatMonth(month)}{running ? " · the month so far, updated weekly" : ""}
          </span>
        </div>
        <MonthPicker value={month} onChange={pickMonth} months={platformMonths(session.platform)} lockFor={lockFor} />
      </div>}

      {error && (
        <p className="notice notice--refused" role="alert">
          {error}
        </p>
      )}

      {spread && <p className="notice notice--settled targets__note">{spread}</p>}

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
            {/* Two radios rather than two buttons: they are one choice, and a
                radio group is what says so to somebody arriving by keyboard. */}
            <div className="seg" role="radiogroup" aria-label="Which numbers">
              <label className="seg-opt">
                <input type="radio" name="targets-mode" checked={mode === "achieved"}
                  onChange={() => { setMode("achieved"); setTried(false); }} />
                <span>Record achieved</span>
              </label>
              <label className="seg-opt">
                <input type="radio" name="targets-mode" checked={mode === "required"}
                  onChange={() => { setMode("required"); setTried(false); }} />
                <span>Set requirements</span>
              </label>
            </div>
          </div>

          {/* The export's right-hand group: what is unsaved, the way back from
              it, and the save. Everything that acts on the whole grid. */}
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
              <span className="targets__saved" role="status">{saved}</span>
            )}
            {canRecord && mode === "required" && !beforePlatform && (
              <label className="targets__year">
                <input
                  type="checkbox"
                  checked={wholeYear}
                  onChange={(event) => setWholeYear(event.target.checked)}
                />
                Whole year
              </label>
            )}
            {canRecord && !beforePlatform && (
              <button
                type="button"
                className="button button--primary"
                ref={saveButton}
                onClick={save}
                disabled={working || dirtyCount === 0}
              >
                {working ? "Saving…" : wholeYear ? `Save for all of ${year}` : "Save changes"}
              </button>
            )}
          </div>
        </div>
      )}

      {/* What the whole-year save does, where its tick is. Past months are
          rewritten, which can turn a met month into a miss (owner, 11 Sep). */}
      {grid && wholeYear && mode === "required" && (
        <p className="notice targets__note">
          Applies to every month of {year}, past ones included, so a month that was
          met can become a miss. Agreed months are left alone.
        </p>
      )}

      {grid && beforePlatform && (
        <p className="notice targets__note">
          {formatMonth(month)} is before the platform. Its outcomes were carried
          over as they were, and nothing here can be changed.
        </p>
      )}

      {grid && !beforePlatform && mode === "achieved" && notStarted && (
        <p className="notice targets__note targets__month-note">
          <span>{formatMonth(month)} hasn't started, so there is nothing to record yet.</span>
          {canRecord && (
            <button type="button" className="button" onClick={() => setMode("required")}>
              Set requirements
            </button>
          )}
        </p>
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
                const lock = monthLocked ? "month" : rowLock(row);
                const closed = lock === "before_start";
                const videos: Field = mode === "achieved" ? "actual_videos" : "required_videos";
                const stories: Field = mode === "achieved" ? "actual_stories" : "required_stories";
                const of = (required: number | null) =>
                  mode === "achieved"
                    ? required === null ? undefined : `of ${required}`
                    : "required";
                return (
                  <tr key={row.affiliate_id} className={closed ? "targets__row--closed" : undefined}>
                    <td className="targets__model">
                      <span className="targets__who">
                      <Link
                        className="targets__name"
                        to={`/affiliates/models/${row.affiliate_id}`}
                      >
                        {row.name}
                      </Link>
                      {/* The export writes the arrangement beside every name,
                          and *Guarantee needs this record* where a guarantee
                          depends on a record that does not exist yet. A
                          locked row says why it is locked instead. */}
                      <span className="targets__arrangement">
                        {closed && row.start_month
                          ? `Starts ${formatMonth(row.start_month)}`
                          : lock === "agreed"
                          ? "Agreed in payroll"
                          : row.determines_pay && row.achieved === null && !beforePlatform
                          ? "Guarantee needs this record"
                          : row.arrangement
                            ? PAY_TYPE[row.arrangement] ?? row.arrangement
                            : "No terms set"}
                      </span>
                      </span>
                    </td>
                    {lock === "no_requirement" ? (
                      <td className="targets__number targets__first" colSpan={2}>
                        {canRecord ? (
                          <button
                            type="button"
                            className="button targets__first-act"
                            onClick={() => setMode("required")}
                          >
                            Set requirements first
                          </button>
                        ) : (
                          <span className="targets__of">Nothing asked for yet</span>
                        )}
                      </td>
                    ) : lock !== null || !canRecord ? (
                      <>
                        <Shown value={cells[videos]} suffix={of(row.required_videos)} label={mode === "achieved" ? "Videos" : "Videos required"} />
                        <Shown value={cells[stories]} suffix={of(row.required_stories)} label={mode === "achieved" ? "Stories" : "Stories required"} />
                      </>
                    ) : (
                      <>
                        <Cell
                          id={`${row.affiliate_id}-${videos}`}
                          value={cells[videos]}
                          label={`${row.name} videos ${mode === "achieved" ? "achieved" : "required"}`}
                          shortLabel="Videos"
                          suffix={of(row.required_videos)}
                          error={shown[`${row.affiliate_id}:${videos}`]}
                          onChange={(v) => edit(row.affiliate_id, videos, v)}
                        />
                        <Cell
                          id={`${row.affiliate_id}-${stories}`}
                          value={cells[stories]}
                          label={`${row.name} stories ${mode === "achieved" ? "achieved" : "required"}`}
                          shortLabel="Stories"
                          suffix={of(row.required_stories)}
                          error={shown[`${row.affiliate_id}:${stories}`]}
                          onChange={(v) => edit(row.affiliate_id, stories, v)}
                        />
                      </>
                    )}
                    {/* The export draws one line here, toned by what it says.
                        In the running month only, D08's weekly pace follows
                        as a quieter line. */}
                    <td className="targets__outcome">
                      {closed ? (
                        <>
                          <span className="targets__closed">Before her start</span>
                          {/* A record made before her start was known stays
                              visible. */}
                          {row.achieved !== null && <Outcome row={row} month={month} />}
                        </>
                      ) : (
                        <>
                          <Outcome row={row} month={month} />
                          {running && mode === "achieved" && <PaceCell row={row} />}
                        </>
                      )}
                    </td>
                    <td className="targets__updated">
                      {row.recorded_at
                        ? new Date(row.recorded_at).toLocaleDateString("en-GB",
                            { day: "numeric", month: "long", year: "numeric" })
                        : <span className={notStarted ? "targets__closed" : "targets__never"}>—</span>}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          </div>

        </>
      )}

      {grid && rows.length === 0 && (
        <p className="empty">
          {needle ? "No model matches that search." : "No models on the Targets list this month."}
        </p>
      )}

      {review && (
        <Review
          changes={review}
          month={month}
          wholeYear={wholeYear}
          year={year}
          onCancel={() => {
            setReview(null);
            requestAnimationFrame(() => saveButton.current?.focus());
          }}
          onSave={commit}
        />
      )}
    </>
  );
}

/**
 * The changes, read before they are written (ADR 0081). Built on the
 * dialog every lifecycle action already uses, so it looks and behaves like
 * the other *are you sure* moments: Escape or *Keep editing* goes back with
 * every box as it was.
 */
function Review({
  changes,
  month,
  wholeYear,
  year,
  onCancel,
  onSave,
}: {
  changes: Change[];
  month: string;
  wholeYear: boolean;
  year: string;
  onCancel: () => void;
  onSave: () => void;
}) {
  const back = useRef<HTMLButtonElement>(null);
  // Held in a ref so a re-render of the page behind does not re-run the
  // effect and pull focus back to *Keep editing* while somebody is reading.
  const cancel = useRef(onCancel);
  cancel.current = onCancel;
  useEffect(() => {
    back.current?.focus();
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") cancel.current();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, []);

  const total = changes.reduce((sum, change) => sum + change.lines.length, 0);
  const many = `${total} ${total === 1 ? "change" : "changes"}`;
  return (
    <div className="lifecycle__layer">
      {/* A click outside goes back, as Escape does; hidden from a screen
          reader, which already has *Keep editing* inside the dialog. */}
      <button type="button" className="lifecycle__scrim" aria-hidden="true" tabIndex={-1} onClick={onCancel} />
      <div className="lifecycle__dialog targets__review" role="dialog" aria-modal="true" aria-labelledby="targets-review-title">
        <h2 id="targets-review-title" className="lifecycle__title">
          {total === 0 ? `Save for all of ${year}?` : `Save ${many} to ${formatMonth(month)}?`}
        </h2>
        {changes.length > 0 && (
          <ul className="targets__changes">
            {changes.map((change) => (
              <li key={change.id}>
                <strong>{change.name}</strong>
                {change.lines.map((line) => <span key={line}>{line}</span>)}
                {change.turn && <span className="targets__turn">{change.turn}</span>}
              </li>
            ))}
          </ul>
        )}
        {wholeYear && (
          <p className="targets__review-note">
            The requirements also go to every month of {year}, past ones
            included. Agreed months are left alone.
          </p>
        )}
        <div className="lifecycle__acts">
          <button type="button" className="button" ref={back} onClick={onCancel}>
            Keep editing
          </button>
          <button type="button" className="button button--primary" onClick={onSave}>
            {wholeYear ? `Save for all of ${year}` : `Save ${many}`}
          </button>
        </div>
      </div>
    </div>
  );
}

function Cell({
  id,
  value,
  label,
  shortLabel,
  suffix,
  error,
  onChange,
}: {
  id: string;
  value: string;
  label: string;
  /** *Videos* / *Stories*: shown on a phone, where the column headings are not. */
  shortLabel: string;
  /** *of 6*, or *required* — what the box beside it is measured against. */
  suffix?: string;
  /** What is wrong with this box, in words that say what to do. */
  error?: string;
  onChange: (value: string) => void;
}) {
  const errorId = `targets-error-${id}`;
  return (
    <td className="targets__number">
      <span className="targets__cell">
        <span className="targets__cell-label" aria-hidden="true">{shortLabel}</span>
        <input
          id={`targets-box-${id}`}
          className={error ? "targets__input targets__input--bad" : "targets__input"}
          inputMode="numeric"
          aria-label={label}
          aria-invalid={error ? true : undefined}
          aria-describedby={error ? errorId : undefined}
          value={value}
          onChange={(event) => onChange(event.target.value)}
        />
        {suffix && <span className="targets__of">{suffix}</span>}
      </span>
      {error && <span className="targets__error" id={errorId}>{error}</span>}
    </td>
  );
}

/** A figure that cannot be changed here, shown as text rather than as a box
 *  that refuses what is typed into it. */
function Shown({ value, suffix, label }: { value: string; suffix?: string; label: string }) {
  return (
    <td className="targets__number">
      <span className="targets__cell">
        <span className="targets__cell-label" aria-hidden="true">{label}</span>
        <span className="targets__value">{value === "" ? "—" : value}</span>
        {suffix && <span className="targets__of">{suffix}</span>}
      </span>
    </td>
  );
}

/**
 * The longer report of a year-wide save: what it reached and what it refused.
 *
 * A year-wide change writes twelve months and **cannot touch an agreed one**
 * (05B). It also rewrites months already gone, which the owner chose knowingly
 * on 11 September 2026. "Saved" alone would be true and would hide both.
 */
export function describeYear(
  year: string,
  spread: { name: string; applied: string[]; skipped: { month: string }[] }[] | undefined,
): string | null {
  if (!spread?.length) return null;
  const reached = spread.reduce((total, row) => total + row.applied.length, 0);
  const refused = spread.reduce((total, row) => total + row.skipped.length, 0);
  const months = `${reached} ${reached === 1 ? "month" : "months"} of ${year}`;
  return refused === 0
    ? `Requirements saved across ${months}.`
    : `Requirements saved across ${months}. ${refused} left alone — already ` +
      `agreed, before the platform, or before her start.`;
}

/** The export's words for a save (`tgSaved`). */
export function savedLine(mode: "achieved" | "required", month: string): string {
  return mode === "required"
    ? `Requirements saved for ${formatMonth(month)}`
    : `Achieved counts recorded for ${formatMonth(month)}`;
}

/**
 * Whether she is keeping up with the running month, week by week. D08.
 *
 * **This screen and nowhere else**, and **the running month only**: once a
 * month is over its outcome answers the question, and a pace line beside it
 * either repeated *Below target* or, because pace adds videos and stories
 * while the target needs each, contradicted it (*Below target · On pace*).
 * The total in any mix is the owner's rule for the weekly line (confirmed
 * again on 10 November 2026).
 */
export function paceWords(pace: Row["pace"] | undefined, achieved: boolean | null): string | null {
  if (!pace || pace.state === "not_started") return null;
  // *No record yet* has answered the question already, and so has *Target
  // met*: a month already met cannot fall behind.
  if (achieved === null || achieved === true) return null;
  if (pace.state === "no_target") return "Nothing asked for yet";
  if (pace.state === "not_recorded_this_week") return `Not updated in week ${pace.week}`;
  if (pace.state === "behind") {
    return `Week ${pace.week} · ${pace.expected_by_now - pace.done} short`;
  }
  return `Week ${pace.week} · on pace`;
}

function PaceCell({ row }: { row: Row }) {
  const words = paceWords(row.pace, row.achieved);
  if (!words) return null;
  return (
    <span className={row.pace.state === "behind" ? "targets__behind" : "targets__pace"}>
      {words}
    </span>
  );
}

/**
 * The export's word for the month's record (`tgRows.state`): *No record yet*,
 * *Recorded zero*, *Target met*, and for a month not met *In progress* while
 * it is still running, *Below target* once it has ended (the export's
 * `mTargetHistory`). Toned as the export tones them.
 */
export function outcomeWord(row: Pick<Row, "achieved" | "actual_videos" | "actual_stories">, month: string, current: string): string {
  // Amber *No record yet* on a month that has not begun warned about
  // something nobody could do yet.
  if (row.achieved === null && month > current) return "Not started";
  if (row.achieved === null) return "No record yet";
  if (row.actual_videos === 0 && row.actual_stories === 0) return "Recorded zero";
  if (row.achieved) return "Target met";
  return month >= current ? "In progress" : "Below target";
}

function Outcome({ row, month }: { row: Row; month: string }) {
  // The outcome, not the counts: a month from before the platform keeps an
  // outcome with no counts (ADR 0036), and this column reads it as it is.
  const word = outcomeWord(row, month, currentMonth());
  const tone = word === "No record yet" ? "targets__unknown" : word === "Target met" ? "targets__met" : "targets__missed";
  return <span className={tone}>{word}</span>;
}
