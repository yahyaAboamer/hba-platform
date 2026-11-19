/**
 * What the Tasks screen decides, kept apart from the screen so each rule can be tested on its own:
 * the filters and groups, the words on a row, and which button a person gets for a task.
 *
 * The server groups and counts (`services/tasks.py`); nothing here recomputes a date against today.
 */
import { cairoDay, daysBetween, plural, shortDay, weekdayOf } from "./format";
import type { Powers } from "./logic";
import type { GeneratedTask, ManualTask, Task, TaskCounts, TaskGroup, TaskUpdate, TaskView } from "./types";

// ── Filters and groups ───────────────────────────────────────────────────────

export type Filter = "all" | "overdue" | "qc" | "owner" | "factory";

export const FILTERS: readonly Filter[] = ["all", "overdue", "qc", "owner", "factory"];

export const FILTER_LABELS: Record<Filter, string> = {
  all: "Everything",
  overdue: "Overdue",
  qc: "QC manager",
  owner: "Owner",
  factory: "Waiting on suppliers",
};

export const GROUP_LABELS: Record<TaskGroup, string> = {
  overdue: "Overdue",
  today: "Today",
  week: "This week",
  later: "Later",
  done: "Done",
};

export const EMPTY_WORDS: Record<Filter, string> = {
  all: "Nothing to do right now.",
  overdue: "Nothing is overdue.",
  qc: "Nothing is waiting on the QC manager.",
  owner: "Nothing is waiting on the owner.",
  factory: "Nothing is waiting on a supplier.",
};

const GROUP_ORDER: readonly TaskGroup[] = ["overdue", "today", "week", "later", "done"];

export function matchesFilter(task: Task, filter: Filter): boolean {
  switch (filter) {
    case "all":
      return true;
    case "overdue":
      return task.group === "overdue";
    default:
      return task.who === filter;
  }
}

/** The tasks a filter shows, in the groups the server put them in, leaving out a group with none. */
export function groupTasks(tasks: readonly Task[], filter: Filter): { group: TaskGroup; tasks: Task[] }[] {
  const shown = tasks.filter((task) => matchesFilter(task, filter));
  return GROUP_ORDER.map((group) => ({ group, tasks: shown.filter((task) => task.group === group) })).filter(
    (entry) => entry.tasks.length > 0,
  );
}

/** "10 open · 3 overdue · 2 for today, Friday 13 Nov". */
export function summarySentence(counts: TaskCounts, tasks: readonly Task[], today: string): string {
  const forToday = tasks.filter((task) => task.group === "today").length;
  const parts = [`${counts.all} open`];
  if (counts.overdue) parts.push(`${counts.overdue} overdue`);
  parts.push(`${forToday} for today, ${weekdayOf(today)} ${shortDay(today)}`);
  return parts.join(" · ");
}

/** "4 done", for the Done tab. */
export const doneSentence = (count: number): string => `${count} done`;

// ── The list's address ───────────────────────────────────────────────────────

/** The date range a person picked; either end may be empty. */
export type Range = { from: string; to: string };

/** The refusal for a range the wrong way round, before anything is sent; `null` when it reads. */
export function rangeProblem(range: Range): string | null {
  return range.from && range.to && range.from > range.to ? "The From date is after the To date." : null;
}

/** `/api/prod/tasks?view=open&from=…&to=…`: the bounds the person gave, nothing for an empty one. */
export function tasksAddress(view: TaskView, range: Range): string {
  return `/api/prod/tasks?${tasksQuery(view, range)}`;
}

/** `view=open&from=…&to=…`: the query part of `tasksAddress`. */
export function tasksQuery(view: TaskView, range: Range): string {
  const query = new URLSearchParams({ view });
  if (range.from) query.set("from", range.from);
  if (range.to) query.set("to", range.to);
  return query.toString();
}

/** What the empty list says on the Done tab, or on the Open tab with a date range. */
export function emptyWords(view: TaskView, filter: Filter, range: Range): string {
  const ranged = Boolean(range.from || range.to);
  if (view === "done") return ranged ? "No tasks were marked done in these dates." : "No tasks have been marked done yet.";
  if (ranged && filter === "all") return "Nothing is due in these dates. Tasks with no deadline are left out while dates are set.";
  return EMPTY_WORDS[filter];
}

// ── The words on a row ───────────────────────────────────────────────────────

/** "Zip hoodie · Olive · PO-2611-03". */
export const orderName = (task: Task): string | null =>
  task.order ? `${task.order.style_name} · ${task.order.colour} · ${task.order.code}` : null;

/** The deadline, and how late when it is past: "Due 10 Nov · 3 days", "No deadline". */
export function dueWords(task: Task): string {
  if (task.kind === "manual" && task.done) return `Done ${shortDay(cairoDay(task.done_at))}`;
  if (!task.due) return "No deadline";
  if (task.group === "overdue") return `Due ${shortDay(task.due)} · ${plural(task.overdue_days, "day")}`;
  // The factory finishes making around its promised date; nobody can say the day.
  return task.stage === "making" ? `Due around ${shortDay(task.due)}` : `Due ${shortDay(task.due)}`;
}

/** Who it is waiting on, and for how long: "waiting on Main factory for 3 days", "waiting 3 days". */
export function waitingWords(task: Task, today: string): string | null {
  if (task.kind !== "generated") return null;
  const days = task.since ? Math.max(0, daysBetween(task.since, today)) : 0;
  const for_ = days > 0 ? plural(days, "day") : null;
  if (task.who === "factory") return task.waiting_on ? `waiting on ${task.waiting_on}${for_ ? ` for ${for_}` : ""}` : null;
  if (task.who === "owner" && for_) return `waiting ${for_}`;
  return null;
}

/** What goes under a task's title, before its note: the order, who it waits on, or that it was added by hand. */
export function detailLine(task: Task, today: string): string {
  const parts: string[] = [];
  const name = orderName(task);
  if (name) parts.push(name);
  const waiting = waitingWords(task, today);
  if (waiting) parts.push(waiting);
  if (task.kind === "manual") parts.push(name ? "Added by hand" : "Added by hand · no order");
  return parts.join(" · ");
}

// ── Which button ─────────────────────────────────────────────────────────────

/** What each form is called on a task's button. */
const FORM_WORDS: Record<string, string> = {
  sample: "Review sample",
  settle: "Settle",
  cut: "Enter counts",
  inspection: "Record inspection",
  "stage:materials": "Mark arrived",
  "stage:fabric_check": "Record check",
  "stage:pattern_check": "Record check",
  "stage:making": "Mark finished",
  delivery: "Record delivery",
  "delivery:count": "Enter counts",
  "delivery-reason": "Add reason",
};

/** The owner's own forms; the QC manager is given the order instead. Everything else is the QC manager's too. */
const OWNER_FORMS = new Set(["sample", "settle"]);

const formKind = (open: string): string => open.split(":")[0];

function formWords(open: string): string | null {
  // A new delivery of one kind (fix pieces coming back, or finished pieces), not a count on an existing one.
  if (open === "delivery:fix" || open === "delivery:finished") return FORM_WORDS.delivery;
  if (open.startsWith("delivery:")) return FORM_WORDS["delivery:count"];
  if (open.startsWith("delivery-reason:")) return FORM_WORDS["delivery-reason"];
  return FORM_WORDS[open] ?? null;
}

export type TaskLink = { label: string; to: string; opens: boolean };

/**
 * Where a generated task's button goes. A purchase's task goes to its supplier's page (see below). With a form this person may use, the order page with that form
 * already open ("Review sample"); with none (waiting on the factory, an owner-only form for the QC
 * manager, or somebody who can only read), the order itself ("Open order"), never a button that writes.
 */
export function taskLink(task: GeneratedTask, powers: Powers): TaskLink | null {
  // A purchase's task (`purchase:<id>`, either "chase" or "check on arrival") goes to its supplier's page, with
  // the purchase's "Mark received" open for somebody who may mark it; anybody else is given the supplier.
  if (task.open?.startsWith("purchase:") && task.supplier) {
    const page = `/production/suppliers/${task.supplier.id}`;
    return powers.canEdit
      ? { label: "Mark received", to: `${page}?open=${task.open}`, opens: true }
      : { label: "Open supplier", to: page, opens: false };
  }
  if (!task.order) return null;
  const page = `/production/orders/${task.order.id}`;
  const open = task.open;
  const words = open ? formWords(open) : null;
  const allowed = open !== null && words !== null && (OWNER_FORMS.has(formKind(open)) ? powers.isOwner : powers.canEdit);
  if (!open || !words || !allowed) return { label: "Open order", to: page, opens: false };
  return { label: words, to: `${page}?open=${open}`, opens: true };
}

export const isManual = (task: Task): task is ManualTask => task.kind === "manual";

// ── Next action and updates ──────────────────────────────────────────────────

/** How long ago an instant was: "just now", "5 min ago", "2 h ago", else the Cairo day ("12 Nov"). */
export function agoWords(iso: string | null, now: Date = new Date()): string {
  if (!iso) return "";
  const moment = new Date(iso);
  if (Number.isNaN(moment.getTime())) return "";
  const minutes = Math.floor((now.getTime() - moment.getTime()) / 60_000);
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes} min ago`;
  if (minutes < 24 * 60) return `${Math.floor(minutes / 60)} h ago`;
  return shortDay(cairoDay(iso));
}

/** "Update · 2 h ago: the fabric is at the cutter". */
export function updateLine(update: TaskUpdate, now?: Date): string {
  const when = agoWords(update.created_at, now);
  return `Update${when ? ` · ${when}` : ""}: ${update.text}`;
}
