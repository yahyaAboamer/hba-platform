import { useCallback, useEffect, useRef, useState } from "react";

import { InboxConnections } from "../../components/InboxConnection";
import { KeyCard } from "../../components/IntegrationKey";
import { OpsIcon, age, clockTime, dayAndTime, dayMonth, useNow } from "../../components/OpsSource";
import { api } from "../../lib/api";
import type { Session } from "../../lib/api";
import { DataPanel } from "../DataPanel";
import "./Integrations.css";
import "../Settings.css";

/** `GET /api/integrations` (Batch 2.3 contract §3), one row per connection, in a fixed order. */
type State = "working" | "late" | "failed" | "not_connected" | "never" | "unknown";
type KeyFormName = "shopify" | "whatsapp" | "bosta" | "estebdal";

export type Connection = {
  key: string;
  name: string;
  what: string;
  used_by: string;
  state: State;
  /** Only when failed, late or not connected. */
  why: string | null;
  when_label: string;
  when: string | null;
  /** Which existing key form the row's button opens; null when the key lives on the server. */
  key_form: KeyFormName | null;
};

type Body = { checked_at: string; connections: Connection[] };

const PILL: Record<State, string> = {
  working: "Working",
  late: "Late",
  failed: "Not working",
  not_connected: "Not connected",
  never: "Not read yet",
  unknown: "Could not check",
};

const PILL_TONE: Partial<Record<State, string>> = {
  failed: " conns__pill--failed",
  late: " conns__pill--late",
  not_connected: " conns__pill--off",
  never: " conns__pill--off",
  unknown: " conns__pill--off",
};

/** *14:22* for today, *3 Nov, 09:38* for any other day. In Cairo. */
function whenWords(iso: string, now: number): string {
  return dayMonth(iso) === dayMonth(new Date(now).toISOString()) ? clockTime(iso) : dayAndTime(iso);
}

/** *Checked 1 minute ago*, from when the server built its answer. */
function checkedWords(iso: string, now: number): string {
  const minutes = Math.floor((now - new Date(iso).getTime()) / 60_000);
  return minutes < 1 ? "Checked just now" : `Checked ${age(iso, now)} ago`;
}

function Pill({ state }: { state: State }) {
  return (
    <span className={`conns__pill${PILL_TONE[state] ?? ""}`}>
      {state === "failed" && <OpsIcon name="alert" />}
      {PILL[state]}
    </span>
  );
}

/** What the row's button opens: the component that changes that key today. */
function KeyForm({ form, session }: { form: KeyFormName; session: Session }) {
  switch (form) {
    case "shopify":
      return <DataPanel goLiveMonth={session.platform.go_live_month} />;
    case "bosta":
    case "estebdal":
      return <KeyCard provider={form} />;
    case "whatsapp":
      return <InboxConnections />;
  }
}

/** Email and File storage: the row's facts, and where the key is. */
function ServerKey({ row, now }: { row: Connection; now: number }) {
  return (
    <>
      <dl className="settings__facts">
        <div className="settings__fact"><dt>State</dt><dd>{PILL[row.state]}</dd></div>
        {row.why && <div className="settings__fact"><dt>What happened</dt><dd>{row.why}</dd></div>}
        {row.when && <div className="settings__fact"><dt>{row.when_label}</dt><dd>{whenWords(row.when, now)}</dd></div>}
        <div className="settings__fact"><dt>Used by</dt><dd>{row.used_by.replace(/^Used by /, "")}</dd></div>
      </dl>
      <p className="integrations__server">This key is set on the server, not here.</p>
    </>
  );
}

/**
 * Settings → Integrations: every connection in one list (the approved
 * mockup's frame 6), which departments rely on it, whether it works now, and
 * its key. The owner's. Nothing here calls the outside: the server builds the
 * list from what each department has already recorded.
 */
export function Integrations({ session }: { session: Session }) {
  const [body, setBody] = useState<Body | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [open, setOpen] = useState<string | null>(null);
  const detail = useRef<HTMLDivElement>(null);
  const now = useNow();

  const load = useCallback(() => {
    api.get<Body>("/api/integrations").then(setBody).catch((caught) => setError(caught.message));
  }, []);
  useEffect(load, [load]);

  // The key form opens below the list; focus goes to it so a keyboard or a
  // screen reader lands where the button led.
  useEffect(() => {
    if (open) detail.current?.focus();
  }, [open]);

  if (error) {
    return (
      <>
        <div className="page__head"><div className="page__title"><h1>Integrations</h1></div></div>
        <p className="notice notice--refused" role="alert">{error}</p>
      </>
    );
  }

  const rows = body?.connections ?? [];
  const failing = rows.filter((row) => row.state === "failed" || row.state === "late" || row.state === "unknown").length;
  const sub = body
    ? `${rows.length} ${rows.length === 1 ? "connection" : "connections"}${
        failing ? ` · ${failing} ${failing === 1 ? "is" : "are"} not working` : ""
      }`
    : null;
  const opened = rows.find((row) => row.key === open) ?? null;

  return (
    <>
      <div className="page__head">
        <div className="page__title">
          <h1>Integrations</h1>
          {sub && <span className="page__subtitle">{sub}</span>}
        </div>
        {body && (
          <p className="integrations__fresh" role="status">
            <OpsIcon name="clock" />
            {checkedWords(body.checked_at, now)}
          </p>
        )}
      </div>
      {!body ? (
        <p className="empty">Loading…</p>
      ) : rows.length === 0 ? (
        <p className="empty">There are no connections to show.</p>
      ) : (
        <section className="panel" aria-label="Connections">
          <ul className="conns">
            {rows.map((row) => {
              const failed = row.state === "failed";
              const expanded = open === row.key;
              return (
                <li key={row.key} className={failed ? "is-failed" : undefined}>
                  <span><b>{row.name}</b><small>{row.what}</small></span>
                  <span>
                    <small>{row.used_by}</small>
                    {row.why && <small className="why">{row.why}</small>}
                  </span>
                  <span><Pill state={row.state} /></span>
                  <span className="when">{row.when ? `${row.when_label} ${whenWords(row.when, now)}` : ""}</span>
                  <span className="act">
                    <button
                      type="button"
                      className={`conns__btn${failed ? " conns__btn--primary" : ""}`}
                      aria-expanded={expanded}
                      aria-label={`${failed ? "Replace key" : "Details"}, ${row.name}`}
                      onClick={() => setOpen(expanded ? null : row.key)}
                    >
                      {failed ? "Replace key" : "Details"}
                    </button>
                  </span>
                </li>
              );
            })}
          </ul>
        </section>
      )}
      {opened && (
        <section className="panel integrations__detail" aria-labelledby="integrations-detail-title">
          <div className="panel__head">
            <h2 className="panel__title" id="integrations-detail-title">{opened.name} details</h2>
            <button type="button" className="conns__btn" onClick={() => setOpen(null)}>Close</button>
          </div>
          <div className="integrations__detail-body" ref={detail} tabIndex={-1}>
            {opened.key_form ? <KeyForm form={opened.key_form} session={session} /> : <ServerKey row={opened} now={now} />}
          </div>
        </section>
      )}
    </>
  );
}
