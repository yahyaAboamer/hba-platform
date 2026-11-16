import { useCallback, useEffect, useId, useMemo, useRef, useState } from "react";

import { api, can } from "../../../lib/api";
import type { Session } from "../../../lib/api";
import type { Powers } from "./logic";
import { TaskForm } from "./TaskForm";
import { deleteButtonId, NarrowRow, WideRow } from "./TaskRows";
import type { RowActions } from "./TaskRows";
import { EMPTY_WORDS, FILTER_LABELS, FILTERS, GROUP_LABELS, groupTasks, summarySentence } from "./taskLogic";
import type { Filter } from "./taskLogic";
import type { ManualTask, OrderRow, TaskList } from "./types";
import { Problem, useIsNarrow } from "./ui";

/** The form is open for a new task (`task: null`) or for one being changed. */
type FormState = { task: ManualTask | null };

/** `/production/tasks`: every piece of work Production has open, from the orders and by hand. */
export function TaskScreen({ session }: { session: Session }) {
  const powers = useMemo<Powers>(
    () => ({ canEdit: can(session, "production.edit"), isOwner: can(session, "production.owner") }),
    [session],
  );
  const narrow = useIsNarrow();

  const [data, setData] = useState<TaskList | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState<Filter>("all");
  const [showDone, setShowDone] = useState(false);
  const [form, setForm] = useState<FormState | null>(null);
  const [orders, setOrders] = useState<OrderRow[] | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [confirming, setConfirming] = useState<string | null>(null);
  const heading = useRef<HTMLHeadingElement>(null);
  const trigger = useRef<Element | null>(null);
  // Which answer is the newest, and whether the screen is still there: an answer that an earlier
  // request delivers late, or one for a screen that has been left, is dropped.
  const latest = useRef(0);
  const alive = useRef(true);
  const doneToggle = useId();

  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
      latest.current += 1;
    };
  }, []);

  const load = useCallback(() => {
    const mine = ++latest.current;
    (showDone ? api.get<TaskList>("/api/prod/tasks?done=1") : api.get<TaskList>("/api/prod/tasks"))
      .then((answer) => {
        if (latest.current !== mine) return;
        setData(answer);
        setError(null);
      })
      .catch((caught) => {
        if (latest.current === mine) setError(caught instanceof Error ? caught.message : "The tasks could not be loaded.");
      });
  }, [showDone]);
  useEffect(load, [load]);

  // The orders to choose from, read the first time the form opens.
  useEffect(() => {
    if (!form || orders !== null) return;
    let current = true;
    api.get<{ orders: OrderRow[] }>("/api/prod/orders?status=open")
      .then((answer) => current && setOrders(answer.orders))
      .catch(() => current && setOrders([])); // the task can still be added without an order
    return () => {
      current = false;
    };
  }, [form, orders]);

  function openForm(task: ManualTask | null, from: Element | null) {
    trigger.current = from;
    setNotice(null);
    setProblem(null);
    setForm({ task });
  }

  function closeForm() {
    setForm(null);
    queueMicrotask(() => {
      const back = trigger.current;
      if (back instanceof HTMLElement && back.isConnected) back.focus();
      else heading.current?.focus();
    });
  }

  async function write(task: ManualTask, request: () => Promise<unknown>, done: string) {
    setBusy(task.key);
    setProblem(null);
    setNotice(null);
    try {
      await request();
      if (!alive.current) return;
      setNotice(done);
      setConfirming(null);
      load();
      // The row the person pressed has moved or gone: focus goes to the heading, and the notice is read.
      heading.current?.focus();
    } catch (caught) {
      if (alive.current) setProblem(caught instanceof Error ? caught.message : "It could not be saved.");
    } finally {
      if (alive.current) setBusy(null);
    }
  }

  const actions: RowActions = {
    onDone: (task) => void write(task, () => api.patch(`/api/prod/tasks/${task.id}`, { done: true }), `Marked done: ${task.title}`),
    onReopen: (task) => void write(task, () => api.patch(`/api/prod/tasks/${task.id}`, { done: false }), `Reopened: ${task.title}`),
    onEdit: (task, from) => openForm(task, from),
    onAskDelete: (task) => {
      setProblem(null);
      setConfirming(task.key);
    },
    onKeep: (task) => {
      setConfirming(null);
      queueMicrotask(() => document.getElementById(deleteButtonId(task))?.focus());
    },
    onDelete: (task) => void write(task, () => api.del(`/api/prod/tasks/${task.id}`), `Deleted: ${task.title}`),
  };

  function saved(task: ManualTask, added: boolean) {
    setForm(null);
    setNotice(added ? `Added: ${task.title}` : `Saved: ${task.title}`);
    load();
    queueMicrotask(() => {
      const back = trigger.current;
      if (back instanceof HTMLElement && back.isConnected) back.focus();
      else heading.current?.focus();
    });
  }

  const Row = narrow ? NarrowRow : WideRow;
  const groups = data ? groupTasks(data.tasks, filter) : [];

  return (
    <>
      <div className="page__head">
        <div className="page__title">
          <h1 ref={heading} tabIndex={-1}>Tasks</h1>
          <span className="page__subtitle">{data ? summarySentence(data.counts, data.tasks, data.today) : "Loading"}</span>
        </div>
        {powers.canEdit && (
          <div className="prod-head-actions">
            <button type="button" className="button button--primary" onClick={(event) => openForm(null, event.currentTarget)}>
              Add task
            </button>
          </div>
        )}
      </div>

      {notice && <p className="notice notice--settled" role="status">{notice}</p>}
      {problem && <Problem>{problem}</Problem>}

      {form && (
        <TaskForm
          key={form.task ? `edit-${form.task.id}` : "add"}
          task={form.task}
          orders={orders}
          onSaved={saved}
          onClose={closeForm}
        />
      )}

      {error && (
        <div>
          <Problem>{error}</Problem>
          <button type="button" className="button" onClick={load}>
            Try again
          </button>
        </div>
      )}

      {!error && data === null && <p className="loading" role="status">Loading tasks…</p>}

      {data && (
        <>
          <div className="prod-chips" role="group" aria-label="Show">
            {FILTERS.map((key) => (
              <button
                key={key}
                type="button"
                className={`chip${filter === key ? " chip--on" : ""}`}
                aria-pressed={filter === key}
                onClick={() => setFilter(key)}
              >
                {FILTER_LABELS[key]} · {data.counts[key]}
              </button>
            ))}
          </div>
          <label className="prod-check" htmlFor={doneToggle}>
            <input id={doneToggle} type="checkbox" checked={showDone} onChange={(event) => setShowDone(event.target.checked)} />
            Show tasks done in the last 14 days
          </label>

          {groups.length === 0 ? (
            <p className="empty">{EMPTY_WORDS[filter]}</p>
          ) : (
            groups.map(({ group, tasks }) => (
              <section key={group} aria-labelledby={`prod-group-${group}`}>
                <h2 id={`prod-group-${group}`} className={`prod-group${group === "overdue" ? " prod-group--late" : ""}`}>
                  {GROUP_LABELS[group]}
                </h2>
                <ul className="surface prod-tasks">
                  {tasks.map((task) => (
                    <Row
                      key={task.key}
                      task={task}
                      today={data.today}
                      powers={powers}
                      busy={busy === task.key}
                      confirming={confirming === task.key}
                      actions={actions}
                    />
                  ))}
                </ul>
              </section>
            ))
          )}
        </>
      )}
    </>
  );
}
