import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";

import { usePortal } from "../components/AffiliateLayout";
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

/** The three questions people actually arrive with. */
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
  const [query] = useSearchParams();
  const [filter, setFilter] = useState<Filter>((["earned","pending","void"].includes(query.get("status") ?? "") ? query.get("status") : "all") as Filter);
  const [open, setOpen] = useState<string | null>(null);

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
  }, [month]);

  if (error) {
    return (
      <p className="notice notice--refused" role="alert">
        {error}
      </p>
    );
  }

  const head = (
    <div className="orders__head">
      <h1>Orders</h1>
      <span>{formatMonth(month)}</span>
    </div>
  );

  if (body === null) return <>{head}<p className="empty">Loading…</p></>;

  const all = body.orders_detail;

  if (all.length === 0) {
    return (
      <>
        {head}
        <p className="empty">
          No orders used your code in {formatMonth(month)} yet.
        </p>
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
            }}
          >
            {option.label} <span className="orders__filter-count">{count(option.key)}</span>
          </button>
        ))}
      </div>

      {shown.length === 0 ? (
        <p className="empty">
          {filter === "earned"
            ? "Nothing has counted yet this month."
            : filter === "pending"
              ? "Nothing is on its way — every order this month has arrived or been cancelled."
              : "Every order this month counts."}
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
 * `0` and says nothing about what the order was. `placed` is the figure as it
 * was placed, kept for exactly this line, and where neither exists the row
 * says so rather than printing a zero that reads as *it was worth nothing*.
 */
function saleLine(order: MyOrder): string {
  if (order.net_sales.kind === "known") return `${order.net_sales.amount} net sales`;
  if (order.net_sales.kind === "placed") return `${order.net_sales.amount} when it was placed`;
  return "amount not available";
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
  const pieces = order.contents.reduce((total, line) => total + line.quantity, 0);
  return (
    <li className="orders__row">
      {/*
       * The whole row opens it. A chevron would be a 12px target on a screen
       * held one-handed, and there is nothing else on the row to press.
       */}
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
          <span className={order.commission !== null ? "orders__fee" : order.forgone ? "orders__fee money--void" : "orders__fee orders__fee--none"}>
            {order.commission ?? order.forgone ?? "—"}
          </span>
          <span className="orders__net">{saleLine(order)}</span>
        </span>
      </button>

      {open && (
        <div className="orders__detail">
          {/*
           * **What was in the order** (owner, 11 September 2026).
           *
           * Inside the expansion, not on the row: the list answers *what did
           * they buy* and the row answers *what did I earn*, and a garment
           * name printed beside a figure reads as though the figure belonged
           * to the garment.
           *
           * **Empty is not the same as none.** Contents are read only for
           * orders that earned somebody commission, and only from 07A
           * onwards, so an older order genuinely has nothing recorded - and
           * saying so is the difference between an honest gap and a claim
           * that somebody bought nothing.
           */}
          {/* The row already says *no product lines available* where there
              are none, so the expansion does not say it twice. */}
          {order.contents.length > 0 && (
            <ul className="orders__contents">
              {order.contents.map((line, index) => (
                <li key={`${line.title}-${index}`}>
                  <span className="orders__item">
                    {line.title}
                    {line.quantity > 1 && ` × ${line.quantity}`}
                    {line.variant && (
                      <span className="orders__variant">Size {line.variant}</span>
                    )}
                  </span>
                  <span className="orders__qty">{line.price}</span>
                </li>
              ))}
            </ul>
          )}

          <p className="orders__explain">{explain(order, month)}</p>

          {/*
           * §11.4, and the one row that will be asked about. Kept inside the
           * expansion now rather than printed on every row: labelling all of
           * them would bury the one or two that matter.
           */}
          {order.paid_in_month && (
            <p className="orders__explain">
              It had not reached the customer when {formatMonth(month)} closed,
              so it was paid with {formatMonth(order.paid_in_month)} instead —
              still at the rate you were on when you sold it, not that
              month&rsquo;s. This is called{" "}
              <Link to="/glossary#carried-forward">carried forward</Link>.
            </p>
          )}
        </div>
      )}
    </li>
  );
}

/**
 * What this order did, in a sentence.
 *
 * The commission figure is the server's, never worked out here — §11.1's rule
 * about a second implementation applies to one order as much as to a month.
 * Where there is no figure the sentence says why rather than showing a zero.
 */
export function explain(order: MyOrder, month: string): string {
  const noRate = order.rate_missing
    ? ` No commission rate is set for ${formatMonth(month)}, so what it earns is not available yet.`
    : "";
  if (order.state === "earned") {
    // The export's sentence, with this month's own rate and the server's
    // figures - a delivered order later refunded is still this one (F04).
    return order.rate_bp !== null && order.commission !== null
      ? `Delivered and counted in ${formatMonth(month)}. Commission is ${percent(order.rate_bp)} of ${order.base}.`
      : `Delivered and counted in ${formatMonth(month)}.${noRate}`;
  }
  if (order.state === "pending") {
    // A month agreed before ADR 0040 counted delivered orders only, so an
    // order still on its way was left for the payroll after it arrives.
    if (!order.counted) {
      return `${formatMonth(month)} was agreed counting delivered orders only, so this order is paid with the month after it arrives — still at ${formatMonth(month)}'s rate.`;
    }
    // The export's sentence, word for word; the figure is on the row above.
    return `Counted in ${formatMonth(month)} while it is on its way. If it fails, it is removed and the difference is settled in a later month.${noRate}`;
  }
  // Void, and said by why. The approved sentence for a courier's failure,
  // and for a cancelled order with nothing left to show; our own, in the same
  // voice, for the two cases the design has no words for.
  if (order.status === "failed") {
    // After approval, the approved amount and any payment stand as recorded,
    // and what happens next is a review (05C). Nothing here says a deduction
    // was chosen, applied or settled anywhere - no record says that of one
    // order.
    return `Delivery failed, so this order is excluded from ${formatMonth(month)}.` +
      (order.failed_after_approval
        ? ` It failed after ${formatMonth(month)} was approved. The approved amount and any payment stay as recorded, and HBA reviews the difference.`
        : "");
  }
  if (order.status === "refunded") {
    return `The payment was refunded before this order arrived, so it is excluded from ${formatMonth(month)}.`;
  }
  if (order.net_sales.kind === "placed") {
    return "This order was cancelled, so nothing is counted. The amount shown is what it came to when it was placed.";
  }
  if (order.net_sales.kind === "known") return "This order was cancelled, so nothing is counted.";
  return "This order was cancelled, so the original sales amount is not available and nothing is counted.";
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
