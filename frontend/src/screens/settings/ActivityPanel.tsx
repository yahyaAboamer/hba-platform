import { useCallback, useEffect, useRef, useState } from "react";

import { api } from "../../lib/api";
import "../Settings.css";

type AuditEntry = {
  id: number;
  /** The entry in words, written on the server from the row. */
  sentence: string;
  /** Who did it - their name, not their address. */
  who: string;
  action: string;
  kind: string | null;
  subject: string;
  actor_email: string | null;
  reason: string | null;
  created_at: string;
  before: Record<string, unknown> | null;
  after: Record<string, unknown> | null;
};

const KIND_LABEL: Record<string, string> = {
  money: "Money",
  access: "Access",
  models: "Models",
  content: "Content",
  settings: "Settings",
  inbox: "Inbox",
  operations: "Operations",
  production: "Production",
};

/** The kinds of entry a department page can show. */
const DEPARTMENT_KINDS: Record<string, string[]> = { affiliates: ["money", "models", "content"] };

type Filters = { models: { id: number; name: string }[]; people: { id: number; name: string }[]; kinds: string[] };

/** *Today*, *Yesterday*, or *Tuesday 29 September*, in Cairo. */
function dayHeading(iso: string): string {
  const key = (value: Date) => new Intl.DateTimeFormat("en-CA", { timeZone: "Africa/Cairo" }).format(value);
  const now = new Date();
  const then = new Date(iso);
  if (key(then) === key(now)) return "Today";
  if (key(then) === key(new Date(now.getTime() - 86_400_000))) return "Yesterday";
  return new Intl.DateTimeFormat("en-GB", {
    timeZone: "Africa/Cairo", weekday: "long", day: "numeric", month: "long",
    ...(then.getFullYear() !== now.getFullYear() ? { year: "numeric" as const } : {}),
  }).format(then);
}

const timeOf = (iso: string) =>
  new Intl.DateTimeFormat("en-GB", { timeZone: "Africa/Cairo", hour: "2-digit", minute: "2-digit", hourCycle: "h23" }).format(new Date(iso));

/** A value from the trail, readable. Objects are rare and shown whole. */
function shown(value: unknown): string {
  if (value === null || value === undefined || value === "") return "—";
  if (typeof value === "boolean") return value ? "Yes" : "No";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

const fieldWords = (key: string) => {
  const words = key.replace(/_/g, " ");
  return words.charAt(0).toUpperCase() + words.slice(1);
};

/** R4: what moved, from the before and after the server already sends. */
function changes(entry: AuditEntry): [string, string, string][] {
  const before = entry.before ?? {};
  const after = entry.after ?? {};
  if (!entry.before || !entry.after) return [];
  const keys = Array.from(new Set([...Object.keys(before), ...Object.keys(after)]));
  return keys
    .filter((key) => JSON.stringify(before[key]) !== JSON.stringify(after[key]))
    .map((key) => [fieldWords(key), shown(before[key]), shown(after[key])]);
}

/**
 * The activity log. `department` narrows it to one department's entries
 * (Affiliates' own page); Company sends none and, for the owner, reads all.
 */
export function ActivityPanel({ department, title }: { department?: string; title?: string } = {}) {
  const [events, setEvents] = useState<AuditEntry[] | null>(null);
  const [hasMore, setHasMore] = useState(false);
  const [filters, setFilters] = useState<Filters | null>(null);
  const [q, setQ] = useState("");
  const [search, setSearch] = useState("");
  const [model, setModel] = useState("");
  const [person, setPerson] = useState("");
  const [kind, setKind] = useState("");
  const [signIns, setSignIns] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [loadingMore, setLoadingMore] = useState(false);
  // Every request is numbered; an answer that is no longer the latest is
  // dropped. A slow *Show older* from before a filter changed would otherwise
  // append the old filter's rows to the new list.
  const latest = useRef(0);

  useEffect(() => {
    api.get<Filters>(`/api/audit/filters${department ? `?department=${department}` : ""}`)
      .then(setFilters).catch(() => undefined);
  }, [department]);

  // The search box waits for a pause in typing rather than a button press.
  useEffect(() => {
    const timer = window.setTimeout(() => setSearch(q.trim()), 300);
    return () => window.clearTimeout(timer);
  }, [q]);

  const params = useCallback((before?: number) => {
    const out = new URLSearchParams();
    if (search) out.set("q", search);
    if (model) out.set("affiliate_id", model);
    if (person) out.set("actor_id", person);
    if (kind) out.set("kind", kind);
    out.set("include_sign_ins", String(signIns));
    if (department) out.set("department", department);
    if (before) out.set("before", String(before));
    return out.toString();
  }, [search, model, person, kind, signIns, department]);

  useEffect(() => {
    const ticket = ++latest.current;
    setError(null);
    setEvents(null);
    setHasMore(false);
    api.get<{ events: AuditEntry[]; has_more: boolean }>(`/api/audit?${params()}`)
      .then((body) => { if (ticket === latest.current) { setEvents(body.events); setHasMore(body.has_more); } })
      .catch((caught) => { if (ticket === latest.current) setError(caught.message); });
  }, [params]);

  async function older() {
    if (!events || events.length === 0) return;
    const ticket = ++latest.current;
    const shown = events;
    setLoadingMore(true);
    try {
      const body = await api.get<{ events: AuditEntry[]; has_more: boolean }>(
        `/api/audit?${params(shown[shown.length - 1].id)}`);
      if (ticket !== latest.current) return;
      setEvents([...shown, ...body.events]);
      setHasMore(body.has_more);
    } catch (caught) {
      if (ticket === latest.current) setError(caught instanceof Error ? caught.message : "Could not load more.");
    } finally {
      setLoadingMore(false);
    }
  }

  const days: [string, AuditEntry[]][] = [];
  for (const entry of events ?? []) {
    const heading = dayHeading(entry.created_at);
    const last = days[days.length - 1];
    if (last && last[0] === heading) last[1].push(entry);
    else days.push([heading, [entry]]);
  }
  // A department page offers only the kinds that can match it; the others
  // (Access, Settings, another department) could only ever come back empty.
  const offered = filters?.kinds ?? (department ? [] : Object.keys(KIND_LABEL));
  const kinds = department
    ? offered.filter((value) => (DEPARTMENT_KINDS[department] ?? offered).includes(value))
    : offered;
  const narrowed = Boolean(search || model || person || kind);

  return (
    <>
      <section className="panel">
        {title && <div className="panel__head"><h2 className="panel__title">{title}</h2></div>}
        <div className="settings__pad settings__filters">
          <div className="settings__filter-row">
            <input className="input settings__filter-search" type="search" value={q}
              onChange={(event) => setQ(event.target.value)}
              placeholder="Search - a model, a colleague, a word" aria-label="Search the activity log" />
            <select className="input settings__filter-select" value={model} onChange={(event) => setModel(event.target.value)} aria-label="Model">
              <option value="">Any model</option>
              {filters?.models.map((row) => <option key={row.id} value={row.id}>{row.name}</option>)}
            </select>
            <select className="input settings__filter-select" value={person} onChange={(event) => setPerson(event.target.value)} aria-label="Done by">
              <option value="">Anyone</option>
              {filters?.people.map((row) => <option key={row.id} value={row.id}>{row.name}</option>)}
            </select>
          </div>
          <div className="settings__filter-row" role="group" aria-label="Kind">
            <button type="button" className={`chip${kind === "" ? " chip--on" : ""}`} aria-pressed={kind === ""} onClick={() => setKind("")}>All</button>
            {kinds.map((value) => (
              <button key={value} type="button" className={`chip${kind === value ? " chip--on" : ""}`} aria-pressed={kind === value}
                onClick={() => setKind(kind === value ? "" : value)}>{KIND_LABEL[value] ?? value}</button>
            ))}
            {/* Sign-ins belong to no department, so a department page has none. */}
            {!department && (
              <button type="button" className={`chip${signIns ? " chip--on" : ""}`} aria-pressed={signIns} onClick={() => setSignIns(!signIns)}>
                Include sign-ins
              </button>
            )}
          </div>
        </div>
      </section>

      {error && <p className="notice notice--refused" role="alert">{error}</p>}
      {events === null && !error && <p className="empty">Loading…</p>}
      {events?.length === 0 && (
        <section className="panel"><p className="settings__none">
          {narrowed ? "Nothing matches that." : "Nothing has been recorded yet."}
        </p></section>
      )}

      {days.map(([heading, entries], index) => (
        <section className="panel" key={`${heading}-${index}`}>
          <div className="panel__head"><h2 className="panel__title">{heading}</h2></div>
          <ul className="settings__activity">
            {entries.map((entry) => {
              const moved = changes(entry);
              return (
                <li key={entry.id} className="settings__activity-row">
                  <span className="settings__activity-what">{entry.sentence}</span>
                  <span className="settings__activity-who">
                    {entry.kind && <span className={`settings__kind settings__kind--${entry.kind}`}>{KIND_LABEL[entry.kind] ?? entry.kind}</span>}
                    {entry.who} · {timeOf(entry.created_at)}
                  </span>
                  {entry.reason && <span className="settings__activity-reason">"{entry.reason}"</span>}
                  {moved.length > 0 && (
                    <details className="settings__changed">
                      <summary>What changed</summary>
                      <dl>
                        {moved.map(([field, from, to]) => (
                          <div key={field}>
                            <dt>{field}</dt>
                            <dd><s>{from}</s> → <ins>{to}</ins></dd>
                          </div>
                        ))}
                      </dl>
                    </details>
                  )}
                </li>
              );
            })}
          </ul>
        </section>
      ))}

      {hasMore && (
        <button type="button" className="button settings__older" onClick={older} disabled={loadingMore}>
          {loadingMore ? "Loading…" : "Show older"}
        </button>
      )}
    </>
  );
}

