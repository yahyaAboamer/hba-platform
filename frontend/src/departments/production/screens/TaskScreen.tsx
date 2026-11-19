import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { api, can } from "../../../lib/api";
import type { Session } from "../../../lib/api";
import type { Powers } from "./logic";
import { TaskForm } from "./TaskForm";
import { deleteButtonId, NarrowRow, WideRow } from "./TaskRows";
import type { RowActions } from "./TaskRows";
import { TaskUpdateForm } from "./TaskUpdateForm";
import { FILTER_LABELS, FILTERS, GROUP_LABELS, doneSentence, emptyWords, groupTasks, rangeProblem, summarySentence, tasksQuery } from "./taskLogic";
import type { Filter, Range } from "./taskLogic";
import type { ManualTask, OrderRow, TaskList, TaskView } from "./types";
import { DateBox, Problem, useIsNarrow } from "./ui";

/** The form is open for a new task (`task: null`), for one being changed, or for an update to one. */
type FormState = { task: ManualTask | null; update?: boolean };

const NO_RANGE: Range = { from: "", to: "" };
const rangeKey = (range: Range): string => `${range.from}|${range.to}`;

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
  const [view, setView] = useState<TaskView>("open");
  const [range, setRange] = useState<Range>(NO_RANGE);
  // How many each tab holds, for the date range it was read with. The Done tab's number is known only once
  // that tab has been read (it is read when opened, not before), so until then it says "Done" alone.
  const [tabCounts, setTabCounts] = useState<Partial<Record<TaskView, { key: string; count: number }>>>({});
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

  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
      latest.current += 1;
    };
  }, []);

  const wrongWay = rangeProblem(range);
  const load = useCallback(() => {
    const mine = ++latest.current;
    // A range the wrong way round is said on the screen, and nothing is asked for.
    if (rangeProblem(range)) return;
    api.get<TaskList>(`/api/prod/tasks?${tasksQuery(view, range)}`)
      .then((answer) => {
        if (latest.current !== mine) return;
        setData(answer);
        setError(null);
        const count = view === "open" ? answer.counts.all : answer.tasks.length;
        setTabCounts((before) => ({ ...before, [view]: { key: rangeKey(range), count } }));
      })
      .catch((caught) => {
        if (latest.current === mine) setError(caught instanceof Error ? caught.message : "The tasks could not be loaded.");
      });
  }, [view, range]);
  useEffect(load, [load]);

  function switchView(next: TaskView) {
    if (next === view) return;
    setData(null);
    setError(null);
    setView(next);
  }

  /** After a write, what the other tab holds has changed too: its number is read again when it is opened. */
  const forgetCounts = () => setTabCounts({});

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

  function openForm(task: ManualTask | null, from: Element | null, update = false) {
    trigger.current = from;
    setNotice(null);
    setProblem(null);
    setForm({ task, update });
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
      forgetCounts();
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
    onUpdate: (task, from) => openForm(task, from, true),
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

  function saved(task: ManualTask, added: boolean, words?: string) {
    setForm(null);
    setNotice(words ?? (added ? `Added: ${task.title}` : `Saved: ${task.title}`));
    forgetCounts();
    load();
    queueMicrotask(() => {
      const back = trigger.current;
      if (back instanceof HTMLElement && back.isConnected) back.focus();
      else heading.current?.focus();
    });
  }

  const Row = narrow ? NarrowRow : WideRow;
  const shownFilter: Filter = view === "open" ? filter : "all";
  const groups = data ? groupTasks(data.tasks, shownFilter) : [];
  const key = rangeKey(range);
  const tabWords = (tab: TaskView): string => {
    const known = tabCounts[tab];
    const name = tab === "open" ? "Open" : "Done";
    return known && known.key === key ? `${name} · ${known.count}` : name;
  };
  const subtitle = !data ? "Loading" : view === "open" ? summarySentence(data.counts, data.tasks, data.today) : doneSentence(data.tasks.length);

  return (
    <>
      <div className="page__head">
        <div className="page__title">
          <h1 ref={heading} tabIndex={-1}>Tasks</h1>
          <span className="page__subtitle">{subtitle}</span>
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

      {form?.update && form.task && (
        <TaskUpdateForm
          key={`update-${form.task.id}`}
          task={form.task}
          onSaved={(task) => saved(task, false, `Update saved: ${task.title}`)}
          onClose={closeForm}
        />
      )}

      {form && !form.update && (
        <TaskForm
          key={form.task ? `edit-${form.task.id}` : "add"}
          task={form.task}
          orders={orders}
          onSaved={saved}
          onClose={closeForm}
        />
      )}

      <div className="prod-chips prod-tabs" role="group" aria-label="Which tasks">
        {(["open", "done"] as const).map((tab) => (
          <button
            key={tab}
            type="button"
            className={`chip${view === tab ? " chip--on" : ""}`}
            aria-pressed={view === tab}
            onClick={() => switchView(tab)}
          >
            {tabWords(tab)}
          </button>
        ))}
      </div>

      <div className="prod-sectionbar prod-range" role="group" aria-label={view === "open" ? "Deadline between" : "Marked done between"}>
        <DateBox label="From" value={range.from} max={range.to || undefined} onChange={(from) => setRange((before) => ({ ...before, from }))} />
        <DateBox label="To" value={range.to} min={range.from || undefined} onChange={(to) => setRange((before) => ({ ...before, to }))} />
        {(range.from || range.to) && (
          <button type="button" className="button button--row" onClick={() => setRange(NO_RANGE)}>
            Clear dates
          </button>
        )}
      </div>
      {wrongWay && <Problem>{wrongWay}</Problem>}

      {error && (
        <div>
          <Problem>{error}</Problem>
          <button type="button" className="button" onClick={load}>
            Try again
          </button>
        </div>
      )}

      {!error && !wrongWay && data === null && <p className="loading" role="status">Loading tasks…</p>}

      {data && !wrongWay && (
        <>
          {view === "open" && (
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
          )}

          {groups.length === 0 ? (
            <p className="empty">{emptyWords(view, shownFilter, range)}</p>
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
