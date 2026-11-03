import { useCallback, useEffect, useRef, useState } from "react";

import { api, can, devices, trustedBrowsers } from "../../lib/api";
import type { DeviceSession, Session, TrustedBrowser } from "../../lib/api";
import { CodeForm } from "../../components/TwoStepSetup";
import { BrowserLine, DeviceLine, lastSeen } from "./DeviceLines";
import "../../departments/affiliates/ModelLifecycle.css";
import "../Settings.css";

type StaffRow = {
  id: number;
  email: string;
  display_name: string | null;
  /** Every staff role held now, widest first (ADR 0067: several per person). */
  roles: string[];
  status: "invited" | "active" | "suspended";
  /** Two-step sign-in is on for them (Batch 1.3). */
  two_step_enabled?: boolean;
  /** Which kind: an authenticator app, or codes by email (Batch 1.3b). */
  two_step_method?: "authenticator" | "email" | null;
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
  ["Build the Khazenly confirmation file", ["khazenly.use"]],
  ["Invite staff, up to their own access", ["invitations.send"]],
  ["Record payments and reopen approved months", ["payments.record", "payroll.reopen"]],
  ["Change anyone's access, Shopify and the pay policy; erase a model", ["settings.manage", "affiliates.erase"]],
];

function holds(permissions: string[] | undefined, line: string[]) {
  return !!permissions && line.every((permission) => permissions.includes(permission));
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


function DevicesDialog({ row, onClose, onChanged }: { row: StaffRow; onClose: () => void; onChanged: () => void }) {
  const name = row.display_name || row.email;
  const [list, setList] = useState<DeviceSession[] | null>(null);
  const [remembered, setRemembered] = useState<TrustedBrowser[]>([]);
  const [problem, setProblem] = useState<string | null>(null);
  const [working, setWorking] = useState(false);

  const load = useCallback(() => {
    trustedBrowsers.of(row.id).then((body) => setRemembered(body.browsers)).catch(() => undefined);
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
      setRemembered([]);
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
      {remembered.length > 0 && <>
        <h3 className="twostep__sub">Remembered browsers</h3>
        <ul className="settings__devices" aria-label={`Remembered browsers for ${name}`}>
          {remembered.map((browser) => <BrowserLine key={browser.id} browser={browser} />)}
        </ul>
      </>}
      <div className="lifecycle__acts">
        <button type="button" className="button" onClick={onClose}>Close</button>
        <button type="button" className="button lifecycle__danger" onClick={endAll}
          disabled={working || !list || (list.length === 0 && remembered.length === 0)}>
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
                        <svg className="twostep__lock" role="img"
                          aria-label={row.two_step_method === "email" ? "Two-step sign-in on, code by email"
                            : row.two_step_method === "authenticator" ? "Two-step sign-in on, authenticator app"
                            : "Two-step sign-in on"} viewBox="0 0 24 24"
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
                              {row.two_step_enabled && row.two_step_method !== "email" && (
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


/** `/settings/team`: who has access and what each can do. The owner's. */
export function Team({ session }: { session: Session }) {
  return <>
    <div className="page__head"><div className="page__title"><h1>Team and access</h1></div></div>
    <div className="settings__sections"><RosterPanel session={session} /></div>
  </>;
}
