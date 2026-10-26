import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";

import { HistoricalReview } from "./HistoricalReview";
import type { HistoricalReviewBody } from "./HistoricalReview";
import { pickMaintainerChoice, storedMaintainerChoice, themePickedThisVisit } from "../lib/theme";
import type { ThemeChoice } from "../lib/theme";

import { MonthPicker } from "../components/MonthPicker";
import { PolicyText } from "../components/PolicyText";
import { api, can, devices, twoStep } from "../lib/api";
import type { DeviceSession, Session, TwoStepStatus } from "../lib/api";
import { CodeForm, RecoveryCodes, TwoStepSetup } from "../components/TwoStepSetup";
import { currentMonth, formatMonth, monthAdd, monthsBetween } from "../lib/money";
import { DataPanel, longWhen } from "./DataPanel";
import "./ModelLifecycle.css";
import "./Settings.css";

type SyncStatus = {
  shopify_configured: boolean;
  webhooks_configured: boolean;
  go_live_month: string | null;
  payroll_can_be_approved: boolean;
  orders_indexed: number;
  last_order_synced_at: string | null;
};

type StaffRow = {
  id: number;
  email: string;
  display_name: string | null;
  /** Every staff role held now, widest first (ADR 0067: several per person). */
  roles: string[];
  status: "invited" | "active" | "suspended";
  /** Two-step sign-in is on for them (Batch 1.3). */
  two_step_enabled?: boolean;
  last_login_at: string | null;
  created_at: string | null;
};

type InvitationRow = {
  id: number;
  email: string;
  role: string;
  expires_at: string;
  expired: boolean;
  created_at: string | null;
};

type Roster = {
  staff: StaffRow[];
  invitations: InvitationRow[];
  assignable_roles: string[];
  /** Only access the signed-in person holds themselves, all their roles
   *  together (`can_grant`). What *Add access* and the invite form offer. */
  invitable_roles: string[];
  /** What each role grants, from the server's own list (T4). */
  role_permissions: Record<string, string[]>;
};

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

const ROLE_LABEL: Record<string, string> = {
  admin: "Admin",
  affiliate_manager: "Affiliate manager",
  content_manager: "Content manager",
  operations_manager: "Operations manager",
  customer_service: "Customer service",
};

const roleWords = (role: string) => ROLE_LABEL[role] ?? role;

/** Several roles in words: *Content manager and Customer service*. */
const rolesWords = (roles: string[]) => {
  const words = roles.map(roleWords);
  return words.length <= 1 ? (words[0] ?? "no access")
    : `${words.slice(0, -1).join(", ")} and ${words[words.length - 1]}`;
};

/** Everything a set of roles grants together, as the server reads it. */
function grantedBy(roles: string[], rolePermissions: Record<string, string[]> | undefined): string[] {
  return [...new Set(roles.flatMap((role) => rolePermissions?.[role] ?? []))];
}

/**
 * *What can each access do?* (Settings audit T4), in plain words. A role has a
 * line when it holds every permission the line names - read from the server's
 * own `ROLES`, so the table cannot drift from what the server enforces.
 */
const ACCESS_LINES: [string, string[]][] = [
  ["See and edit models, and set their pay terms", ["affiliates.manage", "compensation.manage"]],
  ["Set, record and confirm content targets", ["targets.manage", "targets.record", "targets.verify"]],
  ["Read the activity log", ["audit.view"]],
  ["Approve a month's pay", ["payroll.approve"]],
  ["See the operations dashboard", ["order_ops.view"]],
  ["Read and answer customers in the inbox", ["inbox.use"]],
  ["Invite staff, up to their own access", ["invitations.send"]],
  ["Record payments and reopen approved months", ["payments.record", "payroll.reopen"]],
  ["Change anyone's access, Shopify and the pay policy; erase a model", ["settings.manage", "affiliates.erase"]],
];

function holds(permissions: string[] | undefined, line: string[]) {
  return !!permissions && line.every((permission) => permissions.includes(permission));
}

/**
 * The platform's own configuration and who may touch it.
 *
 * Not a workflow like the other screens - nothing here is walked through
 * every month. The rail lists **only the sections this person can use**
 * (Settings audit X2: a content manager used to open Settings on a blank Team
 * page), grouped into what changes the business and what changes only you.
 */
type SectionId = "team" | "shopify" | "historical" | "codes" | "policy" | "activity" | "appearance";

const SECTION_LABEL: Record<SectionId, string> = {
  team: "Team",
  shopify: "Shopify and sync",
  historical: "Historical setup",
  codes: "Brand codes",
  policy: "Pay policy",
  activity: "Activity log",
  appearance: "My preferences",
};

/** Old links (`?section=advanced`) keep landing somewhere sensible. */
const ALIASES: Record<string, SectionId[]> = { advanced: ["policy", "activity"] };

export function Settings({ session }: { session: Session }) {
  const [query, setQuery] = useSearchParams();
  const history = useHistoryState(session);

  const business = useMemo(() => {
    const out: SectionId[] = [];
    if (can(session, "settings.manage") || can(session, "invitations.send")) out.push("team");
    out.push("shopify");
    // D3 (owner, 30 September): once every month before go-live is final, the
    // section has done its job and leaves the rail. A direct link still lands
    // on the one line that says so.
    if (can(session, "compensation.manage") && history.state !== "complete") out.push("historical");
    out.push("codes");
    if (can(session, "settings.manage")) out.push("policy");
    if (can(session, "audit.view")) out.push("activity");
    return out;
  }, [session, history.state]);
  const everything: SectionId[] = [...business, "appearance"];

  const asked = query.get("section") ?? "";
  const section: SectionId =
    (everything as string[]).includes(asked)
      ? (asked as SectionId)
      : asked === "historical" && can(session, "compensation.manage")
        ? "historical"
        : (ALIASES[asked] ?? []).find((id) => everything.includes(id)) ?? everything[0];

  const pick = (id: SectionId) => setQuery({ section: id });

  return <>
    <div className="page__head"><div className="page__title"><h1>Settings</h1></div></div>
    <div className="settings__workspace">
      <nav className="settings__navigation" aria-label="Settings sections">
        <span className="settings__group" aria-hidden="true">Business</span>
        {business.map((id) => <RailButton key={id} id={id} current={section} onPick={pick} />)}
        <span className="settings__group" aria-hidden="true">Just me</span>
        <RailButton id="appearance" current={section} onPick={pick} />
        <Link className="settings__help" to="/glossary">Help and definitions →</Link>
      </nav>
      <div className="settings__sections">
        {section === "team" && (can(session, "settings.manage")
          ? <RosterPanel session={session} />
          : <InviteOnly />)}
        {section === "shopify" && (can(session, "settings.manage")
          ? <DataPanel goLiveMonth={session.platform.go_live_month} />
          : <PlatformPanel session={session} />)}
        {section === "historical" && (history.state === "complete"
          ? <section className="panel"><p className="settings__pad settings__done">
              History is complete: every month before {history.goLive ? formatMonth(history.goLive) : "go-live"} is final.
            </p></section>
          : <SetupRoster session={session} />)}
        {section === "codes" && <BrandCodes session={session} />}
        {section === "policy" && <PolicyPanel />}
        {section === "activity" && <ActivityPanel />}
        {section === "appearance" && <AppearancePanel />}
      </div>
    </div>
  </>;
}

function RailButton({ id, current, onPick }: { id: SectionId; current: SectionId; onPick: (id: SectionId) => void }) {
  return (
    <button type="button" aria-current={current === id ? "page" : undefined}
      className={current === id ? "settings__selected" : ""} onClick={() => onPick(id)}>
      {SECTION_LABEL[id]}
    </button>
  );
}

/**
 * Whether the months before go-live are all final (D3). Asked only of
 * somebody who may see the review; for anybody else the section stays.
 */
function useHistoryState(session: Session) {
  const [state, setState] = useState<"unknown" | "open" | "complete">("unknown");
  const allowed = can(session, "payroll.approve");
  useEffect(() => {
    if (!allowed) return;
    let live = true;
    api.get<HistoricalReviewBody>("/api/payroll/historical/review")
      .then((body) => {
        if (!live) return;
        const waiting = (body.totals.ready ?? 0) + body.totals.blocked + (body.totals.unknown_start ?? 0);
        setState(waiting === 0 ? "complete" : "open");
      })
      .catch(() => undefined);
    return () => { live = false; };
  }, [allowed]);
  return { state, goLive: session.platform.go_live_month };
}

// ── A confirmation, for anything that changes somebody's access ─────────────

function ConfirmDialog({
  title, effects, confirm, danger = false, needsReason = false, onConfirm, onCancel,
}: {
  title: string;
  effects: string[];
  confirm: string;
  danger?: boolean;
  needsReason?: boolean;
  onConfirm: (reason: string) => Promise<void>;
  onCancel: () => void;
}) {
  const [reason, setReason] = useState("");
  const [working, setWorking] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const reasonRef = useRef<HTMLTextAreaElement>(null);
  const cancelRef = useRef<HTMLButtonElement>(null);
  const dialogRef = useRef<HTMLDivElement>(null);

  // Focus goes in on opening and back to whatever opened it on closing - the
  // select or the row's menu button, rather than the top of the page.
  useEffect(() => {
    const opener = document.activeElement as HTMLElement | null;
    (needsReason ? reasonRef.current : cancelRef.current)?.focus();
    return () => { opener?.focus?.(); };
  }, [needsReason]);
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !working) onCancel();
      if (event.key !== "Tab" || !dialogRef.current) return;
      // Tab stays inside the dialog: it is modal, and says so.
      const stops = Array.from(dialogRef.current.querySelectorAll<HTMLElement>("button:not([disabled]), textarea"));
      if (stops.length === 0) return;
      const first = stops[0];
      const last = stops[stops.length - 1];
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onCancel, working]);

  async function go() {
    setWorking(true);
    setProblem(null);
    try {
      await onConfirm(reason.trim());
    } catch (caught) {
      setProblem(caught instanceof Error ? caught.message : "That did not go through.");
      setWorking(false);
    }
  }

  return (
    <div className="lifecycle__layer">
      <button type="button" className="lifecycle__scrim" aria-hidden="true" tabIndex={-1}
        onClick={() => !working && onCancel()} />
      <div ref={dialogRef} className="lifecycle__dialog" role="dialog" aria-modal="true" aria-labelledby="settings-dialog-title">
        <h2 id="settings-dialog-title" className="lifecycle__title">{title}</h2>
        <ul className="lifecycle__effects">{effects.map((line) => <li key={line}>{line}</li>)}</ul>
        {needsReason && (
          <label className="lifecycle__field">
            <span>Reason <span className="lifecycle__faint">(required, kept in the activity log)</span></span>
            <textarea ref={reasonRef} className="input lifecycle__reason" rows={2} value={reason}
              onChange={(event) => setReason(event.target.value)} />
          </label>
        )}
        {problem && <p className="notice notice--refused" role="alert">{problem}</p>}
        <div className="lifecycle__acts">
          <button type="button" className="button" ref={cancelRef} onClick={onCancel} disabled={working}>Cancel</button>
          <button type="button" className={danger ? "button lifecycle__danger" : "button button--primary"}
            onClick={go} disabled={working || (needsReason && !reason.trim())}>
            {working ? "Working…" : confirm}
          </button>
        </div>
      </div>
    </div>
  );
}

/**
 * A modal for the dialogs that hold more than a yes or no (a list of devices,
 * a field for a code). Focus goes in on opening and back on closing, Escape
 * closes, and Tab stays inside - as `ConfirmDialog` does.
 */
function DialogFrame({ title, onClose, children }: { title: string; onClose: () => void; children: React.ReactNode }) {
  const dialogRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const opener = document.activeElement as HTMLElement | null;
    const first = dialogRef.current?.querySelector<HTMLElement>("input, button:not([disabled])");
    first?.focus();
    return () => { opener?.focus?.(); };
  }, []);
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
      if (event.key !== "Tab" || !dialogRef.current) return;
      const stops = Array.from(dialogRef.current.querySelectorAll<HTMLElement>("button:not([disabled]), input, textarea"));
      if (stops.length === 0) return;
      const first = stops[0];
      const last = stops[stops.length - 1];
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose]);
  return (
    <div className="lifecycle__layer">
      <button type="button" className="lifecycle__scrim" aria-hidden="true" tabIndex={-1} onClick={onClose} />
      <div ref={dialogRef} className="lifecycle__dialog" role="dialog" aria-modal="true" aria-labelledby="settings-frame-title">
        <h2 id="settings-frame-title" className="lifecycle__title">{title}</h2>
        {children}
      </div>
    </div>
  );
}

// ── Where somebody is signed in ─────────────────────────────────────────────

/** *Active now*, or when they were last seen. */
function seenWords(iso: string): string {
  if (Date.now() - new Date(iso).getTime() < 5 * 60_000) return "Active now";
  return `Last seen ${lastSeen(iso).replace(/^Today, /, "today at ")}`;
}

/** One device: what it is, the address it came from, and when it was last used. */
function DeviceLine({ device, action }: { device: DeviceSession; action?: React.ReactNode }) {
  return (
    <li className="twostep__row">
      <span>
        {device.device}{device.current && <span className="settings__you">This device</span>}
        <small>{[device.ip_address, seenWords(device.last_seen_at)].filter(Boolean).join(" · ")}</small>
      </span>
      {action}
    </li>
  );
}

function DevicesDialog({ row, onClose, onChanged }: { row: StaffRow; onClose: () => void; onChanged: () => void }) {
  const name = row.display_name || row.email;
  const [list, setList] = useState<DeviceSession[] | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const [working, setWorking] = useState(false);

  const load = useCallback(() => {
    devices.of(row.id).then((body) => setList(body.sessions))
      .catch((caught) => setProblem(caught instanceof Error ? caught.message : "Could not load this."));
  }, [row.id]);
  useEffect(load, [load]);

  async function endAll() {
    setWorking(true);
    setProblem(null);
    try {
      await devices.endAllOf(row.id);
      setList([]);
      onChanged();
    } catch (caught) {
      setProblem(caught instanceof Error ? caught.message : "That did not go through.");
    } finally {
      setWorking(false);
    }
  }

  return (
    <DialogFrame title={`${name} is signed in on`} onClose={onClose}>
      {problem && <p className="notice notice--refused" role="alert">{problem}</p>}
      {list === null && !problem && <p className="empty">Loading…</p>}
      {list && list.length === 0 && <p className="empty">Not signed in anywhere.</p>}
      {list && list.length > 0 && <ul className="settings__devices" aria-label={`Devices for ${name}`}>
        {list.map((device) => <DeviceLine key={device.id} device={device} />)}
      </ul>}
      <div className="lifecycle__acts">
        <button type="button" className="button" onClick={onClose}>Close</button>
        <button type="button" className="button lifecycle__danger" onClick={endAll}
          disabled={working || !list || list.length === 0}>
          {working ? "Working…" : "Sign out of every device"}
        </button>
      </div>
    </DialogFrame>
  );
}

function ResetTwoStepDialog({ row, onClose, onDone }: { row: StaffRow; onClose: () => void; onDone: () => void }) {
  const name = row.display_name || row.email;
  return (
    <DialogFrame title={`Reset two-step sign-in for ${name}?`} onClose={onClose}>
      <ul className="lifecycle__effects">
        <li>Turns off {name}&apos;s two-step sign-in and their recovery codes.</li>
        <li>It lets {name} set it up again, on a new phone, the next time they sign in.</li>
        <li>This asks for your own code, so it is you who is doing it.</li>
      </ul>
      <CodeForm
        label="Your own 6-digit code"
        action="Reset two-step sign-in"
        danger
        onCancel={onClose}
        onSubmit={async (code) => {
          await devices.resetTwoStepOf(row.id, code);
          onDone();
        }}
      />
    </DialogFrame>
  );
}

// ── Team ──────────────────────────────────────────────────────────────────

/** *Today, 14:31*, *Yesterday*, *3 August*, or *Never*. In Cairo. */
function lastSeen(iso: string | null): string {
  if (!iso) return "Never";
  const day = (value: Date) =>
    new Intl.DateTimeFormat("en-CA", { timeZone: "Africa/Cairo" }).format(value);
  const then = new Date(iso);
  const now = new Date();
  if (day(then) === day(now)) {
    return `Today, ${new Intl.DateTimeFormat("en-GB", { timeZone: "Africa/Cairo", hour: "2-digit", minute: "2-digit", hourCycle: "h23" }).format(then)}`;
  }
  if (day(then) === day(new Date(now.getTime() - 86_400_000))) return "Yesterday";
  return new Intl.DateTimeFormat("en-GB", {
    timeZone: "Africa/Cairo", day: "numeric", month: "long",
    ...(then.getFullYear() !== now.getFullYear() ? { year: "numeric" as const } : {}),
  }).format(then);
}

const STATE_ORDER: Record<string, number> = { active: 0, invited: 1, suspended: 2 };

type Pending =
  | { kind: "give"; row: StaffRow; role: string }
  | { kind: "remove"; row: StaffRow; role: string }
  | { kind: "suspend"; row: StaffRow }
  | { kind: "reactivate"; row: StaffRow }
  | { kind: "devices"; row: StaffRow }
  | { kind: "reset"; row: StaffRow };

function RosterPanel({ session }: { session: Session }) {
  const [roster, setRoster] = useState<Roster | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState<Pending | null>(null);
  const [menu, setMenu] = useState<number | null>(null);

  const load = useCallback(() => {
    api.get<Roster>("/api/staff").then(setRoster).catch((caught) => setError(caught.message));
  }, []);
  useEffect(load, [load]);

  useEffect(() => {
    if (menu === null) return;
    const close = (event: Event) => {
      if (event instanceof KeyboardEvent && event.key !== "Escape") return;
      if (event.type === "click" && (event.target as HTMLElement).closest(".settings__menu-wrap")) return;
      setMenu(null);
    };
    document.addEventListener("click", close);
    document.addEventListener("keydown", close);
    return () => { document.removeEventListener("click", close); document.removeEventListener("keydown", close); };
  }, [menu]);

  const staff = roster
    ? [...roster.staff].sort((a, b) =>
      (STATE_ORDER[a.status] ?? 9) - (STATE_ORDER[b.status] ?? 9)
      || (a.display_name || a.email).localeCompare(b.display_name || b.email))
    : [];

  function dialogFor(action: Pending) {
    const name = action.row.display_name || action.row.email;
    if (action.kind === "devices") {
      return <DevicesDialog row={action.row} onClose={() => setPending(null)} onChanged={load} />;
    }
    if (action.kind === "reset") {
      return <ResetTwoStepDialog row={action.row} onClose={() => setPending(null)}
        onDone={() => { setPending(null); load(); }} />;
    }
    if (action.kind === "give" || action.kind === "remove") {
      // ADR 0067: a person holds several roles, and may do everything they
      // grant together - so what changes is read from all of them.
      const giving = action.kind === "give";
      // Asked of what the role grants, not its name: the access that can
      // change everybody else's is the one worth a sterner question.
      const toAdmin = giving && (roster?.role_permissions[action.role] ?? []).includes("settings.manage");
      const afterRoles = giving
        ? [...action.row.roles, action.role]
        : action.row.roles.filter((role) => role !== action.role);
      const before = grantedBy(action.row.roles, roster?.role_permissions);
      const after = grantedBy(afterRoles, roster?.role_permissions);
      const gains = ACCESS_LINES.filter(([, line]) => holds(after, line) && !holds(before, line)).map(([words]) => words);
      const loses = ACCESS_LINES.filter(([, line]) => holds(before, line) && !holds(after, line)).map(([words]) => words);
      return <ConfirmDialog
        title={giving
          ? (toAdmin ? `Make ${name} an admin?` : `Give ${name} ${roleWords(action.role)} access?`)
          : `Take ${roleWords(action.role)} access from ${name}?`}
        effects={[
          ...gains.map((line) => `Can now: ${line.charAt(0).toLowerCase()}${line.slice(1)}`),
          ...loses.map((line) => `Can no longer: ${line.charAt(0).toLowerCase()}${line.slice(1)}`),
          `Keeps: ${rolesWords(giving ? action.row.roles : afterRoles)}.`,
          "Takes effect on their very next click.",
        ]}
        confirm={giving ? (toAdmin ? "Make admin" : "Add access") : "Remove access"}
        danger={!giving}
        onCancel={() => setPending(null)}
        onConfirm={async () => {
          await (giving
            ? api.post(`/api/staff/${action.row.id}/roles`, { role: action.role })
            : api.post(`/api/staff/${action.row.id}/roles/${encodeURIComponent(action.role)}/remove`));
          setPending(null);
          load();
        }} />;
    }
    if (action.kind === "suspend") {
      return <ConfirmDialog
        title={`Suspend ${name}?`}
        effects={[
          "Removes every department and signs out every device at once.",
          `The record of what ${name} did stays.`,
        ]}
        confirm="Suspend" danger needsReason
        onCancel={() => setPending(null)}
        onConfirm={async (reason) => {
          await api.post(`/api/staff/${action.row.id}/suspend`, { reason });
          setPending(null);
          load();
        }} />;
    }
    return <ConfirmDialog
      title={`Reactivate ${name}?`}
      effects={[`Reactivating ${name} gives no access. Add it again with Add access.`]}
      confirm="Reactivate"
      onCancel={() => setPending(null)}
      onConfirm={async () => {
        await api.post(`/api/staff/${action.row.id}/reactivate`);
        setPending(null);
        load();
      }} />;
  }

  return (
    <>
      {error && <p className="notice notice--refused" role="alert">{error}</p>}
      {roster === null && !error && <p className="empty">Loading…</p>}

      {roster && (
        <section className="panel" aria-label="Staff">
          <table className="table settings__table">
            <thead>
              <tr>
                <th>Staff</th>
                <th className="settings__access">Access</th>
                <th className="settings__seen">Last signed in</th>
                <th className="settings__state">State</th>
                <th className="settings__action"><span className="visually-hidden">Actions</span></th>
              </tr>
            </thead>
            <tbody>
              {staff.map((row) => {
                const you = row.id === session.actor.id;
                const name = row.display_name || row.email;
                const changeable = !you && row.status !== "suspended";
                // *Add access* offers only what this person may give
                // (`can_grant`), and nothing already held.
                const addable = roster.invitable_roles.filter((role) => !row.roles.includes(role));
                // The last role is not taken here: suspending is how somebody
                // loses all their access.
                const removable = (role: string) =>
                  row.roles.length > 1 && roster.invitable_roles.includes(role);
                return (
                  <tr key={row.id} className={row.status === "suspended" ? "settings__row--off" : undefined}>
                    <td>
                      {name}
                      {row.two_step_enabled && (
                        <svg className="twostep__lock" role="img" aria-label="Two-step sign-in on" viewBox="0 0 24 24"
                          fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                          <rect x="5" y="11" width="14" height="9" rx="2" /><path d="M8 11V8a4 4 0 0 1 8 0v3" />
                        </svg>
                      )}
                      {you && <span className="settings__you">You</span>}
                      <span className="settings__email">{row.email}</span>
                    </td>
                    <td className="settings__access">
                      <ul className="settings__roles" aria-label={`Access for ${name}`}>
                        {row.roles.map((role) => (
                          <li key={role} className="settings__role">
                            {roleWords(role)}
                            {changeable && removable(role) && (
                              <button type="button" className="settings__link-button"
                                aria-label={`Remove ${roleWords(role)} from ${name}`}
                                onClick={() => setPending({ kind: "remove", row, role })}>Remove</button>
                            )}
                          </li>
                        ))}
                      </ul>
                      {changeable && addable.length > 0 && (
                        <select className="input settings__role-select settings__add-access" value=""
                          aria-label={`Add access for ${name}`}
                          onChange={(event) => {
                            if (event.target.value) setPending({ kind: "give", row, role: event.target.value });
                          }}>
                          <option value="">Add access…</option>
                          {addable.map((role) => <option key={role} value={role}>{roleWords(role)}</option>)}
                        </select>
                      )}
                      {you && <span className="settings__email">Another admin changes yours</span>}
                    </td>
                    <td className="settings__seen">{lastSeen(row.last_login_at)}</td>
                    <td className="settings__state">
                      <span className={`pill settings__pill--${row.status}`}>
                        {row.status === "active" ? "Active" : row.status === "suspended" ? "Suspended" : "Invited"}
                      </span>
                    </td>
                    <td className="settings__action">
                      {!you && (
                        <span className="settings__menu-wrap">
                          <button type="button" className="settings__kebab"
                            aria-expanded={menu === row.id} aria-label={`More for ${name}`}
                            onClick={() => setMenu(menu === row.id ? null : row.id)}>⋯</button>
                          {menu === row.id && (
                            <span className="settings__menu">
                              <button type="button" autoFocus
                                onClick={() => { setMenu(null); setPending({ kind: "devices", row }); }}>
                                Signed in on…
                                <small>See where, and sign them out</small>
                              </button>
                              {row.two_step_enabled && (
                                <button type="button"
                                  onClick={() => { setMenu(null); setPending({ kind: "reset", row }); }}>
                                  Reset two-step sign-in…
                                  <small>Lets them set it up again</small>
                                </button>
                              )}
                              {row.status === "suspended" ? (
                                <button type="button"
                                  onClick={() => { setMenu(null); setPending({ kind: "reactivate", row }); }}>
                                  Reactivate
                                  <small>They can sign in again, with no access</small>
                                </button>
                              ) : (
                                <button type="button" className="settings__menu-danger"
                                  onClick={() => { setMenu(null); setPending({ kind: "suspend", row }); }}>
                                  Suspend…
                                  <small>Removes every department and signs them out</small>
                                </button>
                              )}
                            </span>
                          )}
                        </span>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </section>
      )}

      {roster && can(session, "invitations.send") && (
        <InvitePanel roles={roster.invitable_roles} permissions={roster.role_permissions} onInvited={load} />
      )}
      {roster && <PendingInvitations rows={roster.invitations} onChanged={load} />}
      {pending && dialogFor(pending)}
    </>
  );
}

/**
 * For whoever may invite without holding `settings.manage` - an affiliate
 * manager. The form, and the invitations they may still resend or withdraw
 * (X2: they used to get the form and nothing else).
 */
type MyInvitations = { invitations: InvitationRow[]; invitable_roles: string[]; role_permissions: Record<string, string[]> };

function InviteOnly() {
  const [body, setBody] = useState<MyInvitations | null>(null);
  const [error, setError] = useState<string | null>(null);
  const load = useCallback(() => {
    api.get<MyInvitations>("/api/staff/invitations").then(setBody).catch((caught) => setError(caught.message));
  }, []);
  useEffect(load, [load]);
  if (error) return <p className="notice notice--refused" role="alert">{error}</p>;
  if (!body) return <p className="empty">Loading…</p>;
  return <>
    <InvitePanel roles={body.invitable_roles} permissions={body.role_permissions} onInvited={load} />
    <PendingInvitations rows={body.invitations} onChanged={load} />
  </>;
}

function InvitePanel({ roles, permissions, onInvited }: {
  roles: string[];
  permissions: Record<string, string[]>;
  onInvited?: () => void;
}) {
  // The least access first: an invitation is easy to widen and awkward to
  // take back.
  const offered = [...roles].sort((a, b) => (permissions[a]?.length ?? 0) - (permissions[b]?.length ?? 0));
  const [email, setEmail] = useState("");
  const [role, setRole] = useState(offered[0] ?? "");
  const [link, setLink] = useState<string | null>(null);
  const [emailed, setEmailed] = useState(false);
  const [copied, setCopied] = useState<boolean | null>(false);
  const [error, setError] = useState<string | null>(null);
  const [working, setWorking] = useState(false);

  useEffect(() => { if (!offered.includes(role)) setRole(offered[0] ?? ""); }, [offered, role]);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setWorking(true);
    setError(null);
    setLink(null);
    setCopied(false);
    try {
      const result = await api.post<{ token: string; emailed: boolean; link?: string }>(
        "/api/auth/invitations",
        { email: email.trim(), role },
      );
      setEmailed(result.emailed);
      // The server builds the link from its own public address; where none is
      // set (a development machine) it sends "", and the page builds it.
      setLink(result.link || `${window.location.origin}/accept-invitation?token=${result.token}`);
      setEmail("");
      onInvited?.();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Could not invite them.");
    } finally {
      setWorking(false);
    }
  }

  async function copy() {
    if (!link) return;
    try {
      await navigator.clipboard.writeText(link);
      setCopied(true);
    } catch {
      // The browser refused. Say so, rather than let somebody paste nothing.
      setCopied(null);
    }
  }

  if (offered.length === 0) return null;

  return (
    <section className="panel">
      <div className="panel__head"><h2 className="panel__title">Invite a staff member</h2></div>
      <div className="settings__pad">
        {error && <p className="notice notice--refused" role="alert">{error}</p>}
        {/*
         * §16. The platform emails the link, and the link is still shown here
         * - once, because it is a working credential until it is used - for
         * the moment the recipient says it never arrived.
         */}
        {link && (
          <div className="settings__linkbox" role="status">
            <span>
              {emailed
                ? "Emailed to them. The same link, in case it does not arrive - it only appears here once:"
                : "Send this to them yourself - it only appears here once:"}
            </span>
            <code>{link}</code>
            <button type="button" className="button button--row" onClick={copy}>
              {copied ? "Copied" : copied === null ? "Could not copy - select it instead" : "Copy link"}
            </button>
          </div>
        )}
        <form onSubmit={submit} className="settings__invite-row">
          <input className="input settings__invite-email" type="email" required value={email}
            onChange={(event) => setEmail(event.target.value)} placeholder="name@hbawear.store" aria-label="Email" />
          <select className="input settings__invite-role" value={role}
            onChange={(event) => setRole(event.target.value)} aria-label="Access">
            {offered.map((value) => <option key={value} value={value}>{roleWords(value)}</option>)}
          </select>
          <button type="submit" className="button button--primary settings__invite-send"
            disabled={working || !email.trim() || !role}>
            {working ? "Sending…" : "Send invitation"}
          </button>
        </form>
        <details className="settings__explain">
          <summary>What can each access do?</summary>
          <table className="settings__perm">
            <thead>
              <tr><th>Can…</th>{["content_manager", "affiliate_manager", "operations_manager", "admin"].filter((r) => permissions[r]).map((r) => <th key={r}>{roleWords(r)}</th>)}</tr>
            </thead>
            <tbody>
              {ACCESS_LINES.map(([words, line]) => (
                <tr key={words}>
                  <td>{words}</td>
                  {["content_manager", "affiliate_manager", "operations_manager", "admin"].filter((r) => permissions[r]).map((r) => (
                    <td key={r} className="settings__perm-mark">
                      {holds(permissions[r], line) ? <span aria-label="Yes">✓</span> : <span aria-label="No" className="settings__perm-no">—</span>}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </details>
      </div>
    </section>
  );
}

const longDate = (iso: string) =>
  new Intl.DateTimeFormat("en-GB", { timeZone: "Africa/Cairo", day: "numeric", month: "long" }).format(new Date(iso));

/**
 * One line per address, the newest (T1). A live link can be resent or
 * withdrawn; a lapsed one resent or removed - nothing sits here for ever.
 */
function PendingInvitations({ rows, onChanged }: { rows: InvitationRow[]; onChanged: () => void }) {
  const [busy, setBusy] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function act(id: number, path: "resend" | "revoke") {
    setBusy(id);
    setError(null);
    try {
      await api.post(path === "resend" ? `/api/staff/invitations/${id}/resend` : `/api/staff/invitations/${id}/revoke`);
      onChanged();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "That did not go through.");
    } finally {
      setBusy(null);
    }
  }

  return (
    <section className="panel">
      <div className="panel__head"><h2 className="panel__title">Pending staff invitations</h2></div>
      {error && <p className="notice notice--refused settings__pad" role="alert">{error}</p>}
      {rows.length === 0 ? (
        <p className="settings__none">No staff invitation is outstanding.</p>
      ) : (
        <ul className="settings__pending">
          {rows.map((row) => (
            <li key={row.id}>
              <span className="settings__pending-who">
                {row.email}
                <span className="settings__email">
                  {roleWords(row.role)}
                  {row.created_at && ` · Sent ${longDate(row.created_at)}`}
                  {" · "}
                  {row.expired
                    ? <span className="settings__gap">Link expired {longDate(row.expires_at)}</span>
                    : `expires ${longDate(row.expires_at)}`}
                </span>
              </span>
              <button type="button" className="button button--row" disabled={busy === row.id}
                onClick={() => act(row.id, "resend")}>Resend</button>
              <button type="button" className={`button button--row${row.expired ? "" : " settings__withdraw"}`}
                disabled={busy === row.id} onClick={() => act(row.id, "revoke")}>
                {row.expired ? "Remove" : "Withdraw"}
              </button>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

// ── Shopify and sync, for somebody without `settings.manage` ───────────────

function PlatformPanel({ session }: { session: Session }) {
  const [sync, setSync] = useState<SyncStatus | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.get<SyncStatus>("/api/operations/sync").then(setSync).catch((caught) => setError(caught.message));
  }, []);

  return (
    <section className="panel">
      <div className="panel__head"><h2 className="panel__title">Connection</h2></div>
      {error && <p className="notice notice--refused settings__pad" role="alert">{error}</p>}
      <dl className="settings__facts">
        <Row label="Shopify">{sync ? (sync.shopify_configured ? "Connected" : "Not connected") : "—"}</Row>
        <Row label="Order updates">{sync ? (sync.webhooks_configured ? "Arriving as they happen" : "Only on the half-hourly sweep") : "—"}</Row>
        <Row label="Last order">{sync?.last_order_synced_at ? longWhen(sync.last_order_synced_at) : "None yet"}</Row>
        <Row label="Go-live">{session.platform.go_live_month ? formatMonth(session.platform.go_live_month) : "Not set"}</Row>
      </dl>
    </section>
  );
}

// ── Historical setup ──────────────────────────────────────────────────────

type SetupRow = {
  id: number;
  name: string;
  account_kind: string;
  code?: string;
  status: string;
  uses?: number;
  collaboration_start_month?: string | null;
  /** The first month her terms cover. `null` means none were ever written. */
  earliest_terms_month?: string | null;
  /**
   * A09. How many of her eligible months can actually be calculated, counted
   * on the server with the same per-month rule the profile uses.
   */
  historical_setup?: {
    eligible: number;
    ready: number;
    blocking: number;
    /** Of `blocking`, the months before go-live - what the review counts. */
    blocking_before_go_live?: number;
    /** The earliest month that cannot be calculated, to link straight to. */
    first_gap: string | null;
    start_is_recorded: boolean;
  } | null;
};

/** Whether her row asks anything of anybody (H2). */
function needsSomething(row: SetupRow) {
  const setup = row.historical_setup;
  return !setup || setup.blocking > 0 || setup.eligible === 0;
}

/**
 * Whether her months can be worked out, and what to do where not (H3, H5).
 *
 * The count is split at go-live, so the row and the review under the table
 * agree on the page: it used to say *9 of 9* above *5 months* for one model.
 */
export function historicalState(row: SetupRow) {
  const setup = row.historical_setup;
  if (!setup) return <span className="settings__gap">Not known</span>;
  if (setup.eligible === 0) {
    return <>
      <span className="pill settings__pill--owed">No start month</span>
      <Link className="settings__fix" to={`/affiliates/${row.id}`}>Record her start month →</Link>
    </>;
  }
  if (setup.blocking === 0) return <span className="pill settings__pill--ok">Ready</span>;
  const before = setup.blocking_before_go_live ?? 0;
  const after = setup.blocking - before;
  const parts = [
    before > 0 && `${before} ${before === 1 ? "month" : "months"} before go-live`,
    after > 0 && `${after} after`,
  ].filter(Boolean).join(" · ");
  return <>
    <span className="pill settings__pill--owed">{parts || `${setup.blocking} months`} cannot be calculated</span>
    <Link className="settings__fix" to={`/affiliates/${row.id}/compensation`}>
      {/* Only a model with no terms at all is known to need terms; a gap
          later on may be a guarantee outcome or unconfirmed targets instead. */}
      {!setup.first_gap
        ? "Set the months →"
        : row.earliest_terms_month
          ? `Fix from ${formatMonth(setup.first_gap)} →`
          : `Write her terms from ${formatMonth(setup.first_gap)} →`}
    </Link>
  </>;
}

/** The export's Historical setup opens on eight and expands to the whole list. */
const HISTORICAL_PREVIEW = 8;

function SetupRoster({ session }: { session: Session }) {
  const [rows, setRows] = useState<SetupRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [expanded, setExpanded] = useState(false);
  useEffect(() => {
    let live = true;
    api.get<{ affiliates: SetupRow[] }>("/api/affiliates?include_archived=true")
      // H1: models who have started. An applicant has no history to work out,
      // and listing her as *No month can be worked out* padded the list.
      .then((body) => { if (live) setRows(body.affiliates.filter((row) =>
        row.account_kind === "model" && row.status !== "pending" && row.status !== "declined")); })
      .catch((caught) => { if (live) setError(caught.message); });
    return () => { live = false; };
  }, []);
  if (error) return <p className="notice notice--refused" role="alert">{error}</p>;
  if (!rows) return <p className="empty">Loading…</p>;

  // H2: whoever needs something first, so nobody hides behind *Show all*.
  const sorted = [...rows].sort((a, b) =>
    Number(needsSomething(b)) - Number(needsSomething(a)) || a.name.localeCompare(b.name));
  const waiting = sorted.filter(needsSomething).length;
  const shownRows = expanded ? sorted : sorted.slice(0, Math.max(HISTORICAL_PREVIEW, waiting));

  return <section className="panel">
    <div className="panel__head">
      <h2 className="panel__title">Historical setup</h2>
      <span className="settings__head-note">
        {rows.length - waiting} ready · {waiting} {waiting === 1 ? "needs" : "need"} something
      </span>
    </div>
    <table className="table settings__table settings__hist">
      <thead><tr>
        <th>Model</th><th>Started</th><th>Terms from</th><th>What is needed</th>
      </tr></thead>
      <tbody>{shownRows.map((row) => <tr key={row.id}>
        <td><Link to={`/affiliates/${row.id}`}>{row.name}</Link></td>
        <td>{row.collaboration_start_month ? formatMonth(row.collaboration_start_month) : <span className="settings__gap">Not recorded</span>}</td>
        <td>{row.earliest_terms_month ? formatMonth(row.earliest_terms_month) : <span className="settings__gap">None written</span>}</td>
        <td className="settings__need">{historicalState(row)}</td>
      </tr>)}</tbody>
    </table>
    {rows.length === 0 && <p className="empty">No model has started yet.</p>}
    {!expanded && sorted.length > shownRows.length && (
      <div className="settings__pad settings__rule">
        <button type="button" className="button" onClick={() => setExpanded(true)}>Show all {rows.length} models</button>
      </div>
    )}
    <div className="settings__pad settings__rule"><HistoricalReview session={session} /></div>
  </section>;
}

// ── Brand codes ───────────────────────────────────────────────────────────

const CODE_STATE: Record<string, [string, string]> = {
  active: ["Active", "ok"],
  inactive: ["Paused", "owed"],
  archived: ["Retired", "off"],
  // A house account waits in *pending* only while Shopify has not confirmed
  // its code.
  pending: ["Not confirmed", "owed"],
};

function BrandCodes({ session }: { session: Session }) {
  const [rows, setRows] = useState<SetupRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [showRetired, setShowRetired] = useState(false);
  const [code, setCode] = useState("");
  const [purpose, setPurpose] = useState("");
  const [working, setWorking] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [problem, setProblem] = useState<string | null>(null);

  const load = useCallback(() => {
    api.get<{ affiliates: SetupRow[] }>("/api/affiliates?include_archived=true")
      .then((body) => setRows(body.affiliates.filter((row) => row.account_kind === "house")))
      .catch((caught) => setError(caught.message));
  }, []);
  useEffect(load, [load]);

  async function add(event: React.FormEvent) {
    event.preventDefault();
    setWorking(true);
    setProblem(null);
    setNotice(null);
    const typed = code.trim().toUpperCase();
    try {
      const made = await api.post<{ status?: string }>("/api/affiliates/house", {
        name: purpose.trim() || typed,
        code: typed,
      });
      setNotice(made.status === "active"
        ? `${typed} is confirmed by Shopify and counting.`
        : `${typed} is saved, but Shopify does not know it yet - it starts counting once it is confirmed.`);
      setCode("");
      setPurpose("");
      load();
    } catch (caught) {
      setProblem(caught instanceof Error ? caught.message : "Could not add it.");
    } finally {
      setWorking(false);
    }
  }

  if (error) return <p className="notice notice--refused" role="alert">{error}</p>;
  if (!rows) return <p className="empty">Loading…</p>;
  const retired = rows.filter((row) => row.status === "archived");
  const shown = showRetired ? rows : rows.filter((row) => row.status !== "archived");

  return (
    <section className="panel">
      <table className="table settings__table">
        <thead><tr>
          <th>Code</th><th>Purpose</th><th className="numeric">Orders this month</th><th>State</th>
        </tr></thead>
        <tbody>{shown.map((row) => {
          const [words, tone] = CODE_STATE[row.status] ?? [row.status, "off"];
          return <tr key={row.id}>
            <td><Link to={`/affiliates/${row.id}`}>{row.code || "No code"}</Link></td>
            <td className="settings__muted">{row.name === row.code ? "—" : row.name}</td>
            <td className="numeric">{row.uses ?? 0}</td>
            <td><span className={`pill settings__pill--${tone}`}>{words}</span></td>
          </tr>;
        })}</tbody>
      </table>
      {shown.length === 0 && <p className="settings__none">No brand codes yet.</p>}
      {retired.length > 0 && (
        <div className="settings__pad settings__rule">
          <button type="button" className="settings__link-button" onClick={() => setShowRetired(!showRetired)}>
            {showRetired ? "Hide retired" : `Show retired (${retired.length})`}
          </button>
        </div>
      )}
      <div className="settings__pad settings__rule">
        {can(session, "affiliates.manage") && (
          <form className="settings__invite-row" onSubmit={add}>
            <input className="input settings__code-input" value={code} onChange={(event) => setCode(event.target.value)}
              placeholder="New code, e.g. WINTER26" aria-label="New code" required />
            <input className="input settings__invite-email" value={purpose} onChange={(event) => setPurpose(event.target.value)}
              placeholder="Purpose (optional)" aria-label="Purpose" />
            <button type="submit" className="button button--primary settings__invite-send" disabled={working || !code.trim()}>
              {working ? "Asking Shopify…" : "Add code"}
            </button>
          </form>
        )}
        {problem && <p className="notice notice--refused" role="alert">{problem}</p>}
        {notice && <p className="notice notice--settled" role="status">{notice}</p>}
        <p className="settings__note settings__note--tail">
          Checked with Shopify before it is saved. HBA's own codes do not belong
          to a model, carry no pay and are excluded from model rankings and
          active counts.
        </p>
      </div>
    </section>
  );
}

// ── Pay policy ────────────────────────────────────────────────────────────

type PolicyVersionRow = {
  id: number;
  effective_month: string;
  summary_markdown: string;
  created_at: string;
};

/**
 * §16, Phase 10 Batch C. The commission rules in the words a model reads -
 * linked from her own statement of each month.
 *
 * **A new version, never an edit.** Every payroll snapshot freezes which
 * version it was calculated under. The text is written beside a preview of
 * exactly what she will see (R5), because a policy written blind is how a
 * typo reaches twenty models.
 */
function PolicyPanel() {
  const [versions, setVersions] = useState<PolicyVersionRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [adding, setAdding] = useState(false);
  const [effectiveMonth, setEffectiveMonth] = useState(currentMonth());
  const [text, setText] = useState("");
  const [working, setWorking] = useState(false);

  const load = useCallback(() => {
    api.get<{ versions: PolicyVersionRow[] }>("/api/policy/versions")
      .then((body) => setVersions(body.versions)).catch((caught) => setError(caught.message));
  }, []);
  useEffect(load, [load]);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setWorking(true);
    setError(null);
    try {
      await api.post("/api/policy/versions", { effective_month: effectiveMonth, summary_markdown: text });
      setText("");
      setAdding(false);
      load();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Could not save that.");
    } finally {
      setWorking(false);
    }
  }

  const now = currentMonth();
  const all = versions ?? [];
  const newest = all.length > 0 ? all[all.length - 1] : null;
  // The first month the server will take: this one, or the month after the
  // newest version when that is already this month or later. The picker
  // offered earlier months the server then refused.
  const firstAllowed = newest && newest.effective_month >= now ? monthAdd(newest.effective_month, 1) : now;
  const inForce = [...all].reverse().find((version) => version.effective_month <= now) ?? null;
  const upcoming = all.filter((version) => version.effective_month > now);
  const earlier = all.filter((version) => version !== inForce && version.effective_month <= now).reverse();

  return (
    <>
      <section className="panel">
        <div className="panel__head">
          <h2 className="panel__title">Pay policy</h2>
          <span className="settings__head-note">What every model reads about her pay</span>
        </div>
        <div className="settings__pad">
          {error && <p className="notice notice--refused" role="alert">{error}</p>}
          {versions === null ? <p className="empty">Loading…</p> : all.length === 0 ? (
            <p className="settings__note">
              None written yet. Every settled month shows that no rules were in
              force - add the first version below.
            </p>
          ) : <>
            {upcoming.map((version) => (
              <PolicyCard key={version.id} version={version} tag={`Starts ${formatMonth(version.effective_month)}`} tone="owed" />
            ))}
            {inForce && <PolicyCard version={inForce} tag={`In force from ${formatMonth(inForce.effective_month)}`} tone="ok" />}
            {earlier.length > 0 && (
              <details className="settings__earlier">
                <summary>Earlier versions ({earlier.length})</summary>
                {earlier.map((version) => (
                  <PolicyCard key={version.id} version={version} tag={`From ${formatMonth(version.effective_month)}`} tone="off" />
                ))}
              </details>
            )}
          </>}
          {!adding && (
            <button type="button" className="button settings__policy-add" onClick={() => { setAdding(true); setEffectiveMonth(firstAllowed); }}>
              Write a new version
            </button>
          )}
        </div>
      </section>

      {adding && (
        <section className="panel">
          <form onSubmit={submit}>
            <div className="panel__head">
              <h2 className="panel__title">New version</h2>
              <label className="settings__head-note settings__inline-field">
                From
                {/* From this month (or the newest version's, if later) to the
                 *  end of next year; the server still decides what may be saved. */}
                <MonthPicker value={effectiveMonth} onChange={setEffectiveMonth} size="section" label={false}
                  months={monthsBetween(firstAllowed, `${Number(now.slice(0, 4)) + 1}-12`)} />
              </label>
            </div>
            <div className="settings__pad">
              <p className="settings__note">
                {newest
                  ? `Must start later than ${formatMonth(newest.effective_month)}. Months already agreed keep the words they were agreed under.`
                  : "Every month from here onward reads this version."}
              </p>
              <div className="settings__split">
                <label className="field">
                  <span className="field__label">The text</span>
                  <textarea className="input settings__policy-text" rows={12} required value={text}
                    onChange={(event) => setText(event.target.value)}
                    placeholder={"## How commission works\n\nCommission is worked out on..."} />
                  <span className="field__hint">`## ` starts a heading and `**text**` is bold - nothing else is read specially.</span>
                </label>
                <div className="field">
                  <span className="field__label">What a model will see</span>
                  <div className="settings__preview">
                    {text.trim() ? <PolicyText markdown={text} /> : <p className="settings__muted">The preview appears as you type.</p>}
                  </div>
                </div>
              </div>
              <div className="settings__acts">
                <button type="button" className="button" onClick={() => { setAdding(false); setError(null); }} disabled={working}>Cancel</button>
                <button type="submit" className="button button--primary" disabled={working || !text.trim()}>
                  {working ? "Saving…" : "Save this version"}
                </button>
              </div>
            </div>
          </form>
        </section>
      )}
    </>
  );
}

function PolicyCard({ version, tag, tone }: { version: PolicyVersionRow; tag: string; tone: string }) {
  return (
    <article className="settings__policy">
      <span className={`pill settings__pill--${tone}`}>{tag}</span>
      <PolicyText markdown={version.summary_markdown} />
    </article>
  );
}

// ── Activity log ──────────────────────────────────────────────────────────

const KIND_LABEL: Record<string, string> = {
  money: "Money",
  access: "Access",
  models: "Models",
  content: "Content",
  settings: "Settings",
  inbox: "Inbox",
};

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

function ActivityPanel() {
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
    api.get<Filters>("/api/audit/filters").then(setFilters).catch(() => undefined);
  }, []);

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
    if (before) out.set("before", String(before));
    return out.toString();
  }, [search, model, person, kind, signIns]);

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
  const narrowed = Boolean(search || model || person || kind);

  return (
    <>
      <section className="panel">
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
            {(filters?.kinds ?? Object.keys(KIND_LABEL)).map((value) => (
              <button key={value} type="button" className={`chip${kind === value ? " chip--on" : ""}`} aria-pressed={kind === value}
                onClick={() => setKind(kind === value ? "" : value)}>{KIND_LABEL[value] ?? value}</button>
            ))}
            <button type="button" className={`chip${signIns ? " chip--on" : ""}`} aria-pressed={signIns} onClick={() => setSignIns(!signIns)}>
              Include sign-ins
            </button>
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

// ── My preferences ────────────────────────────────────────────────────────

const THEME_WORDS: [ThemeChoice, string][] = [["dark", "Dark"], ["light", "Light"], ["system", "Match my device"]];

/**
 * The theme, saved on the account so it follows this person between devices
 * (P1). It paints at once and is put back if the server refuses.
 */
function AppearancePanel() {
  const [theme, setTheme] = useState<ThemeChoice>(() => storedMaintainerChoice());
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  // The account's choice is the one that holds. This device's copy can be a
  // step behind it on the first visit from a new laptop, and a radio that
  // shows the wrong side cannot be pressed back to the right one.
  useEffect(() => {
    let live = true;
    api.get<{ theme: ThemeChoice | null }>("/api/staff/me/preferences")
      .then((body) => { if (live && body.theme && !themePickedThisVisit()) setTheme(body.theme); })
      .catch(() => undefined);
    return () => { live = false; };
  }, []);

  async function choose(value: ThemeChoice) {
    if (saving) return;
    const before = theme;
    setTheme(value);
    pickMaintainerChoice(value);
    setError(null);
    setSaving(true);
    try {
      await api.put("/api/staff/me/theme", { theme: value });
    } catch (caught) {
      setTheme(before);
      pickMaintainerChoice(before);
      setError(`${caught instanceof Error ? caught.message : "Could not save that."} Nothing changed.`);
    } finally {
      setSaving(false);
    }
  }

  return <>
    <section className="panel settings__appearance">
      <span>Theme<small>Saved to your account, so it follows you to any device</small></span>
      <div className="seg" role="radiogroup" aria-label="Theme">{THEME_WORDS.map(([value, words]) =>
        <label key={value} className="seg-opt">
          <input type="radio" name="admin-theme" checked={theme === value} disabled={saving} onChange={() => choose(value)} />
          <span>{words}</span>
        </label>)}</div>
    </section>
    {error && <p className="notice notice--refused" role="alert">{error}</p>}
    <PreferenceSwitches />
    <TwoStepPanel />
    <DevicesPanel />
  </>;
}

type TwoStepMode = "idle" | "setup" | "renew" | "off" | "codes";

/**
 * Two-step sign-in for the signed-in person. Setting up, new recovery codes
 * and turning off each ask for a code, so a borrowed laptop cannot change it.
 * Turning off is not offered when their access needs it.
 */
function TwoStepPanel() {
  const [status, setStatus] = useState<TwoStepStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [mode, setMode] = useState<TwoStepMode>("idle");
  // Held only while they are on screen; cleared as soon as they are saved.
  const [codes, setCodes] = useState<string[] | null>(null);

  const load = useCallback(() => {
    twoStep.status().then(setStatus)
      .catch((caught) => setError(caught instanceof Error ? caught.message : "Could not load this."));
  }, []);
  useEffect(load, [load]);

  const finish = () => { setCodes(null); setMode("idle"); load(); };

  return (
    <section className="panel" aria-labelledby="twostep-title">
      <div className="panel__head">
        <h2 className="panel__title" id="twostep-title">Two-step sign-in</h2>
        {status && <span className={`pill ${status.enabled ? "twostep__on" : "twostep__off"}`}>{status.enabled ? "On" : "Off"}</span>}
      </div>
      <div className="twostep__panel-body">
        {error && <p className="notice notice--refused" role="alert">{error}</p>}
        {status && mode === "idle" && <>
          <p className="settings__explain-line">
            {status.required && <b>Required for your access. </b>}
            {status.enabled
              ? `Signing in asks for a code from your phone. ${status.recovery_codes_left} recovery ${status.recovery_codes_left === 1 ? "code" : "codes"} left.`
              : "Signing in asks for a code from your phone, as well as your password."}
          </p>
          <div className="twostep__acts">
            {!status.enabled && <button type="button" className="button button--primary" onClick={() => setMode("setup")}>Set up two-step sign-in</button>}
            {status.enabled && <button type="button" className="button" onClick={() => setMode("renew")}>New recovery codes</button>}
            {status.enabled && !status.required && <button type="button" className="button lifecycle__danger" onClick={() => setMode("off")}>Turn off</button>}
          </div>
        </>}
        {mode === "setup" && <TwoStepSetup onDone={finish} onCancel={() => setMode("idle")} />}
        {mode === "renew" && <CodeForm
          label="6-digit code"
          hint="Your old recovery codes stop working."
          action="Make new recovery codes"
          onCancel={() => setMode("idle")}
          onSubmit={async (code) => { setCodes((await twoStep.newRecoveryCodes(code)).recovery_codes); setMode("codes"); }} />}
        {mode === "codes" && codes && <RecoveryCodes codes={codes} onSaved={finish} />}
        {mode === "off" && <CodeForm
          label="6-digit code"
          action="Turn off two-step sign-in"
          danger
          onCancel={() => setMode("idle")}
          onSubmit={async (code) => { await twoStep.turnOff(code); finish(); }} />}
      </div>
    </section>
  );
}

/** Where this account is signed in, with a way to end any of it. */
function DevicesPanel() {
  const [list, setList] = useState<DeviceSession[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [working, setWorking] = useState<number | "others" | null>(null);

  const load = useCallback(() => {
    devices.mine().then((body) => setList(body.sessions))
      .catch((caught) => setError(caught instanceof Error ? caught.message : "Could not load this."));
  }, []);
  useEffect(load, [load]);

  async function end(which: number | "others") {
    setWorking(which);
    setError(null);
    try {
      await (which === "others" ? devices.endOthers() : devices.endOne(which));
      load();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "That did not go through.");
    } finally {
      setWorking(null);
    }
  }

  const others = (list ?? []).filter((device) => !device.current);
  return (
    <section className="panel" aria-labelledby="devices-title">
      <div className="panel__head"><h2 className="panel__title" id="devices-title">Signed in on</h2></div>
      {error && <p className="notice notice--refused" role="alert">{error}</p>}
      {list === null && !error && <p className="empty">Loading…</p>}
      {list && <ul className="settings__devices" aria-label="Devices">
        {list.map((device) => <DeviceLine key={device.id} device={device} action={device.current ? undefined :
          <button type="button" className="button button--row" disabled={working !== null}
            aria-label={`Sign out ${device.device}`} onClick={() => end(device.id)}>Sign out</button>} />)}
      </ul>}
      {others.length > 0 && <div className="twostep__panel-body">
        <div className="twostep__acts">
          <button type="button" className="button" disabled={working !== null} onClick={() => end("others")}>
            Sign out of every other device
          </button>
        </div>
      </div>}
    </section>
  );
}

type Preferences = {
  preferences: Record<string, boolean>;
  labels: Record<string, string>;
  /** One line under each switch saying what it does (P2). */
  descriptions?: Record<string, string>;
  theme?: ThemeChoice | null;
};

/**
 * The export's two switches (`prefRows`, Admin lines 749-757), **saved on the
 * server for this account**, so they hold after a reload and on another
 * device. A switch moves when the server has said so, not before; a refusal
 * leaves it where it was and says why.
 */
export function PreferenceSwitches() {
  const [body, setBody] = useState<Preferences | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState<string | null>(null);

  useEffect(() => {
    api.get<Preferences>("/api/staff/me/preferences").then(setBody)
      .catch((caught) => setError(caught instanceof Error ? caught.message : "Could not load these."));
  }, []);

  async function toggle(key: string) {
    if (!body) return;
    setSaving(key);
    setError(null);
    try {
      setBody(await api.put<Preferences>("/api/staff/me/preferences", { key, enabled: !body.preferences[key] }));
    } catch (caught) {
      setError(`${caught instanceof Error ? caught.message : "Could not save that."} Nothing changed.`);
    } finally {
      setSaving(null);
    }
  }

  return <>
    {body && <div className="settings__switches">
      {Object.entries(body.labels).map(([key, label]) => {
        const on = body.preferences[key];
        const hint = body.descriptions?.[key];
        return <button key={key} type="button" role="switch" aria-checked={on} aria-label={label} disabled={saving === key}
          className="settings__switch" onClick={() => toggle(key)}>
          <span className="settings__switch-words">{label}{hint && <small>{hint}</small>}</span>
          <span className={`settings__track${on ? " settings__track--on" : ""}`} aria-hidden="true"><span /></span>
        </button>;
      })}
    </div>}
    {error && <p className="notice notice--refused settings__switch-error" role="alert">{error}</p>}
  </>;
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="settings__fact">
      <dt>{label}</dt>
      <dd>{children}</dd>
    </div>
  );
}
