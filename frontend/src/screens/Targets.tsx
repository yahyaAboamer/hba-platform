import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

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
};

type Grid = { month: string; rows: Row[] };

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
function waitingOn(row: Row): string | null {
  if (!row.determines_pay) return null;
  if (row.actual_videos === null) return "Blocks this month — nothing recorded";
  if (row.achieved && !row.verified) {
    return "Blocks this month — met, and not yet confirmed";
  }
  return null;
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
 */
export function Targets({ session }: { session: Session }) {
  const [month, setMonth] = useState(session.platform.working_month);
  const [grid, setGrid] = useState<Grid | null>(null);
  const [draft, setDraft] = useState<Draft>({});
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState<string | null>(null);
  const [working, setWorking] = useState(false);
  const [chosen, setChosen] = useState<Set<number>>(new Set());
  //: Undoing is its own selection and its own reason. Sharing `chosen`
  //: with confirming would let one button act on rows picked for the
  //: other, which on a screen that releases guarantees is not a mistake
  //: worth risking to save a state variable.
  const [undoing, setUndoing] = useState(false);
  const [takingBack, setTakingBack] = useState<Set<number>>(new Set());
  const [why, setWhy] = useState("");

  function load() {
    setError(null);
    api
      .get<Grid>(`/api/targets/${month}`)
      .then((body) => {
        setGrid(body);
        setDraft(draftFrom(body.rows));
        setChosen(new Set());
      })
      .catch((caught) => setError(caught.message));
  }

  useEffect(load, [month]);

  function edit(id: number, field: keyof Draft[number], value: string) {
    setSaved(null);
    setDraft((was) => ({ ...was, [id]: { ...was[id], [field]: value } }));
  }

  async function save() {
    if (grid === null) return;
    setWorking(true);
    setError(null);
    setSaved(null);
    try {
      const rows = [];
      for (const row of grid.rows.filter((r) => r.account_kind !== "house")) {
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

        rows.push({
          affiliate_id: row.affiliate_id,
          required_videos: required_videos ?? 0,
          required_stories: required_stories ?? 0,
          actual_videos,
          actual_stories,
        });
      }

      const result = await api.put<{ saved: number }>(
        `/api/targets/${month}`,
        { rows },
      );
      setSaved(
        result.saved === 1 ? "One row saved." : `${result.saved} rows saved.`,
      );
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
  const rows = (grid?.rows ?? []).filter((row) => row.account_kind !== "house");
  const blocking = rows.filter((row) => waitingOn(row) !== null);
  const confirmable = rows.filter(
    (row) => row.actual_videos !== null && !row.verified,
  );
  const confirmed = rows.filter((row) => row.verified);

  return (
    <>
      <div className="page__head">
        <div className="page__title">
          <h1>Targets</h1>
          <span className="page__subtitle">{formatMonth(month)}</span>
        </div>
        <MonthPicker value={month} onChange={setMonth} lockFor={lockFor} />
      </div>

      {error && (
        <p className="notice notice--refused" role="alert">
          {error}
        </p>
      )}

      {saved && <p className="notice notice--settled targets__note">{saved}</p>}

      {grid === null && !error && <p className="empty">Loading…</p>}

      {grid && (
        <p className="targets__lead">
          Videos and stories published, from your own tracking. On a guaranteed
          minimum these decide the pay; for everyone else they are worth
          knowing and change nothing.{" "}
          <strong>{blocking.length}</strong>{" "}
          {blocking.length === 1 ? "model is" : "models are"} held up by them
          this month.
        </p>
      )}

      {grid && rows.length > 0 && (
        <>
          <table className="table targets__grid">
            <thead>
              <tr>
                <th className="targets__pick" />
                <th>Name</th>
                <th className="targets__number" colSpan={2}>
                  Asked for
                </th>
                <th className="targets__number" colSpan={2}>
                  Produced
                </th>
                <th>Outcome</th>
                <th>Waiting on</th>
              </tr>
              <tr className="targets__subhead">
                <th />
                <th />
                <th className="targets__number">Videos</th>
                <th className="targets__number">Stories</th>
                <th className="targets__number">Videos</th>
                <th className="targets__number">Stories</th>
                <th />
                <th />
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => {
                const cells = draft[row.affiliate_id];
                if (!cells) return null;
                const waiting = waitingOn(row);
                return (
                  <tr key={row.affiliate_id}>
                    <td className="targets__pick">
                      {can(session, "targets.verify") &&
                        row.actual_videos !== null &&
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
                    </td>
                    <td>
                      <Link
                        className="targets__name"
                        to={`/affiliates/${row.affiliate_id}`}
                      >
                        {row.name}
                      </Link>
                      {row.determines_pay && (
                        <span className="targets__decides">decides pay</span>
                      )}
                    </td>
                    <Cell
                      value={cells.required_videos}
                      label={`${row.name} videos asked for`}
                      onChange={(v) => edit(row.affiliate_id, "required_videos", v)}
                    />
                    <Cell
                      value={cells.required_stories}
                      label={`${row.name} stories asked for`}
                      onChange={(v) => edit(row.affiliate_id, "required_stories", v)}
                    />
                    <Cell
                      value={cells.actual_videos}
                      label={`${row.name} videos produced`}
                      onChange={(v) => edit(row.affiliate_id, "actual_videos", v)}
                    />
                    <Cell
                      value={cells.actual_stories}
                      label={`${row.name} stories produced`}
                      onChange={(v) => edit(row.affiliate_id, "actual_stories", v)}
                    />
                    <td className="targets__outcome">
                      <Outcome row={row} />
                    </td>
                    <td>
                      {waiting && <span className="blocker">{waiting}</span>}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>

          <div className="payroll__actions">
            {can(session, "targets.record") && (
              <button
                type="button"
                className="button button--primary"
                onClick={save}
                disabled={working}
              >
                {working ? "Saving…" : "Save the month"}
              </button>
            )}
            {can(session, "targets.verify") && confirmable.length > 0 && (
              <button
                type="button"
                className="button"
                onClick={confirm}
                disabled={working || chosen.size === 0}
              >
                {chosen.size === 0
                  ? "Choose whose numbers to confirm"
                  : `Confirm ${chosen.size} ${chosen.size === 1 ? "model" : "models"}`}
              </button>
            )}
          </div>

          {/*
           * §15 and §11.3. Confirming is what unlocks a guarantee, so it is
           * worth saying plainly that it is about the numbers and not about
           * their month — somebody who thinks they are approving a *result* will
           * hesitate to confirm a miss, and a miss left unconfirmed is
           * indistinguishable from a month nobody looked at.
           */}
          <p className="targets__lead">
            Confirming says the numbers are right, not that the month went well.
            Confirming a miss is normal and costs nothing — the commission is
            paid either way. It is <em>nothing recorded</em> that holds a
            month up.
          </p>

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
  onChange,
}: {
  value: string;
  label: string;
  onChange: (value: string) => void;
}) {
  return (
    <td className="targets__number">
      <input
        className="targets__input"
        inputMode="numeric"
        aria-label={label}
        value={value}
        onChange={(event) => onChange(event.target.value)}
      />
    </td>
  );
}

function Outcome({ row }: { row: Row }) {
  if (row.actual_videos === null) {
    return <span className="targets__unknown">Not recorded</span>;
  }
  if (row.achieved) {
    return (
      <span className="targets__met">
        Met
        {row.verified ? (
          <span className="targets__confirmed">confirmed</span>
        ) : (
          <span className="targets__unconfirmed">not confirmed</span>
        )}
      </span>
    );
  }
  return (
    <span className="targets__missed">
      Missed
      {row.verified && <span className="targets__confirmed">confirmed</span>}
    </span>
  );
}
