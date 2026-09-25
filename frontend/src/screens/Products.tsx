import { useCallback, useEffect, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";

import { api, can } from "../lib/api";
import type { Session } from "../lib/api";
import "./Products.css";
import "./PaymentDetail.css";

type Row = {
  shopify_product_id: string;
  title: string;
  status: string;
  image_url: string | null;
  sizes: number;
  /** Distinct models who have one, on the same gift rule as her wardrobe. */
  models_with_it: number;
  /** `null` where nothing has been asked for; `false` is a request that
   *  exists and is currently hidden, which is not the same thing (W09). */
  featured: boolean | null;
};

type RosterEntry = {
  affiliate_id: number;
  name: string;
  status: string;
  /** Her newest gift of this product, when there is one: the order that
   *  carried it and the size (the export's `orderRefFor` / `vShipment`). */
  shopify_order_id?: string;
  order_number?: string;
  size?: string | null;
};

/**
 * What HBA has asked the models to post about this product (W09).
 *
 * Named rather than written inline at the call site: `test_reachability`
 * finds a route by scanning for `api.put<...>("/path")`, and a **nested**
 * generic — `NonNullable<Detail["feature_request"]>` — stops it matching, so
 * the route reads as one with no way in from the interface. The message is
 * optional (D12): a product can be featured on its picture alone.
 */
/**
 * *4 models*, or the fact that nobody has one yet.
 *
 * Zero is written out rather than shown as `0`, because a nought in a column
 * of counts reads as a measurement that came back empty. **No model has one**
 * is the thing HBA would act on.
 */
/**
 * *3 of 12 received* — the export's words for model coverage.
 *
 * Out of the models working with HBA now, which the server counts, so a
 * product nobody has reads *0 of 12 received* rather than a bare nought: the
 * denominator is what makes the number something HBA can act on.
 */
export function coverageLabel(count: number, of: number): string {
  return `${count} of ${of} received`;
}

/** How full the coverage bar is, as a CSS width. Geometry, not money. */
export function coverageWidth(count: number, of: number): string {
  if (of <= 0) return "0%";
  return `${Math.min(100, Math.round((count / of) * 100))}%`;
}

/**
 * The feature-request column: *Active* while a request is showing to models,
 * and nothing otherwise — the export draws one pill and leaves the rest of
 * the column empty. A hidden request is still kept (W09); it is simply not
 * something this list needs to say.
 */
export function featureLabel(featured: boolean | null): string | null {
  return featured === true ? "Active" : null;
}

export type FeatureRequest = { message: string | null; visible: boolean };

type Detail = {
  shopify_product_id: string;
  title: string;
  status: string;
  image_url: string | null;
  sizes: { title: string; sku: string | null }[];
  roster: {
    received: RosterEntry[];
    processing: RosterEntry[];
    needs_checking: RosterEntry[];
    not_sent: RosterEntry[];
  };
  feature_request: FeatureRequest | null;
};

/**
 * The catalogue.
 *
 * **Active by default; All products includes draft and archived** (W01). A
 * product archived in Shopify is still in somebody's wardrobe, so the default
 * answers *what are we selling* and the switch answers *what have we ever
 * sold*.
 *
 * Search is on the name, because W01 puts colour in the product name and there
 * is no separate colour taxonomy to filter by.
 */

type Scope = "active" | "all" | "requests";

type Listing = {
  products: Row[];
  total: number;
  counts: { active: number; all: number; requests: number };
  active_models: number;
};

/** The export's page is ten rows, with Previous and Next under it. */
const CATALOGUE_PAGE = 10;

/**
 * *Products* — `vProducts` in the approved export.
 *
 * Three filters and a search on one row; a table of Product, Status, Model
 * coverage and Feature request; and *1–10 of 340* with Previous and Next
 * under it.
 *
 * It had an *All products* checkbox where the export has three filters, a
 * *Show 60 more* button where the export pages, and a *Selling best through
 * codes* panel the export does not draw - removed by the owner's decision e
 * (25 September). A model's own best sellers are hers, in her wardrobe.
 */
export function Products({ session }: { session: Session }) {
  const navigate = useNavigate();
  const [listing, setListing] = useState<Listing | null>(null);
  const [params, setParams] = useSearchParams();
  const asked_scope = params.get("scope");
  const scope: Scope =
    asked_scope === "all" || asked_scope === "requests" ? asked_scope : "active";
  const [search, setSearch] = useState(() => params.get("q") ?? "");
  const [page, setPage] = useState(0);

  const remember = useCallback(
    (next: { scope?: string; q?: string }) => {
      setParams(
        (previous) => {
          const updated = new URLSearchParams(previous);
          for (const [key, value] of Object.entries(next)) {
            // The default filter and an empty search leave no trace.
            if (!value || value === "active") updated.delete(key);
            else updated.set(key, value);
          }
          return updated;
        },
        { replace: true },
      );
    },
    [setParams],
  );
  const [asked, setAsked] = useState(search);
  const [error, setError] = useState<string | null>(null);

  /*
   * A third of a second after the last keystroke, not on every one: typing
   * "dress" was five requests, four of them stale before they returned.
   */
  useEffect(() => {
    const timer = setTimeout(() => {
      setAsked(search);
      remember({ q: search.trim() });
    }, 300);
    return () => clearTimeout(timer);
  }, [search, remember]);

  useEffect(() => setPage(0), [scope, asked]);

  useEffect(() => {
    const query = new URLSearchParams();
    query.set("scope", scope);
    if (asked.trim()) query.set("search", asked.trim());
    query.set("limit", String(CATALOGUE_PAGE));
    query.set("offset", String(page * CATALOGUE_PAGE));
    let live = true;
    api
      .get<Listing>(`/api/products?${query}`)
      .then((body) => {
        if (live) setListing(body);
      })
      .catch((caught) => setError(caught.message));
    return () => {
      live = false;
    };
  }, [scope, asked, page]);

  const rows = listing?.products ?? null;
  const total = listing?.total ?? 0;
  const filters: { key: Scope; label: string; count: number }[] = [
    { key: "active", label: "Active", count: listing?.counts.active ?? 0 },
    { key: "all", label: "All products", count: listing?.counts.all ?? 0 },
    { key: "requests", label: "Active requests", count: listing?.counts.requests ?? 0 },
  ];

  return (
    <>
      <div className="page__head">
        <div className="page__title">
          <h1>Products</h1>
        </div>
      </div>

      {error && (
        <p className="notice notice--refused" role="alert">
          {error}
        </p>
      )}

      <div className="products__bar">
        <div className="products__filters" role="group" aria-label="Filter the catalogue">
          {filters.map((option) => (
            <button
              key={option.key}
              type="button"
              className={scope === option.key ? "chip chip--on" : "chip"}
              aria-pressed={scope === option.key}
              onClick={() => remember({ scope: option.key })}
            >
              {option.label}
              {listing && <span className="products__filter-count">{option.count}</span>}
            </button>
          ))}
        </div>
        <input
          type="search"
          className="input products__search"
          value={search}
          onChange={(event) => setSearch(event.target.value)}
          placeholder="Search name or SKU"
          aria-label="Search products by name or SKU"
        />
      </div>

      {rows === null && !error && <p className="empty">Loading…</p>}

      {rows !== null && (
        <div className="surface">
          {rows.length === 0 ? (
            /*
             * **Three different facts, three different messages** (S06). A
             * search with no hits is not an empty catalogue, and an empty
             * catalogue is a thing to fix in Settings rather than a shrug.
             */
            <p className="empty">
              {asked.trim()
                ? `No product matches “${asked.trim()}”.`
                : scope === "requests"
                  ? "No feature request is visible to models right now."
                  : "The catalogue has not been read yet. Settings → Connection → Read the catalogue."}
            </p>
          ) : (
            <table className="table products__table">
              <thead>
                <tr>
                  <th>Product</th>
                  <th className="products__status-cell">Status</th>
                  <th className="products__coverage">Model coverage</th>
                  <th className="products__feature">Feature request</th>
                  <th className="products__go" aria-hidden="true" />
                </tr>
              </thead>
              <tbody>
                {rows.map((row) => {
                  const feature = featureLabel(row.featured);
                  const of = listing?.active_models ?? 0;
                  return (
                    // The export's row is one button: the whole row opens the
                    // product, in the control font (ADR 0044), so its pill is
                    // the export's 20px. The name stays a link.
                    <tr key={row.shopify_product_id} className="control-font products__row"
                      onClick={() => navigate(`/products/${row.shopify_product_id}`)}>
                      <td>
                        <Link
                          className="products__who"
                          to={`/products/${row.shopify_product_id}`}
                        >
                          {row.image_url ? (
                            <img className="products__thumb" src={row.image_url} alt="" loading="lazy" />
                          ) : (
                            <span className="products__nothumb" aria-hidden="true">image</span>
                          )}
                          <span className="products__who-text">
                            {/* The name alone: no SKU and no size count under
                             *  it (owner, decision d). Sizes stay where they
                             *  help - the product's own page and the
                             *  wardrobes - and the search still finds a SKU. */}
                            <span className="products__name">{row.title}</span>
                          </span>
                        </Link>
                      </td>
                      <td className="products__status-cell">
                        <span className={`pill products__status--${row.status}`}>
                          {row.status.charAt(0).toUpperCase() + row.status.slice(1)}
                        </span>
                      </td>
                      <td className="products__coverage">
                        {coverageLabel(row.models_with_it, of)}
                        <span className="products__bar-track" aria-hidden="true">
                          <span
                            className="products__bar-fill"
                            style={{ width: coverageWidth(row.models_with_it, of) }}
                          />
                        </span>
                      </td>
                      <td className="products__feature">
                        {feature && (
                          <span className="products__active">
                            <span className="products__active-dot" aria-hidden="true" />
                            {feature}
                          </span>
                        )}
                      </td>
                      <td className="products__go" aria-hidden="true">→</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )}
        </div>
      )}

      {rows !== null && total > 0 && (
        <div className="products__pager">
          <span>
            {page * CATALOGUE_PAGE + 1}–{page * CATALOGUE_PAGE + rows.length} of {total}
            {asked.trim() ? " matching" : ""}
          </span>
          <span className="products__pager-acts">
            <button
              type="button"
              className="button button--row"
              disabled={page === 0}
              onClick={() => setPage(page - 1)}
            >
              Previous
            </button>
            <button
              type="button"
              className="button button--row"
              disabled={(page + 1) * CATALOGUE_PAGE >= total}
              onClick={() => setPage(page + 1)}
            >
              Next
            </button>
          </span>
        </div>
      )}

      {session && null}
    </>
  );
}

/** Product coverage and the approved secondary promotion editor. */
export function ProductDetail({ session }: { session: Session }) {
  const { id = "" } = useParams();
  return <ProductDetailPage key={id} id={id} session={session} />;
}

function ProductDetailPage({ id, session }: { id: string; session: Session }) {
  const [query, setQuery] = useSearchParams();
  const [detail, setDetail] = useState<Detail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);
  const [saving, setSaving] = useState(false);
  const promotion = query.get("view") === "promotion";
  const search = query.get("q") ?? "";
  const mayEdit = can(session, "affiliates.manage");
  const [closed, setClosed] = useState<string[]>([]);

  useEffect(() => {
    let live = true;
    setError(null);
    api.get<Detail>(`/api/products/${id}`)
      .then((found) => { if (live) setDetail(found); })
      .catch((caught) => { if (live) setError(caught.message); });
    return () => { live = false; };
  }, [id, attempt]);

  function setView(open: boolean) {
    setQuery((previous) => {
      const next = new URLSearchParams(previous);
      if (open) next.set("view", "promotion"); else next.delete("view");
      return next;
    });
    setError(null);
  }

  async function saveRequest(visible: boolean, message?: string) {
    setSaving(true);
    setError(null);
    try {
      const saved = await api.put<FeatureRequest>(`/api/products/${id}/feature-request`, {
        visible, ...(message !== undefined ? { message } : {}),
      });
      setDetail((current) => current && { ...current, feature_request: saved });
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Could not save.");
      throw caught;
    } finally { setSaving(false); }
  }

  async function removeRequest() {
    setSaving(true);
    setError(null);
    try {
      await api.del(`/api/products/${id}/feature-request`);
      setDetail((current) => current && { ...current, feature_request: null });
      setView(false);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Could not remove it.");
    } finally { setSaving(false); }
  }

  if (!detail) return error ? (
    <div className="notice notice--refused" role="alert">
      <p>{error}</p><button className="button" onClick={() => setAttempt((n) => n + 1)}>Try again</button>
    </div>
  ) : <p className="empty" role="status">Loading product…</p>;

  const groups: [string, RosterEntry[], string][] = [
    ["Received", detail.roster.received, "approved"], ["Processing", detail.roster.processing, "owed"],
    ["Needs checking", detail.roster.needs_checking, "refused"], ["Not sent", detail.roster.not_sent, "quiet"],
  ];
  const audience = detail.roster.received.length + detail.roster.processing.length;

  const shipmentOrder = query.get("shipment");
  const shipment = shipmentOrder ? findShipment(detail, shipmentOrder, Number(query.get("model"))) : null;
  if (shipmentOrder) {
    return <>
      <div className="page__head">
        <Link className="button product__back" to={`/products/${id}`}>← {detail.title}</Link>
        <div className="page__title">
          <h1>Shipment record</h1>
          {shipment && <span className="page__subtitle">{detail.title} · {shipment.entry.name}</span>}
        </div>
      </div>
      {shipment
        ? <ShipmentRecord productId={id} title={detail.title} shipment={shipment} />
        : <p className="notice notice--refused" role="alert">That shipment is not on this product any more.</p>}
    </>;
  }

  return <>
    <div className="page__head">
      {promotion
        ? <button type="button" className="button product__back" onClick={() => setView(false)} disabled={saving}>← {detail.title}</button>
        : <Link className="button product__back" to="/products">← Products</Link>}
      <div className="page__title">
        <h1>{promotion ? "Feature request" : detail.title}</h1>
      </div>
    </div>
    {error && <p className="notice notice--refused" role="alert">{error}</p>}
    {promotion ? (
      <PromotionEditor detail={detail} audience={audience} saving={saving} mayEdit={mayEdit}
        onSave={saveRequest} onRemove={removeRequest} onCancel={() => setView(false)} />
    ) : <>
      {/*
       * `vProduct`: the photograph beside its state, its sizes and one pill for
       * each coverage group with its count; the feature request on a surface
       * of its own; then every model by group, with a search.
       */}
      <div className="product__hero">
        <ProductImage source={detail.image_url} />
        <div className="product__facts">
          <div className="product__line">
            <span className={`pill products__status--${detail.status}`}>
              {detail.status.charAt(0).toUpperCase() + detail.status.slice(1)}
            </span>
            {/* The export prints a SKU here; a product has one per size, so
             *  the sizes are what is true at this level. */}
            <span className="product__sizes">{detail.sizes.map((size) => size.title).join(" · ")}</span>
          </div>
          <div className="product__coverage">
            {groups.map(([label, entries, tone]) => (
              <span className="product__coverage-pill" key={label}>
                <span className={`product__dot product__dot--${tone}`} aria-hidden="true" />
                {label} <span className="product__coverage-count">{entries.length}</span>
              </span>
            ))}
          </div>
        </div>
      </div>

      <section className="product__request">
        <div className="product__request-head">
          <div className="product__request-title">
            <h2>Feature request</h2>
            {detail.feature_request
              ? detail.feature_request.visible
                ? <span className="products__active"><span className="products__active-dot" aria-hidden="true" />Visible to models</span>
                : <span className="pill product__pill--owed">Hidden</span>
              : <span className="pill product__pill--quiet">None</span>}
          </div>
          {mayEdit && <div className="product__request-acts">
            {detail.feature_request ? <>
              <button type="button" className="button product__act--accent" onClick={() => setView(true)} disabled={saving}>Edit</button>
              <button type="button" className="button" disabled={saving} onClick={() => { void saveRequest(!detail.feature_request?.visible).catch(() => {}); }}>
                {detail.feature_request.visible ? "Hide" : "Show"}
              </button>
              <button type="button" className="button button--danger" disabled={saving} onClick={removeRequest}>Remove</button>
            </> : (
              <button type="button" className="button button--primary" onClick={() => setView(true)} disabled={saving}>Ask models to feature this</button>
            )}
          </div>}
        </div>
        {detail.feature_request?.message && <p className="product__message">{detail.feature_request.message}</p>}
      </section>

      <div className="product__coverage-head">
        <h2>Model coverage</h2>
        <input className="input product__search" aria-label="Search model names" placeholder="Search model names" value={search}
          onChange={(event) => setQuery((previous) => { const next = new URLSearchParams(previous); if (event.target.value) next.set("q", event.target.value); else next.delete("q"); return next; }, { replace: true })} />
      </div>
      <div className="product__groups">
        {groups.map(([label, entries, tone]) => {
          const shown = entries.filter((entry) => entry.name.toLocaleLowerCase().includes(search.toLocaleLowerCase())).sort((a, b) => a.name.localeCompare(b.name));
          const open = !closed.includes(label);
          return <section className="surface product__group" key={label}>
            <button type="button" className="product__group-head" aria-expanded={open}
              onClick={() => setClosed(open ? [...closed, label] : closed.filter((each) => each !== label))}>
              <span className="product__group-title">
                <span className={`product__dot product__dot--${tone}`} aria-hidden="true" />
                <span className="product__group-label">{label}</span>
                <span className="product__group-count">{search ? `${shown.length} of ${entries.length}` : entries.length}</span>
              </span>
              <span className="product__group-toggle">{open ? "Hide" : "Show"}</span>
            </button>
            {open && (shown.length === 0
              ? <p className="product__group-empty">{search ? "No matching models." : "None."}</p>
              : <ul className="product__roster">
                  {shown.map((entry) => <li key={entry.affiliate_id}>
                    <Link className="product__roster-name" to={`/affiliates/${entry.affiliate_id}?section=wardrobe`}>{entry.name}</Link>
                    {/* The export's second column: the order that carried it,
                     *  opening its shipment record; *not sent* otherwise. */}
                    {entry.shopify_order_id
                      ? <Link className="product__roster-ref control-font" to={`/products/${id}?shipment=${entry.shopify_order_id}&model=${entry.affiliate_id}`}>{entry.order_number}</Link>
                      : <span className="product__roster-ref product__roster-ref--none">not sent</span>}
                  </li>)}
                </ul>)}
          </section>;
        })}
      </div>
    </>}
  </>;
}

/** The export's message presets (`prPresets`, Admin lines 3103-3107). */
const PRESETS = [
  "Back in stock — please feature this in your upcoming content.",
  "Sales push this week — include it where it fits.",
  "New colourway — we would love to see it styled.",
];

type Shipment = { entry: RosterEntry; state: "received" | "processing" | "needs_checking" };

function findShipment(detail: Detail, order: string, affiliateId: number): Shipment | null {
  for (const state of ["received", "processing", "needs_checking"] as const) {
    const entry = detail.roster[state].find((row) => row.shopify_order_id === order && row.affiliate_id === affiliateId);
    if (entry) return { entry, state };
  }
  return null;
}

const SHIPMENT_STATE = {
  received: { label: "Received", tone: "approved", note: "Delivered and part of the wardrobe." },
  processing: { label: "Processing", tone: "owed", note: "In transit according to Shopify. It becomes part of the wardrobe once it arrives." },
  needs_checking: { label: "Needs checking", tone: "refused", note: "Shopify reports a delivery problem on this shipment. A replacement updates this shipment state." },
} as const;

/**
 * *Shipment record* - the export's `vShipment` (Admin lines 1135-1155): the
 * product, the state, the model, the size and the Shopify order, with what
 * the state means. Read from the product's own roster, so a reload lands on
 * the same record.
 */
function ShipmentRecord({ productId, title, shipment }: { productId: string; title: string; shipment: Shipment }) {
  const state = SHIPMENT_STATE[shipment.state];
  return <section className="pay-detail__card shipment">
    <div className="shipment__head">
      <Link className="shipment__product control-font" to={`/products/${productId}`}>{title}</Link>
      <span className={`shipment__state shipment__state--${state.tone}`}>{state.label}</span>
    </div>
    <div className="shipment__row"><span>Model</span>
      <Link className="control-font" to={`/affiliates/${shipment.entry.affiliate_id}?section=wardrobe`}>{shipment.entry.name}</Link></div>
    <div className="shipment__row"><span>Size</span><span>{shipment.entry.size || "not recorded"}</span></div>
    <div className="shipment__row"><span>Shopify order</span><span>{shipment.entry.order_number}</span></div>
    <p className="shipment__note">{state.note}</p>
  </section>;
}

/**
 * *Feature request* — `vPromo` in the approved export.
 *
 * Left: whether models see it, who would, and the short message; Save,
 * Cancel and Remove under them. Right: the model's Wardrobe as it will look,
 * drawn in the portal's own dark theme, with the two states a model can be
 * in - received, or on the way.
 *
 * **The message is optional (D12).** Save used to stay disabled until one was
 * typed, which quietly overruled the owner's decision that a featured product
 * needs no words.
 */
function PromotionEditor({ detail, audience, saving, mayEdit, onSave, onRemove, onCancel }: {
  detail: Detail; audience: number; saving: boolean; mayEdit: boolean;
  onSave: (visible: boolean, message: string) => Promise<void>;
  onRemove: () => Promise<void>; onCancel: () => void;
}) {
  const [message, setMessage] = useState(detail.feature_request?.message ?? "");
  const [visible, setVisible] = useState(detail.feature_request?.visible ?? true);
  const [preview, setPreview] = useState<"received" | "processing">("received");
  const [saved, setSaved] = useState(false);
  async function save() {
    setSaved(false);
    try { await onSave(visible, message); setSaved(true); } catch { /* Parent displays API error; retain the draft. */ }
  }
  return <div className="promo">
    <div className="promo__edit">
      {saved && <p className="promo__saved" role="status">Feature request saved.</p>}
      <section className="pay-detail__card">
        <div className="promo__switch-row">
          <span>
            <span className="promo__label">Show to models</span>
            <span className="promo__hint">{visible ? "Models who have this product see it in their Wardrobe." : "Kept, and hidden from every model."}</span>
          </span>
          <button type="button" role="switch" aria-label="Show to models" aria-checked={visible}
            className={visible ? "promo__switch promo__switch--on" : "promo__switch"}
            disabled={saving || !mayEdit} onClick={() => { setVisible(!visible); setSaved(false); }}>
            <span className="promo__knob" />
          </button>
        </div>
        <p className="promo__audience">Seen by models who have this product: {audience}</p>
        {audience === 0 && <p className="promo__nobody">Nobody will see this until one of them has it, received or on the way.</p>}
      </section>
      <section className="pay-detail__card">
        <label htmlFor="promotion-message" className="promo__label">Short message <span className="promo__optional">optional</span></label>
        <textarea id="promotion-message" className="input promo__textarea" value={message} rows={3} maxLength={2000} disabled={saving || !mayEdit}
          onChange={(event) => { setMessage(event.target.value); setSaved(false); }} placeholder="Back in stock — please feature this in your upcoming content." />
        <div className="promo__under">
          <span className="promo__count">{message.length} characters</span>
          {/* The export's three presets (`prPresets`): each fills the message
           *  with its sentence, which can then be edited. */}
          {mayEdit && <span className="promo__presets">
            {PRESETS.map((preset) => <button key={preset} type="button" className="promo__preset" disabled={saving}
              onClick={() => { setMessage(preset); setSaved(false); }}>{preset.split(" —")[0]}</button>)}
          </span>}
        </div>
      </section>
      <div className="promo__acts">
        {mayEdit && <button type="button" className="button button--primary promo__big" disabled={saving} onClick={save}>{saving ? "Saving…" : "Save"}</button>}
        <button type="button" className="button promo__big" disabled={saving} onClick={onCancel}>Cancel</button>
        {mayEdit && detail.feature_request && <button type="button" className="button button--danger promo__big" disabled={saving} onClick={onRemove}>Remove</button>}
      </div>
    </div>
    <aside className="promo__preview">
      <div className="promo__preview-label">Preview · model Wardrobe</div>
      {/* The portal is dark by default, so the preview is drawn in the dark
       *  theme whatever this screen is in - it is what a model will see. */}
      <div className="promo__phone" data-theme="dark">
        {visible ? <>
          <div className="promo__phone-title">HBA would like you to feature</div>
          <div className="promo__phone-sub">Chosen by the HBA team. These are requests, not targets.</div>
          <div className="promo__phone-card">
            <ProductImage source={detail.image_url} />
            <span className="promo__phone-text">
              <span className="promo__phone-name">{detail.title}</span>
              <span className={preview === "received" ? "promo__phone-own promo__phone-own--yes" : "promo__phone-own"}>
                {preview === "received" ? "In your wardrobe" : "On its way to you"}
              </span>
              {message.trim() && <span className="promo__phone-message">{message}</span>}
            </span>
          </div>
        </> : <p className="promo__phone-hidden">Nothing appears on model dashboards while this is hidden.</p>}
      </div>
      <div className="promo__preview-acts" aria-label="Preview shipment state">
        <button type="button" className={preview === "received" ? "button promo__toggle promo__toggle--on" : "button promo__toggle"} aria-pressed={preview === "received"} onClick={() => setPreview("received")}>Received</button>
        <button type="button" className={preview === "processing" ? "button promo__toggle promo__toggle--on" : "button promo__toggle"} aria-pressed={preview === "processing"} onClick={() => setPreview("processing")}>On the way</button>
      </div>
      <p className="promo__audience">Audience: {audience}</p>
    </aside>
  </div>;
}

function ProductImage({ source }: { source: string | null }) {
  const [failedSource, setFailedSource] = useState<string | null>(null);
  return source && source !== failedSource
    ? <img className="products__detail-image" src={source} alt="" onError={() => setFailedSource(source)} />
    : <span className="products__detail-image products__detail-image--empty">No image</span>;
}
