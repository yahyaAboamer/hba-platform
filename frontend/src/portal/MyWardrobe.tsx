import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";

import { usePortal } from "./AffiliateLayout";
import { PortalSkeleton } from "./PortalSkeleton";
import { api } from "../lib/api";
import { formatMonth } from "../lib/money";
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
 * "your code". The server lists every code she has held, including when the
 * product list is narrowed to a month. "your code" is the fallback only when
 * no code is on record.
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
  const { month, months } = usePortal();
  const [body, setBody] = useState<Wardrobe | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);
  const [sellerPeriod, setSellerPeriod] = useState<"all" | "month">("all");
  const [sellerMonth, setSellerMonth] = useState(month);
  const [best, setBest] = useState<BestSeller[] | null>(null);
  const [bestError, setBestError] = useState<string | null>(null);
  const [allTimeHadBest, setAllTimeHadBest] = useState(false);
  const [codes, setCodes] = useState<string[]>([]);

  useEffect(() => {
    let live = true;
    setError(null);
    setBody(null);
    api.get<Wardrobe>("/api/me/wardrobe")
      .then((found) => { if (live) setBody(found); })
      .catch((caught) => { if (live) setError(caught.message); });
    return () => { live = false; };
  }, [attempt]);

  useEffect(() => {
    let live = true;
    // Her own best sellers. A failure here costs the section rather than the
    // wardrobe: it is a second question on the same screen.
    //
    // **It no longer costs it silently** (A12). `setBest([])` turned a failed
    // request into "she has sold nothing", and the section then vanished
    // exactly as it does for a model who genuinely has no sales - so a broken
    // read was indistinguishable from an empty one, on the screen least able
    // to tell the difference.
    setBestError(null);
    setBest(null);
    // Each branch calls with its own literal path: the reachability guard
    // (tests/test_reachability.py) reads paths written into the call, and a
    // path held in a variable read as a route nothing reached.
    (sellerPeriod === "month"
      ? api.get<BestSellers>(`/api/me/best-sellers?month=${encodeURIComponent(sellerMonth)}`)
      : api.get<BestSellers>("/api/me/best-sellers"))
      .then((found) => {
        if (live) {
          setBest(found.products);
          setCodes(found.codes ?? []);
          if (sellerPeriod === "all") setAllTimeHadBest(found.products.length > 0);
          setBestError(null);
        }
      })
      .catch((caught) => { if (live) { setBest(null); setBestError(caught.message); } });
    return () => { live = false; };
  }, [attempt, sellerPeriod, sellerMonth]);

  if (error) return (
    <div className="notice notice--refused" role="alert">
      <p>Could not load your wardrobe.</p>
      <button type="button" className="button" onClick={() => setAttempt((n) => n + 1)}>Try again</button>
    </div>
  );
  if (body === null) return <PortalSkeleton screen="wardrobe" />;
  return (
    <WardrobeContents
      body={body}
      best={best}
      codes={codes}
      bestError={bestError}
      bestLoading={best === null && !bestError}
      allTimeHadBest={allTimeHadBest}
      sellerPeriod={sellerPeriod}
      sellerMonth={sellerMonth}
      sellerMonths={months}
      onSellerPeriod={setSellerPeriod}
      onSellerMonth={setSellerMonth}
      onRetryBest={() => setAttempt((n) => n + 1)}
    />
  );
}

export function WardrobeContents({
  body,
  best = null,
  codes = [],
  bestError = null,
  bestLoading = false,
  allTimeHadBest = false,
  sellerPeriod = "all",
  sellerMonth = "",
  sellerMonths = [],
  onSellerPeriod,
  onSellerMonth,
  onRetryBest,
}: {
  body: Wardrobe;
  best?: BestSeller[] | null;
  /** Her codes, for *Sales through HBA15*. */
  codes?: string[];
  /** A12. Set when the best-sellers read failed, which is not "no sales". */
  bestError?: string | null;
  bestLoading?: boolean;
  allTimeHadBest?: boolean;
  sellerPeriod?: "all" | "month";
  sellerMonth?: string;
  sellerMonths?: string[];
  onSellerPeriod?: (period: "all" | "month") => void;
  onSellerMonth?: (month: string) => void;
  onRetryBest?: () => void;
}) {
  const waiting = [...body.processing, ...body.failed];
  const hasBest = Boolean(best && best.length > 0);
  const showBest = hasBest || Boolean(bestError) || allTimeHadBest || sellerPeriod === "month";
  return (
    <div className="wardrobe">
      <h1 className="wardrobe__page-title">Wardrobe</h1>
      <p className="wardrobe__intro">Your pieces, feature requests and sales</p>
      <nav className="wardrobe__jumps" aria-label="Wardrobe sections">
        <button type="button" onClick={() => jumpTo("wardrobe-owned")}>{body.received.length} received</button>
        {body.feature_requests.length > 0 && <button type="button" onClick={() => jumpTo("wardrobe-feature")}>To feature</button>}
        {showBest && <button type="button" onClick={() => jumpTo("wardrobe-best")}>Best sellers</button>}
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

      {showBest && (
        <section className="wardrobe__block" id="wardrobe-best">
          <div className="wardrobe__heading">
            <h2 className="wardrobe__title">Your best sellers</h2>
            {hasBest && <span className="wardrobe__count">Through {throughCodes(codes)}</span>}
          </div>
          <SellerControls period={sellerPeriod} month={sellerMonth} months={sellerMonths} onPeriod={onSellerPeriod} onMonth={onSellerMonth} />
          {bestError ? (
            <p className="wardrobe__subtitle" role="status">
              Could not load your best sellers.{" "}
              {onRetryBest && <button type="button" className="button" onClick={onRetryBest}>Try again</button>}
            </p>
          ) : bestLoading ? (
            <div className="wardrobe__seller-loading" role="status" aria-label="Loading best sellers">
              <span className="portal-skeleton__bar" aria-hidden="true" />
              <span className="portal-skeleton__bar" aria-hidden="true" />
            </div>
          ) : (
            <>
              <p className="wardrobe__subtitle">Sales through {throughCodes(codes)} · {sellerPeriod === "all" ? "all time" : formatMonth(sellerMonth)} · delivered and pending</p>
              {hasBest ? <BestSellerList rows={best!.slice(0, 3)} /> : <p className="empty">{sellerPeriod === "month" ? `No products sold through your code in ${formatMonth(sellerMonth)}.` : "Nothing has sold through your code yet."}</p>}
              {hasBest && <p className="wardrobe__sales-note">Product sales, not your payout.</p>}
              {best && best.length > 3 && <Link className="wardrobe__all" to={sellerPeriod === "month" ? `/best?month=${encodeURIComponent(sellerMonth)}` : "/best"}>Show all {best.length} products</Link>}
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
 * Every product sold through her code in the chosen period, best first.
 * Delivered and pending orders count; failed deliveries do not (ADR 0040).
 */
export function MyBestSellers() {
  const { month: currentMonth, months } = usePortal();
  const [query, setQuery] = useSearchParams();
  const selected = query.get("month");
  const sellerMonth = selected && months.includes(selected) ? selected : currentMonth;
  const sellerPeriod = selected && months.includes(selected) ? "month" : "all";
  const [rows, setRows] = useState<BestSeller[] | null>(null);
  const [codes, setCodes] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let live = true;
    setError(null);
    setRows(null);
    (sellerPeriod === "month"
      ? api.get<BestSellers>(`/api/me/best-sellers?month=${encodeURIComponent(sellerMonth)}`)
      : api.get<BestSellers>("/api/me/best-sellers"))
      .then((found) => { if (live) { setRows(found.products); setCodes(found.codes ?? []); } })
      .catch((caught) => { if (live) setError(caught.message); });
    return () => { live = false; };
  }, [attempt, sellerPeriod, sellerMonth]);

  if (error) return (
    <div className="notice notice--refused" role="alert">
      <p>Could not load what you sold.</p>
      <button type="button" className="button" onClick={() => setAttempt((n) => n + 1)}>Try again</button>
    </div>
  );
  if (rows === null) return <PortalSkeleton screen="wardrobe" />;

  return (
    <div className="wardrobe">
      <h1 className="wardrobe__page-title">Your best sellers</h1>
      <SellerControls
        period={sellerPeriod} month={sellerMonth} months={months}
        onPeriod={(period) => setQuery(period === "all" ? {} : { month: sellerMonth })}
        onMonth={(month) => setQuery({ month })}
      />
      <p className="wardrobe__lead">
        Every product sold through {throughCodes(codes)}, {sellerPeriod === "all" ? "all time" : formatMonth(sellerMonth)}. Delivered and
        pending orders; failed deliveries excluded.
      </p>
      {rows.length === 0
        ? <p className="empty">{sellerPeriod === "month" ? `No products sold through your code in ${formatMonth(sellerMonth)}.` : "Nothing has sold through your code yet."}</p>
        : <BestSellerList rows={rows} />}
    </div>
  );
}

function SellerControls({ period, month, months, onPeriod, onMonth }: {
  period: "all" | "month";
  month: string;
  months: string[];
  onPeriod?: (period: "all" | "month") => void;
  onMonth?: (month: string) => void;
}) {
  if (!onPeriod) return null;
  return <div className="wardrobe__period">
    <div className="wardrobe__period-buttons" role="group" aria-label="Best seller period">
      <button type="button" aria-pressed={period === "all"} onClick={() => onPeriod("all")}>All time</button>
      <button type="button" aria-pressed={period === "month"} onClick={() => onPeriod("month")}>Monthly</button>
    </div>
    {period === "month" && <label className="wardrobe__month-label">
      <span>Business month</span>
      <select value={month} onChange={(event) => onMonth?.(event.target.value)}>
        {months.map((option) => <option key={option} value={option}>{formatMonth(option)}</option>)}
      </select>
    </label>}
  </div>;
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
