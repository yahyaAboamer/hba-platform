import { useState } from "react";

import { RATING_WORDS, REORDER_WORDS, feedbackStateNote, formatPhone } from "../../lib/inbox";
import type { FeedbackOptions, FeedbackRow, FollowUpEntry } from "../../lib/inbox";
import { clockTime, dayMonth } from "../../components/OpsSource";

/**
 * The Feedback sheet's rows (ADR 0083 decision 6, ADR 0088): seven columns on
 * a wide screen, a card each on a phone, in the same order. The pieces that
 * say what a row is (answer, customer, comment) are shared with the
 * *To follow up* list.
 */

/** A comment longer than this can be opened out; every one carries its full text as a tooltip. */
const LONG_COMMENT = 60;

function titleCase(id: string): string {
  const words = id.replace(/_/g, " ");
  return `${words.charAt(0).toUpperCase()}${words.slice(1)}`;
}

/** The reason's name from the menu the server sends, or the id made readable. */
export function reasonTitle(row: Pick<FeedbackRow, "reason" | "rating">, options: FeedbackOptions | null): string | null {
  if (!row.reason) return null;
  const menu = row.rating ? options?.reasons[row.rating] : undefined;
  return menu?.find((choice) => choice.id === row.reason)?.title ?? titleCase(row.reason);
}

/** A quiet note on a question that did not go as it should have. */
function problemNote(row: FeedbackRow): string | null {
  // "Not on WhatsApp" already says it; the stored reason only repeats it.
  const why = row.state === "no_whatsapp" ? null : row.last_error;
  const words = [feedbackStateNote(row.state), why].filter(Boolean);
  return words.length ? words.join(": ") : null;
}

const askedOf = (row: FeedbackRow) => row.asked_at ?? row.sent_at;

export function AnswerChip({ row }: { row: Pick<FeedbackRow, "rating"> }) {
  if (!row.rating) return <span className="ops-muted">No answer yet</span>;
  const tone = row.rating === "loved" ? "settled" : row.rating === "unhappy" ? "refused" : "plain";
  return <span className={`inbox-status inbox-status--${tone}`}>{RATING_WORDS[row.rating]}</span>;
}

/**
 * What she wrote: two lines, the whole of it on a tap and as a tooltip. It is
 * her own words, in any script, so each line reads in its own direction.
 * `order` says whose comment the button opens, for a screen reader that hears
 * every one of them in turn.
 */
export function Comment({ text, order, empty = "—" }: { text: string | null; order?: string | null; empty?: string }) {
  const [open, setOpen] = useState(false);
  if (!text) return <span className="ops-muted">{empty}</span>;
  const whose = order ? ` of the comment on ${order}` : " of the comment";
  return (
    <>
      <span
        className={open ? "inbox-fb__comment inbox-fb__comment--open" : "inbox-fb__comment"}
        dir="auto"
        title={text}
      >
        {text}
      </span>
      {text.length > LONG_COMMENT && (
        <button
          type="button"
          className="ops-linkbtn inbox-fb__more"
          aria-expanded={open}
          aria-label={`${open ? "Show less" : "Show all"}${whose}`}
          onClick={() => setOpen(!open)}
        >
          {open ? "Show less" : "Show all"}
        </button>
      )}
    </>
  );
}

// ── The cells ──────────────────────────────────────────────────────────────

function Asked({ row }: { row: FeedbackRow }) {
  const at = askedOf(row);
  const note = problemNote(row);
  return (
    <>
      {at ? (
        <>
          <span className="num">{dayMonth(at)}</span>
          <span className="inbox-fb__line ops-muted num">{clockTime(at)}</span>
        </>
      ) : (
        <span className="num">—</span>
      )}
      {note && <span className="inbox-fb__line inbox-fb__note">{note}</span>}
    </>
  );
}

function Customer({ row }: { row: FeedbackRow }) {
  return (
    <>
      <span className="inbox-fb__name" dir="auto">
        {row.customer_name?.trim() || <span className="ops-muted">No name</span>}
      </span>
      <span className="inbox-fb__line ops-muted num">{formatPhone(row.phone) || "—"}</span>
    </>
  );
}

function OrderCell({ row }: { row: FeedbackRow }) {
  const what = [row.products.join(", "), row.courier].filter(Boolean).join(" · ");
  return (
    <>
      <span className="num inbox-fb__nowrap">{row.order_name ?? row.order_id}</span>
      {what && (
        <span className="inbox-fb__line inbox-fb__products ops-muted" dir="auto" title={what}>
          {what}
        </span>
      )}
    </>
  );
}

function AnswerCell({ row, options }: { row: FeedbackRow; options: FeedbackOptions | null }) {
  const reason = reasonTitle(row, options);
  return (
    <>
      <AnswerChip row={row} />
      {reason && <span className="inbox-fb__line">{reason}</span>}
      {row.reorder && <span className="inbox-fb__line ops-muted">Order again: {REORDER_WORDS[row.reorder]}</span>}
    </>
  );
}

/** The kinds whose note is a person's own words. */
const NOTED = new Set(["no_answer", "note", "resolved", "unreached"]);

function latestNote(history: FollowUpEntry[], round?: number): FollowUpEntry | null {
  for (let at = history.length - 1; at >= 0; at -= 1) {
    const entry = history[at];
    if (round !== undefined && entry.round !== round) continue;
    if (entry.note && NOTED.has(entry.kind)) return entry;
  }
  return null;
}

const calls = (count: number) => `${count} ${count === 1 ? "call" : "calls"}, no answer`;

/** Where the follow-up stands: a chip and one line under it, or nothing. */
export function followUpOf(row: FeedbackRow): { chip: string; tone: string; line: string | null } | null {
  const history = row.history ?? [];
  const noAnswers = row.no_answer_count ?? 0;
  const reopened = row.reopened_count > 0 ? `Reopened ${row.reopened_count}×` : null;
  const join = (...parts: (string | null)[]) => parts.filter(Boolean).join(" · ") || null;
  const state = row.follow_up_state ?? (row.needs_follow_up ? "needs_follow_up" : row.resolved_at ? "resolved" : null);

  if (state === "needs_follow_up") {
    let line: string;
    const note = latestNote(history, row.follow_up_round);
    if (noAnswers > 0) line = join(calls(noAnswers), row.message_sent ? "WhatsApp sent" : null)!;
    else if (note) line = `"${note.note}"`;
    else line = "Not called yet";
    return { chip: "To follow up", tone: "owed", line: join(line, reopened) };
  }
  if (state === "unreached") {
    const by = row.unreached_by_name ? `closed by ${row.unreached_by_name}` : "closed";
    return { chip: "Couldn't reach", tone: "plain", line: join(noAnswers > 0 ? calls(noAnswers) : null, by) };
  }
  if (state === "resolved") {
    const note = latestNote(history);
    const said = note ? join(note.by_name, `"${note.note}"`) : row.resolved_by_name ? `by ${row.resolved_by_name}` : null;
    const solved = row.solved === null ? null : row.solved ? "solved" : "not solved";
    return { chip: "Resolved", tone: "settled", line: join(said, solved, reopened) };
  }
  if (reopened) return { chip: "Reopened", tone: "plain", line: null };
  return null;
}

function FollowUpCell({ row }: { row: FeedbackRow }) {
  const where = followUpOf(row);
  if (!where) return <span className="ops-muted">—</span>;
  return (
    <>
      <span className={`inbox-status inbox-status--${where.tone}`}>{where.chip}</span>
      {where.line && (
        <span className="inbox-fb__line inbox-fb__fuline" dir="auto">
          {where.line}
        </span>
      )}
    </>
  );
}

function Code({ row }: { row: FeedbackRow }) {
  if (!row.code) return <span className="ops-muted">—</span>;
  return (
    <>
      <span className="num inbox-fb__code">{row.code}</span>
      <span className="inbox-fb__line ops-muted">
        {row.code_used_at ? (row.code_order_name ? `Used on ${row.code_order_name}` : "Used") : "Not used"}
      </span>
    </>
  );
}

// ── The sheet ──────────────────────────────────────────────────────────────

export function SheetTable({ rows, options }: { rows: FeedbackRow[]; options: FeedbackOptions | null }) {
  return (
    <div className="inbox-fb__scroll">
      <table className="ops-table inbox-fb__table">
        <caption className="visually-hidden">Answers to the delivery question, newest first</caption>
        <thead>
          <tr>
            <th scope="col">Asked</th>
            <th scope="col">Customer</th>
            <th scope="col">Order</th>
            <th scope="col">Answer</th>
            <th scope="col">What she said</th>
            <th scope="col">Follow-up</th>
            <th scope="col">Reward code</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.id}>
              <td className="inbox-fb__askedcell">
                <Asked row={row} />
              </td>
              <td>
                <Customer row={row} />
              </td>
              <td className="inbox-fb__ordercell">
                <OrderCell row={row} />
              </td>
              <td className="inbox-fb__answercell">
                <AnswerCell row={row} options={options} />
              </td>
              <td className="inbox-fb__commentcell">
                <Comment text={row.comment} order={row.order_name} />
              </td>
              <td className="inbox-fb__followcell">
                <FollowUpCell row={row} />
              </td>
              <td className="inbox-fb__nowrap">
                <Code row={row} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** On a phone each answer is a card, never a row to scroll sideways; the table's content, in its order. */
export function SheetCards({ rows, options }: { rows: FeedbackRow[]; options: FeedbackOptions | null }) {
  return (
    <ul className="ops-rows">
      {rows.map((row) => {
        const at = askedOf(row);
        const note = problemNote(row);
        const what = [row.products.join(", "), row.courier].filter(Boolean).join(" · ");
        return (
          <li key={row.id} className="inbox-fb__card">
            <div className="ops-rows__top">
              <span className="num">{row.order_name ?? row.order_id}</span>
              <span className="ops-muted num">{at ? `${dayMonth(at)}, ${clockTime(at)}` : "—"}</span>
            </div>
            <div className="inbox-fb__who">
              <Customer row={row} />
            </div>
            {what && (
              <div className="inbox-fb__block ops-muted" dir="auto">
                {what}
              </div>
            )}
            <div className="inbox-fb__said">
              <AnswerCell row={row} options={options} />
            </div>
            {row.comment && (
              <div className="inbox-fb__block">
                <Comment text={row.comment} order={row.order_name} />
              </div>
            )}
            {followUpOf(row) && (
              <div className="inbox-fb__block">
                <FollowUpCell row={row} />
              </div>
            )}
            {row.code && (
              <div className="inbox-fb__block">
                <Code row={row} />
              </div>
            )}
            {note && <span className="inbox-fb__line inbox-fb__note">{note}</span>}
          </li>
        );
      })}
    </ul>
  );
}
