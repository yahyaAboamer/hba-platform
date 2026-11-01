import { useEffect, useState } from "react";

import { ApiError, api } from "../../lib/api";
import {
  FreshLine,
  OpsIcon,
  SourceBanner,
  clockTime,
  dayAndTime,
  stateNow,
  useNow,
  useOpsTab,
} from "../../components/OpsSource";
import type { Freshness } from "../../components/OpsSource";
import "./OperationsDashboard.css";

/**
 * Operations → Khazenly: the bulk-confirm file for orders confirmed in
 * Shopify (ADR 0071), and every run before it (ADR 0072).
 *
 * Khazenly holds every order on hold until it is confirmed on their
 * dashboard. Upload their *Active Orders* export here; the platform keeps
 * the orders tagged Confirmed in Shopify and returns Khazenly's own template
 * filled in with them, to upload back to Khazenly. Each run's summary is
 * kept and listed under the upload, newest first. Nothing is sent anywhere,
 * and nothing about the customer is shown: order numbers only.
 *
 * Customer service holds this tab too, and no other tab of Operations.
 *
 * No approved frame exists for this tab; it is drawn from the Operations
 * dashboard's own pieces (heading, freshness line, cards, panels).
 */

type Order = { sales_order: string; order_number: string | null };
type LeftOut = { reason: string; label: string; count: number; orders: Order[] };

/** What a run's summary shows, live or from the history. */
type Shown = {
  rows_read: number;
  skipped_rows: number;
  confirmed: number;
  not_confirmed: number;
  confirmed_orders: Order[];
  left_out: LeftOut[];
};
type Result = Shown & {
  freshness: Freshness;
  run_id: number;
  stated_count: number | null;
  file: { name: string; content_base64: string } | null;
};
type RunHead = {
  id: number;
  built_at: string;
  built_by: string | null;
  shopify_read_at: string | null;
  rows_read: number;
  stated_count: number | null;
  skipped_rows: number;
  confirmed: number;
  not_confirmed: number;
  file_name: string | null;
};
type Run = RunHead & Shown;
type KhazenlyTab = { freshness: Freshness; runs: RunHead[] };

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

/** One group of orders - the confirmed ones, or one reason - opening to its list. */
function OrderGroup({
  id,
  label,
  note,
  orders,
}: {
  id: string;
  label: string;
  note?: string;
  orders: Order[];
}) {
  const [open, setOpen] = useState(false);
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
          {label}
          {note && <small>{note}</small>}
        </span>
        <span className="num">{orders.length}</span>
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
            {orders.map((order) => (
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

/** The three cards and the orders behind them: the same for a run just built and one from the history. */
function SummaryBody({ shown, prefix }: { shown: Shown; prefix: string }) {
  return (
    <>
      <div className="ops-tiles">
        <div className="ops-tile ops-tile--zero">
          <span className="ops-tile__label">In Khazenly's file</span>
          <span className="ops-tile__value">{shown.rows_read}</span>
          <span className="ops-tile__note">Orders on hold, read from the export</span>
        </div>
        <div className="ops-tile ops-tile--zero ops-kh__tile--in">
          <span className="ops-tile__label">Confirmed</span>
          <span className="ops-tile__value">{shown.confirmed}</span>
          <span className="ops-tile__note">In the file, each True</span>
        </div>
        <div className="ops-tile ops-tile--zero">
          <span className="ops-tile__label">Not confirmed</span>
          <span className="ops-tile__value">{shown.not_confirmed}</span>
          <span className="ops-tile__note">Left out: they stay on hold at Khazenly</span>
        </div>
      </div>

      {shown.skipped_rows > 0 && (
        <p className="ops-hint ops-list">
          {plural(shown.skipped_rows, "row", "rows")} in the export had no Khazenly sales order
          number, so {shown.skipped_rows === 1 ? "it was" : "they were"} not read as orders.
        </p>
      )}

      <section className="panel ops-list" aria-labelledby={`${prefix}-orders`}>
        <div className="panel__head ops-kh__head">
          <h2 className="panel__title" id={`${prefix}-orders`}>
            Orders · {plural(shown.rows_read, "order", "orders")}
          </h2>
          <p className="ops-hint">Open a group to see its orders.</p>
        </div>
        <ul className="ops-kh__groups">
          {shown.confirmed_orders.length > 0 && (
            <OrderGroup
              id={`${prefix}-confirmed`}
              label="Confirmed: in the file"
              orders={shown.confirmed_orders}
            />
          )}
          {shown.left_out.map((group) => (
            <OrderGroup
              key={group.reason}
              id={`${prefix}-${group.reason}`}
              label={group.label}
              note={HELD_BACK.has(group.reason) ? "Held back for safety" : "Not confirmed: left out"}
              orders={group.orders}
            />
          ))}
        </ul>
      </section>
    </>
  );
}

/** A run just built: its summary, then the file to download. */
function Summary({ result }: { result: Result }) {
  const url = useFileUrl(result.file);
  const readAt = result.freshness.updated_at;
  return (
    <>
      <SummaryBody shown={result} prefix="ops-kh-now" />

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

/** One run in the history, opening to its summary (read when opened). */
function HistoryRun({ run }: { run: RunHead }) {
  const [open, setOpen] = useState(false);
  const [found, setFound] = useState<Run | null>(null);
  const [failed, setFailed] = useState(false);
  const id = `ops-kh-run-${run.id}`;

  function toggle() {
    const opening = !open;
    setOpen(opening);
    if (opening && !found) {
      setFailed(false);
      api
        .get<Run>(`/api/khazenly/runs/${run.id}`)
        .then(setFound)
        .catch(() => setFailed(true));
    }
  }

  return (
    <li className="ops-kh__group">
      <button
        type="button"
        className="ops-kh__run"
        aria-expanded={open}
        aria-controls={open ? id : undefined}
        onClick={toggle}
      >
        <span>
          <span className="num">{dayAndTime(run.built_at)}</span>
          <small>
            {run.built_by ? `By ${run.built_by}` : "By someone no longer here"}
            {" · "}
            {run.file_name ? "File built" : "No file: nothing confirmed"}
          </small>
        </span>
        <span className="ops-kh__counts">
          <span className="num">{run.rows_read} read</span>
          <span className="num ops-kh__in">{run.confirmed} confirmed</span>
          <span className="num">{run.not_confirmed} not</span>
        </span>
        <OpsIcon name={open ? "up" : "down"} />
      </button>
      {open && (
        <div className="ops-kh__past" id={id}>
          {failed && (
            <p className="notice notice--refused" role="alert">
              Couldn't load this run.{" "}
              <button type="button" className="ops-linkbtn" onClick={() => { setOpen(false); setFound(null); }}>
                Close
              </button>
            </p>
          )}
          {!found && !failed && <p className="loading">Loading…</p>}
          {found && (
            <>
              {found.shopify_read_at && (
                <p className="ops-hint ops-list">
                  Checked against Shopify's tags from {dayAndTime(found.shopify_read_at)}
                  {found.file_name ? ` · ${found.file_name}` : ""}
                </p>
              )}
              <SummaryBody shown={found} prefix={id} />
            </>
          )}
        </div>
      )}
    </li>
  );
}

function History({ runs }: { runs: RunHead[] }) {
  return (
    <section className="panel ops-list" aria-labelledby="ops-kh-history">
      <div className="panel__head ops-kh__head">
        <h2 className="panel__title" id="ops-kh-history">
          History
        </h2>
        <p className="ops-hint">
          {runs.length ? `Last built ${dayAndTime(runs[0].built_at)}` : "Every file built is kept here."}
        </p>
      </div>
      {runs.length ? (
        <ul className="ops-kh__groups">
          {runs.map((run) => (
            <HistoryRun key={run.id} run={run} />
          ))}
        </ul>
      ) : (
        <p className="empty">No file has been built yet.</p>
      )}
    </section>
  );
}

export function OperationsKhazenly() {
  const now = useNow();
  const { tab, failed, reload } = useOpsTab(() => api.get<KhazenlyTab>("/api/khazenly"));
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
      .upload<Result>("/api/khazenly", file)
      .then(setResult)
      .catch((caught: unknown) => {
        setError(caught instanceof ApiError ? caught.message : "Couldn't reach the platform. Try again.");
      })
      // The new run joins the history; a refusal for old tags shows the line as it is now.
      .finally(() => {
        setBusy(false);
        reload();
      });
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

      {tab && <History runs={tab.runs} />}
    </>
  );
}
