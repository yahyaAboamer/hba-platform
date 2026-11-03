import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { api, can } from "../../lib/api";
import type { SetupRow } from "./HistoricalSetup";
import type { Session } from "../../lib/api";
import "./ModelLifecycle.css";
import "../../screens/Settings.css";

const CODE_STATE: Record<string, [string, string]> = {
  active: ["Active", "ok"],
  inactive: ["Paused", "owed"],
  archived: ["Retired", "off"],
  // A house account waits in *pending* only while Shopify has not confirmed
  // its code.
  pending: ["Not confirmed", "owed"],
};

function BrandCodesPanel({ session }: { session: Session }) {
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
            <td><Link to={`/affiliates/models/${row.id}`}>{row.code || "No code"}</Link></td>
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


/** `/affiliates/brand-codes`: which model holds which discount code. */
export function BrandCodes({ session }: { session: Session }) {
  return <>
    <div className="page__head"><div className="page__title"><h1>Brand codes</h1></div></div>
    <div className="settings__sections"><BrandCodesPanel session={session} /></div>
  </>;
}
