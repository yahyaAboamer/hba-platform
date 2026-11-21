import { useEffect, useId, useRef, useState } from "react";
import { createPortal } from "react-dom";

import { ApiError, api } from "../../lib/api";
import { RATING_WORDS } from "../../lib/inbox";
import type { FeedbackRating, FeedbackRow, FollowUpEntry } from "../../lib/inbox";
import { clockTime, dayMonth } from "../../components/OpsSource";

/**
 * The follow-up of an unhappy answer (ADR 0088): what has been done, how long
 * she has waited, and the three things a person can record. Shared by the
 * Feedback screen's *To follow up* list and the block beside her chat.
 *
 * The history is a record: nothing here edits or deletes an entry. A mistake
 * is corrected by a new note.
 */

const HOUR = 3_600_000;
const MINUTE = 60_000;
/** The server's limit (`feedback_follow_up.NOTE_MAX`). */
const NOTE_MAX = 1000;
/** After she has said *No, not solved* this often, *Resolved* closes it without asking (`feedback_replies.MAX_REOPENS`). */
const MAX_REOPENS = 2;

function when(iso: string): string {
  return `${dayMonth(iso)} ${clockTime(iso)}`;
}

// ── The history ────────────────────────────────────────────────────────────

/** "No answer · Mona", "WhatsApp sent by the platform": who did what, before the time. */
function lead(entry: FollowUpEntry): { words: string; owed: boolean; platform: boolean } {
  const by = entry.by_name ? ` · ${entry.by_name}` : "";
  switch (entry.kind) {
    case "no_answer":
      return { words: `No answer${by}`, owed: false, platform: false };
    case "note":
      return { words: `Note${by}`, owed: false, platform: false };
    case "resolved":
      return { words: `Resolved${by}`, owed: false, platform: false };
    case "unreached":
      return { words: `Closed: couldn't reach${by}`, owed: false, platform: false };
    case "message_sent":
      return { words: "WhatsApp sent by the platform", owed: false, platform: true };
    case "message_failed":
      // The platform's own sentence ("Couldn't send … Write to her yourself.").
      return { words: entry.note ?? "Couldn't send the WhatsApp message.", owed: true, platform: true };
    case "wrote_back":
      return { words: "She wrote back", owed: false, platform: true };
    case "returned":
      return {
        words: entry.note ? `Back to your team: ${entry.note}` : "Back to your team",
        owed: false,
        platform: true,
      };
    default:
      return { words: String(entry.kind), owed: false, platform: true };
  }
}

/** The kinds whose note is a person's own words, shown under the line. */
const PERSON_NOTES = new Set(["no_answer", "note", "resolved", "unreached"]);

/**
 * Oldest first. Longer than `limit`, it shows the newest `limit` and a
 * *Show all (N)* button; empty, it shows nothing.
 */
export function FollowUpHistory({ entries, limit = 3 }: { entries: FollowUpEntry[]; limit?: number }) {
  const [all, setAll] = useState(false);
  if (entries.length === 0) return null;
  const folded = !all && entries.length > limit;
  const shown = folded ? entries.slice(-limit) : entries;

  return (
    <div className="inbox-fu-history">
      <ul>
        {shown.map((entry) => {
          const { words, owed, platform } = lead(entry);
          const classes = ["inbox-fu-entry"];
          if (platform) classes.push("inbox-fu-entry--platform");
          if (owed) classes.push("inbox-fu-entry--owed");
          return (
            <li key={entry.id} className={classes.join(" ")}>
              <span className="inbox-fu-entry__line">
                <b>{words}</b> · <span className="num">{when(entry.at)}</span>
              </span>
              {entry.note && PERSON_NOTES.has(entry.kind) && (
                <q className="inbox-fu-note" dir="auto">
                  {entry.note}
                </q>
              )}
            </li>
          );
        })}
      </ul>
      {entries.length > limit && (
        <button type="button" className="ops-linkbtn inbox-fu-history__more" onClick={() => setAll(!all)}>
          {folded ? `Show all (${entries.length})` : "Show fewer"}
        </button>
      )}
    </div>
  );
}

// ── The waiting clock ──────────────────────────────────────────────────────

function waited(ms: number): string {
  if (ms < HOUR) return `${Math.max(0, Math.floor(ms / MINUTE))} min`;
  if (ms > 48 * HOUR) return `${Math.floor(ms / (24 * HOUR))} days`;
  return `${Math.floor(ms / HOUR)} h`;
}

/** How long she has waited and the words for it, against the promised hours. */
export function waitingWords(since: string, hours: number, now: number): { words: string; late: boolean } {
  const ms = now - new Date(since).getTime();
  const left = hours * HOUR - ms;
  if (left <= 0) return { words: `Waiting ${waited(ms)} · past the ${hours} h promise`, late: true };
  const leftWords = left < HOUR ? `${Math.max(1, Math.floor(left / MINUTE))} min` : `${Math.floor(left / HOUR)} h`;
  return { words: `Waiting ${waited(ms)} · ${leftWords} left`, late: false };
}

/**
 * "Waiting 6 h · 18 h left", or "Waiting 27 h · past the 24 h promise" in the
 * refused tone. Calls and notes do not restart it: the promise is to reach
 * her, not to try.
 */
export function WaitingClock({ since, hours, now }: { since: string | null; hours: number; now: number }) {
  if (!since) return null;
  const { words, late } = waitingWords(since, hours, now);
  return <span className={late ? "inbox-fu-clock inbox-fu-clock--late" : "inbox-fu-clock"}>{words}</span>;
}

// ── The three actions and their pop-up ─────────────────────────────────────

export type FollowUpAction = "resolve" | "no_answer" | "note";

/** What the pop-ups need to know about the survey; a sheet row and the chat's block both have it. */
export type FollowUpSurvey = {
  id: number;
  order_name: string | null;
  customer_name?: string | null;
  rating: FeedbackRating | null;
  reason_title?: string | null;
  no_answer_count?: number;
  message_sent?: boolean;
  /** How often she has said *No, not solved*. */
  reopened_count?: number;
  /** The words the server would send her after the 2nd call; quoted only when given. */
  tried_to_call_text?: string | null;
  /** Feedback messages are switched off: nothing is sent to her. */
  feedback_off?: boolean;
};

/**
 * Each action's address written out whole, not built from parts:
 * `tests/test_reachability.py` reads the interface for the addresses it calls,
 * and an address assembled at run time is invisible to it.
 */
function send(action: FollowUpAction, id: number, body: object): Promise<FeedbackRow> {
  if (action === "resolve") return api.post<FeedbackRow>(`/api/inbox/feedback/${id}/resolve`, body);
  if (action === "no_answer") return api.post<FeedbackRow>(`/api/inbox/feedback/${id}/no-answer`, body);
  return api.post<FeedbackRow>(`/api/inbox/feedback/${id}/note`, body);
}

/**
 * One pop-up for each action. It says what she will receive before anything
 * is saved, keeps what was typed if saving fails, and shows the server's words.
 */
export function FollowUpDialog({
  action,
  survey,
  onClose,
  onDone,
}: {
  action: FollowUpAction;
  survey: FollowUpSurvey;
  onClose: () => void;
  onDone: (updated: FeedbackRow) => void;
}) {
  const [note, setNote] = useState("");
  const [close, setClose] = useState(false);
  const [saving, setSaving] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const dialogRef = useRef<HTMLDivElement>(null);
  const noteRef = useRef<HTMLTextAreaElement>(null);
  const ids = useId();
  const titleId = `${ids}-title`;
  const noteId = `${ids}-note`;
  const problemId = `${ids}-problem`;
  const counterId = `${ids}-count`;

  const order = survey.order_name ?? "this order";
  const who = survey.customer_name ?? null;
  const call = (survey.no_answer_count ?? 0) + 1;
  const sent = survey.message_sent ?? false;
  const lastResolve = (survey.reopened_count ?? 0) >= MAX_REOPENS;
  const triedWords = survey.tried_to_call_text ?? null;
  const required = action !== "no_answer";
  const canSave = !saving && (!required || note.trim() !== "");

  useEffect(() => {
    noteRef.current?.focus();
  }, []);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !saving) onClose();
      if (event.key !== "Tab" || !dialogRef.current) return;
      // Tab stays inside: it is modal, and says so.
      const stops = Array.from(
        dialogRef.current.querySelectorAll<HTMLElement>("button:not([disabled]), textarea, input:not([disabled])"),
      );
      if (stops.length === 0) return;
      const first = stops[0];
      const last = stops[stops.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose, saving]);

  async function save() {
    if (!canSave) return;
    setSaving(true);
    setProblem(null);
    const words = note.trim();
    const body = action === "no_answer" ? { note: words || null, close } : { note: words };
    try {
      const updated = await send(action, survey.id, body);
      onDone(updated);
      onClose();
    } catch (error) {
      setProblem(error instanceof ApiError ? error.message : "That could not be saved.");
      setSaving(false);
    }
  }

  const title =
    action === "resolve" ? `Resolve ${order}` : action === "no_answer" ? `No answer: ${order}` : `Add a note: ${order}`;
  const whoLine = [who, survey.rating ? RATING_WORDS[survey.rating] : null, survey.reason_title ?? null]
    .filter(Boolean)
    .join(" · ");
  const sub = action === "no_answer" ? `This is call ${call}${who ? ` for ${who}` : ""}` : whoLine;
  const label = action === "resolve" ? "What did you agree with her?" : action === "no_answer" ? "Note (optional)" : "Note";
  const saveWords = action === "resolve" ? "Save and resolve" : action === "no_answer" ? "Save call" : "Save note";
  const nearLimit = note.length >= NOTE_MAX - 100;
  const describedBy = [problem ? problemId : null, nearLimit ? counterId : null].filter(Boolean).join(" ") || undefined;

  return createPortal(
    <div className="inbox-fu-layer">
      <button
        type="button"
        className="inbox-fu-scrim"
        aria-hidden="true"
        tabIndex={-1}
        onClick={() => !saving && onClose()}
      />
      <div ref={dialogRef} className="inbox-fu-dialog" role="dialog" aria-modal="true" aria-labelledby={titleId}>
        <h2 id={titleId} className="inbox-fu-dialog__title">
          {title}
        </h2>
        {sub && (
          <p className="inbox-fu-dialog__sub" dir="auto">
            {sub}
          </p>
        )}
        <label className="inbox-fu-field" htmlFor={noteId}>
          {label}
          {required && (
            <span className="inbox-fu-req" aria-hidden="true">
              {" "}
              *
            </span>
          )}
        </label>
        <textarea
          id={noteId}
          ref={noteRef}
          className="input inbox-fu-textarea"
          dir="auto"
          rows={action === "resolve" ? 4 : 3}
          maxLength={NOTE_MAX}
          required={required}
          aria-invalid={problem ? true : undefined}
          aria-describedby={describedBy}
          value={note}
          onChange={(event) => setNote(event.target.value)}
        />
        {nearLimit && (
          <p id={counterId} className="inbox-fu-count num">
            {note.length.toLocaleString("en-US")} / 1,000
          </p>
        )}

        {action === "resolve" && lastResolve && (
          <p className="inbox-fu-hint">
            This closes the follow-up. She has said it wasn't solved twice, so she won't be asked again.
          </p>
        )}
        {action === "resolve" && !lastResolve && (
          <p className="inbox-fu-hint">
            Tomorrow she'll get a WhatsApp message: <i>"Was your issue solved?"</i> If she says no, she comes back to{" "}
            <b>To follow up</b>.
          </p>
        )}
        {action === "no_answer" && call === 2 && !sent && survey.feedback_off && (
          <p className="inbox-fu-hint">Feedback messages are switched off, so nothing will be sent to her.</p>
        )}
        {action === "no_answer" && call === 2 && !sent && !survey.feedback_off && (
          <p className="inbox-fu-hint inbox-fu-hint--owed">
            {triedWords ? (
              <>
                After this call she'll get a WhatsApp message from the platform: <i dir="auto">"{triedWords}"</i>
              </>
            ) : (
              "After this call she'll get a WhatsApp message from the platform saying we tried to call her."
            )}
          </p>
        )}
        {action === "no_answer" && call > 2 && sent && (
          <p className="inbox-fu-hint">She has already been sent the WhatsApp message.</p>
        )}
        {action === "no_answer" && call >= 3 && (
          <label className="inbox-fu-check">
            <input type="checkbox" checked={close} disabled={saving} onChange={(event) => setClose(event.target.checked)} />
            <span>
              Close as <b>Couldn't reach</b>. She won't be asked "Was your issue solved?". If she writes back within 14
              days, it opens again.
            </span>
          </label>
        )}

        {problem && (
          <p id={problemId} className="notice notice--refused inbox-fu-problem" role="alert">
            {problem}
          </p>
        )}
        <div className="inbox-fu-dialog__acts">
          <button type="button" className="inbox-btn inbox-btn--quiet" onClick={onClose} disabled={saving}>
            Cancel
          </button>
          <button type="button" className="inbox-btn" onClick={() => void save()} disabled={!canSave}>
            {saving ? "Saving…" : saveWords}
          </button>
        </div>
      </div>
    </div>,
    document.body,
  );
}

/**
 * *Resolved…* (filled), *No answer* and *Add note*. Each opens its pop-up;
 * focus goes back to the button that opened it.
 */
export function FollowUpActions({
  survey,
  onDone,
}: {
  survey: FollowUpSurvey;
  onDone: (updated: FeedbackRow) => void;
}) {
  const [open, setOpen] = useState<FollowUpAction | null>(null);
  const openers = useRef<Partial<Record<FollowUpAction, HTMLButtonElement | null>>>({});
  const last = useRef<FollowUpAction | null>(null);

  useEffect(() => {
    if (open) {
      last.current = open;
      return;
    }
    if (last.current) {
      // Still on the page (a call or a note keeps it open): back to the button pressed.
      const button = openers.current[last.current];
      if (button?.isConnected) button.focus();
      last.current = null;
    }
  }, [open]);

  const button = (action: FollowUpAction, words: string, filled: boolean) => (
    <button
      type="button"
      ref={(element) => {
        openers.current[action] = element;
      }}
      className={filled ? "inbox-btn inbox-btn--small" : "inbox-btn inbox-btn--small inbox-btn--quiet"}
      aria-haspopup="dialog"
      onClick={() => setOpen(action)}
    >
      {words}
    </button>
  );

  return (
    <div className="inbox-fu-actions">
      {button("resolve", "Resolved…", true)}
      {button("no_answer", "No answer", false)}
      {button("note", "Add note", false)}
      {open && <FollowUpDialog action={open} survey={survey} onClose={() => setOpen(null)} onDone={onDone} />}
    </div>
  );
}
