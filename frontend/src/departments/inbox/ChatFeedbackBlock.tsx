import { useState } from "react";

import { ApiError, api } from "../../lib/api";
import { RATING_WORDS, REORDER_WORDS, dayTimeLabel, feedbackStateNote } from "../../lib/inbox";
import type { ChatFeedback } from "../../lib/inbox";
import { dayMonth } from "../../components/OpsSource";

/**
 * How her delivered order went, in her own words, beside her chat
 * (ADR 0083, decision 4).
 *
 * An unhappy answer is followed up by a person: the one who has written to
 * her presses *Resolved*, and a day later she is asked whether it was solved.
 * Pressing it changes nothing about the order. It does not apologise or
 * refund; it only tells the platform a person has been in touch.
 */

/** Who pressed it and when, as soon as the press is in, before the chat is read again. */
type JustResolved = { by: string | null; at: string };

function resolvedWords(by: string | null, at: string): string {
  return by ? `Resolved by ${by} on ${dayMonth(at)}` : `Resolved on ${dayMonth(at)}`;
}

export function ChatFeedbackBlock({
  feedback,
  now,
  late,
  onResolved,
}: {
  feedback: ChatFeedback;
  now: number;
  /** Not the first thing in the panel: nothing waits on a person. */
  late: boolean;
  /** Read the chat and the list again. */
  onResolved: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const [just, setJust] = useState<JustResolved | null>(null);

  const waiting = feedback.rating === "unhappy" && feedback.step === "support" && feedback.needs_follow_up;
  const canResolve = waiting && just === null;
  // What the server says wins once it says it; until then, what was pressed.
  const resolved: JustResolved | null =
    feedback.resolved_at && !feedback.needs_follow_up
      ? { by: feedback.resolved_by_name, at: feedback.resolved_at }
      : just;
  const note = feedbackStateNote(feedback.state);

  async function resolve() {
    setBusy(true);
    setProblem(null);
    // Shown at once; taken back below if the platform refuses.
    setJust({ by: null, at: new Date().toISOString() });
    try {
      const done = await api.post<{ resolved_by_name?: string | null; resolved_at?: string | null }>(
        `/api/inbox/feedback/${feedback.id}/resolve`,
      );
      setJust({ by: done?.resolved_by_name ?? null, at: done?.resolved_at ?? new Date().toISOString() });
      onResolved();
    } catch (error) {
      setJust(null);
      setProblem(error instanceof ApiError ? error.message : "That could not be saved.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section
      className={late ? "inbox-fb-block inbox-fb-block--late" : "inbox-fb-block"}
      aria-labelledby="inbox-feedback-title"
    >
      <h3 id="inbox-feedback-title">Feedback</h3>
      <dl>
        <dt>Order</dt>
        <dd className="num">{feedback.order_name ?? "—"}</dd>
        <dt>Asked</dt>
        <dd className="num">{feedback.asked_at ? dayTimeLabel(feedback.asked_at, now) : "—"}</dd>
        <dt>Answer</dt>
        <dd>
          {feedback.rating ? (
            <span
              className={`inbox-status inbox-status--${
                feedback.rating === "loved" ? "settled" : feedback.rating === "unhappy" ? "refused" : "plain"
              }`}
            >
              {RATING_WORDS[feedback.rating]}
            </span>
          ) : (
            <span className="ops-muted">No answer yet</span>
          )}
        </dd>
        {feedback.reason_title && (
          <>
            <dt>Reason</dt>
            <dd>{feedback.reason_title}</dd>
          </>
        )}
        {feedback.comment && (
          <>
            <dt>She wrote</dt>
            <dd className="inbox-fb-block__said">{feedback.comment}</dd>
          </>
        )}
        {feedback.reorder && (
          <>
            <dt>Order again</dt>
            <dd>{REORDER_WORDS[feedback.reorder]}</dd>
          </>
        )}
        {feedback.code && (
          <>
            <dt>Reward code</dt>
            <dd>
              <span className="num">{feedback.code}</span> · {feedback.code_used ? "used" : "not used yet"}
            </dd>
          </>
        )}
      </dl>

      {waiting && !resolved && (
        <p className="inbox-order__hint">
          <span className="inbox-status inbox-status--owed">Needs follow-up</span>
        </p>
      )}
      {feedback.reopened_count > 0 && (
        <p className="inbox-order__why">
          Reopened: she said her issue was not solved
          {feedback.reopened_count > 1 ? ` (${feedback.reopened_count} times)` : ""}.
        </p>
      )}
      {resolved && <p className="inbox-order__why">{resolvedWords(resolved.by, resolved.at)}.</p>}
      {feedback.solved !== null && (
        <p className="inbox-order__why">Solved: {feedback.solved ? "yes" : "no"}</p>
      )}
      {note && <p className="inbox-order__hint">{note}.</p>}
      {feedback.last_error && (
        <p className="inbox-order__hint">The last message to her could not be sent: {feedback.last_error}</p>
      )}

      {canResolve && (
        <>
          <p className="inbox-order__hint">She will be asked tomorrow whether her issue was solved.</p>
          <div className="inbox-setstatus">
            <button
              type="button"
              className="inbox-btn inbox-btn--small"
              disabled={busy}
              onClick={() => void resolve()}
            >
              {busy ? "Saving…" : "Resolved"}
            </button>
          </div>
        </>
      )}
      {problem && (
        <p className="notice notice--refused" role="alert">
          {problem}
        </p>
      )}
    </section>
  );
}
