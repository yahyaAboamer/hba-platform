import { useEffect, useState } from "react";

import { ApiError, api } from "../../lib/api";
import {
  FreshLine,
  OpsIcon,
  SourceBanner,
  clockTime,
  stateNow,
  useNow,
  useOpsTab,
} from "../../components/OpsSource";
import type { Freshness } from "../../components/OpsSource";
import "./OperationsDashboard.css";

/**
 * Operations → Khazenly: the bulk-confirm file for orders confirmed in
 * Shopify (ADR 0071).
 *
 * Khazenly holds every order on hold until it is confirmed on their
 * dashboard. Upload their *Active Orders* export here; the platform keeps
 * the orders tagged Confirmed in Shopify and returns Khazenly's own template
 * filled in with them, to upload back to Khazenly. Nothing is sent anywhere,
 * and nothing about the customer is shown: order numbers only.
 *
 * No approved frame exists for this tab; it is drawn from the Operations
 * dashboard's own pieces (heading, freshness line, cards, panels).
 */

type LeftOut = {
  reason: string;
  label: string;
  count: number;
  orders: { sales_order: string; order_number: string | null }[];
};
type Result = {
  freshness: Freshness;
  rows_read: number;
  stated_count: number | null;
  skipped_rows: number;
  confirmed: number;
  not_confirmed: number;
  left_out: LeftOut[];
  file: { name: string; content_base64: string } | null;
};
type KhazenlyTab = { freshness: Freshness };

/** The safety exclusions: confirmed, but held back (ADR 0071, decision 3). */
const HELD_BACK = new Set(["not_open", "confirmed_but_cancelled", "confirmed_but_shipped"]);

const XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet";

function plural(count: number, one: string, many: string): string {
  return `${count} ${count === 1 ? one : many}`;
}

/** The file as a link the browser saves, revoked when it is replaced. Made
 *  and revoked in one effect, so a remount never leaves a dead link. */
function useFileUrl(file: Result["file"]): string | null {
  const [url, setUrl] = useState<string | null>(null);
  useEffect(() => {
    if (!file) {
      setUrl(null);
      return;
    }
    const bytes = Uint8Array.from(atob(file.content_base64), (char) => char.charCodeAt(0));
    const made = URL.createObjectURL(new Blob([bytes], { type: XLSX }));
    setUrl(made);
    return () => URL.revokeObjectURL(made);
  }, [file]);
  return url;
}

function LeftOutGroup({ group }: { group: LeftOut }) {
  const [open, setOpen] = useState(false);
  const id = `ops-kh-${group.reason}`;
  return (
    <li className="ops-kh__group">
      <button
        type="button"
        className="ops-kh__reason"
        aria-expanded={open}
        aria-controls={open ? id : undefined}
        onClick={() => setOpen(!open)}
      >
        <span>
          {group.label}
          {HELD_BACK.has(group.reason) && <small>Held back for safety</small>}
        </span>
        <span className="num">{group.count}</span>
        <OpsIcon name={open ? "up" : "down"} />
      </button>
      {open && (
        <table className="ops-table" id={id}>
          <thead>
            <tr>
              <th scope="col">Shopify order</th>
              <th scope="col">Khazenly order</th>
            </tr>
          </thead>
          <tbody>
            {group.orders.map((order) => (
              <tr key={order.sales_order}>
                <td className="num">{order.order_number ?? "—"}</td>
                <td className="num">{order.sales_order}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </li>
  );
}

function Summary({ result }: { result: Result }) {
  const url = useFileUrl(result.file);
  const readAt = result.freshness.updated_at;
  return (
    <>
      <div className="ops-tiles">
        <div className="ops-tile ops-tile--zero">
          <span className="ops-tile__label">In Khazenly's file</span>
          <span className="ops-tile__value">{result.rows_read}</span>
          <span className="ops-tile__note">Orders on hold, read from the export</span>
        </div>
        <div className="ops-tile ops-tile--zero ops-kh__tile--in">
          <span className="ops-tile__label">Confirmed</span>
          <span className="ops-tile__value">{result.confirmed}</span>
          <span className="ops-tile__note">In the file, each True</span>
        </div>
        <div className="ops-tile ops-tile--zero">
          <span className="ops-tile__label">Not confirmed</span>
          <span className="ops-tile__value">{result.not_confirmed}</span>
          <span className="ops-tile__note">Left out: they stay on hold at Khazenly</span>
        </div>
      </div>

      {result.skipped_rows > 0 && (
        <p className="ops-hint ops-list">
          {plural(result.skipped_rows, "row", "rows")} in the export had no Khazenly sales order
          number, so {result.skipped_rows === 1 ? "it was" : "they were"} not read as orders.
        </p>
      )}

      {result.left_out.length > 0 && (
        <section className="panel ops-list" aria-labelledby="ops-kh-left-out">
          <div className="panel__head ops-kh__head">
            <h2 className="panel__title" id="ops-kh-left-out">
              Left out · {plural(result.not_confirmed, "order", "orders")}
            </h2>
            <p className="ops-hint">By reason. Open one to see its orders.</p>
          </div>
          <ul className="ops-kh__groups">
            {result.left_out.map((group) => (
              <LeftOutGroup key={group.reason} group={group} />
            ))}
          </ul>
        </section>
      )}

      <section className="panel ops-list" aria-labelledby="ops-kh-file">
        <div className="panel__head ops-kh__head">
          <h2 className="panel__title" id="ops-kh-file">
            File for Khazenly
          </h2>
          {readAt && <p className="ops-hint">Checked against Shopify's tags from {clockTime(readAt)}</p>}
        </div>
        {result.file && url ? (
          <div className="ops-kh__file">
            <p>
              {plural(result.confirmed, "confirmed order", "confirmed orders")}, ready to upload to
              Khazenly's bulk confirm.
            </p>
            <a className="button button--primary" href={url} download={result.file.name}>
              Download {result.file.name}
            </a>
          </div>
        ) : (
          <p className="empty">
            None of these orders is confirmed in Shopify, so there is no file to upload.
          </p>
        )}
      </section>
    </>
  );
}

export function OperationsKhazenly() {
  const now = useNow();
  const { tab, failed, reload } = useOpsTab(() => api.get<KhazenlyTab>("/api/order-ops/khazenly"));
  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<Result | null>(null);

  const freshness = tab?.freshness;
  const fresh = freshness ? stateNow(freshness, now) === "fresh" : false;

  function build(event: React.FormEvent) {
    event.preventDefault();
    if (!file || busy) return;
    setBusy(true);
    setError(null);
    setResult(null);
    api
      .upload<Result>("/api/order-ops/khazenly", file)
      .then(setResult)
      .catch((caught: unknown) => {
        setError(caught instanceof ApiError ? caught.message : "Couldn't reach the platform. Try again.");
        // A refusal for old tags: show the line as it is now.
        reload();
      })
      .finally(() => setBusy(false));
  }

  return (
    <>
      <header className="page__head">
        <div className="page__title">
          <h1>Khazenly</h1>
          <span className="page__subtitle">Confirm orders for shipping</span>
        </div>
        {freshness && <FreshLine freshness={freshness} now={now} />}
      </header>

      {failed && (
        <p className="notice notice--refused" role="alert">
          Couldn't load this tab.{" "}
          <button type="button" className="ops-linkbtn" onClick={reload}>
            Try again
          </button>
        </p>
      )}

      {!tab && !failed && <p className="loading">Loading…</p>}

      {freshness && <SourceBanner freshness={freshness} now={now} />}

      {tab && (
        <section className="panel ops-list" aria-labelledby="ops-kh-upload">
          <div className="panel__head ops-kh__head">
            <h2 className="panel__title" id="ops-kh-upload">
              Build the bulk-confirm file
            </h2>
          </div>
          <form className="ops-kh__form" onSubmit={build}>
            <ol className="ops-kh__steps">
              <li>On Khazenly, download the Dashboard – Active Orders export.</li>
              <li>Choose it here. Orders tagged Confirmed in Shopify go in the file; the rest stay on hold.</li>
              <li>Upload the file you get back to Khazenly's bulk confirm.</li>
            </ol>
            <label className={file ? "ops-kh__drop ops-kh__drop--on" : "ops-kh__drop"}>
              <input
                type="file"
                disabled={busy}
                accept=".xlsx,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                className="visually-hidden"
                onChange={(event) => {
                  setFile(event.target.files?.[0] ?? null);
                  setResult(null);
                  setError(null);
                }}
              />
              {file ? `${file.name} · choose another to replace it` : "Choose Khazenly's export (.xlsx)"}
            </label>
            <div className="ops-kh__actions">
              <button type="submit" className="button button--primary" disabled={!file || busy || !fresh}>
                {busy ? "Reading the file…" : "Build the file"}
              </button>
              {!fresh && (
                <p className="ops-hint">
                  Shopify's tags must be up to date before a file is built, so a cancelled order is
                  never confirmed by mistake.
                </p>
              )}
            </div>
          </form>
        </section>
      )}

      {error && (
        <p className="notice notice--refused ops-list" role="alert">
          {error}
        </p>
      )}

      {busy && (
        <p className="loading" role="status">
          Matching the orders to Shopify…
        </p>
      )}

      {result && <Summary result={result} />}
    </>
  );
}
