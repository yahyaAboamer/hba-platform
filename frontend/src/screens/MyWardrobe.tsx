import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { api } from "../lib/api";
import "./MyWardrobe.css";

type Item = {
  shopify_product_id: string | null;
  title: string;
  size: string | null;
  state: string;
  image_url: string | null;
  image_thumb_url: string | null;
  shopify_order_id: string;
  placed_at?: string | null;
};

type Request = {
  shopify_product_id: string;
  message: string;
  title: string | null;
  image_url: string | null;
};

/** One product she sold through her own code - never the programme's list. */
export type BestSeller = {
  shopify_product_id: string;
  title: string;
  quantity: number;
  sales_piastres: number;
  sales: string;
  image_url: string | null;
};

type BestSellers = { products: BestSeller[]; codes: string[] };

/**
 * *Sales through HBA15* - the export names her code where it could have said
 * "your code". Every code she has held, because the list is all time; "your
 * code" only for a model the server has no code on record for.
 */
export function throughCodes(codes: string[] | undefined): string {
  return codes && codes.length ? codes.join(", ") : "your code";
}

type Wardrobe = {
  received: Item[];
  processing: Item[];
  failed: Item[];
  feature_requests: Request[];
};

/** Server-selected gift products and passive, Received/Processing-only requests. */
export function MyWardrobe() {
  const [body, setBody] = useState<Wardrobe | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);
  const [best, setBest] = useState<BestSeller[] | null>(null);
  const [bestError, setBestError] = useState<string | null>(null);
  const [codes, setCodes] = useState<string[]>([]);

  useEffect(() => {
    let live = true;
    setError(null);
    setBody(null);
    api.get<Wardrobe>("/api/me/wardrobe")
      .then((found) => { if (live) setBody(found); })
      .catch((caught) => { if (live) setError(caught.message); });
    // Her own best sellers. A failure here costs the section rather than the
    // wardrobe: it is a second question on the same screen.
    //
    // **It no longer costs it silently** (A12). `setBest([])` turned a failed
    // request into "she has sold nothing", and the section then vanished
    // exactly as it does for a model who genuinely has no sales - so a broken
    // read was indistinguishable from an empty one, on the screen least able
    // to tell the difference.
    setBestError(null);
    api.get<BestSellers>("/api/me/best-sellers")
      .then((found) => {
        if (live) { setBest(found.products); setCodes(found.codes ?? []); setBestError(null); }
      })
      .catch((caught) => { if (live) { setBest(null); setBestError(caught.message); } });
    return () => { live = false; };
  }, [attempt]);

  if (error) return (
    <div className="notice notice--refused" role="alert">
      <p>Could not load your wardrobe.</p>
      <button type="button" className="button" onClick={() => setAttempt((n) => n + 1)}>Try again</button>
    </div>
  );
  if (body === null) return <p className="empty" role="status">Loading wardrobe…</p>;
  return (
    <WardrobeContents
      body={body}
      best={best}
      codes={codes}
      bestError={bestError}
      onRetryBest={() => setAttempt((n) => n + 1)}
    />
  );
}

export function WardrobeContents({
  body,
  best = null,
  codes = [],
  bestError = null,
  onRetryBest,
}: {
  body: Wardrobe;
  best?: BestSeller[] | null;
  /** Her codes, for *Sales through HBA15*. */
  codes?: string[];
  /** A12. Set when the best-sellers read failed, which is not "no sales". */
  bestError?: string | null;
  onRetryBest?: () => void;
}) {
  const waiting = [...body.processing, ...body.failed];
  const hasBest = Boolean(best && best.length > 0);
  return (
    <div className="wardrobe">
      <h1 className="wardrobe__page-title">Wardrobe</h1>
      <p className="wardrobe__intro">Your pieces, feature requests and sales</p>
      <nav className="wardrobe__jumps" aria-label="Wardrobe sections">
        <button type="button" onClick={() => jumpTo("wardrobe-owned")}>{body.received.length} received</button>
        {body.feature_requests.length > 0 && <button type="button" onClick={() => jumpTo("wardrobe-feature")}>To feature</button>}
        {(hasBest || bestError) && <button type="button" onClick={() => jumpTo("wardrobe-best")}>Best sellers</button>}
      </nav>

      <section className="wardrobe__block" id="wardrobe-owned">
        <div className="wardrobe__heading">
          <h2 className="wardrobe__title">In your wardrobe</h2>
          <span className="wardrobe__count">{body.received.length} {body.received.length === 1 ? "piece" : "pieces"} received</span>
        </div>
        {body.received.length === 0 ? (
          <p className="empty">{waiting.length ? "Your received products will appear here." : "No products yet."}</p>
        ) : (
          <ul className="wardrobe__received">
            {body.received.map((item) => (
              <li key={item.shopify_product_id ?? `${item.shopify_order_id}:${item.title}`}>
                <Picture source={item.image_thumb_url ?? item.image_url} />
                <div className="wardrobe__product-copy">
                  <span className="wardrobe__name">{item.title}</span>
                  <span className="wardrobe__size">{item.size ? `Size ${item.size} · ` : ""}Received</span>
                  <OrderDate value={item.placed_at} />
                </div>
              </li>
            ))}
          </ul>
        )}
        {waiting.length > 0 && (
          <div className="wardrobe__incoming">
            <h3>Not received yet</h3>
            <ul className="wardrobe__waiting">
              {waiting.map((item) => (
                <li key={item.shopify_product_id ?? `${item.shopify_order_id}:${item.title}`}>
                  <Picture source={item.image_thumb_url ?? item.image_url} />
                  <div className="wardrobe__copy">
                    <span className="wardrobe__name">{item.title}</span>
                    {item.size && <span className="wardrobe__size">Size {item.size}</span>}
                    <span className={`wardrobe__state ${item.state === "failed" ? "wardrobe__state--failed" : "wardrobe__state--coming"}`}>
                      {item.state === "failed" ? "Failed delivery" : "On the way"}
                    </span>
                  </div>
                </li>
              ))}
            </ul>
          </div>
        )}
      </section>

      {body.feature_requests.length > 0 && (
        <section className="wardrobe__block" id="wardrobe-feature">
          <h2 className="wardrobe__title">HBA would like you to feature</h2>
          <ul className="wardrobe__requests">
            {body.feature_requests.map((request) => {
              const received = body.received.find((item) => item.shopify_product_id === request.shopify_product_id);
              const incoming = body.processing.find((item) => item.shopify_product_id === request.shopify_product_id);
              return (
                <li key={request.shopify_product_id}>
                  <Picture source={request.image_url} />
                  <div className="wardrobe__copy">
                    <span className="wardrobe__name">{request.title ?? received?.title ?? incoming?.title ?? "Product"}</span>
                    {received && <span className="wardrobe__state wardrobe__state--have">Ready to feature · in your wardrobe{received.size ? ` · size ${received.size}` : ""}</span>}
                    {!received && incoming && <span className="wardrobe__state wardrobe__state--coming">On the way{incoming.size ? ` · size ${incoming.size}` : ""}</span>}
                    <p className="wardrobe__ask">{request.message}</p>
                  </div>
                </li>
              );
            })}
          </ul>
        </section>
      )}

      {(hasBest || bestError) && (
        <section className="wardrobe__block" id="wardrobe-best">
          <div className="wardrobe__heading">
            <h2 className="wardrobe__title">Your best sellers</h2>
            {hasBest && <span className="wardrobe__count">Through {throughCodes(codes)}</span>}
          </div>
          {bestError ? (
            <p className="wardrobe__subtitle" role="status">
              Could not load your best sellers.{" "}
              {onRetryBest && <button type="button" className="button" onClick={onRetryBest}>Try again</button>}
            </p>
          ) : (
            <>
              <p className="wardrobe__subtitle">Sales through {throughCodes(codes)} · all time · delivered and pending</p>
              <BestSellerList rows={best!.slice(0, 3)} />
              <p className="wardrobe__sales-note">Product sales, not your payout.</p>
              {best!.length > 3 && <Link className="wardrobe__all" to="/best">Show all {best!.length} products</Link>}
            </>
          )}
        </section>
      )}
    </div>
  );
}

function jumpTo(id: string) {
  const reducedMotion = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
  document.getElementById(id)?.scrollIntoView({ behavior: reducedMotion ? "auto" : "smooth", block: "start" });
}

function BestSellerList({ rows, offset = 0 }: { rows: BestSeller[]; offset?: number }) {
  return (
    <ol className="wardrobe__best">
      {rows.map((row, index) => (
        <li key={row.shopify_product_id}>
          <span className={index + offset === 0 ? "wardrobe__rank wardrobe__rank--first" : "wardrobe__rank"}>
            {index + offset + 1}
          </span>
          <Picture source={row.image_url} />
          <span className="wardrobe__copy">
            <span className="wardrobe__name">{row.title}</span>
            <span className="wardrobe__units">
              {row.quantity} {row.quantity === 1 ? "unit sold" : "units sold"}
            </span>
          </span>
          <span className="wardrobe__sales">{row.sales}</span>
        </li>
      ))}
    </ol>
  );
}

/**
 * *All products sold* - `vBest` in the approved portal.
 *
 * Every product sold through her code, all time, best first. Delivered and
 * pending orders, failed deliveries excluded - the export's line, and the rule
 * she is paid on since ADR 0040.
 */
export function MyBestSellers() {
  const [rows, setRows] = useState<BestSeller[] | null>(null);
  const [codes, setCodes] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let live = true;
    setError(null);
    api.get<BestSellers>("/api/me/best-sellers")
      .then((found) => { if (live) { setRows(found.products); setCodes(found.codes ?? []); } })
      .catch((caught) => { if (live) setError(caught.message); });
    return () => { live = false; };
  }, [attempt]);

  if (error) return (
    <div className="notice notice--refused" role="alert">
      <p>Could not load what you sold.</p>
      <button type="button" className="button" onClick={() => setAttempt((n) => n + 1)}>Try again</button>
    </div>
  );
  if (rows === null) return <p className="empty" role="status">Loading…</p>;

  return (
    <div className="wardrobe">
      <p className="wardrobe__lead">
        Every product sold through {throughCodes(codes)}, all time. Delivered and
        pending orders; failed deliveries excluded.
      </p>
      {rows.length === 0
        ? <p className="empty">Nothing has sold through your code yet.</p>
        : <BestSellerList rows={rows} />}
    </div>
  );
}

function OrderDate({ value }: { value?: string | null }) {
  if (!value) return null;
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return null;
  // Shopify supplies the order date, not proof of when delivery happened.
  return <span className="wardrobe__date">Ordered {date.toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" })}</span>;
}

function Picture({ source }: { source: string | null }) {
  const [failedSource, setFailedSource] = useState<string | null>(null);
  if (!source || source === failedSource) {
    return <span className="wardrobe__nopic" aria-label="Product image unavailable">No image</span>;
  }
  return <img className="wardrobe__pic" src={source} alt="" loading="lazy" onError={() => setFailedSource(source)} />;
}
