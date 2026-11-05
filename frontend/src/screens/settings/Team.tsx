import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";

import { api, devices, roleWords as storedRoleWords, trustedBrowsers } from "../../lib/api";
import type { DeviceSession, Session, TrustedBrowser } from "../../lib/api";
import { CodeForm } from "../../components/TwoStepSetup";
import { BrowserLine, DeviceLine, lastSeen } from "./DeviceLines";
import {
  ACCESS_LINES, LEVELS, LEVEL_WORDS, ROLE_BLURB, accessWordsOf, givesSentence, grantedBy, holds,
  levelIn, roleOf, rolesOfDepartment, rolesWords,
} from "./teamAccess";
import type { Department, Level } from "./teamAccess";
import "../../departments/affiliates/ModelLifecycle.css";
import "../Settings.css";
import "./Team.css";

/** The stored name of the owner's role (shown as "Owner"). */
const OWNER_ROLE = "admin";

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
  /** Batch 2.4 contract §3. */
  owner?: boolean;
  access?: Record<string, Level>;
  access_words?: string;
  /** The server's own answer to *is two-step asked of them* (Batch 2.4 review). */
  two_step_required?: boolean;
  joined_at?: string | null;
};

type InvitationRow = {
  id: number;
  email: string;
  role: string;
  access_words?: string;
  sent_at?: string | null;
  expires_at: string;
  expired: boolean;
  created_at: string | null;
};

type Roster = {
  staff: StaffRow[];
  invitations: InvitationRow[];
  assignable_roles: string[];
  /** Only access the signed-in person holds themselves, all their roles
   *  together (`can_grant`). What the invite form offers. */
  invitable_roles: string[];
  /** What each role grants, from the server's own list (T4). */
  role_permissions: Record<string, string[]>;
  departments?: Department[];
  role_words?: Record<string, string>;
};

const nameOf = (row: StaffRow) => row.display_name || row.email;
const firstNameOf = (row: StaffRow) => (row.display_name || row.email.split("@")[0]).trim().split(/\s+/)[0];

function initialsOf(text: string): string {
  const words = text.split("@")[0].trim().split(/[\s._-]+/).filter(Boolean);
  const letters = words.length >= 2 ? words[0][0] + words[1][0] : (words[0] ?? "?").slice(0, 1);
  return letters.toUpperCase();
}

const dayWords = (iso: string) =>
  new Intl.DateTimeFormat("en-GB", { timeZone: "Africa/Cairo", day: "numeric", month: "long" }).format(new Date(iso));

/** *sent yesterday*, *sent today*, *sent 21 October*. */
function sentWords(iso: string | null | undefined): string {
  if (!iso) return "sent";
  const seen = lastSeen(iso);
  if (seen.startsWith("Today")) return "sent today";
  if (seen === "Yesterday") return "sent yesterday";
  return `sent ${dayWords(iso)}`;
}

function DeptIcon({ name }: { name: string }) {
  const common = { fill: "none", stroke: "currentColor", strokeWidth: 2, strokeLinecap: "round" as const, strokeLinejoin: "round" as const };
  return (
    <svg className="team__ic" viewBox="0 0 24 24" aria-hidden="true" focusable="false">
      {name === "inbox" && <path d="M4 5h16v11h-6l-2 3-2-3H4z" {...common} />}
      {name === "operations" && <><path d="M3 7h11v9H3zM14 10h4l3 3v3h-7z" {...common} /><circle cx="7" cy="17.5" r="1.6" {...common} /><circle cx="17" cy="17.5" r="1.6" {...common} /></>}
      {name === "affiliates" && <><circle cx="9" cy="8" r="3" {...common} /><path d="M3 19c0-3 2.7-5 6-5s6 2 6 5M16 5.5a3 3 0 0 1 0 5.5M18 14c2 .6 3 2.2 3 4.5" {...common} /></>}
    </svg>
  );
}

function Lock({ method }: { method?: StaffRow["two_step_method"] }) {
  return (
    <svg className="team__lock" role="img"
      aria-label={method === "email" ? "Two-step sign-in on, code by email"
        : method === "authenticator" ? "Two-step sign-in on, authenticator app"
        : "Two-step sign-in on"} viewBox="0 0 24 24"
      fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <rect x="5" y="11" width="14" height="9" rx="2" /><path d="M8 11V8a4 4 0 0 1 8 0v3" />
    </svg>
  );
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

// ── A person's page ─────────────────────────────────────────────────────────

type Pending =
  | { kind: "level"; row: StaffRow; dept: Department; level: Level }
  | { kind: "owner"; row: StaffRow; give: boolean }
  | { kind: "suspend"; row: StaffRow }
  | { kind: "reactivate"; row: StaffRow }
  | { kind: "reset"; row: StaffRow };

/** The four levels of one department as a segmented control. Levels not offered are drawn, and cannot be chosen. */
function LevelControl({ dept, current, locked, onChoose }: {
  dept: Department;
  current: Level;
  locked: boolean;
  onChoose: (level: Level) => void;
}) {
  const group = useRef<HTMLDivElement>(null);

  function move(event: React.KeyboardEvent, step: 1 | -1) {
    const stops = Array.from(group.current?.querySelectorAll<HTMLButtonElement>("button:not([disabled])") ?? []);
    const at = stops.indexOf(document.activeElement as HTMLButtonElement);
    if (at < 0 || stops.length === 0) return;
    event.preventDefault();
    stops[(at + step + stops.length) % stops.length].focus();
  }

  return (
    <div ref={group} className="team__seg" role="radiogroup" aria-label={`${dept.name} access`}
      aria-disabled={locked || undefined}
      onKeyDown={(event) => {
        if (event.key === "ArrowRight" || event.key === "ArrowDown") move(event, 1);
        if (event.key === "ArrowLeft" || event.key === "ArrowUp") move(event, -1);
      }}>
      {LEVELS.map((level) => {
        const entry = dept.levels.find((candidate) => candidate.level === level);
        const offered = entry?.offered ?? false;
        return (
          <button key={level} type="button" role="radio" aria-checked={current === level}
            tabIndex={current === level ? 0 : -1}
            disabled={locked || !offered}
            title={offered ? undefined : "Not offered yet"}
            onClick={() => { if (current !== level) onChoose(level); }}>
            {LEVEL_WORDS[level]}
            {!offered && <span className="visually-hidden"> Not offered yet</span>}
          </button>
        );
      })}
    </div>
  );
}

function TwoStepPanel({ row, you, required, onReset }: {
  row: StaffRow;
  you: boolean;
  required: boolean;
  onReset: () => void;
}) {
  const first = firstNameOf(row);
  const on = !!row.two_step_enabled;
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState<string | null>(null);
  const [problem, setProblem] = useState<string | null>(null);

  async function remind() {
    setBusy(true);
    setProblem(null);
    setDone(null);
    try {
      const result = await api.post<{ emailed?: boolean }>(`/api/staff/${row.id}/two-step/remind`);
      setDone(result?.emailed === false ? "Saved, but this server sends no email." : `A reminder was emailed to ${first}.`);
    } catch (caught) {
      setProblem(caught instanceof Error ? caught.message : "That did not go through.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="panel" aria-labelledby="twostep-title">
      <div className="panel__head">
        <h2 className="panel__title" id="twostep-title">Two-step sign-in</h2>
        <span className={`team__state${on ? " team__state--on" : ""}`}>{on ? "On" : "Off"}</span>
      </div>
      <p className="team__para">
        {on
          ? <>On for {first}{row.two_step_method === "email" ? ", with a code sent by email" : ", with an authenticator app"}.</>
          : required
            ? <><b>Required for {first}&apos;s access</b>, and not on yet. Required for anyone who approves or pays money, and for the owner.</>
            : <>Not required for {first}&apos;s access. <b>Required for anyone who approves or pays money</b>, and for the owner.</>}
      </p>
      {problem && <p className="notice notice--refused team__pad" role="alert">{problem}</p>}
      {done && <p className="team__para" role="status">{done}</p>}
      {!you && row.status !== "suspended" && (
        <div className="team__foot">
          {!on && (
            <button type="button" className="button button--row" disabled={busy} onClick={remind}>
              {busy ? "Sending…" : "Send a reminder"}
            </button>
          )}
          {on && row.two_step_method !== "email" && (
            <button type="button" className="button button--row" onClick={onReset}>Reset two-step sign-in…</button>
          )}
        </div>
      )}
    </section>
  );
}

function SignedInOn({ row, you, onChanged }: { row: StaffRow; you: boolean; onChanged: () => void }) {
  const [list, setList] = useState<DeviceSession[] | null>(null);
  const [remembered, setRemembered] = useState<TrustedBrowser[]>([]);
  const [problem, setProblem] = useState<string | null>(null);
  const [working, setWorking] = useState(false);

  useEffect(() => {
    let alive = true;
    setList(null);
    setRemembered([]);
    setProblem(null);
    trustedBrowsers.of(row.id).then((body) => { if (alive) setRemembered(body.browsers); }).catch(() => undefined);
    devices.of(row.id).then((body) => { if (alive) setList(body.sessions); })
      .catch((caught) => { if (alive) setProblem(caught instanceof Error ? caught.message : "Could not load this."); });
    return () => { alive = false; };
  }, [row.id]);

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

  const name = nameOf(row);
  return (
    <section className="panel" aria-labelledby="devices-title">
      <div className="panel__head"><h2 className="panel__title" id="devices-title">Signed in on</h2></div>
      {problem && <p className="notice notice--refused team__pad" role="alert">{problem}</p>}
      {list === null && !problem && <p className="empty">Loading…</p>}
      {list && list.length === 0 && <p className="team__para">Not signed in anywhere.</p>}
      {list && list.length > 0 && (
        <ul className="settings__devices" aria-label={`Devices for ${name}`}>
          {list.map((device) => <DeviceLine key={device.id} device={device} />)}
        </ul>
      )}
      {remembered.length > 0 && (
        <>
          <h3 className="twostep__sub team__sub">Remembered browsers</h3>
          <ul className="settings__devices" aria-label={`Remembered browsers for ${name}`}>
            {remembered.map((browser) => <BrowserLine key={browser.id} browser={browser} />)}
          </ul>
        </>
      )}
      {!you && (
        <div className="team__foot">
          <button type="button" className="button button--row" onClick={endAll}
            disabled={working || !list || (list.length === 0 && remembered.length === 0)}>
            {working ? "Working…" : "Sign out of every device"}
          </button>
        </div>
      )}
    </section>
  );
}

function PersonPage({ row, roster, you, ask, reload }: {
  row: StaffRow;
  roster: Roster;
  you: boolean;
  ask: (action: Pending) => void;
  reload: () => void;
}) {
  const name = nameOf(row);
  const first = firstNameOf(row);
  const suspended = row.status === "suspended";
  const owner = row.owner ?? row.roles.includes("admin");
  const departments = roster.departments ?? [];
  const joined = row.joined_at ?? row.created_at;
  const permissions = grantedBy(row.roles, roster.role_permissions);
  // Two-step is asked of whoever approves or pays money, and of the owner.
  const required = row.two_step_required ?? (owner || permissions.some((permission) =>
    permission === "payroll.approve" || permission === "payments.record" || permission === "settings.manage"));
  const locked = you || suspended || owner;
  const canGiveOwner = roster.invitable_roles.includes("admin");

  return (
    <div className="stack team__person">
      <section className="panel" aria-labelledby="person-title">
        <div className="panel__head team__namehead">
          <h2 className="panel__title" id="person-title">
            {name}
            {you && <span className="settings__you">You</span>}
            {suspended && <span className="team__state team__state--suspended">Suspended</span>}
          </h2>
          <p className="team__hint">{row.email}{joined && ` · joined ${dayWords(joined)}`}</p>
        </div>

        <div className="team__owner">
          <span><b>Owner</b> — every department, Settings and money</span>
          {owner && <span className="team__state team__state--on">Owner</span>}
          {!you && !suspended && (owner
            ? <button type="button" className="button button--row"
                onClick={() => ask({ kind: "owner", row, give: false })}>Take ownership</button>
            : canGiveOwner && <button type="button" className="button button--row"
                onClick={() => ask({ kind: "owner", row, give: true })}>Make owner</button>)}
        </div>

        <table className="access">
          <tbody>
            {departments.map((dept) => {
              const current = (row.access?.[dept.key] as Level | undefined) ?? levelIn(dept, row.roles);
              const role = roleOf(dept, current);
              return (
                <tr key={dept.key}>
                  <td><span className="dept-cell"><DeptIcon name={dept.key} />{dept.name}</span></td>
                  <td>
                    <LevelControl dept={dept} current={current} locked={locked}
                      onChoose={(level) => ask({ kind: "level", row, dept, level })} />
                  </td>
                  <td>{owner ? "The owner reaches every department." : (role && ROLE_BLURB[role]) || "–"}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
        {you && <p className="team__note">You cannot change your own access. Another owner changes yours.</p>}
        {suspended && <p className="team__note">{first} is suspended. Reactivate them to give access.</p>}

        <p className="gives" aria-live="polite">
          <span className="gives__label">What this gives {first}:</span> {suspended ? "nothing while suspended." : givesSentence(first, row.roles, roster.role_permissions)}
        </p>
      </section>

      <div className="secure">
        <TwoStepPanel row={row} you={you} required={required} onReset={() => ask({ kind: "reset", row })} />
        <SignedInOn row={row} you={you} onChanged={reload} />
      </div>

      {!you && (suspended ? (
        <div className="danger">
          <p><b>{name} is suspended.</b> Reactivating gives no access. Give it again from the levels above.</p>
          <button type="button" className="button button--row" onClick={() => ask({ kind: "reactivate", row })}>
            Reactivate {name}
          </button>
        </div>
      ) : (
        <div className="danger">
          <p><b>Suspend {name}.</b> Removes every department and signs out every device at once. The record of what {first} did stays.</p>
          <button type="button" className="button button--danger button--row"
            onClick={() => ask({ kind: "suspend", row })}>Suspend {name}</button>
        </div>
      ))}
    </div>
  );
}

// ── A waiting invitation's page ─────────────────────────────────────────────

function InvitationPage({ row, roster, onChanged, onGone }: {
  row: InvitationRow;
  roster: Roster;
  onChanged: () => void;
  onGone: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [resent, setResent] = useState(false);
  const words = row.access_words ?? (roster.role_words?.[row.role] ?? storedRoleWords(row.role));

  async function act(path: "resend" | "revoke") {
    setBusy(true);
    setError(null);
    setResent(false);
    try {
      // Written out in full, so the reachability check can match each route.
      await api.post(path === "resend" ? `/api/staff/invitations/${row.id}/resend` : `/api/staff/invitations/${row.id}/revoke`);
      if (path === "revoke") onGone(); else setResent(true);
      onChanged();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "That did not go through.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="stack team__person">
      <section className="panel" aria-labelledby="invitation-title">
        <div className="panel__head team__namehead">
          <h2 className="panel__title" id="invitation-title">{row.email}</h2>
          <p className="team__hint">
            {words} · {sentWords(row.sent_at ?? row.created_at)} ·{" "}
            {row.expired
              ? <span className="settings__gap">Link expired {dayWords(row.expires_at)}</span>
              : `expires ${dayWords(row.expires_at)}`}
          </p>
        </div>
        <p className="team__para">
          {row.email} has not joined yet. The invitation gives {words} access once they accept it.
        </p>
        {error && <p className="notice notice--refused team__pad" role="alert">{error}</p>}
        {resent && <p className="team__para" role="status">Sent again.</p>}
        <div className="team__foot">
          <button type="button" className="button button--row" disabled={busy} onClick={() => act("resend")}>Resend</button>
          <button type="button" className={`button button--row${row.expired ? "" : " settings__withdraw"}`}
            disabled={busy} onClick={() => act("revoke")}>
            {row.expired ? "Remove" : "Withdraw"}
          </button>
        </div>
      </section>
    </div>
  );
}

// ── Invite someone ──────────────────────────────────────────────────────────

function InviteDialog({ roster, onClose, onInvited }: { roster: Roster; onClose: () => void; onInvited: () => void }) {
  const words = (role: string) => roster.role_words?.[role] ?? storedRoleWords(role);
  // Only what the signed-in person may give, and only levels offered.
  const options = (roster.departments ?? []).map((dept) => ({
    dept,
    levels: dept.levels.filter((entry) => entry.offered && entry.role && roster.invitable_roles.includes(entry.role)),
  })).filter((option) => option.levels.length > 0);
  const canOwner = roster.invitable_roles.includes("admin");

  const [email, setEmail] = useState("");
  const [where, setWhere] = useState<string>(options[0]?.dept.key ?? (canOwner ? "owner" : ""));
  const [level, setLevel] = useState<string>("");
  const [link, setLink] = useState<string | null>(null);
  const [emailed, setEmailed] = useState(false);
  const [copied, setCopied] = useState<boolean | null>(false);
  const [error, setError] = useState<string | null>(null);
  const [working, setWorking] = useState(false);

  const chosen = options.find((option) => option.dept.key === where);
  // The smallest access first: an invitation is easy to widen and awkward to take back.
  const levelsHere = chosen?.levels ?? [];
  const levelNow = levelsHere.find((entry) => entry.level === level) ?? levelsHere[0];
  const role = where === "owner" ? "admin" : (levelNow?.role ?? "");

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
      onInvited();
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
      setCopied(null);
    }
  }

  return (
    <DialogFrame title="Invite someone" onClose={onClose}>
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
      <form onSubmit={submit} className="team__invite">
        <label className="lifecycle__field">
          <span>Email</span>
          <input className="input" type="email" required value={email}
            onChange={(event) => setEmail(event.target.value)} placeholder="name@hbawear.store" aria-label="Email" />
        </label>
        <label className="lifecycle__field">
          <span>Access</span>
          <select className="input" value={where} aria-label="Department"
            onChange={(event) => { setWhere(event.target.value); setLevel(""); }}>
            {canOwner && <option value="owner">{words("admin")}</option>}
            {options.map((option) => <option key={option.dept.key} value={option.dept.key}>{option.dept.name}</option>)}
          </select>
        </label>
        {where !== "owner" && (
          <label className="lifecycle__field">
            <span>Level</span>
            <select className="input" value={levelNow?.level ?? ""} aria-label="Level"
              onChange={(event) => setLevel(event.target.value)}>
              {levelsHere.map((entry) => <option key={entry.level} value={entry.level}>{LEVEL_WORDS[entry.level]}</option>)}
            </select>
          </label>
        )}
        <p className="team__para team__para--flush">
          {role ? `${email.trim() || "They"} will have ${role === "operations_manager" ? `${words(role)} and ${words("customer_service")}` : words(role)} access.` : "Choose what they can reach."}
        </p>
        <div className="lifecycle__acts">
          <button type="button" className="button" onClick={onClose}>{link ? "Done" : "Cancel"}</button>
          <button type="submit" className="button button--primary" disabled={working || !email.trim() || !role}>
            {working ? "Sending…" : "Send invitation"}
          </button>
        </div>
      </form>
    </DialogFrame>
  );
}

// ── The page ────────────────────────────────────────────────────────────────

const plural = (count: number, one: string, many: string) => `${count} ${count === 1 ? one : many}`;

const LEVEL_RANK: Record<string, number> = { manager: 3, staff: 2, viewer: 1, none: 0 };

/** Where a person sits in the list: the sidebar's department order, then how much, then name. */
function peopleOrder(a: StaffRow, b: StaffRow, departments: Department[]): number {
  const key = (row: StaffRow) => {
    const levels = departments.map((dept) => (row.access?.[dept.key] as Level | undefined) ?? levelIn(dept, row.roles));
    const first = levels.findIndex((level) => level !== "none");
    return {
      suspended: row.status === "suspended" ? 1 : 0,
      owner: row.owner ?? row.roles.includes("admin") ? 0 : 1,
      first: first < 0 ? 99 : first,
      count: levels.filter((level) => level !== "none").length,
      rank: first < 0 ? 0 : LEVEL_RANK[levels[first]],
    };
  };
  const x = key(a);
  const y = key(b);
  return x.suspended - y.suspended || x.owner - y.owner || x.first - y.first || y.count - x.count
    || y.rank - x.rank || nameOf(a).localeCompare(nameOf(b));
}

/** `/settings/team`: who has access, by department, and what each can do. The owner's. */
export function Team({ session }: { session: Session }) {
  const [roster, setRoster] = useState<Roster | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState<Pending | null>(null);
  const [inviting, setInviting] = useState(false);
  const [params, setParams] = useSearchParams();

  const load = useCallback(() => {
    api.get<Roster>("/api/staff").then(setRoster).catch((caught) => setError(caught.message));
  }, []);
  useEffect(load, [load]);

  const staff = roster ? [...roster.staff].sort((a, b) => peopleOrder(a, b, roster.departments ?? [])) : [];
  const invitations = roster?.invitations ?? [];

  const personId = Number(params.get("person")) || null;
  const invitationId = Number(params.get("invitation")) || null;
  const chosen = personId !== null || invitationId !== null;
  const selectedInvitation = invitationId !== null ? invitations.find((row) => row.id === invitationId) ?? null : null;
  const selectedPerson = selectedInvitation ? null
    : (personId !== null ? staff.find((row) => row.id === personId) : undefined) ?? (invitationId === null ? staff[0] ?? null : null);

  const words = (role: string) => roster?.role_words?.[role] ?? storedRoleWords(role);

  function replaceRow(next: StaffRow) {
    setRoster((current) => current && ({
      ...current,
      staff: current.staff.map((row) => (row.id === next.id ? { ...row, ...next } : row)),
    }));
  }

  function dialogFor(action: Pending) {
    const name = nameOf(action.row);
    if (action.kind === "reset") {
      return <ResetTwoStepDialog row={action.row} onClose={() => setPending(null)}
        onDone={() => { setPending(null); load(); }} />;
    }
    if (action.kind === "level" || action.kind === "owner") {
      // ADR 0067: a person holds several roles, and may do everything they
      // grant together - so what changes is read from all of them.
      let afterRoles: string[];
      let title: string;
      let confirm: string;
      let danger = false;
      if (action.kind === "owner") {
        afterRoles = action.give ? [...action.row.roles, "admin"] : action.row.roles.filter((role) => role !== "admin");
        title = action.give ? `Make ${name} the owner?` : `Take ownership from ${name}?`;
        confirm = action.give ? "Make owner" : "Take ownership";
        danger = !action.give;
      } else {
        const departmentRoles = rolesOfDepartment(action.dept);
        const newRole = roleOf(action.dept, action.level);
        const kept = action.row.roles.filter((role) => !departmentRoles.includes(role));
        afterRoles = newRole ? [...kept, newRole] : kept;
        const had = levelIn(action.dept, action.row.roles) !== "none";
        if (!newRole) {
          title = `Take ${action.dept.name} access from ${name}?`;
          confirm = "Remove access";
          danger = true;
        } else if (had) {
          title = `Change ${name} to ${words(newRole)}?`;
          confirm = "Change access";
        } else {
          title = `Give ${name} ${words(newRole)} access?`;
          confirm = "Give access";
        }
      }
      const before = grantedBy(action.row.roles, roster?.role_permissions);
      const after = grantedBy(afterRoles, roster?.role_permissions);
      const gains = ACCESS_LINES.filter(([, line]) => holds(after, line) && !holds(before, line)).map(([text]) => text);
      const loses = ACCESS_LINES.filter(([, line]) => holds(before, line) && !holds(after, line)).map(([text]) => text);
      const lower = (line: string) => `${line.charAt(0).toLowerCase()}${line.slice(1)}`;
      const keeping = action.kind === "owner" ? afterRoles : afterRoles.filter((role) =>
        action.kind === "level" && !rolesOfDepartment(action.dept).includes(role));
      return <ConfirmDialog
        title={title}
        effects={[
          ...gains.map((line) => `Can now: ${lower(line)}`),
          ...loses.map((line) => `Can no longer: ${lower(line)}`),
          keeping.length > 0 ? `Keeps: ${rolesWords(keeping, words)}.` : "Keeps: nothing else.",
          "Takes effect on their very next click.",
        ]}
        confirm={confirm}
        danger={danger}
        onCancel={() => setPending(null)}
        onConfirm={async () => {
          if (action.kind === "owner") {
            try {
              await (action.give
                ? api.post(`/api/staff/${action.row.id}/roles`, { role: OWNER_ROLE })
                : api.post(`/api/staff/${action.row.id}/roles/${OWNER_ROLE}/remove`));
            } catch (caught) {
              load();
              throw caught;
            }
            setPending(null);
            load();
            return;
          }
          let next: StaffRow;
          try {
            next = await api.put<StaffRow>(`/api/staff/${action.row.id}/access/${action.dept.key}`, { level: action.level });
          } catch (caught) {
            load();
            throw caught;
          }
          setPending(null);
          if (next && Array.isArray(next.roles)) replaceRow(next); else load();
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
      effects={[`Reactivating ${name} gives no access. Give it again from the levels on their page.`]}
      confirm="Reactivate"
      onCancel={() => setPending(null)}
      onConfirm={async () => {
        await api.post(`/api/staff/${action.row.id}/reactivate`);
        setPending(null);
        load();
      }} />;
  }

  const canInvite = !!roster && roster.invitable_roles.length > 0;

  return (
    <>
      <div className="page__head">
        <div className="page__title">
          <h1>Team and access</h1>
          {roster && (
            <span className="page__subtitle">
              {plural(roster.staff.length, "person", "people")} · {plural(invitations.length, "invitation", "invitations")} waiting
            </span>
          )}
        </div>
        {canInvite && (
          <div className="team__headact">
            <button type="button" className="team__btn team__btn--primary" onClick={() => setInviting(true)}>Invite someone</button>
          </div>
        )}
      </div>
      {error && <p className="notice notice--refused" role="alert">{error}</p>}
      {roster === null && !error && <p className="empty">Loading…</p>}

      {roster && (
        <div className={`team${chosen ? " team--chosen" : ""}`}>
          <section className="panel team__list" aria-label="People">
            <ul className="people">
              {staff.map((row) => {
                const selected = selectedPerson?.id === row.id;
                return (
                  <li key={row.id} className={row.status === "suspended" ? "people__off" : undefined}>
                    <Link to={{ search: `?person=${row.id}` }} aria-current={selected ? "true" : undefined}>
                      <span className="avatar" aria-hidden="true">{initialsOf(nameOf(row))}</span>
                      <span>
                        <b>{nameOf(row)}</b>
                        <small>{row.status === "suspended" ? "Suspended" : (row.access_words ?? accessWordsOf(row.roles))}</small>
                      </span>
                      {row.two_step_enabled ? <Lock method={row.two_step_method} /> : <span />}
                    </Link>
                  </li>
                );
              })}
              {invitations.length > 0 && <li><p className="people__group">Invited, not joined yet</p></li>}
              {invitations.map((row) => {
                const selected = selectedInvitation?.id === row.id;
                return (
                  <li key={`invitation-${row.id}`}>
                    <Link to={{ search: `?invitation=${row.id}` }} aria-current={selected ? "true" : undefined}>
                      <span className="avatar" aria-hidden="true">{initialsOf(row.email)}</span>
                      <span>
                        <b>{row.email}</b>
                        <small>{row.access_words ?? words(row.role)} · {sentWords(row.sent_at ?? row.created_at)}</small>
                      </span>
                      <span />
                    </Link>
                  </li>
                );
              })}
            </ul>
          </section>

          <div className="team__detail">
            <Link className="team__back" to={{ search: "" }}>
              <span aria-hidden="true">‹</span> Team and access
            </Link>
            {selectedPerson && (
              <PersonPage key={selectedPerson.id} row={selectedPerson} roster={roster}
                you={selectedPerson.id === session.actor.id} ask={setPending} reload={load} />
            )}
            {selectedInvitation && (
              <InvitationPage key={`invitation-${selectedInvitation.id}`} row={selectedInvitation} roster={roster}
                onChanged={load} onGone={() => setParams({})} />
            )}
            {!selectedPerson && !selectedInvitation && <p className="empty">No one to show.</p>}
          </div>
        </div>
      )}

      {roster && inviting && (
        <InviteDialog roster={roster} onClose={() => setInviting(false)} onInvited={load} />
      )}
      {pending && dialogFor(pending)}
    </>
  );
}
