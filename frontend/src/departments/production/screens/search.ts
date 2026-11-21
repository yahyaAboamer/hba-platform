import type { OrderRow, Task } from "./types";

/**
 * The search boxes on Orders, Tasks and the Library (the owner, 21 November 2026). What is typed is
 * split into words; a row matches when every word appears somewhere in what the row is searched by,
 * in any case and in any order, so "black cutting" finds the black order that is at cutting.
 */
export function matches(fields: readonly (string | null | undefined)[], query: string): boolean {
  const wanted = query.toLocaleLowerCase().split(/\s+/).filter(Boolean);
  if (wanted.length === 0) return true;
  const text = fields.filter(Boolean).join("\n").toLocaleLowerCase();
  return wanted.every((word) => text.includes(word));
}

/** What an order is searched by. */
export const ORDER_SEARCH_HINT = "order no., style, colour or colour code, factory, print house, fabric, stage, notes";

/** An order is found by its number, style, colour and colour code, factory, print house, fabric, current stage and notes. */
export function orderMatches(row: OrderRow, query: string): boolean {
  return matches(
    [
      row.code,
      row.style_name,
      row.colour,
      row.colour_code,
      row.factory.name,
      row.print_supplier_name,
      row.fabric_type,
      row.stage?.label,
      row.notes,
    ],
    query,
  );
}

/** What a task is searched by. */
export const TASK_SEARCH_HINT = "task, note, next action, updates, supplier, the order's no., style or colour";

/** A task is found by its title, who it waits on, its order, and (typed-in tasks) its note, next action and updates. */
export function taskMatches(task: Task, query: string): boolean {
  const typed = task.kind === "manual" ? [task.note, task.next_action, ...task.updates.map((update) => update.text)] : [];
  return matches(
    [
      task.title,
      task.waiting_on,
      task.supplier?.name,
      task.order?.code,
      task.order?.style_name,
      task.order?.colour,
      ...typed,
    ],
    query,
  );
}

/**
 * The Overview's orders, most urgent first: late ones (latest first), then those waiting for the owner,
 * then the rest in the order they came (nearest delivery date first).
 */
export function byUrgency(rows: readonly OrderRow[]): OrderRow[] {
  const rank = (row: OrderRow) => (row.flags.late ? 0 : row.flags.waiting_for_owner ? 1 : 2);
  return rows
    .map((row, index) => ({ row, index }))
    .sort(
      (a, b) =>
        rank(a.row) - rank(b.row) ||
        (rank(a.row) === 0 ? b.row.lateness_days - a.row.lateness_days : 0) ||
        a.index - b.index,
    )
    .map(({ row }) => row);
}
