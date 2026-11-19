import { useEffect, useId, useRef, useState } from "react";
import { Link } from "react-router-dom";

import { stamp, WHO } from "./format";
import type { Powers } from "./logic";
import { detailLine, dueWords, taskLink, updateLine } from "./taskLogic";
import type { ManualTask, Task } from "./types";

/** What a row can do to a hand-added task. */
export type RowActions = {
  onDone: (task: ManualTask) => void;
  onReopen: (task: ManualTask) => void;
  onEdit: (task: ManualTask, trigger: HTMLElement) => void;
  /** Open the Update panel for this task. */
  onUpdate: (task: ManualTask, trigger: HTMLElement) => void;
  onAskDelete: (task: ManualTask) => void;
  onKeep: (task: ManualTask) => void;
  onDelete: (task: ManualTask) => void;
};

type RowProps = {
  task: Task;
  today: string;
  powers: Powers;
  /** A write to this task is on its way. */
  busy: boolean;
  /** This task's Delete was pressed and is waiting for a yes. */
  confirming: boolean;
  actions: RowActions;
};

/** The id a row's Delete button carries, so focus can go back to it after "Keep it". */
export const deleteButtonId = (task: ManualTask): string => `prod-task-delete-${task.id}`;

function Confirm({ task, busy, actions }: { task: ManualTask; busy: boolean; actions: RowActions }) {
  const keep = useRef<HTMLButtonElement>(null);
  const question = useId();
  // Focus goes to the safe answer, and the question is read with it.
  useEffect(() => {
    keep.current?.focus();
  }, []);
  return (
    <>
      <span id={question}>Delete this task?</span>
      <button type="button" className="button button--row" disabled={busy} onClick={() => actions.onDelete(task)} aria-label={`Delete task: ${task.title}`}>
        Delete task
      </button>
      <button ref={keep} type="button" className="button button--row" aria-describedby={question} onClick={() => actions.onKeep(task)}>
        Keep it
      </button>
    </>
  );
}

/** A row's buttons: the form to go and fill in for a generated task; done, edit and delete for a hand-added one. */
function Buttons({ task, powers, busy, confirming, actions }: Omit<RowProps, "today">) {
  if (task.kind === "generated") {
    const link = taskLink(task, powers);
    return link ? (
      <Link className="button button--row" to={link.to} aria-label={`${link.label}: ${task.title}`}>
        {link.label}
      </Link>
    ) : null;
  }
  const page = task.order ? `/production/orders/${task.order.id}` : null;
  const openOrder = page ? (
    <Link className="button button--row" to={page} aria-label={`Open order: ${task.title}`}>
      Open order
    </Link>
  ) : null;
  if (!powers.canEdit) return openOrder;
  if (confirming) return <Confirm task={task} busy={busy} actions={actions} />;
  return (
    <>
      {task.done ? (
        <button type="button" className="button button--row" disabled={busy} onClick={() => actions.onReopen(task)} aria-label={`Reopen: ${task.title}`}>
          Reopen
        </button>
      ) : (
        <button type="button" className="button button--row" disabled={busy} onClick={() => actions.onDone(task)} aria-label={`Mark done: ${task.title}`}>
          Mark done
        </button>
      )}
      <button
        type="button"
        className="button button--row"
        disabled={busy}
        onClick={(event) => actions.onUpdate(task, event.currentTarget)}
        aria-label={`Update: ${task.title}`}
      >
        Update
      </button>
      {openOrder}
      {!task.done && (
        <button
          type="button"
          className="button button--row"
          disabled={busy}
          onClick={(event) => actions.onEdit(task, event.currentTarget)}
          aria-label={`Edit: ${task.title}`}
        >
          Edit
        </button>
      )}
      <button id={deleteButtonId(task)} type="button" className="button button--row" disabled={busy} onClick={() => actions.onAskDelete(task)} aria-label={`Delete: ${task.title}`}>
        Delete
      </button>
    </>
  );
}

/** Every update on a task, newest first, behind a button that says how many there are. */
function AllUpdates({ task }: { task: ManualTask }) {
  const [shown, setShown] = useState(false);
  const list = useId();
  const count = task.updates.length;
  if (count < 2) return null;
  return (
    <div className="prod-task__updates">
      <button
        type="button"
        className="button button--quiet prod-task__more"
        aria-expanded={shown}
        aria-controls={list}
        onClick={() => setShown(!shown)}
      >
        {shown ? "Hide updates" : `All updates (${count})`}
        <span className="prod-sr"> for {task.title}</span>
      </button>
      {shown && (
        <ol id={list} className="prod-history">
          {task.updates.map((update) => (
            <li key={update.id}>
              {update.text}
              {update.next_action && <div className="prod-small">Next action set to: {update.next_action}</div>}
              <time dateTime={update.created_at ?? undefined}>
                {update.created_by ? `${update.created_by} · ` : ""}
                {stamp(update.created_at)}
              </time>
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}

function Text({ task, today }: { task: Task; today: string }) {
  const detail = detailLine(task, today);
  const latest = task.kind === "manual" ? task.updates[0] : undefined;
  return (
    <>
      <b>{task.title}</b>
      {task.kind === "manual" && task.next_action && <div className="prod-task__next">Next: {task.next_action}</div>}
      {detail && <div className="prod-small">{detail}</div>}
      {latest && <div className="prod-small prod-task__note">{updateLine(latest)}</div>}
      {task.kind === "manual" && task.note && <div className="prod-small prod-task__note">{task.note}</div>}
      {task.kind === "manual" && <AllUpdates task={task} />}
    </>
  );
}

const lateClass = (task: Task): string | undefined => (task.group === "overdue" ? "prod-late" : undefined);

/** One task on a wide screen: what it is, then who, when and the button. */
export function WideRow(props: RowProps) {
  const { task, today } = props;
  const done = task.kind === "manual" && task.done;
  return (
    <li className={`prod-task${done ? " prod-task--done" : ""}`}>
      <div className="prod-task__what">
        <Text task={task} today={today} />
      </div>
      <div className="prod-task__side">
        <span>{WHO[task.who]}</span>
        <span className={lateClass(task)}>{dueWords(task)}</span>
        <Buttons {...props} />
      </div>
    </li>
  );
}

/** The same task on a phone: stacked, with the buttons below at a thumb's size. */
export function NarrowRow(props: RowProps) {
  const { task, today } = props;
  const done = task.kind === "manual" && task.done;
  return (
    <li className={`prod-task prod-task--narrow${done ? " prod-task--done" : ""}`}>
      <div>
        <Text task={task} today={today} />
      </div>
      <div className="prod-small">
        {WHO[task.who]} · <span className={lateClass(task)}>{dueWords(task)}</span>
      </div>
      <div className="prod-task__actions">
        <Buttons {...props} />
      </div>
    </li>
  );
}
