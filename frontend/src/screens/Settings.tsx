import { useEffect, useState } from "react";

import { api, can } from "../lib/api";
import type { Session } from "../lib/api";
import { formatMonth } from "../lib/money";
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
export function Settings({ session }: { session: Session }) {
  return (
    <>
      <div className="page__head">
        <div className="page__title">
          <h1>Settings</h1>
        </div>
      </div>

      <div className="settings__sections">
        <PlatformPanel session={session} />
        {can(session, "invitations.send") && <InvitePanel />}
        {can(session, "settings.manage") && <RosterPanel />}
        {can(session, "audit.view") && <ActivityPanel />}
      </div>
    </>
  );
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
        <h2 className="panel__title">Platform</h2>
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

function InvitePanel() {
  const [email, setEmail] = useState("");
  const [role, setRole] = useState("content_manager");
  const [link, setLink] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [working, setWorking] = useState(false);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setWorking(true);
    setError(null);
    setLink(null);
    try {
      const result = await api.post<{ token: string }>("/api/auth/invitations", {
        email: email.trim(),
        role,
      });
      setLink(`${window.location.origin}/accept-invitation?token=${result.token}`);
      setEmail("");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Could not invite them.");
    } finally {
      setWorking(false);
    }
  }

  return (
    <section className="panel settings__panel">
      <div className="panel__head">
        <h2 className="panel__title">Invite someone</h2>
      </div>

      {error && (
        <p className="notice notice--refused" role="alert">
          {error}
        </p>
      )}

      {/*
       * §16: email delivery is a later phase. Until it exists, the link is
       * shown once, here, for whoever invited them to send it themselves -
       * WhatsApp, email, however they'd reach that person anyway. It is
       * shown once because it is a working credential until it is used.
       */}
      {link && (
        <div className="notice notice--settled settings__link">
          <p>Send this to them yourself — it only appears here once.</p>
          <code className="code settings__link-value">{link}</code>
        </div>
      )}

      <form onSubmit={submit} className="settings__form">
        <label className="field settings__field">
          <span className="field__label">Email</span>
          <input
            className="input"
            type="email"
            required
            value={email}
            onChange={(event) => setEmail(event.target.value)}
          />
        </label>
        <label className="field settings__field">
          <span className="field__label">Role</span>
          <select
            className="input"
            value={role}
            onChange={(event) => setRole(event.target.value)}
          >
            <option value="content_manager">Content manager</option>
            <option value="affiliate_manager">Affiliate manager</option>
            <option value="admin">Admin</option>
          </select>
        </label>
        <button
          type="submit"
          className="button button--primary"
          disabled={working || !email.trim()}
        >
          {working ? "Inviting…" : "Invite"}
        </button>
      </form>
    </section>
  );
}

function RosterPanel() {
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

  return (
    <section className="panel settings__panel">
      <div className="panel__head">
        <h2 className="panel__title">Staff &amp; roles</h2>
      </div>

      {error && (
        <p className="notice notice--refused" role="alert">
          {error}
        </p>
      )}

      {roster === null && !error && <p className="empty">Loading…</p>}

      {roster && (
        <table className="table settings__table">
          <thead>
            <tr>
              <th>Name</th>
              <th>Role</th>
              <th>Status</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {roster.staff.map((row) => (
              <tr key={row.id}>
                <td>
                  {row.display_name || row.email}
                  <span className="settings__email">{row.email}</span>
                </td>
                <td>
                  <select
                    className="input settings__role-select"
                    value={row.role}
                    disabled={busyId === row.id || !roster.assignable_roles.includes(row.role)}
                    onChange={(event) => changeRole(row.id, event.target.value)}
                  >
                    {!roster.assignable_roles.includes(row.role) && (
                      <option value={row.role}>{row.role}</option>
                    )}
                    {roster.assignable_roles.map((role) => (
                      <option key={role} value={role}>
                        {ROLE_LABEL[role] ?? role}
                      </option>
                    ))}
                  </select>
                </td>
                <td className={`settings__status settings__status--${row.status}`}>
                  {row.status}
                </td>
                <td className="settings__action">
                  {row.status === "suspended" ? (
                    <button
                      type="button"
                      className="button"
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
                        className="button button--danger"
                        disabled={busyId === row.id || !reason.trim()}
                        onClick={() => suspend(row.id)}
                      >
                        Confirm
                      </button>
                      <button
                        type="button"
                        className="button"
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
                      className="button button--danger"
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
      )}

      {roster && roster.invitations.length > 0 && (
        <>
          <h3 className="settings__subhead">Waiting to be accepted</h3>
          <table className="table settings__table">
            <thead>
              <tr>
                <th>Email</th>
                <th>Role</th>
                <th>State</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {roster.invitations.map((row) => (
                <tr key={row.id}>
                  <td>{row.email}</td>
                  <td>{ROLE_LABEL[row.role] ?? row.role}</td>
                  <td className="settings__quiet">
                    {row.expired ? "Expired — never accepted" : "Waiting"}
                  </td>
                  <td className="settings__action">
                    <button
                      type="button"
                      className="button"
                      disabled={busyId === row.id}
                      onClick={() => revokeInvitation(row.id)}
                    >
                      Withdraw
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
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
