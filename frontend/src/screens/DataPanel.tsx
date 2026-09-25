import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { ShopifyConnection } from "../components/ShopifyConnection";
import type { ShopifyConnectionState } from "../components/ShopifyConnection";
import { api } from "../lib/api";
import { formatMonth } from "../lib/money";
import "./PaymentDetail.css";

type Sync = {
  shopify_configured: boolean;
  webhooks_configured: boolean;
  orders_indexed: number;
  last_order_synced_at: string | null;
  last_event_received_at: string | null;
  proof_stored_bytes: number;
  jobs: { pending: number; running: number; succeeded: number; failed: number };
  refresh: Refresh;
};

/**
 * The reconciliation sweep, as *Refresh now* shows it. Only a sweep that
 * finished moves `last_success_at`; a failure keeps it.
 */
export type Refresh = {
  state: "not_connected" | "never" | "queued" | "running" | "failed" | "succeeded";
  last_success_at: string | null;
  failed_at: string | null;
  error_line: string | null;
};

/** How often to look again while a refresh is queued or running. */
const REFRESH_POLL_MS = 2000;

/**
 * The catalogue, and when HBA last heard about it.
 *
 * `last_synced_at` is the half that matters: a catalogue nobody has read for a
 * fortnight looks identical to a fresh one until it says so.
 */
/**
 * A parcel that needs a person (W12).
 *
 * Only ambiguities reach here. A parcel matching no model is a customer, which
 * is what almost every order in the shop is — listing those buried the ones
 * that mattered under fourteen thousand rows that were never HBA's parcels.
 */
type Unmatched = {
  shopify_order_id: string;
  reason: "ambiguous" | "no_match";
  classification: string;
  /** A model's own number, which is what makes it safe to show. */
  phone: string | null;
  /** The models sharing it. This is the thing to fix. */
  models: string[];
};

type ParcelSummary = {
  needs_you: number;
  customers: number;
  unusable_phone: number;
  no_phone: number;
  matched: number;
};

type Catalogue = {
  products: number;
  active_products: number;
  variants: number;
  line_items: number;
  last_synced_at: string | null;
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
/**
 * *Shopify and sync* — the export's Settings subsection.
 *
 * A card saying whether the shop is connected and when an order last arrived,
 * a card of what the connection is, and *Technical detail* behind a toggle.
 *
 * Everything this panel used to lay out at once - the history import, the
 * catalogue read, parcel matching, codes that belong to nobody, emails that
 * never arrived, work that stopped - is kept, behind that toggle. None of it
 * is in the export, and all of it is real work somebody sometimes has to do.
 *
 * ***Refresh now*** is the reconciliation sweep brought forward - the same
 * 48-hour read of changed orders that runs every half hour, and read-only
 * towards Shopify. Asking is not refreshing: the card says *Refreshing* until
 * the sweep finishes, and *last successful refresh* moves only then. A failed
 * sweep keeps the last success and says what went wrong. The catalogue read
 * is under *Technical detail*.
 */
export function DataPanel({ goLiveMonth }: { goLiveMonth: string | null }) {
  const [sync, setSync] = useState<Sync | null>(null);
  const [jobs, setJobs] = useState<FailedJob[] | null>(null);
  const [codes, setCodes] = useState<UnownedCode[] | null>(null);
  const [mail, setMail] = useState<MailHealth | null>(null);
  const [since, setSince] = useState(EARLIEST);
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [working, setWorking] = useState(false);
  const [catalogue, setCatalogue] = useState<Catalogue | null>(null);
  const [syncingCatalogue, setSyncingCatalogue] = useState(false);
  const [parcels, setParcels] = useState<Unmatched[] | null>(null);
  const [parcelSummary, setParcelSummary] = useState<ParcelSummary | null>(null);
  const [scanning, setScanning] = useState(false);
  const [detailOpen, setDetailOpen] = useState(false);
  const [connection, setConnection] = useState<ShopifyConnectionState | null>(null);
  const [asking, setAsking] = useState(false);
  const [refreshError, setRefreshError] = useState<string | null>(null);

  const load = useCallback(() => {
    Promise.all([
      api.get<Sync>("/api/operations/sync"),
      api.get<{ jobs: FailedJob[] }>("/api/operations/failed-jobs"),
      api.get<{ codes: UnownedCode[] }>("/api/operations/unregistered-codes"),
      api.get<MailHealth>("/api/operations/notifications"),
      api.get<Catalogue>("/api/operations/catalogue"),
      api.get<{ parcels: Unmatched[]; summary: ParcelSummary }>(
        "/api/operations/unmatched-parcels",
      ),
    ])
      .then(([status, failed, unowned, health, products, unattached]) => {
        setSync(status);
        setJobs(failed.jobs);
        setCodes(unowned.codes);
        setMail(health);
        setCatalogue(products);
        setParcels(unattached.parcels);
        setParcelSummary(unattached.summary);
      })
      .catch((caught) => setError(caught.message));
  }, []);

  useEffect(load, [load]);

  // While a refresh is queued or running, look again until it finishes. Only
  // the status is re-read, not the whole panel.
  const inFlight = sync?.refresh.state === "queued" || sync?.refresh.state === "running";
  useEffect(() => {
    if (!inFlight) return;
    const timer = window.setTimeout(() => {
      api.get<Sync>("/api/operations/sync").then(setSync).catch(() => undefined);
    }, REFRESH_POLL_MS);
    return () => window.clearTimeout(timer);
  }, [inFlight, sync]);

  async function refreshNow() {
    setAsking(true);
    setRefreshError(null);
    try {
      const body = await api.post<{ refresh: Refresh }>("/api/operations/refresh", {});
      setSync((current) => (current ? { ...current, refresh: body.refresh } : current));
    } catch (caught) {
      setRefreshError(caught instanceof Error ? caught.message : "The refresh could not be started.");
    } finally {
      setAsking(false);
    }
  }

  async function syncCatalogue() {
    setSyncingCatalogue(true);
    setError(null);
    setNotice(null);
    try {
      await api.post("/api/operations/sync-catalogue", {});
      setNotice(
        "Queued. It walks the shop a page at a time — the counts below will climb.",
      );
      load();
    } catch (caught) {
      setError(
        caught instanceof Error ? caught.message : "Could not start it.",
      );
    } finally {
      setSyncingCatalogue(false);
    }
  }

  async function scanRecipients() {
    setScanning(true);
    setError(null);
    setNotice(null);
    try {
      await api.post("/api/operations/scan-recipients", { since });
      setNotice(
        "Queued. It works through the history a few pages at a time and carries on by itself.",
      );
      load();
    } catch (caught) {
      setError(
        caught instanceof Error ? caught.message : "Could not start it.",
      );
    } finally {
      setScanning(false);
    }
  }

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

  const failed = sync?.jobs.failed ?? 0;
  const refresh = sync?.refresh;
  const refreshing = inFlight || asking;
  // The export's three states (`syncState`), and *Not connected*, which it
  // never drew. Queued and running both read *Refreshing*: neither is done.
  const tone = !refresh ? "quiet" : refresh.state === "not_connected" || refresh.state === "failed" ? "refused" : "approved";
  const stateWords = !refresh
    ? "Checking…"
    : refresh.state === "not_connected"
      ? "Not connected"
      : refreshing
        ? "Refreshing"
        : refresh.state === "failed"
          ? "Last refresh failed"
          : "Connected";

  return (
    <>
      <section className="pay-detail__card sync__card">
        <div className="sync__head">
          <div>
            <h2 className="sync__store">{connection?.shop_name ?? connection?.shop_domain ?? "Shopify"}</h2>
            <div className="sync__state" role="status">
              <span className={`sync__dot sync__dot--${tone}`} aria-hidden="true" />
              <span className={`sync__tone--${tone}`}>{stateWords}</span>
              {refresh && refresh.state !== "not_connected" && (
                <span className="sync__when">
                  · {refresh.last_success_at ? `last successful refresh ${longWhen(refresh.last_success_at)}` : "no successful refresh yet"}
                </span>
              )}
            </div>
          </div>
          <button
            type="button"
            className="sync__refresh"
            onClick={refreshNow}
            disabled={refreshing || !refresh || refresh.state === "not_connected"}
          >
            {refreshing ? "Refreshing…" : refresh?.state === "failed" ? "Try again" : "Refresh now"}
          </button>
        </div>
        {refresh?.state === "failed" && !refreshing && refresh.error_line && (
          <p className="sync__error">{refresh.error_line}</p>
        )}
        {refreshError && <p className="sync__error" role="alert">{refreshError}</p>}
        {failed > 0 && (
          <p className="sync__error">
            {failed} {failed === 1 ? "piece of work" : "pieces of work"} stopped and will not retry on its own. The technical detail below lists {failed === 1 ? "it" : "them"}.
          </p>
        )}
        {error && <p className="sync__error" role="alert">{error}</p>}
        {notice && <p className="sync__notice">{notice}</p>}
      </section>

      {/* The export's Connection card, editable (owner, decision b). */}
      <ShopifyConnection onChanged={setConnection} />

      <button
        type="button"
        className="sync__toggle"
        aria-expanded={detailOpen}
        onClick={() => setDetailOpen(!detailOpen)}
      >
        Technical detail
      </button>

      {detailOpen && <section className="panel settings__panel">
      <div className="data__body">
        <dl className="data__facts">
          <Fact
            label="Shopify"
            value={sync?.shopify_configured ? "Connected" : "Not configured"}
          />
          <Fact
            label="Webhooks"
            value={sync?.webhooks_configured ? "Registered" : "Not registered"}
          />
          <Fact label="Go-live month" value={goLiveMonth ? formatMonth(goLiveMonth) : "Not set"} />
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
         * **Safe against the shared shop**, unlike the import above it, and
         * said here because the two sit side by side and one of them is not.
         * The import is a bulk operation and Shopify allows one per shop; this
         * is ordinary paginated reads.
         *
         * The freshness line matters more than the counts. A catalogue nobody
         * has synced for a fortnight looks identical to a fresh one until
         * something says otherwise.
         */}
        <div className="data__import">
          <h3 className="data__heading">Product catalogue</h3>
          <p className="data__note">
            {catalogue === null
              ? "Checking…"
              : catalogue.products === 0
                ? "Nothing read yet. Products, sizes and images are what a wardrobe is built from."
                : `${catalogue.products} product${catalogue.products === 1 ? "" : "s"} · ${catalogue.active_products} active · ${catalogue.variants} size${catalogue.variants === 1 ? "" : "s"}`}
          </p>
          <p className="data__note">
            {catalogue?.last_synced_at
              ? `Last read from Shopify ${when(catalogue.last_synced_at)}.`
              : "Reading it is ordinary paginated requests — safe to run at any time, unlike the import above."}
          </p>
          <div className="data__import-row">
            <button
              type="button"
              className="button"
              onClick={syncCatalogue}
              disabled={syncingCatalogue || !sync?.shopify_configured}
            >
              {syncingCatalogue ? "Starting…" : "Read the catalogue"}
            </button>
          </div>
        </div>

        {/*
         * **Matching, not attribution.** Attribution asks who *sold* an order
         * - a code on it. This asks who it was *sent to* - the phone on the
         * parcel, which HBA typed from her profile (D11). A model can sell a
         * hundred orders she never touched.
         */}
        <div className="data__import">
          <h3 className="data__heading">Parcels sent to models</h3>
          <p className="data__note">
            Works out which orders were shipments to a model, by the phone on
            the parcel. Ordinary paginated reads — safe to run at any time, and
            it carries on by itself until the history is done.
          </p>
          <div className="data__import-row">
            <button
              type="button"
              className="button"
              onClick={scanRecipients}
              disabled={scanning || !sync?.shopify_configured}
            >
              {scanning ? "Starting…" : "Match parcels from " + since}
            </button>
          </div>
          {/*
           * **The shape first, then the work.** Almost every order in the shop
           * is a customer's, and saying so as a number is the difference
           * between a screen that reports and one that appears to demand
           * fourteen thousand things.
           */}
          {parcelSummary !== null && parcelSummary.matched + parcelSummary.customers > 0 && (
            <p className="data__note">
              {parcelSummary.matched} parcel
              {parcelSummary.matched === 1 ? "" : "s"} attached to a model ·{" "}
              {parcelSummary.customers} customer order
              {parcelSummary.customers === 1 ? "" : "s"}, which is normal
              {parcelSummary.unusable_phone > 0 &&
                ` · ${parcelSummary.unusable_phone} with a number that is not an Egyptian mobile`}
              .
            </p>
          )}

          {/*
           * Only ambiguities. A parcel matching no model is a customer, not a
           * problem — and the only genuinely stuck state is two models sharing
           * a number, because then a real parcel cannot reach either of them.
           */}
          {parcels && parcels.length > 0 && (
            <>
              <p className="data__note data__parcels-lede">
                <strong>
                  {parcels.length} parcel{parcels.length === 1 ? "" : "s"} cannot
                  be attached to anyone.
                </strong>{" "}
                More than one model has the same phone number on file, so the
                platform cannot tell whose parcel it is. Give each model her own
                number under <Link to="/affiliates">Models</Link> → her profile →
                Contact and shipping → More address details → Phone on the
                parcel, then run this again.
              </p>
              <ul className="data__parcels">
                {parcels.map((row) => (
                  <li key={row.shopify_order_id}>
                    <span className="data__parcel-order">
                      Order {row.shopify_order_id}
                    </span>
                    <span className="data__parcel-why">
                      {row.phone}
                      {row.models.length > 0 &&
                        ` — ${row.models.join(", ")}`}
                    </span>
                  </li>
                ))}
              </ul>
            </>
          )}
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
              <Link to="/affiliates">Models</Link>.
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
    </section>}
    </>
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

/** The export's `lastSync`: *6 November 2026, 08:15*, in Cairo. */
export function longWhen(iso: string): string {
  const parts = new Intl.DateTimeFormat("en-GB", {
    timeZone: "Africa/Cairo",
    day: "numeric",
    month: "long",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: "h23",
  }).formatToParts(new Date(iso));
  const part = (type: string) => parts.find((p) => p.type === type)?.value ?? "";
  return `${part("day")} ${part("month")} ${part("year")}, ${part("hour")}:${part("minute")}`;
}

function when(iso: string): string {
  return new Date(iso).toLocaleString("en-GB", {
    day: "numeric",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  });
}
