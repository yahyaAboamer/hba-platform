import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";

import { usePortal } from "./AffiliateLayout";
import { api } from "../lib/api";
import { formatMonth } from "../lib/money";
import type { MyEarnings, MyOrder } from "../lib/portal";
import "./MyOrders.css";

/**
 * The orders behind the figure, so they can count them against their own list.
 *
 * **No customer appears here**, and not because anything filters them: §10.2's
 * order index never stored a name, an address or a phone number, so there is
 * nothing to leak. What they see is their side of the sale — the order number,
 * when it was placed, what it was worth to them, and whether it counts yet.
 *
 * A row is never removed. §9.4 pays on delivery, so an order can go from
 * counting to not counting, and one that quietly disappeared would look like a
 * mistake somebody made rather than a parcel that did not arrive.
 *
 * ## What the row leads with
 *
 * The approved portal puts **her commission** in the large figure and the sale
 * underneath it, which is the opposite of what this screen used to do. It is
 * the right way round: the sale is the shop's number and the commission is
 * hers, and she opened this screen to check hers.
 */

/** The four filters, keyed by the order's counting state (`?status=` uses the same keys). */
type Filter = "all" | "earned" | "pending" | "void";

/**
 * The approved four: *All*, *Delivered*, *Pending*, *Failed*.
 *
 * *Failed* holds every order that did not count - the export files its own
 * cancelled order there too - and each row's chip and sentence then say which
 * it was. Only a courier's failure reads *Failed delivery*; a cancelled order
 * reads *Cancelled*, and one refunded while travelling reads *Refunded*.
 */
const FILTERS: { key: Filter; label: string }[] = [
  { key: "all", label: "All" },
  { key: "earned", label: "Delivered" },
  { key: "pending", label: "Pending" },
  { key: "void", label: "Failed" },
];

export function MyOrders() {
  const { month } = usePortal();
  const [body, setBody] = useState<MyEarnings | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useSearchParams();
  const [filter, setFilter] = useState<Filter>((["earned","pending","void"].includes(query.get("status") ?? "") ? query.get("status") : "all") as Filter);
  const [open, setOpen] = useState<string | null>(null);
  const [retry, setRetry] = useState(0);

  useEffect(() => {
    let live = true;
    setBody(null);
    setError(null);
    // The month changed underneath them, so an expanded row from the last one
    // would be pointing at an order that is no longer on screen.
    setOpen(null);
    api
      .get<MyEarnings>(`/api/me/earnings/${month}`)
      .then(value => { if(live) setBody(value); })
      .catch((caught) => {if(live) setError(caught.message);});
    return () => {live=false;};
  }, [month, retry]);

  const head = (
    <div className="orders__head">
      <h1>Orders</h1>
      <span>{formatMonth(month)}</span>
    </div>
  );

  // The title and month stay, so she still knows where she is. The words are
  // ours rather than the browser's: *Failed to fetch* describes a request,
  // not her orders.
  if (error) {
    return (
      <>
        {head}
        <p className="notice notice--refused orders__error" role="alert">
          Could not load your orders.{" "}
          <button type="button" className="button" onClick={() => setRetry((n) => n + 1)}>
            Retry
          </button>
        </p>
      </>
    );
  }

  // The page's own shape while it loads - four chips and three rows at their
  // real height - so nothing jumps when the list arrives (ADR 0050).
  if (body === null) {
    return (
      <>
        {head}
        <div className="orders__loading" role="status" aria-busy="true">
          <span className="visually-hidden">Loading your orders</span>
          <div className="orders__filters" aria-hidden="true">
            {FILTERS.map((option) => <span key={option.key} className="orders__skeleton-chip" />)}
          </div>
          {[0, 1, 2].map((n) => (
            <div key={n} className="orders__skeleton" aria-hidden="true">
              <span><i style={{ width: "44%" }} /><i style={{ width: "80%" }} /><i style={{ width: "38%" }} /></span>
              <span><i style={{ width: "70%" }} /><i style={{ width: "90%" }} /></span>
            </div>
          ))}
        </div>
      </>
    );
  }

  const all = body.orders_detail;

  if (all.length === 0) {
    // *Yet* only while the month can still take an order: `days_left` is
    // null once it is over, and an agreed month is over whatever the date.
    return (
      <>
        {head}
        <p className="empty">
          No orders used your code in {formatMonth(month)}
          {body.window.days_left !== null ? " yet" : ""}.
        </p>
        {/* What happens next, while it still can. */}
        {body.window.days_left !== null && (
          <p className="orders__hint">
            Orders appear here as soon as someone uses your code at checkout.
          </p>
        )}
      </>
    );
  }

  const count = (key: Filter) =>
    key === "all" ? all.length : all.filter((o) => o.state === key).length;
  const shown = filter === "all" ? all : all.filter((o) => o.state === filter);

  return (
    <>
      {head}

      {/* The count lives on the control, so choosing one and reading the
          answer are the same act. */}
      <div className="orders__filters" role="group" aria-label="Which orders">
        {FILTERS.map((option) => (
          <button
            key={option.key}
            type="button"
            className="orders__filter"
            aria-pressed={filter === option.key}
            onClick={() => {
              setFilter(option.key);
              setOpen(null);
              // Kept in the address, so Back and a refresh return to it.
              // Replaced rather than pushed: a filter is not a page.
              setQuery(
                (was) => {
                  const next = new URLSearchParams(was);
                  if (option.key === "all") next.delete("status");
                  else next.set("status", option.key);
                  return next;
                },
                { replace: true },
              );
            }}
          >
            {option.label} <span className="orders__filter-count">{count(option.key)}</span>
          </button>
        ))}
      </div>

      {/* A filter with nothing in it says so and names the month - nothing
          more. It once said *nothing has counted yet* over a month of
          pending orders, which count (ADR 0040). */}
      {shown.length === 0 ? (
        <p className="empty">
          No {FILTERS.find((option) => option.key === filter)!.label.toLowerCase()} orders in{" "}
          {formatMonth(month)}.
        </p>
      ) : (
        <ul className="orders">
          {shown.map((order) => (
            <Row
              key={order.order_number}
              order={order}
              month={month}
              open={open === order.order_number}
              onToggle={() =>
                setOpen((was) =>
                  was === order.order_number ? null : order.order_number,
                )
              }
            />
          ))}
        </ul>
      )}

      <p className="orders__note">Customer details aren't shown here.</p>
    </>
  );
}

/**
 * What the sale was, under the commission.
 *
 * Shopify zeroes a cancelled order's totals — correct for commission, since
 * §9.3 pays on what the customer actually paid — so a cancelled row's base is
 * `0` and says nothing about what the order was. `placed` is the figure at
 * checkout, kept for exactly this line, and where neither exists the row says
 * so rather than printing a zero that reads as *it was worth nothing*.
 */
function saleLine(order: MyOrder): string {
  if (order.net_sales.kind === "known") return `${order.net_sales.amount} net sales`;
  if (order.net_sales.kind === "placed") return `${order.net_sales.amount} at checkout`;
  return "amount not available";
}

/**
 * The second line under a product: `Size XL · Black · Qty 2`.
 *
 * Which value is the size is the server's answer (ADR 0050), from Shopify's
 * own option names - HBA's catalogue spells *size* 32 ways, and a colour on
 * its own must never read as one. Where the options were never read, the
 * variant title is shown as it is, and nothing is called a size.
 */
export function productDetail(line: MyOrder["contents"][number]): string {
  const size = line.size
    ? line.size.toLowerCase() === "one size" ? "One size" : `Size ${line.size}`
    : null;
  const rest = line.options ?? (line.variant && line.variant !== "Default Title" ? [line.variant] : []);
  return [size, ...rest, line.quantity > 1 ? `Qty ${line.quantity}` : null]
    .filter(Boolean)
    .join(" · ");
}

export function Row({
  order,
  month,
  open,
  onToggle,
}: {
  order: MyOrder;
  month: string;
  open: boolean;
  onToggle: () => void;
}) {
  const [why, setWhy] = useState(false);
  // An order opened again starts on its facts, not on the last explanation.
  useEffect(() => {
    if (!open) setWhy(false);
  }, [open]);
  const pieces = order.contents.reduce((total, line) => total + line.quantity, 0);
  const fact = facts(order, month);
  const sentence = explain(order, month);
  const hasWhy = sentence !== null || order.paid_in_month !== null;
  return (
    <li className="orders__row">
      {/* The whole row opens it; the chevron only says that it does. */}
      <button
        type="button"
        className="orders__button"
        aria-expanded={open}
        onClick={onToggle}
      >
        <span className="orders__left">
          <span className="orders__number">{order.order_number}</span>
          <span className="orders__meta">
            {/* *product* / *products*, the export's word. Ours said *pieces*,
                which is warehouse language for the same thing. */}
            {onlyTheDate(order.placed_at)} ·{" "}
            {pieces > 0
              ? `${pieces} ${pieces === 1 ? "product" : "products"}`
              : "no product lines available"}
          </span>
          {/* Her words for the state, from the server, in the tone that
              matches it: counted is money, on its way is not yet, and did
              not arrive is neither. */}
          <span className={`orders__pill orders__pill--${order.state}`}>{order.state_text}</span>
        </span>
        <span className="orders__right">
          {/*
           * **What it was worth to her**, and only where there is an answer.
           *
           * Delivered and pending both carry their figure (ADR 0040; the
           * owner asked for it), `EGP 0.00` included - a zero is an answer. A
           * void order keeps what it would have earned, struck through, so
           * she can still match the row against her own record. Where there
           * is no figure at all - no rate set, or an order its month did not
           * count - the row prints a dash, never a zero.
           */}
          {/* A strike-through is not read aloud, so the struck figure says
              in words that it was not earned. */}
          {order.commission !== null ? (
            <span className="orders__fee">{order.commission}</span>
          ) : order.forgone ? (
            <s className="orders__fee money--void">
              {order.forgone}
              <span className="visually-hidden"> (not earned)</span>
            </s>
          ) : (
            <span className="orders__fee orders__fee--none">—</span>
          )}
          <span className="orders__net">{saleLine(order)}</span>
          <svg className="orders__chevron" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
            <path d="m6 9 6 6 6-6" />
          </svg>
        </span>
      </button>

      {open && (
        <div className="orders__detail">
          {/*
           * **What was in the order** (owner, 11 September 2026; ADR 0050):
           * each product with its size, and how many where it was more than
           * one. Inside the expansion, not on the row: a garment name printed
           * beside a figure reads as though the figure belonged to it.
           *
           * The row already says *no product lines available* where there are
           * none yet, so the expansion does not say it twice.
           */}
          {order.contents.length > 0 && (
            <ul className="orders__contents">
              {order.contents.map((line, index) => {
                const detail = productDetail(line);
                return (
                  <li key={`${line.title}-${index}`}>
                    <span className="orders__item">
                      {line.title}
                      {detail && <span className="orders__variant">{detail}</span>}
                    </span>
                    <span className="orders__qty">{line.price}</span>
                  </li>
                );
              })}
            </ul>
          )}

          {/* Three facts in place of a paragraph (ADR 0050): what happened to
              it, what it earns, and which month it counts in. */}
          <dl className="orders__facts">
            <dt>Delivery</dt>
            <dd>{fact.delivery}</dd>
            <dt>Commission</dt>
            <dd>{fact.commission}</dd>
            <dt>Counted in</dt>
            <dd>
              {fact.countedIn}
              {/* The why, on request - the export's own ⓘ, as on Targets. */}
              {hasWhy && (
                <button
                  type="button"
                  className="orders__info"
                  aria-label="How this order is counted"
                  aria-expanded={why}
                  onClick={() => setWhy(!why)}
                >
                  i
                </button>
              )}
            </dd>
          </dl>

          {why && (
            <p className="orders__why">
              {sentence}
              {/*
               * §11.4, and the one row that will be asked about: an order its
               * month's agreement left for the month it arrived in.
               */}
              {order.paid_in_month && (
                <>
                  {sentence && " "}
                  It had not reached the customer when {formatMonth(month)} closed,
                  so it was paid with {formatMonth(order.paid_in_month)} instead —
                  still at the rate you were on when you sold it, not that
                  month&rsquo;s. This is called{" "}
                  <Link to="/glossary#carried-forward">carried forward</Link>.
                </>
              )}
            </p>
          )}
        </div>
      )}
    </li>
  );
}

/**
 * The three facts of an opened order (ADR 0050).
 *
 * Words on the server's facts - the state, the rate the server used, the
 * month that paid it - and never a figure worked out here: §11.1's rule about
 * a second implementation applies to one order as much as to a month.
 */
export function facts(order: MyOrder, month: string): { delivery: string; commission: string; countedIn: string } {
  const delivery = {
    delivered: order.delivered_at ? onlyTheDate(order.delivered_at) : "Delivered",
    pending: "On its way",
    failed: "Failed",
    cancelled: "Cancelled before delivery",
    refunded: "Refunded before delivery",
  }[order.status];
  const commission =
    order.state === "void"
      ? "Not earned"
      : order.rate_bp === null || order.rate_missing
        ? "Rate not set yet"
        : `${percent(order.rate_bp)} of net sales`;
  const countedIn =
    order.state === "void"
      ? "Not counted"
      : order.paid_in_month
        ? formatMonth(order.paid_in_month)
        : order.state === "pending" && !order.counted
          ? "After it arrives"
          : formatMonth(month);
  return { delivery, commission, countedIn };
}

/**
 * Why it is counted the way the facts say, behind the ⓘ - or `null` where the
 * facts already say it all (a delivered order, a cancelled one).
 *
 * The carried-forward sentence is the Row's own, because it holds a link.
 */
export function explain(order: MyOrder, month: string): string | null {
  const noRate = order.rate_missing
    ? `No commission rate is set for ${formatMonth(month)}, so what it earns is not available yet.`
    : null;
  if (order.state === "pending") {
    // A month agreed before ADR 0040 counted delivered orders only, so an
    // order still on its way was left for the payroll after it arrives.
    if (!order.counted) {
      return `${formatMonth(month)} was agreed counting delivered orders only, so this order is paid with the month after it arrives — still at ${formatMonth(month)}'s rate.`;
    }
    // The export's sentence, word for word.
    return `Counted in ${formatMonth(month)} while it is on its way. If it fails, it is removed and the difference is settled in a later month.` +
      (noRate ? ` ${noRate}` : "");
  }
  // After approval, the approved amount and any payment stand as recorded,
  // and what happens next is a review (05C). Nothing here says a deduction
  // was chosen, applied or settled - no record says that of one order.
  if (order.state === "void" && order.failed_after_approval) {
    return `It failed after ${formatMonth(month)} was approved. The approved amount and any payment stay as recorded, and HBA reviews the difference.`;
  }
  if (order.state === "earned") return noRate;
  return null;
}

/** 1000 → `10%`, 1250 → `12.5%`. A rate, never an amount. */
function percent(bp: number): string {
  const whole = bp / 100;
  return `${Number.isInteger(whole) ? whole : whole.toFixed(2).replace(/0$/, "")}%`;
}

/**
 * `2026-08-14T…` → `14 August`.
 *
 * The year is already on the month bar above, and repeating it on forty rows
 * is forty things to read past.
 */
function onlyTheDate(iso: string): string {
  return new Date(iso).toLocaleDateString("en-GB", {
    day: "numeric",
    month: "long",
  });
}
