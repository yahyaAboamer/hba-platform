import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { AddHouseCode } from "./AddHouseCode";
import { applyMaintainerTheme, storedTheme, storeTheme } from "../lib/theme";

import { MonthPicker } from "../components/MonthPicker";
import { PolicyText } from "../components/PolicyText";
import { api, can } from "../lib/api";
import type { Session } from "../lib/api";
import { currentMonth, formatMonth } from "../lib/money";
import { DataPanel } from "./DataPanel";
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
  role: string;
  status: "invited" | "active" | "suspended";
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
};

type AuditEntry = {
  id: number;
  action: string;
  subject: string;
  actor_email: string | null;
  reason: string | null;
  created_at: string;
};

const ROLE_LABEL: Record<string, string> = {
  admin: "Admin",
  affiliate_manager: "Affiliate manager",
  content_manager: "Content manager",
};

/**
 * The platform's own configuration and who may touch it.
 *
 * Not a workflow like the other screens — nothing here is walked through
 * every month. It is the handful of switches sitting on top of everything
 * already built: who has access, what they may do about it, and a plain
 * read of the platform's own state.
 *
 * Every section is gated on its own permission and simply does not render
 * without it, the same pattern Payroll and Payments already use for their
 * approve and reveal actions — a control that would refuse the request is
 * not offered rather than offered and refused.
 */
const SETTINGS_SECTIONS = [
  ["team", "Team"], ["shopify", "Shopify and sync"], ["historical", "Historical setup"],
  ["codes", "Brand codes"], ["appearance", "Appearance"], ["advanced", "Reference"],
];

export function Settings({ session }: { session: Session }) {
  const [query, setQuery] = useSearchParams();
  const section = SETTINGS_SECTIONS.some(([id]) => id === query.get("section")) ? query.get("section")! : "team";
  return <>
    <div className="page__head"><div className="page__title"><h1>Settings</h1></div></div>
    <div className="settings__workspace">
      <nav className="settings__navigation" aria-label="Settings sections">
        {SETTINGS_SECTIONS.map(([id,label]) => <button key={id} type="button"
          aria-current={section === id ? "page" : undefined} className={section === id ? "settings__selected" : ""}
          onClick={() => setQuery({section:id})}>{label}</button>)}
      </nav>
      <div className="settings__sections">
        {section === "team" && (can(session, "settings.manage")
          ? <RosterPanel invite={can(session, "invitations.send")} />
          : can(session, "invitations.send") && <InvitePanel />)}
        {section === "shopify" && (can(session, "settings.manage")
          ? <DataPanel goLiveMonth={session.platform.go_live_month} />
          : <PlatformPanel session={session} />)}
        {section === "historical" && (can(session, "compensation.manage") ? <SetupRoster kind="model" /> : <p className="empty">Your account cannot manage payment terms.</p>)}
        {section === "codes" && <>
          <SetupRoster kind="house" />
          {can(session, "affiliates.manage") && <AddHouseCode onCreated={() => undefined} />}
          <p className="settings__note">Brand codes have no model payments and are excluded from model rankings.</p>
        </>}
        {section === "appearance" && <AppearancePanel />}
        {section === "advanced" && <>
          <Link to="/glossary">Help and definitions →</Link>
          {can(session, "settings.manage") && <PolicyPanel />}
          {can(session, "audit.view") && <ActivityPanel />}
        </>}
      </div>
    </div>
  </>;
}

function AppearancePanel() {
  const [theme, setTheme] = useState(() => storedTheme("maintainer"));
  // The export's segmented switch - two radios that read as one control -
  // rather than two buttons that could both look pressed.
  return <section className="panel settings__appearance"><span>Theme</span>
    <div className="seg" role="radiogroup" aria-label="Theme">{(["dark", "light"] as const).map(value =>
      <label key={value} className="seg-opt">
        <input type="radio" name="admin-theme" checked={theme === value}
          onChange={() => { setTheme(value); storeTheme(value,"maintainer"); applyMaintainerTheme(value); }} />
        <span>{value === "dark" ? "Dark" : "Light"}</span>
      </label>)}</div>
  </section>;
}

type SetupRow = {
  id: number;
  name: string;
  account_kind: string;
  code?: string;
  status: string;
  collaboration_start_month?: string | null;
  /** The first month her terms cover. `null` means none were ever written. */
  earliest_terms_month?: string | null;
  /**
   * A09. How many of her eligible months can actually be calculated.
   *
   * Counts, from the server's per-month rule — the same one the profile
   * screen uses. **Not two dates**, which is what this column compared
   * before: her earliest terms against her start month, an answer that cannot
   * see a gap in the middle of a year or a guaranteed month with no recorded
   * outcome.
   */
  historical_setup?: {
    eligible: number;
    ready: number;
    blocking: number;
    /** The earliest month that cannot be calculated, to link straight to. */
    first_gap: string | null;
    start_is_recorded: boolean;
  } | null;
};

/**
 * Whether her terms reach back to when she started.
 *
 * **A month before her earliest terms cannot be calculated**, so this is not
 * a tidiness column: it is the list of months nobody can pay, and the state
 * word is what turns a date somebody has to compare into an answer.
 */
export function historicalState(row: SetupRow) {
  const setup = row.historical_setup;
  // The server did not send a verdict. Say that, rather than working one out
  // here from whatever else is on the row - which is how this column came to
  // have its own rule in the first place (A09).
  if (!setup) return <span className="settings__gap">Not known</span>;
  if (setup.eligible === 0) {
    return <span className="settings__gap">No month can be worked out</span>;
  }
  if (setup.blocking === 0) {
    // **Every eligible month, not the earliest one.** "Covered from the
    // start" used to mean only that her terms began early enough.
    return setup.start_is_recorded
      ? `All ${setup.eligible} months ready`
      : `All ${setup.eligible} months ready · start not recorded`;
  }
  return (
    <span className="settings__gap">
      {setup.blocking} of {setup.eligible} months cannot be calculated
    </span>
  );
}

function SetupRoster({kind}: {kind: "model" | "house"}) {
  const [rows,setRows] = useState<SetupRow[] | null>(null);
  const [error,setError] = useState<string | null>(null);
  useEffect(() => { let live = true; api.get<{affiliates:NonNullable<typeof rows>}>("/api/affiliates?include_archived=true")
    .then(body => { if(live) setRows(body.affiliates.filter(row => row.account_kind === kind)); })
    .catch(caught => { if(live) setError(caught.message); }); return () => {live=false;}; },[kind]);
  if(error) return <p className="notice notice--refused" role="alert">{error}</p>;
  if(!rows) return <p className="empty">Loading…</p>;
  return <section className="panel">
    <div className="panel__head"><h2 className="panel__title">{kind === "house" ? "Brand codes" : "Historical setup"}</h2></div>
    {/* The export's four columns for models — Model, Started, Earliest terms,
        State — and its three for brand codes, which have no terms at all. */}
    <table className="table"><thead><tr>
      <th>{kind === "house" ? "Code" : "Model"}</th>
      <th>{kind === "house" ? "Purpose" : "Started"}</th>
      <th>{kind === "house" ? "State" : "Earliest terms"}</th>
      {kind === "model" && <th>State</th>}
    </tr></thead>
      <tbody>{rows.map(row => <tr key={row.id}>
        <td><Link to={`/affiliates/${row.id}`}>{kind === "house" ? row.code || "No code" : row.name}</Link></td>
        <td>{kind === "house" ? row.name : row.collaboration_start_month ? formatMonth(row.collaboration_start_month) : "Not recorded"}</td>
        <td>{kind === "house"
          ? row.status
          : row.earliest_terms_month
            ? formatMonth(row.earliest_terms_month)
            : <span className="settings__gap">None written</span>}</td>
        {kind === "model" && <td>
          {historicalState(row)}
          {/* The way to fix it, where there is something to fix - and it goes
              to the first month that cannot be calculated rather than to the
              top of the grid. */}
          {row.historical_setup && row.historical_setup.blocking > 0 && <>
            {" · "}<Link to={`/affiliates/${row.id}/compensation`}>
              {row.historical_setup.first_gap
                ? `Fix from ${formatMonth(row.historical_setup.first_gap)} →`
                : "Set the months →"}
            </Link>
          </>}
        </td>}
      </tr>)}</tbody></table>
    {rows.length === 0 && <p className="empty">No {kind === "house" ? "brand codes" : "models"}.</p>}
  </section>;
}

function PlatformPanel({ session }: { session: Session }) {
  const [sync, setSync] = useState<SyncStatus | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .get<SyncStatus>("/api/operations/sync")
      .then(setSync)
      .catch((caught) => setError(caught.message));
  }, []);

  return (
    <section className="panel settings__panel">
      <div className="panel__head">
        <h2 className="panel__title">Connection</h2>
      </div>

      {error && (
        <p className="notice notice--refused" role="alert">
          {error}
        </p>
      )}

      <dl className="detail__list">
        <Row label="Go-live month">
          {session.platform.go_live_month ? (
            formatMonth(session.platform.go_live_month)
          ) : (
            <span className="orders__quiet">Not set</span>
          )}
          {/*
           * Deliberately not a field on this page. §11.2 has this blank by
           * default and refuses every approval until it is set, on purpose -
           * an unset go-live would silently make months already settled
           * outside the platform look approvable a second time. Changing it
           * is rare and consequential enough to want a deploy, not a click,
           * so it stays an environment variable rather than a setting here.
           */}
          <span className="detail__note">
            Set on the server when the platform goes live, not from here.
          </span>
        </Row>
        <Row label="Shopify">
          {sync?.shopify_configured ? "Connected" : "Not connected"}
        </Row>
        <Row label="Order webhooks">
          {sync?.webhooks_configured ? "Configured" : "Not configured"}
        </Row>
        <Row label="Orders indexed">{sync?.orders_indexed ?? "—"}</Row>
      </dl>
    </section>
  );
}

function InvitePanel({ onInvited }: { onInvited?: () => void }) {
  const [email, setEmail] = useState("");
  const [role, setRole] = useState("content_manager");
  const [link, setLink] = useState<string | null>(null);
  const [emailed, setEmailed] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [working, setWorking] = useState(false);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setWorking(true);
    setError(null);
    setLink(null);
    try {
      const result = await api.post<{ token: string; emailed: boolean }>(
        "/api/auth/invitations",
        { email: email.trim(), role },
      );
      setEmailed(result.emailed);
      setLink(`${window.location.origin}/accept-invitation?token=${result.token}`);
      setEmail("");
      onInvited?.();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Could not invite them.");
    } finally {
      setWorking(false);
    }
  }

  return (
    <section className="panel settings__panel">
      <div className="panel__head">
        <h2 className="panel__title">Invite a staff member</h2>
      </div>

      {error && (
        <p className="notice notice--refused" role="alert">
          {error}
        </p>
      )}

      {/*
       * §16. The platform emails the link, and the link is still shown here.
       *
       * Both, deliberately. An emailed link is exactly what somebody wants on
       * screen the moment the recipient says it never arrived - and on a
       * machine with no mail credentials, which is every development machine,
       * the copyable link is the only way in at all.
       *
       * Shown once because it is a working credential until it is used.
       */}
      {link && (
        <div className="notice notice--settled settings__link">
          <p>
            {emailed
              ? "Emailed to them. Here is the same link, in case it does not arrive — it only appears here once."
              : "Send this to them yourself — it only appears here once."}
          </p>
          <code className="code settings__link-value">{link}</code>
        </div>
      )}

      {/*
       * One row: the address, the access, and the act - the export's form.
       * It used to be two labelled fields stacked over a button with a
       * paragraph above them pointing models elsewhere; the Models screen's
       * own *Invite a model* already says that, where somebody inviting a
       * model actually is.
       */}
      <form onSubmit={submit} className="settings__invite-row">
        <input
          className="input settings__invite-email"
          type="email"
          required
          value={email}
          onChange={(event) => setEmail(event.target.value)}
          placeholder="name@hbawear.store"
          aria-label="Email"
        />
        <select
          className="input settings__invite-role"
          value={role}
          onChange={(event) => setRole(event.target.value)}
          aria-label="Access"
        >
          <option value="content_manager">Content manager</option>
          <option value="affiliate_manager">Affiliate manager</option>
          <option value="admin">Admin</option>
        </select>
        <button
          type="submit"
          className="button button--primary settings__invite-send"
          disabled={working || !email.trim()}
        >
          {working ? "Sending…" : "Send invitation"}
        </button>
      </form>
    </section>
  );
}

function RosterPanel({ invite = false }: { invite?: boolean }) {
  const [roster, setRoster] = useState<Roster | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<number | null>(null);
  const [suspending, setSuspending] = useState<number | null>(null);
  const [reason, setReason] = useState("");

  function load() {
    api
      .get<Roster>("/api/staff")
      .then(setRoster)
      .catch((caught) => setError(caught.message));
  }

  useEffect(load, []);

  async function changeRole(id: number, role: string) {
    setBusyId(id);
    setError(null);
    try {
      await api.post(`/api/staff/${id}/role`, { role });
      load();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Could not change that.");
    } finally {
      setBusyId(null);
    }
  }

  async function suspend(id: number) {
    if (!reason.trim()) return;
    setBusyId(id);
    setError(null);
    try {
      await api.post(`/api/staff/${id}/suspend`, { reason: reason.trim() });
      setSuspending(null);
      setReason("");
      load();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Could not suspend them.");
    } finally {
      setBusyId(null);
    }
  }

  async function reactivate(id: number) {
    setBusyId(id);
    setError(null);
    try {
      await api.post(`/api/staff/${id}/reactivate`);
      load();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Could not reactivate them.");
    } finally {
      setBusyId(null);
    }
  }

  async function resendInvitation(id: number) {
    setBusyId(id);
    setError(null);
    try {
      await api.post(`/api/staff/invitations/${id}/resend`);
      load();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Could not send it again.");
    } finally {
      setBusyId(null);
    }
  }

  async function revokeInvitation(id: number) {
    setBusyId(id);
    setError(null);
    try {
      await api.post(`/api/staff/invitations/${id}/revoke`);
      load();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Could not withdraw it.");
    } finally {
      setBusyId(null);
    }
  }

  /*
   * The export's Team section, in its order: the staff list on a surface of
   * its own with no title above it - its column header already says *Staff*
   * - then the invite form, then *Pending staff invitations* as a third
   * surface. Pending invitations used to be a sub-table inside the staff
   * panel with no way to send one again.
   */
  return (
    <>
      {error && (
        <p className="notice notice--refused" role="alert">
          {error}
        </p>
      )}

      {roster === null && !error && <p className="empty">Loading…</p>}

      {roster && (
        <section className="panel" aria-label="Staff">
          <table className="table settings__table">
            <thead>
              <tr>
                <th>Staff</th>
                <th className="settings__access">Access</th>
                <th className="settings__state">State</th>
                <th className="settings__action" aria-label="Actions" />
              </tr>
            </thead>
            <tbody>
              {roster.staff.map((row) => (
                <tr key={row.id}>
                  <td>
                    {row.display_name || row.email}
                    <span className="settings__email">{row.email}</span>
                  </td>
                  <td className="settings__access">
                    <select
                      className="input settings__role-select"
                      value={row.role}
                      aria-label={`Access for ${row.display_name || row.email}`}
                      disabled={busyId === row.id || !roster.assignable_roles.includes(row.role)}
                      onChange={(event) => changeRole(row.id, event.target.value)}
                    >
                      {!roster.assignable_roles.includes(row.role) && (
                        <option value={row.role}>{ROLE_LABEL[row.role] ?? row.role}</option>
                      )}
                      {roster.assignable_roles.map((role) => (
                        <option key={role} value={role}>
                          {ROLE_LABEL[role] ?? role}
                        </option>
                      ))}
                    </select>
                  </td>
                  <td className={`settings__state settings__status--${row.status}`}>
                    {row.status.charAt(0).toUpperCase() + row.status.slice(1)}
                  </td>
                  {/*
                   * Suspend and reactivate are not in the export, and they
                   * are not optional: a departed member of staff has to be
                   * locked out today. They sit at the end of the row, the
                   * quietest place that still reaches them.
                   */}
                  <td className="settings__action">
                    {row.status === "suspended" ? (
                      <button
                        type="button"
                        className="button button--row"
                        disabled={busyId === row.id}
                        onClick={() => reactivate(row.id)}
                      >
                        Reactivate
                      </button>
                    ) : suspending === row.id ? (
                      <div className="settings__suspend-form">
                        <input
                          className="input settings__reason"
                          placeholder="Why?"
                          value={reason}
                          onChange={(event) => setReason(event.target.value)}
                        />
                        <button
                          type="button"
                          className="button button--row button--danger"
                          disabled={busyId === row.id || !reason.trim()}
                          onClick={() => suspend(row.id)}
                        >
                          Confirm
                        </button>
                        <button
                          type="button"
                          className="button button--row"
                          onClick={() => {
                            setSuspending(null);
                            setReason("");
                          }}
                        >
                          Cancel
                        </button>
                      </div>
                    ) : (
                      <button
                        type="button"
                        className="button button--row button--danger"
                        onClick={() => setSuspending(row.id)}
                      >
                        Suspend
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}

      {invite && <InvitePanel onInvited={load} />}

      {roster && (
        <section className="panel">
          <div className="panel__head">
            <h2 className="panel__title">Pending staff invitations</h2>
          </div>
          {roster.invitations.length === 0 ? (
            <p className="settings__none">No staff invitation is outstanding.</p>
          ) : (
            <ul className="settings__pending">
              {roster.invitations.map((row) => (
                <li key={row.id}>
                  <span className="settings__pending-who">
                    {row.email}
                    <span className="settings__email">
                      {ROLE_LABEL[row.role] ?? row.role}
                      {" · "}
                      {row.expired
                        ? "Link expired"
                        : row.created_at
                          ? `Sent ${new Date(row.created_at).toLocaleDateString("en-GB", {
                              day: "numeric",
                              month: "long",
                              year: "numeric",
                            })}`
                          : "Sent"}
                    </span>
                  </span>
                  <button
                    type="button"
                    className="button button--row"
                    disabled={busyId === row.id}
                    onClick={() => resendInvitation(row.id)}
                  >
                    Resend
                  </button>
                  {!row.expired && (
                    <button
                      type="button"
                      className="button button--row settings__withdraw"
                      disabled={busyId === row.id}
                      onClick={() => revokeInvitation(row.id)}
                    >
                      Withdraw
                    </button>
                  )}
                </li>
              ))}
            </ul>
          )}
        </section>
      )}
    </>
  );
}

type PolicyVersionRow = {
  id: number;
  effective_month: string;
  summary_markdown: string;
  created_at: string;
};

/**
 * §16, Phase 10 Batch C. The commission rules, in the words a model reads -
 * not the ADRs, which stay the engineering record for nobody but whoever
 * reads code.
 *
 * **A new version, never an edit.** A rate reworded next year is a fact about
 * the future, not a rewrite of what a model already agreed to in September -
 * every payroll snapshot freezes which version it was calculated under, and
 * that has to stay true regardless of what this form does later.
 */
function PolicyPanel() {
  const [versions, setVersions] = useState<PolicyVersionRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [adding, setAdding] = useState(false);
  const [effectiveMonth, setEffectiveMonth] = useState(currentMonth());
  const [text, setText] = useState("");
  const [working, setWorking] = useState(false);

  function load() {
    api
      .get<{ versions: PolicyVersionRow[] }>("/api/policy/versions")
      .then((body) => setVersions(body.versions))
      .catch((caught) => setError(caught.message));
  }

  useEffect(load, []);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setWorking(true);
    setError(null);
    try {
      await api.post("/api/policy/versions", {
        effective_month: effectiveMonth,
        summary_markdown: text,
      });
      setText("");
      setAdding(false);
      load();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Could not save that.");
    } finally {
      setWorking(false);
    }
  }

  const newest = versions && versions.length > 0 ? versions[versions.length - 1] : null;

  return (
    <section className="panel settings__panel">
      <div className="panel__head">
        <h2 className="panel__title">Policy in force</h2>
      </div>

      {error && (
        <p className="notice notice--refused" role="alert">
          {error}
        </p>
      )}

      <p className="settings__note">
        What a model reads, not the engineering record. A new version applies
        from its effective month onward - it never changes what an already
        agreed month was told.
      </p>

      {versions === null ? (
        <p className="empty">Loading…</p>
      ) : versions.length === 0 ? (
        <p className="empty">
          None recorded yet. Every settled month simply shows no rules were in
          force - add the first version below.
        </p>
      ) : (
        <ul className="settings__policy-list">
          {versions.map((version) => (
            <li key={version.id} className="settings__policy-item">
              <div className="settings__policy-head">
                <strong>Effective {formatMonth(version.effective_month)}</strong>
                {version.id === newest?.id && (
                  <span className="detail__note">current</span>
                )}
              </div>
              <PolicyText markdown={version.summary_markdown} />
            </li>
          ))}
        </ul>
      )}

      {!adding ? (
        <button
          type="button"
          className="button"
          onClick={() => {
            setAdding(true);
            setEffectiveMonth(currentMonth());
          }}
        >
          Add a version
        </button>
      ) : (
        <form onSubmit={submit} className="comp__form">
          <label className="field comp__field">
            <span className="field__label">Effective from</span>
            <MonthPicker value={effectiveMonth} onChange={setEffectiveMonth} />
            <span className="field__hint">
              {newest
                ? `Must be later than ${formatMonth(newest.effective_month)}, the current version.`
                : "Every month from here onward reads this version."}
            </span>
          </label>
          <label className="field">
            <span className="field__label">The text</span>
            <textarea
              className="input reopen__textarea"
              rows={10}
              required
              value={text}
              onChange={(event) => setText(event.target.value)}
              placeholder="## How commission works&#10;&#10;Commission is worked out on..."
            />
            <span className="field__hint">
              Plain language, not the ADRs. `## ` starts a heading, `**text**`
              is bold - nothing else is read specially.
            </span>
          </label>
          <div className="payroll__actions">
            <button
              type="button"
              className="button"
              onClick={() => {
                setAdding(false);
                setError(null);
              }}
              disabled={working}
            >
              Cancel
            </button>
            <button
              type="submit"
              className="button button--primary"
              disabled={working || !text.trim()}
            >
              {working ? "Saving…" : "Save this version"}
            </button>
          </div>
        </form>
      )}
    </section>
  );
}

function ActivityPanel() {
  const [events, setEvents] = useState<AuditEntry[] | null>(null);
  const [subject, setSubject] = useState("");
  const [error, setError] = useState<string | null>(null);

  function load(query: string) {
    api
      .get<{ events: AuditEntry[] }>(
        `/api/audit${query ? `?subject=${encodeURIComponent(query)}` : ""}`,
      )
      .then((body) => setEvents(body.events))
      .catch((caught) => setError(caught.message));
  }

  useEffect(() => load(""), []);

  return (
    <section className="panel settings__panel">
      <div className="panel__head">
        <h2 className="panel__title">Recent activity</h2>
      </div>

      <form
        className="settings__search"
        onSubmit={(event) => {
          event.preventDefault();
          load(subject.trim());
        }}
      >
        <input
          className="input"
          placeholder="Filter by subject — affiliate:3, or a name"
          value={subject}
          onChange={(event) => setSubject(event.target.value)}
        />
        <button type="submit" className="button">
          Filter
        </button>
      </form>

      {error && (
        <p className="notice notice--refused" role="alert">
          {error}
        </p>
      )}

      {events === null && !error && <p className="empty">Loading…</p>}

      {events?.length === 0 && <p className="empty">Nothing matches that.</p>}

      {events && events.length > 0 && (
        <ul className="settings__activity">
          {events.map((event) => (
            <li key={event.id} className="settings__activity-row">
              <span className="code settings__activity-action">{event.action}</span>
              <span className="settings__activity-subject">{event.subject}</span>
              <span className="settings__quiet">
                {event.actor_email ?? "system"} ·{" "}
                {new Date(event.created_at).toLocaleString("en-GB", {
                  day: "numeric",
                  month: "short",
                  hour: "2-digit",
                  minute: "2-digit",
                })}
              </span>
              {event.reason && (
                <span className="settings__activity-reason">"{event.reason}"</span>
              )}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="detail__row">
      <dt className="detail__label">{label}</dt>
      <dd className="detail__value">{children}</dd>
    </div>
  );
}
