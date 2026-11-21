import { useEffect, useState } from "react";

import { RATING_WORDS, REORDER_WORDS, dayTimeLabel, feedbackStateNote } from "../../lib/inbox";
import type { ChatFeedback, FeedbackRow } from "../../lib/inbox";
import { dayMonth } from "../../components/OpsSource";
import { FollowUpActions, FollowUpHistory, WaitingClock } from "./FollowUp";

/**
 * How her delivered order went, in her own words, beside her chat
 * (ADR 0083, decision 4; ADR 0088).
 *
 * An unhappy answer is followed up by a person, who records what happened:
 * a call she did not answer, a note, or *Resolved* with what was agreed. A day
 * after *Resolved* she is asked whether it was solved. None of it changes the
 * order. It does not apologise or refund; it tells the platform, and the next
 * person, what has been done.
 */

function resolvedWords(by: string | null, at: string): string {
  return by ? `Resolved by ${by} on ${dayMonth(at)}` : `Resolved on ${dayMonth(at)}`;
}

function unreachedWords(by: string | null, at: string): string {
  return by ? `Closed as couldn't reach by ${by} on ${dayMonth(at)}` : `Closed as couldn't reach on ${dayMonth(at)}`;
}

export function ChatFeedbackBlock({
  feedback,
  now,
  late,
  onChanged,
}: {
  feedback: ChatFeedback;
  now: number;
  /** Not the first thing in the panel: nothing waits on a person. */
  late: boolean;
  /** Read the chat and the list again. */
  onChanged: () => void;
}) {
  // The server's answer to the last action, shown at once until the chat is read again.
  const [latest, setLatest] = useState<FeedbackRow | null>(null);
  useEffect(() => setLatest(null), [feedback]);
  const view: ChatFeedback = latest && latest.id === feedback.id ? { ...feedback, ...latest } : feedback;

  const waiting = view.rating === "unhappy" && view.step === "support" && view.needs_follow_up;
  const resolved = view.resolved_at && !view.needs_follow_up ? { by: view.resolved_by_name, at: view.resolved_at } : null;
  const history = view.history ?? [];
  const note = feedbackStateNote(view.state);

  function done(updated: FeedbackRow) {
    setLatest(updated);
    onChanged();
  }

  return (
    <section
      className={late ? "inbox-fb-block inbox-fb-block--late" : "inbox-fb-block"}
      aria-labelledby="inbox-feedback-title"
    >
      <h3 id="inbox-feedback-title">Feedback</h3>
      {view.is_test && (
        <p className="inbox-order__hint">
          <span className="inbox-status inbox-status--plain">Test</span> Sent from Settings to try the
          questions. Not counted.
        </p>
      )}
      <dl>
        <dt>Order</dt>
        <dd className="num">{view.order_name ?? "—"}</dd>
        <dt>Asked</dt>
        <dd className="num">{view.asked_at ? dayTimeLabel(view.asked_at, now) : "—"}</dd>
        <dt>Answer</dt>
        <dd>
          {view.rating ? (
            <span
              className={`inbox-status inbox-status--${
                view.rating === "loved" ? "settled" : view.rating === "unhappy" ? "refused" : "plain"
              }`}
            >
              {RATING_WORDS[view.rating]}
            </span>
          ) : (
            <span className="ops-muted">No answer yet</span>
          )}
        </dd>
        {view.reason_title && (
          <>
            <dt>Reason</dt>
            <dd>{view.reason_title}</dd>
          </>
        )}
        {view.comment && (
          <>
            <dt>She wrote</dt>
            <dd className="inbox-fb-block__said" dir="auto">
              {view.comment}
            </dd>
          </>
        )}
        {view.reorder && (
          <>
            <dt>Order again</dt>
            <dd>{REORDER_WORDS[view.reorder]}</dd>
          </>
        )}
        {view.code && (
          <>
            <dt>Reward code</dt>
            <dd>
              <span className="num">{view.code}</span> · {view.code_used ? "used" : "not used yet"}
            </dd>
          </>
        )}
      </dl>

      {waiting && view.reply_hours > 0 && view.waiting_since && (
        <p className="inbox-order__why">
          <WaitingClock since={view.waiting_since} hours={view.reply_hours} now={now} />
        </p>
      )}
      {waiting && (
        <p className="inbox-order__hint">
          <span className="inbox-status inbox-status--owed">Needs follow-up</span>
        </p>
      )}
      {view.reopened_count > 0 && (
        <p className="inbox-order__why">
          Reopened: she said her issue was not solved
          {view.reopened_count > 1 ? ` (${view.reopened_count} times)` : ""}.
        </p>
      )}
      {resolved && <p className="inbox-order__why">{resolvedWords(resolved.by, resolved.at)}.</p>}
      {view.unreached_at && !waiting && (
        <p className="inbox-order__why">{unreachedWords(view.unreached_by_name, view.unreached_at)}.</p>
      )}
      {view.solved !== null && (
        <p className="inbox-order__why">Solved: {view.solved ? "yes" : "no"}</p>
      )}
      {note && <p className="inbox-order__hint">{note}.</p>}
      {/* The platform's own sentence ("The question … could not be sent: …"), so nothing is put in front of it. */}
      {view.last_error && <p className="inbox-order__hint">{view.last_error}</p>}

      {history.length > 0 && (
        <>
          <h4 className="inbox-fu-heading">Follow-up</h4>
          <FollowUpHistory entries={history} />
        </>
      )}
      {waiting && (
        <FollowUpActions
          survey={{
            id: view.id,
            order_name: view.order_name,
            rating: view.rating,
            reason_title: view.reason_title,
            no_answer_count: view.no_answer_count ?? 0,
            message_sent: view.message_sent ?? false,
            reopened_count: view.reopened_count,
            tried_to_call_text: view.tried_to_call_text ?? null,
            // An administrator's test is sent even with the switch off.
            feedback_off: view.enabled === false && !view.is_test,
          }}
          onDone={done}
        />
      )}
    </section>
  );
}
