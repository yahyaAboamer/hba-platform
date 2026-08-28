import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { api } from "../lib/api";
import { formatMonth } from "../lib/money";

type Sync = {
  shopify_configured: boolean;
  webhooks_configured: boolean;
  orders_indexed: number;
  last_order_synced_at: string | null;
  last_event_received_at: string | null;
  proof_stored_bytes: number;
  jobs: { pending: number; running: number; succeeded: number; failed: number };
};

type FailedJob = {
  id: number;
  kind: string;
  attempts: number;
  last_error: string | null;
  finished_at: string | null;
};

type UnownedCode = {
  code: string;
  order_count: number;
  unowned_months: string[];
};

type MailHealth = {
  configured: boolean;
  from_address: string | null;
  counts: Record<string, number>;
  failed: {
    id: number;
    event: string;
    recipient_email: string;
    attempts: number;
    last_error: string | null;
  }[];
};

/** §18.2 step 3. Nothing before 2026 is imported; there is nothing to claim. */
const EARLIEST = "2026-01-01";

/**
 * The operations the platform could do and had no button for.
 *
 * A reachability audit — every route the server serves, against every call the
 * interface makes — found nineteen capabilities with no way to reach them.
 * The worst was this one: **there was no way to import order history**, which
 * is step 3 of the cutover and the thing without which every other screen is
 * empty.
 *
 * The rest here are the ones the attention panel can only count. It says
 * "three codes belong to nobody" and "two emails could not be delivered", and
 * a number nobody can take apart is a number nobody can act on.
 */
export function DataPanel() {
  const [sync, setSync] = useState<Sync | null>(null);
  const [jobs, setJobs] = useState<FailedJob[] | null>(null);
  const [codes, setCodes] = useState<UnownedCode[] | null>(null);
  const [mail, setMail] = useState<MailHealth | null>(null);
  const [since, setSince] = useState(EARLIEST);
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [working, setWorking] = useState(false);

  const load = useCallback(() => {
    Promise.all([
      api.get<Sync>("/api/operations/sync"),
      api.get<{ jobs: FailedJob[] }>("/api/operations/failed-jobs"),
      api.get<{ codes: UnownedCode[] }>("/api/operations/unregistered-codes"),
      api.get<MailHealth>("/api/operations/notifications"),
    ])
      .then(([status, failed, unowned, health]) => {
        setSync(status);
        setJobs(failed.jobs);
        setCodes(unowned.codes);
        setMail(health);
      })
      .catch((caught) => setError(caught.message));
  }, []);

  useEffect(load, [load]);

  async function startImport() {
    setWorking(true);
    setError(null);
    setNotice(null);
    try {
      await api.post("/api/operations/start-import", { since });
      setNotice(
        "Queued. It runs as a server-side export and takes minutes — the order count below will climb.",
      );
      load();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Could not start it.");
    } finally {
      setWorking(false);
    }
  }

  return (
    <section className="panel settings__panel">
      <div className="panel__head">
        <h2 className="panel__title">Shopify &amp; data</h2>
      </div>

      <div className="data__body">
        {error && (
          <p className="notice notice--refused" role="alert">
            {error}
          </p>
        )}
        {notice && <p className="notice notice--settled">{notice}</p>}

        <dl className="data__facts">
          <Fact
            label="Shopify"
            value={sync?.shopify_configured ? "Connected" : "Not configured"}
          />
          <Fact
            label="Webhooks"
            value={sync?.webhooks_configured ? "Registered" : "Not registered"}
          />
          <Fact label="Orders indexed" value={sync?.orders_indexed ?? "—"} />
          <Fact
            label="Last order synced"
            value={sync?.last_order_synced_at ? when(sync.last_order_synced_at) : "Never"}
          />
          <Fact
            label="Email"
            value={mail?.configured ? (mail.from_address ?? "On") : "Not configured"}
          />
          <Fact
            label="Screenshots stored"
            value={sync ? `${Math.round(sync.proof_stored_bytes / 1024)} KB` : "—"}
          />
        </dl>

        {/*
         * §18.2 step 3, and it had no button at all. Shopify runs one bulk
         * operation per shop at a time, which is why the endpoint refuses a
         * second one rather than queueing it — said here so the refusal is
         * expected rather than alarming.
         */}
        <div className="data__import">
          <h3 className="data__heading">Import order history</h3>
          <p className="data__note">
            A server-side export of everything from this date onwards. It takes
            minutes, and Shopify allows one at a time — starting a second is
            refused rather than queued.
          </p>
          <div className="data__import-row">
            <label className="field data__field">
              <span className="field__label">From</span>
              <input
                className="input code"
                value={since}
                onChange={(event) => setSince(event.target.value)}
                placeholder={EARLIEST}
              />
            </label>
            <button
              type="button"
              className="button button--primary"
              onClick={startImport}
              disabled={working || !sync?.shopify_configured}
            >
              {working ? "Starting…" : "Import from Shopify"}
            </button>
          </div>
        </div>

        {/*
         * The attention panel says how many. This says which - and which month
         * to register each from, because guessing leaves a gap and the gap is
         * somebody's sales.
         */}
        {codes && codes.length > 0 && (
          <div className="data__list">
            <h3 className="data__heading">
              Discount codes belonging to nobody
            </h3>
            <p className="data__note">
              These have been used on orders and no model owns them for the
              months in question, so those sales are attributed to no one.
              Register the code from the first month listed.
            </p>
            <table className="table">
              <thead>
                <tr>
                  <th>Code</th>
                  <th className="numeric">Orders</th>
                  <th>Months with no owner</th>
                </tr>
              </thead>
              <tbody>
                {codes.map((row) => (
                  <tr key={row.code}>
                    <td>
                      <span className="code">{row.code}</span>
                    </td>
                    <td className="numeric">{row.order_count}</td>
                    <td className="data__months">
                      {row.unowned_months.map(formatMonth).join(", ")}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            <p className="data__note">
              Register one on the model's own page under{" "}
              <Link to="/affiliates">Affiliates</Link>.
            </p>
          </div>
        )}

        {mail && mail.failed.length > 0 && (
          <div className="data__list">
            <h3 className="data__heading">Emails that never arrived</h3>
            {/*
             * The provider being switched off is the usual reason a batch
             * fails, and it is fixed outside the platform - so the retry is a
             * button rather than something automatic. Retrying on its own
             * would hide the cause by eventually succeeding.
             */}
            <button
              type="button"
              className="button"
              onClick={() =>
                api
                  .post<{ queued: number }>("/api/operations/notifications/retry")
                  .then((result) => {
                    setNotice(
                      `${result.queued} queued again. They will go out within a minute if the problem is fixed.`,
                    );
                    load();
                  })
                  .catch((caught) => setError(caught.message))
              }
            >
              Send them again
            </button>
            <p className="data__note">
              Somebody was told nothing. This is invisible from every other
              screen — the month is approved, the payment recorded, and one
              person simply never heard.
            </p>
            <table className="table">
              <thead>
                <tr>
                  <th>To</th>
                  <th>About</th>
                  <th>Why not</th>
                </tr>
              </thead>
              <tbody>
                {mail.failed.map((row) => (
                  <tr key={row.id}>
                    <td>{row.recipient_email}</td>
                    <td>{row.event}</td>
                    <td className="data__error">{row.last_error ?? "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        {jobs && jobs.length > 0 && (
          <div className="data__list">
            <h3 className="data__heading">Work that did not happen</h3>
            <p className="data__note">
              These will not retry on their own.
            </p>
            <table className="table">
              <thead>
                <tr>
                  <th>Job</th>
                  <th className="numeric">Tries</th>
                  <th>Why it stopped</th>
                </tr>
              </thead>
              <tbody>
                {jobs.map((row) => (
                  <tr key={row.id}>
                    <td>
                      <span className="code">{row.kind}</span>
                    </td>
                    <td className="numeric">{row.attempts}</td>
                    <td className="data__error">{row.last_error ?? "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </section>
  );
}

function Fact({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="data__fact">
      <dt>{label}</dt>
      <dd>{value}</dd>
    </div>
  );
}

function when(iso: string): string {
  return new Date(iso).toLocaleString("en-GB", {
    day: "numeric",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  });
}
