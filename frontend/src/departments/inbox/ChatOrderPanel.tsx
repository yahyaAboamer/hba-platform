import { useState } from "react";

import { ApiError, api } from "../lib/api";
import { ANSWER_WORDS, dayTimeLabel, orderStatus, totalLabel } from "../lib/inbox";
import type { ChatOrder } from "../lib/inbox";
import { OpsIcon, dayMonth } from "./OpsSource";

/**
 * The customer's order, beside her chat (ADR 0059; the approved mockup's
 * frame 1, right-hand column).
 *
 * Staff can record her answer here - she confirmed by phone, say. That
 * changes the order's tag in Shopify and nothing else there: an order marked
 * cancelled here is still cancelled in Shopify, by hand.
 *
 * The mockup also lists the payment method and the items. The platform keeps
 * neither for a customer's order (ADR 0059, point 9): they are one click
 * away, on the order in Shopify.
 */

/** Where the answer was given (ADR 0063). */
const ANSWERED_IN: Record<string, string> = {
  whatsapp: "She answered in WhatsApp.",
  inbox: "Marked here in the Inbox.",
  shopify: "Tagged by the team in Shopify.",
};

const MARK: [string, string][] = [
  ["confirmed", "Mark confirmed"],
  ["edit", "Mark wants a change"],
  ["cancelled", "Mark cancelled"],
];

function OrderLink({ order }: { order: ChatOrder }) {
  const name = order.order ?? order.order_id;
  if (!order.admin_url) return <span className="num">{name}</span>;
  return (
    <a className="ops-ext num" href={order.admin_url} target="_blank" rel="noopener noreferrer">
      {name}
      <OpsIcon name="ext" />
      <span className="visually-hidden"> (opens in Shopify)</span>
    </a>
  );
}

export function ChatOrderPanel({
  orders,
  now,
  onAnswered,
}: {
  /** Newest first. */
  orders: ChatOrder[];
  now: number;
  onAnswered: () => void;
}) {
  const [busy, setBusy] = useState<string | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const [order, ...earlier] = orders;

  async function mark(answer: string) {
    if (!order) return;
    setBusy(answer);
    setProblem(null);
    try {
      await api.post(`/api/inbox/confirmations/${encodeURIComponent(order.order_id)}/answer`, { answer });
      onAnswered();
    } catch (error) {
      setProblem(error instanceof ApiError ? error.message : "That could not be saved.");
    } finally {
      setBusy(null);
    }
  }

  if (!order) {
    return (
      <div className="inbox-order">
        <h3>Order</h3>
        <p className="inbox-order__none">No order with a confirmation for this number.</p>
      </div>
    );
  }

  const status = orderStatus(order);
  return (
    <div className="inbox-order">
      <h3>Order</h3>
      <dl>
        <dt>Number</dt>
        <dd>
          <OrderLink order={order} />
        </dd>
        <dt>Placed</dt>
        <dd className="num">{order.placed_at ? dayTimeLabel(order.placed_at, now) : "—"}</dd>
        <dt>Total</dt>
        <dd className="num">{totalLabel(order.total)}</dd>
      </dl>

      {order.kind === "payment" ? (
        <>
          {/* An international order's payment link (ADR 0062): nothing to
              tap, so nothing to record here. Shopify says when it is paid. */}
          <h3>Payment</h3>
          <span className={`inbox-status inbox-status--${status.tone}`}>{status.words}</span>
          {order.why && !order.paid_at && <p className="inbox-order__why">{order.why}</p>}
          <p className="inbox-order__hint">
            {order.paid_at
              ? `Paid ${dayTimeLabel(order.paid_at, now)}.`
              : order.reminded_at
                ? `Reminded ${dayTimeLabel(order.reminded_at, now)}. No more reminders are sent.`
                : "One reminder is sent 24 hours after the link if it is still unpaid."}
          </p>
          <p className="inbox-order__hint">
            {order.invoice_error
              ? `Invoice email: ${order.invoice_error}`
              : order.invoice_at
                ? `Shopify emailed the invoice ${dayTimeLabel(order.invoice_at, now)}.`
                : "No invoice email has been sent."}
          </p>
        </>
      ) : (
        <>
          <h3>Confirmation</h3>
          <span className={`inbox-status inbox-status--${status.tone}`}>{status.words}</span>
          {order.answer && order.answered_in && ANSWERED_IN[order.answered_in] && (
            <p className="inbox-order__hint">{ANSWERED_IN[order.answered_in]}</p>
          )}
          {order.why && !order.answer && <p className="inbox-order__why">{order.why}</p>}
          <div className="inbox-setstatus">
            {MARK.filter(([answer]) => answer !== order.answer).map(([answer, label]) => (
              <button
                key={answer}
                type="button"
                className={
                  answer === "confirmed"
                    ? "inbox-btn inbox-btn--small"
                    : "inbox-btn inbox-btn--quiet inbox-btn--small"
                }
                disabled={busy !== null}
                onClick={() => mark(answer)}
              >
                {busy === answer ? "Saving…" : label}
              </button>
            ))}
          </div>
          <p className="inbox-order__hint">
            Changes the order's tag in Shopify. It does not cancel or change the order there.
          </p>
          {problem && (
            <p className="notice notice--refused" role="alert">
              {problem}
            </p>
          )}
        </>
      )}

      <h3>Tags in Shopify</h3>
      {/* What Shopify really has, once read - not what the platform last
          wrote, which the team may have changed there (ADR 0063). */}
      <div>
        {order.tags_read_at ? (
          order.shopify_tags ? (
            order.shopify_tags.split(" + ").map((tag) => (
              <span key={tag} className="ops-tag ops-tag--hit">
                {tag}
              </span>
            ))
          ) : (
            <span className="ops-muted">None</span>
          )
        ) : order.tag ? (
          <span className="ops-tag ops-tag--hit">{order.tag}</span>
        ) : (
          <span className="ops-muted">None yet</span>
        )}
      </div>
      <p className="inbox-order__hint">
        {order.tags_read_at
          ? `As Shopify had them ${dayTimeLabel(order.tags_read_at, now)}.`
          : "The tag the platform wrote. Not read back from Shopify yet."}
      </p>

      {earlier.length > 0 && (
        <>
          <h3>Earlier orders</h3>
          <ul className="inbox-other">
            {earlier.map((past) => (
              <li key={past.order_id}>
                <OrderLink order={past} />
                <span className="ops-muted">
                  {(past.answer && ANSWER_WORDS[past.answer]) || orderStatus(past).words}
                  {past.placed_at ? ` · ${dayMonth(past.placed_at)}` : ""}
                </span>
              </li>
            ))}
          </ul>
        </>
      )}
    </div>
  );
}
