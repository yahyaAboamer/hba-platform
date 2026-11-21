import type { Ref } from "react";
import { Link } from "react-router-dom";

import { formatPhone } from "../../lib/inbox";
import type { FeedbackOptions, FeedbackRow } from "../../lib/inbox";
import { AnswerChip, Comment, reasonTitle } from "./FeedbackSheet";
import { FollowUpActions, FollowUpHistory, WaitingClock, waitingWords } from "./FollowUp";

/**
 * *To follow up* (ADR 0087): every unhappy answer still waiting on a person,
 * longest-waiting first. It ignores the sheet's filters, because nobody
 * waiting may fall outside one, and it is not drawn at all when nobody waits.
 */
export function FollowUpList({
  rows,
  hours,
  options,
  now,
  headingRef,
  onChanged,
  feedbackOff = false,
}: {
  rows: FeedbackRow[];
  /** The promised hours (Feedback setup). */
  hours: number;
  options: FeedbackOptions | null;
  now: number;
  headingRef: Ref<HTMLHeadingElement>;
  /** Something was recorded: read the list, the cards and the sheet again. */
  onChanged: () => void;
  /** Feedback messages are switched off: the pop-ups promise nothing. */
  feedbackOff?: boolean;
}) {
  if (rows.length === 0) return null;
  return (
    <section className="panel inbox-fbq" aria-labelledby="inbox-fbq-title">
      <div className="inbox-fbq__head">
        <h2 id="inbox-fbq-title" ref={headingRef} tabIndex={-1}>
          To follow up{" "}
          <span className="inbox-status inbox-status--owed num">{rows.length.toLocaleString("en-US")}</span>
        </h2>
        <span className="inbox-fbq__order">Longest-waiting first</span>
      </div>
      <ul className="inbox-fbq__list">
        {rows.map((row) => {
          const late = row.waiting_since ? waitingWords(row.waiting_since, hours, now).late : false;
          const reason = reasonTitle(row, options);
          const order = row.order_name ?? row.order_id;
          const name = row.customer_name?.trim() || null;
          const chat = row.conversation_id
            ? `/inbox/chats/${row.conversation_id}?view=follow_up`
            : "/inbox/chats?view=follow_up";
          return (
            <li key={row.id} className={late ? "inbox-fbq__card inbox-fbq__card--late" : "inbox-fbq__card"}>
              <div className="inbox-fbq__who">
                <span className="inbox-fbq__name" dir="auto">
                  {name ?? <span className="ops-muted">No name</span>}
                </span>
                <span className="inbox-fbq__meta num">
                  {[formatPhone(row.phone), order].filter(Boolean).join(" · ")}
                </span>
                <WaitingClock since={row.waiting_since} hours={hours} now={now} />
              </div>
              <div className="inbox-fbq__said">
                <div className="inbox-fbq__answer">
                  <AnswerChip row={row} />
                  {reason && <span>{reason}</span>}
                </div>
                <div className="inbox-fbq__words">
                  <Comment text={row.comment} order={row.order_name} empty="No comment written" />
                </div>
              </div>
              <div className="inbox-fbq__history">
                {row.history.length > 0 ? (
                  <FollowUpHistory entries={row.history} />
                ) : (
                  <span className="ops-muted">Not called yet</span>
                )}
              </div>
              <div className="inbox-fbq__acts">
                <FollowUpActions
                  survey={{
                    id: row.id,
                    order_name: row.order_name,
                    customer_name: name,
                    rating: row.rating,
                    reason_title: reason,
                    no_answer_count: row.no_answer_count,
                    message_sent: row.message_sent,
                    reopened_count: row.reopened_count,
                    tried_to_call_text: row.tried_to_call_text ?? null,
                    feedback_off: feedbackOff,
                  }}
                  onDone={onChanged}
                />
                <Link className="inbox-btn inbox-btn--small inbox-btn--quiet" to={chat}>
                  Open chat<span className="visually-hidden"> with {name ?? order}</span>
                </Link>
              </div>
            </li>
          );
        })}
      </ul>
    </section>
  );
}
