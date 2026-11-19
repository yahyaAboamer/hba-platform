import { useState } from "react";
import type { FormEvent } from "react";

import { api } from "../../../lib/api";
import type { ManualTask, TaskAnswer } from "./types";
import { Actions, PanelShell, TextBox } from "./ui";

/**
 * Add an update to a hand-added task: what happened (required) and the next action, which starts as the
 * task's current one. The next action is sent only when it was changed, so an update that leaves it alone
 * does not rewrite it; emptied, it is cleared.
 */
export function TaskUpdateForm({
  task,
  onSaved,
  onClose,
}: {
  task: ManualTask;
  onSaved: (task: ManualTask) => void;
  onClose: () => void;
}) {
  const [text, setText] = useState("");
  const [next, setNext] = useState(task.next_action ?? "");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function save(event: FormEvent) {
    event.preventDefault();
    if (busy) return;
    if (!text.trim()) {
      setError("Say what happened.");
      return;
    }
    const nextAction = next.trim() || null;
    const body: { text: string; next_action?: string | null } = { text: text.trim() };
    if (nextAction !== (task.next_action ?? null)) body.next_action = nextAction;
    setError(null);
    setBusy(true);
    try {
      const answer = await api.post<TaskAnswer>(`/api/prod/tasks/${task.id}/updates`, body);
      onSaved(answer.task);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "The update could not be saved.");
      setBusy(false);
    }
  }

  return (
    <PanelShell title={`Update: ${task.title}`} onClose={onClose}>
      <form className="prod-form" onSubmit={save} noValidate>
        <TextBox label="What happened" value={text} onChange={setText} area max={2000} wide />
        <TextBox label="Next action" hint="Leave it as it is, change it, or empty it." value={next} onChange={setNext} max={500} wide />
        <Actions error={error} busy={busy} label="Save update" working="Saving…" />
      </form>
    </PanelShell>
  );
}
