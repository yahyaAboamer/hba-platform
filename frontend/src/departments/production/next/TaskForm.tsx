import { useId, useState } from "react";
import type { FormEvent } from "react";

import { api } from "../../../lib/api";
import type { ManualTask, TaskAnswer, TaskOrder } from "./types";
import { Actions, DateBox, PanelShell, TextBox } from "./ui";

/** What the server sends for a hand-added task (`NewTask`, `TaskEdit`). */
type Body = { title: string; due_on: string | null; order_id: number | null; note: string | null; for_owner: boolean };

/**
 * Add a task by hand, or change one (`task`). The server checks every rule again: this only says the
 * obvious one (a title) before sending, and shows the server's own words when it refuses.
 */
export function TaskForm({
  task,
  orders,
  onSaved,
  onClose,
}: {
  task: ManualTask | null;
  /** The orders still in production; `null` while they load. */
  orders: TaskOrder[] | null;
  onSaved: (task: ManualTask, added: boolean) => void;
  onClose: () => void;
}) {
  const id = useId();
  const [title, setTitle] = useState(task?.title ?? "");
  const [due, setDue] = useState(task?.due ?? "");
  const [orderId, setOrderId] = useState(task?.order ? String(task.order.id) : "");
  const [note, setNote] = useState(task?.note ?? "");
  const [forOwner, setForOwner] = useState(task?.for_owner ?? false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  // A task already on an order that has since closed keeps that order in the list.
  const choices: TaskOrder[] = [...(orders ?? [])];
  if (task?.order && !choices.some((order) => order.id === task.order?.id)) choices.unshift(task.order);

  async function save(event: FormEvent) {
    event.preventDefault();
    if (!title.trim()) {
      setError("Give the task's title.");
      return;
    }
    const body: Body = {
      title: title.trim(),
      due_on: due || null,
      order_id: orderId ? Number(orderId) : null,
      note: note.trim() || null,
      for_owner: forOwner,
    };
    setError(null);
    setBusy(true);
    try {
      const answer = task
        ? await api.patch<TaskAnswer>(`/api/prod/tasks/${task.id}`, body)
        : await api.post<TaskAnswer>("/api/prod/tasks", body);
      onSaved(answer.task, task === null);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "The task could not be saved.");
      setBusy(false);
    }
  }

  return (
    <PanelShell title={task ? "Edit task" : "Add task"} onClose={onClose}>
      <form className="prod-form" onSubmit={save} noValidate>
        <TextBox label="Task" value={title} onChange={setTitle} max={200} wide />
        <DateBox label="Date (optional)" value={due} onChange={setDue} />
        <div className="prod-field">
          <label className="field__label" htmlFor={`${id}-order`}>
            Order (optional)
          </label>
          <select id={`${id}-order`} className="input" value={orderId} onChange={(event) => setOrderId(event.target.value)}>
            <option value="">{orders === null ? "Loading orders…" : "No order"}</option>
            {choices.map((order) => (
              <option key={order.id} value={order.id}>
                {order.style_name} · {order.colour} · {order.code}
              </option>
            ))}
          </select>
        </div>
        <TextBox label="Note (optional)" value={note} onChange={setNote} area max={2000} wide />
        <label className="prod-check prod-wide">
          <input type="checkbox" checked={forOwner} onChange={(event) => setForOwner(event.target.checked)} />
          For the owner
        </label>
        <Actions error={error} busy={busy} label={task ? "Save task" : "Add task"} working="Saving…" />
      </form>
    </PanelShell>
  );
}
