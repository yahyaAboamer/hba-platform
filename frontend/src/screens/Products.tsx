import { useCallback, useEffect, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";

import { Money } from "../components/Money";
import { api, can } from "../lib/api";
import { currentMonth, formatMonth } from "../lib/money";
import type { Session } from "../lib/api";
import "./Products.css";

type Row = {
  shopify_product_id: string;
  title: string;
  status: string;
  image_url: string | null;
  sizes: number;
};

type RosterEntry = { affiliate_id: number; name: string; status: string };

/**
 * What HBA has asked the models to post about this product (W09).
 *
 * Named rather than written inline at the call site: `test_reachability`
 * finds a route by scanning for `api.put<...>("/path")`, and a **nested**
 * generic — `NonNullable<Detail["feature_request"]>` — stops it matching, so
 * the route reads as one with no way in from the interface. The message is
 * optional (D12): a product can be featured on its picture alone.
 */
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
const PAGE = 60;

type TopSeller = {
  shopify_product_id: string | null;
  title: string;
  quantity: number;
  sales_piastres: number;
};

/**
 * What sold through the models' codes this month. W11.
 *
 * **Three different questions, and this answers one.** Selling through a code,
 * owning something from the wardrobe, and being asked to feature it look alike
 * and are not — *a model can sell products she never received*. This counts
 * what was bought.
 *
 * The figures are what customers actually paid after each model's discount,
 * not list prices. On a ten per cent code, list prices would be a ten per cent
 * overstatement on every row.
 */
function TopSellers({ month }: { month: string }) {
  const [body, setBody] = useState<{
    products: TopSeller[];
    no_longer_in_shopify_piastres: number;
  } | null>(null);

  useEffect(() => {
    let live = true;
    api
      .get<{ products: TopSeller[]; no_longer_in_shopify_piastres: number }>(
        `/api/products/top-sellers/${month}`,
      )
      .then((found) => {
        if (live) setBody(found);
      })
      // Silent on failure, deliberately: this is context beside the
      // catalogue, and a red banner over the whole screen because a side
      // panel could not load would be out of proportion to what was lost.
      .catch(() => undefined);
    return () => {
      live = false;
    };
  }, [month]);

  if (!body || body.products.length === 0) return null;

  return (
    <section className="panel products__panel">
      <div className="panel__head">
        <h2 className="panel__title">Selling best through codes</h2>
        <span className="page__subtitle">{formatMonth(month)}</span>
      </div>
      <ol className="products__top">
        {body.products.slice(0, 5).map((row) => (
          <li key={row.shopify_product_id ?? row.title}>
            {row.shopify_product_id ? (
              <Link to={`/products/${row.shopify_product_id}`}>{row.title}</Link>
            ) : (
              <span>{row.title}</span>
            )}
            <span className="products__sold">
              {row.quantity} sold · <Money piastres={row.sales_piastres} />
            </span>
          </li>
        ))}
      </ol>
      {body.no_longer_in_shopify_piastres > 0 && (
        <p className="detail__note products__gone">
          A further <Money piastres={body.no_longer_in_shopify_piastres} /> sold
          products that have since been deleted from Shopify, so they cannot be
          listed by name.
        </p>
      )}
    </section>
  );
}

export function Products({ session }: { session: Session }) {
  const [rows, setRows] = useState<Row[] | null>(null);
  const [total, setTotal] = useState(0);
  const [all, setAll] = useState(false);
  const [search, setSearch] = useState("");
  /**
   * What was actually asked for, as opposed to what is being typed.
   *
   * The first version fetched on every keystroke: typing "dress" was five
   * requests, four of them already stale before they returned, and on a real
   * catalogue each one is a query and a page of images. A third of a second is
   * long enough to finish a word and short enough not to feel laggy.
   */
  const [asked, setAsked] = useState("");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const timer = setTimeout(() => setAsked(search), 300);
    return () => clearTimeout(timer);
  }, [search]);

  const load = useCallback(
    (offset = 0) => {
      const query = new URLSearchParams();
      if (all) query.set("all_products", "true");
      if (asked.trim()) query.set("search", asked.trim());
      query.set("limit", String(PAGE));
      query.set("offset", String(offset));
      api
        .get<{ products: Row[]; total: number }>(`/api/products?${query}`)
        .then((body) => {
          // Appended when paging, replaced when the filter changed. Replacing
          // on a "show more" would scroll somebody back to the top of a list
          // they were reading.
          setRows((was) =>
            offset === 0 ? body.products : [...(was ?? []), ...body.products],
          );
          setTotal(body.total);
        })
        .catch((caught) => setError(caught.message));
    },
    [all, asked],
  );

  useEffect(() => load(0), [load]);

  return (
    <>
      <div className="page__head">
        <div className="page__title">
          <h1>Products</h1>
          <span className="page__subtitle">
            {rows === null
              ? "…"
              : rows.length < total
                ? `${rows.length} of ${total}`
                : `${total} ${all ? "in the catalogue" : "active"}`}
          </span>
        </div>
        <div className="products__controls">
          <input
            className="input products__search"
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            placeholder="Search by name"
            aria-label="Search products by name"
          />
          <label className="products__toggle">
            <input
              type="checkbox"
              checked={all}
              onChange={(event) => setAll(event.target.checked)}
            />
            All products
          </label>
        </div>
      </div>

      {error && (
        <p className="notice notice--refused" role="alert">
          {error}
        </p>
      )}

      {/*
       * **Three different facts, three different messages** (§S06). Loading is
       * not empty; a search with no hits is not an empty catalogue; and an
       * empty catalogue is a thing to fix in Settings rather than a shrug.
       */}
      {rows === null && !error && <p className="empty">Loading…</p>}
      {rows !== null && rows.length === 0 && search.trim() && (
        <p className="empty">Nothing matches “{search.trim()}”.</p>
      )}
      {rows !== null && rows.length === 0 && !search.trim() && (
        <p className="empty">
          The catalogue has not been read yet. Settings → Shopify &amp; data →
          Read the catalogue.
        </p>
      )}

      <TopSellers month={currentMonth()} />

      {rows !== null && rows.length > 0 && (
        <ul className="products__grid">
          {rows.map((row) => (
            <li key={row.shopify_product_id}>
              <Link
                className="products__card"
                to={`/products/${row.shopify_product_id}`}
              >
                {row.image_url ? (
                  <img
                    className="products__pic"
                    src={row.image_url}
                    alt=""
                    loading="lazy"
                  />
                ) : (
                  <span className="products__nopic" aria-hidden="true" />
                )}
                <span className="products__name">{row.title}</span>
                <span className="products__meta">
                  {row.sizes} size{row.sizes === 1 ? "" : "s"}
                  {row.status !== "active" && ` · ${row.status}`}
                </span>
              </Link>
            </li>
          ))}
        </ul>
      )}

      {/*
       * **More, rather than every page as a number.** Nobody navigating a
       * catalogue knows which page a garment is on, and a page count invites
       * clicking through six of them to find out.
       */}
      {rows !== null && rows.length < total && (
        <button
          type="button"
          className="button products__more"
          onClick={() => load(rows.length)}
        >
          Show {Math.min(PAGE, total - rows.length)} more
        </button>
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

  const groups: [string, RosterEntry[]][] = [
    ["Received", detail.roster.received], ["Processing", detail.roster.processing],
    ["Needs checking", detail.roster.needs_checking], ["Not sent", detail.roster.not_sent],
  ];
  const audience = detail.roster.received.length + detail.roster.processing.length;

  return <>
    <div className="page__head"><div className="page__title">
      <p className="crumb">{promotion ? <button className="button" onClick={() => setView(false)} disabled={saving}>← {detail.title}</button> : <Link to="/products">Products</Link>}</p>
      <h1>{promotion ? "Feature request" : detail.title}</h1>
    </div></div>
    {error && <p className="notice notice--refused" role="alert">{error}</p>}
    {promotion ? (
      <PromotionEditor detail={detail} audience={audience} saving={saving} mayEdit={mayEdit}
        onSave={saveRequest} onRemove={removeRequest} onCancel={() => setView(false)} />
    ) : <>
      <div className="products__hero">
        <ProductImage source={detail.image_url} />
        <div><span className="products__badge">{detail.status}</span>
          <p className="detail__note">{detail.sizes.map((size) => size.title).join(" · ")}</p>
          <div className="products__coverage-counts">{groups.map(([label, entries]) => <span className="products__badge" key={label}>{label} · {entries.length}</span>)}</div>
        </div>
      </div>
      <section className="panel products__feature-summary">
        <div className="products__summary-head">
          <h2 className="panel__title">Feature request</h2>
          <span className="products__badge">{detail.feature_request ? detail.feature_request.visible ? "Visible to models" : "Hidden" : "None"}</span>
          {mayEdit && <div className="products__actions">
            <button className="button" onClick={() => setView(true)} disabled={saving}>{detail.feature_request ? "Edit" : "Ask models to feature this"}</button>
            {detail.feature_request && <>
              <button className="button" disabled={saving} onClick={() => { void saveRequest(!detail.feature_request?.visible).catch(() => {}); }}>{detail.feature_request.visible ? "Hide" : "Show"}</button>
              <button className="button button--danger" disabled={saving} onClick={removeRequest}>Remove</button>
            </>}
          </div>}
        </div>
        {detail.feature_request && <p className="products__ask">{detail.feature_request.message}</p>}
      </section>
      <div className="products__coverage-head"><h2 className="panel__title">Model coverage</h2>
        <input className="input products__search" aria-label="Search model names" placeholder="Search model names" value={search}
          onChange={(event) => setQuery((previous) => { const next = new URLSearchParams(previous); if (event.target.value) next.set("q", event.target.value); else next.delete("q"); return next; }, { replace: true })} />
      </div>
      {groups.map(([label, entries]) => {
        const shown = entries.filter((entry) => entry.name.toLocaleLowerCase().includes(search.toLocaleLowerCase())).sort((a, b) => a.name.localeCompare(b.name));
        return <details className="panel products__coverage-group" key={label} open>
          <summary>{label}<span className="products__count">{search ? `${shown.length} of ` : ""}{entries.length}</span></summary>
          {shown.length === 0 ? <p className="detail__note">{search ? "No matching models." : "None."}</p> : <ul className="products__roster">
            {shown.map((entry) => <li key={entry.affiliate_id}><Link to={`/affiliates/${entry.affiliate_id}`}>{entry.name}</Link></li>)}
          </ul>}
        </details>;
      })}
    </>}
  </>;
}

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
  return <div className="products__promotion">
    <div className="products__promotion-edit">
      {saved && <p className="notice" role="status">Feature request saved.</p>}
      <section className="panel products__promotion-panel">
        <div className="products__summary-head"><h2 className="panel__title">Show to models</h2>
          <button className="button" role="switch" aria-label="Show to models" aria-checked={visible} disabled={saving || !mayEdit} onClick={() => { setVisible(!visible); setSaved(false); }}>{visible ? "On" : "Off"}</button>
        </div>
        <p className="detail__note">{audience} eligible {audience === 1 ? "model" : "models"} · Received or Processing</p>
        {audience === 0 && <p className="detail__note">Nobody will see this until an eligible shipment is recorded.</p>}
      </section>
      <section className="panel products__promotion-panel">
        <label htmlFor="promotion-message">Short message</label>
        <textarea id="promotion-message" className="input products__textarea" value={message} rows={3} maxLength={2000} disabled={saving || !mayEdit}
          onChange={(event) => { setMessage(event.target.value); setSaved(false); }} placeholder="Back in stock — please feature this in your upcoming content." />
        <span className="detail__note">{message.length}/2000</span>
      </section>
      <div className="products__actions">
        {mayEdit && <button className="button button--primary" disabled={saving || !message.trim()} onClick={save}>{saving ? "Saving…" : "Save"}</button>}
        <button className="button" disabled={saving} onClick={onCancel}>Cancel</button>
        {mayEdit && detail.feature_request && <button className="button button--danger" disabled={saving} onClick={onRemove}>Remove</button>}
      </div>
    </div>
    <aside className="products__promotion-preview">
      <p className="detail__note">Preview · model Wardrobe</p>
      <div className="panel products__promotion-panel">
        {visible ? <><h2 className="panel__title">HBA would like you to feature</h2><p className="detail__note">Chosen by the HBA team</p>
          <div className="products__preview-card"><ProductImage source={detail.image_url} /><div>
            <span>{detail.title}</span><p className="detail__note">{preview === "received" ? "In your wardrobe" : "On its way"}</p><p className="products__ask">{message}</p>
          </div></div>
        </> : <p className="detail__note">Nothing appears on model dashboards while this is hidden.</p>}
      </div>
      <div className="products__actions" aria-label="Preview shipment state">
        <button className="button" aria-pressed={preview === "received"} onClick={() => setPreview("received")}>Received</button>
        <button className="button" aria-pressed={preview === "processing"} onClick={() => setPreview("processing")}>On the way</button>
      </div>
    </aside>
  </div>;
}

function ProductImage({ source }: { source: string | null }) {
  const [failedSource, setFailedSource] = useState<string | null>(null);
  return source && source !== failedSource
    ? <img className="products__detail-image" src={source} alt="" onError={() => setFailedSource(source)} />
    : <span className="products__detail-image products__detail-image--empty">No image</span>;
}
