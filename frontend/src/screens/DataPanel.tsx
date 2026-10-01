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
  /** Only the orders nobody owns — never the code's whole total. */
  order_count: number;
  unowned_months: string[];
  /** Who holds the code in its other months, and how many orders are theirs. */
  held_by?: {
    affiliate_id: number;
    name: string;
    start_month: string;
    end_month: string | null;
    order_count: number;
  }[];
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
  const [staleCount, setStaleCount] = useState(0);

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
  const validSince = /^\d{4}-\d{2}-\d{2}$/.test(since) && since >= EARLIEST;
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

  // S2: everything below that means somebody is waiting, gathered into one
  // card at the top - it used to sit two clicks deep among tools and trivia.
  // Counted in lists, not rows: forty orders and a hundred stopped jobs are
  // two things to deal with, not "141 things".
  const waiting = [codes?.length, mail?.failed.length, jobs?.length, parcels?.length, staleCount]
    .filter((count) => (count ?? 0) > 0).length;
  const connected = Boolean(sync?.shopify_configured);

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
        {/* S1: a disabled button says why. */}
        {refresh?.state === "not_connected" && (
          <p className="sync__hint">Connect the shop below first - there is nothing to refresh yet.</p>
        )}
        {refresh?.state === "failed" && !refreshing && refresh.error_line && (
          <p className="sync__error">{refresh.error_line}</p>
        )}
        {refreshError && <p className="sync__error" role="alert">{refreshError}</p>}
        {error && <p className="sync__error" role="alert">{error}</p>}
        {notice && <p className="sync__notice">{notice}</p>}
      </section>

      <section className="panel" hidden={waiting === 0} aria-hidden={waiting === 0}>
        <div className="panel__head">
          <h2 className="panel__title">Needs attention</h2>
          <span className="settings__head-note">
            {waiting === 1 ? "One list is" : `${waiting} lists are`} waiting on a person
          </span>
        </div>
        <div className="data__body">
          <StaleFulfilments onCount={setStaleCount} />

          {parcels && parcels.length > 0 && (
            <div className="data__import">
              <h3 className="data__heading">Parcels that cannot be attached to anyone</h3>
              <p className="data__note data__parcels-lede">
                <strong>
                  {parcels.length} parcel{parcels.length === 1 ? "" : "s"} matched more
                  than one model.
                </strong>{" "}
                More than one model has the same phone number on file, so the
                platform cannot tell whose parcel it is. Give each model her own
                number under <Link to="/affiliates">Models</Link> → her profile →
                Contact and shipping → Phone on the parcel, then match again under
                Tools.
              </p>
              <ul className="data__parcels">
                {parcels.map((row) => (
                  <li key={row.shopify_order_id}>
                    <span className="data__parcel-order">Order {row.shopify_order_id}</span>
                    <span className="data__parcel-why">
                      {row.phone}
                      {row.models.length > 0 && ` — ${row.models.join(", ")}`}
                    </span>
                  </li>
                ))}
              </ul>
            </div>
          )}

          {/*
           * Which codes, and from which month. Since ADR 0053 a model's code is
           * the one she applied with, so an unowned code is usually HBA's own -
           * a brand code - or a model's that was typed differently when she
           * applied.
           */}
          {codes && codes.length > 0 && (
            <div className="data__list">
              <h3 className="data__heading">Discount codes belonging to nobody</h3>
              <p className="data__note">
                These were used on orders in months when nobody owns them, so
                those sales count for no one. Only those orders are counted here:
                a code a model holds from a later month is listed with her, and
                her own orders are on her profile. If a code is HBA's own, add it
                under <Link to="/settings?section=codes">Brand codes</Link>.
              </p>
              <table className="table">
                <thead>
                  <tr>
                    <th>Code</th>
                    <th className="numeric">Orders with no owner</th>
                    <th>Months with no owner</th>
                    <th>Held by</th>
                  </tr>
                </thead>
                <tbody>
                  {codes.map((row) => (
                    <tr key={row.code}>
                      <td><span className="code">{row.code}</span></td>
                      <td className="numeric">{row.order_count}</td>
                      <td className="data__months">{row.unowned_months.map(formatMonth).join(", ")}</td>
                      <td className="data__months">
                        {/* Owner, 1 October 2026: ALI10's five January orders
                            read as the code's whole total. Naming who holds it,
                            from when and with how many orders, says otherwise. */}
                        {row.held_by && row.held_by.length > 0
                          ? row.held_by.map((holder, index) => (
                              <span key={`${holder.affiliate_id}-${holder.start_month}-${index}`} className="data__holder">
                                <Link to={`/affiliates/${holder.affiliate_id}`}>{holder.name}</Link>
                                {holder.end_month
                                  ? `, ${formatMonth(holder.start_month)} – ${formatMonth(holder.end_month)}`
                                  : `, from ${formatMonth(holder.start_month)}`}
                                {` · ${holder.order_count} ${holder.order_count === 1 ? "order" : "orders"} credited`}
                              </span>
                            ))
                          : "Nobody"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          {mail && mail.failed.length > 0 && (
            <div className="data__list">
              <h3 className="data__heading">Emails that never arrived</h3>
              {/*
               * The provider being switched off is the usual reason a batch
               * fails, and it is fixed outside the platform - so the retry is a
               * button rather than something automatic.
               */}
              <p className="data__note">
                Somebody was told nothing. This is invisible from every other
                screen - the month is approved, the payment recorded, and one
                person simply never heard.
              </p>
              <button
                type="button"
                className="button"
                onClick={() =>
                  api
                    .post<{ queued: number }>("/api/operations/notifications/retry")
                    .then((result) => {
                      setNotice(`${result.queued} queued again. They will go out within a minute if the problem is fixed.`);
                      load();
                    })
                    .catch((caught) => setError(caught.message))
                }
              >
                Send them again
              </button>
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
                These will not retry on their own. The same failure is one line,
                with how many times it happened.
              </p>
              <table className="table">
                <thead>
                  <tr>
                    <th>Job</th>
                    <th className="numeric">Times</th>
                    <th>Why it stopped</th>
                  </tr>
                </thead>
                <tbody>
                  {groupJobs(jobs).map((row) => (
                    <tr key={`${row.kind}|${row.error}`}>
                      <td><span className="code">{row.kind}</span></td>
                      <td className="numeric">{row.count}</td>
                      <td className="data__error">{row.error}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </section>

      {/* The export's Connection card, editable (owner, decision b). */}
      <ShopifyConnection onChanged={setConnection} />

      {/*
       * S2: the three things somebody runs rarely, together and out of the
       * way of what needs a person. Each says whether it is safe against the
       * shared shop, because one of them is not like the others.
       */}
      <section className="panel">
        <div className="panel__head">
          <h2 className="panel__title">Tools</h2>
          <span className="settings__head-note">Rare, and each says whether it is safe to run</span>
        </div>
        <div className="data__body">
          {/*
           * §18.2 step 3. Shopify runs one bulk operation per shop at a time,
           * which is why the endpoint refuses a second one rather than
           * queueing it - said here so the refusal is expected.
           */}
          <div className="data__tool">
            <h3 className="data__heading">Import order history</h3>
            <p className="data__note">
              A server-side export of every order from the date below. It takes
              minutes, and Shopify allows one at a time - starting a second is
              refused rather than queued.
            </p>
            <div className="data__import-row">
              <label className="field data__field">
                <span className="field__label">From</span>
                {/* S3: a real date, not free text. Nothing before 2026 is
                 *  imported, so nothing earlier is offered. */}
                <input
                  className="input"
                  type="date"
                  min={EARLIEST}
                  max={today()}
                  value={since}
                  onChange={(event) => setSince(event.target.value)}
                />
              </label>
              <button type="button" className="button button--primary" onClick={startImport}
                disabled={working || !connected || !validSince}>
                {working ? "Starting…" : "Import from Shopify"}
              </button>
            </div>
          </div>

          {/*
           * **Safe against the shared shop**, unlike the import above it:
           * ordinary paginated reads. The freshness line matters more than the
           * counts - a stale catalogue looks identical to a fresh one.
           */}
          <div className="data__import">
            <h3 className="data__heading">Read the catalogue</h3>
            <p className="data__note">
              {catalogue === null
                ? "Checking…"
                : catalogue.products === 0
                  ? "Nothing read yet. Products, sizes and images are what a wardrobe is built from."
                  : `${catalogue.products} product${catalogue.products === 1 ? "" : "s"} · ${catalogue.active_products} active · ${catalogue.variants} size${catalogue.variants === 1 ? "" : "s"}`}
              {catalogue?.last_synced_at ? ` · last read ${when(catalogue.last_synced_at)}` : ""}. Safe to run at any time.
            </p>
            <button type="button" className="button" onClick={syncCatalogue} disabled={syncingCatalogue || !connected}>
              {syncingCatalogue ? "Starting…" : "Read the catalogue"}
            </button>
          </div>

          {/*
           * **Matching, not attribution.** Attribution asks who *sold* an
           * order; this asks who it was *sent to* - the phone on the parcel,
           * which HBA typed from her profile (D11).
           */}
          <div className="data__import">
            <h3 className="data__heading">Match parcels to models</h3>
            <p className="data__note">
              Works out which orders were shipments to a model, by the phone on
              the parcel, from {validSince ? formatDay(since) : "the date above"}. Safe to run at any
              time, and it carries on by itself until the history is done.
              {parcelSummary !== null && parcelSummary.matched + parcelSummary.customers > 0 && (
                <>
                  {" "}So far: {parcelSummary.matched} parcel{parcelSummary.matched === 1 ? "" : "s"} attached
                  to a model · {parcelSummary.customers} customer order{parcelSummary.customers === 1 ? "" : "s"},
                  which is normal
                  {parcelSummary.unusable_phone > 0 && ` · ${parcelSummary.unusable_phone} with a number that is not an Egyptian mobile`}.
                </>
              )}
            </p>
            <button type="button" className="button" onClick={scanRecipients} disabled={scanning || !connected || !validSince}>
              {scanning ? "Starting…" : "Match parcels"}
            </button>
          </div>
        </div>
      </section>

      <button type="button" className="sync__toggle" aria-expanded={detailOpen} onClick={() => setDetailOpen(!detailOpen)}>
        Technical detail
      </button>

      {/* S4: what is left is what somebody debugging needs - no trivia, and
          nothing the card above already says. */}
      {detailOpen && (
        <section className="panel">
          <dl className="data__facts data__body">
            <Fact label="Order webhooks" value={sync?.webhooks_configured ? "Registered" : "Not registered"} />
            <Fact label="Go-live month" value={goLiveMonth ? formatMonth(goLiveMonth) : "Not set"} />
            <Fact label="Orders indexed" value={sync?.orders_indexed ?? "—"} />
            <Fact label="Last order synced" value={sync?.last_order_synced_at ? when(sync.last_order_synced_at) : "Never"} />
            <Fact label="Email" value={mail?.configured ? (mail.from_address ?? "On") : "Not configured"} />
            <Fact label="Background work" value={sync ? `${sync.jobs.pending} waiting · ${sync.jobs.running} running · ${failed} stopped` : "—"} />
          </dl>
        </section>
      )}
    </>
  );
}

/**
 * Stopped work, one line per kind and reason. A shop that is not connected
 * stops the same job a hundred times, and a hundred identical rows buried the
 * one different failure somebody needed to see.
 */
function groupJobs(jobs: FailedJob[]) {
  const groups = new Map<string, { kind: string; error: string; count: number }>();
  for (const job of jobs) {
    const error = job.last_error ?? "—";
    const key = `${job.kind}|${error}`;
    const found = groups.get(key) ?? { kind: job.kind, error, count: 0 };
    found.count += 1;
    groups.set(key, found);
  }
  return [...groups.values()].sort((a, b) => b.count - a.count);
}

/** Today's date in Cairo, as a date field wants it. */
function today(): string {
  return new Intl.DateTimeFormat("en-CA", { timeZone: "Africa/Cairo" }).format(new Date());
}

/** *1 January 2026*, from `2026-01-01`. */
function formatDay(iso: string): string {
  const [year, month, day] = iso.split("-").map(Number);
  return new Intl.DateTimeFormat("en-GB", { day: "numeric", month: "long", year: "numeric", timeZone: "UTC" })
    .format(new Date(Date.UTC(year, month - 1, day)));
}

type StaleOrder = {
  shopify_order_id: string;
  order_number: string;
  days: number | null;
  courier: string | null;
  attributed: boolean;
  admin_url: string | null;
};

type Stale = {
  after_days: number;
  total: number;
  groups: { reason: string; orders: StaleOrder[] }[];
};

/** Why nothing will ever report on these, in the words the list uses. */
const STALE_REASON: Record<string, string> = {
  no_tracking: "No tracking number",
  other_courier: "Shipped with another courier",
  courier_silent: "Bosta has gone quiet",
  not_yet_read: "Not read since the rules changed",
};

/**
 * *Waiting on a person* (ADR 0051).
 *
 * Only Bosta reports delivery back to Shopify. An order shipped with no
 * tracking number or with Aramex or DHL stays *fulfilled* for ever unless
 * somebody marks it delivered or cancels it **in Shopify** — so each row opens
 * the order there, and the next sweep brings the answer back. The platform
 * never marks them itself: delivery comes from Shopify (ADR 0023).
 *
 * Its own read, so a failure here costs this list and not the panel.
 */
export function StaleFulfilments({ onCount }: { onCount?: (count: number) => void } = {}) {
  const [stale, setStale] = useState<Stale | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    api.get<Stale>("/api/operations/stale-fulfilments")
      .then((found) => { if (live) { setStale(found); onCount?.(found.total); } })
      .catch((caught) => { if (live) setError(caught.message); });
    return () => { live = false; };
    // Once, on arrival; `onCount` is the parent's setter.
  }, []);

  if (error) {
    return (
      <div className="data__import">
        <h3 className="data__heading">Shipped, and nobody will report on it</h3>
        <p className="data__note" role="status">Could not load this list.</p>
      </div>
    );
  }
  if (stale === null || stale.total === 0) return null;

  return (
    <div className="data__import">
      <h3 className="data__heading">Shipped, and nobody will report on it</h3>
      <p className="data__note data__parcels-lede">
        <strong>
          {stale.total} order{stale.total === 1 ? "" : "s"} shipped over{" "}
          {stale.after_days} days ago still {stale.total === 1 ? "has" : "have"} no
          delivery news.
        </strong>{" "}
        Only Bosta reports back to Shopify. Open each one in Shopify and mark it
        delivered, or cancel it — the platform picks the change up on its next
        sweep. Until then it counts as pending.
      </p>
      {stale.groups.filter((group) => group.orders.length > 0).map((group) => (
        <details key={group.reason} className="data__stale">
          <summary>
            {STALE_REASON[group.reason] ?? group.reason} · {group.orders.length}
          </summary>
          <ul className="data__parcels">
            {group.orders.map((row) => (
              <li key={row.shopify_order_id}>
                <span className="data__parcel-order">
                  {row.admin_url ? (
                    <a href={row.admin_url} target="_blank" rel="noreferrer">
                      {row.order_number || `Order ${row.shopify_order_id}`}
                    </a>
                  ) : (
                    row.order_number || `Order ${row.shopify_order_id}`
                  )}
                </span>
                <span className="data__parcel-why">
                  {row.days !== null ? `${row.days} days` : ""}
                  {row.courier ? ` · ${row.courier}` : ""}
                  {row.attributed ? " · a model's code" : ""}
                </span>
              </li>
            ))}
          </ul>
        </details>
      ))}
    </div>
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
