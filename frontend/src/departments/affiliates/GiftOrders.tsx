import { useEffect, useState } from "react";

import { api } from "../../lib/api";

/**
 * The gift orders placed for one model, on her Wardrobe section.
 *
 * Her wardrobe says what she has; this says whether an order was placed for
 * her at all, and when - so staff can check the person who places gift
 * orders placed hers. The same orders her wardrobe is built from: zero-priced
 * orders matched to her, never an order that used her discount code.
 */
export type GiftOrder = {
  shopify_order_id: string;
  order_number: string;
  placed_at: string | null;
  state: "received" | "processing" | "failed" | "cancelled";
  delivered_at: string | null;
  admin_url: string | null;
  items: { title: string; size: string | null; quantity: number }[];
};

const STATE: Record<GiftOrder["state"], { label: string; tone: string }> = {
  received: { label: "Delivered", tone: "approved" },
  processing: { label: "On its way", tone: "owed" },
  failed: { label: "Needs checking", tone: "refused" },
  cancelled: { label: "Cancelled", tone: "quiet" },
};

function day(iso: string): string {
  return new Date(iso).toLocaleDateString("en-GB", { day: "numeric", month: "long", year: "numeric" });
}

function piece(item: GiftOrder["items"][number]): string {
  const size = item.size ? ` (${item.size})` : "";
  const many = item.quantity > 1 ? ` ×${item.quantity}` : "";
  return `${item.title}${size}${many}`;
}

export function GiftOrders({ affiliateId, name, reload }: { affiliateId: number; name: string; reload: number }) {
  const [orders, setOrders] = useState<GiftOrder[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [retry, setRetry] = useState(0);

  useEffect(() => {
    let live = true;
    setOrders(null);
    setError(null);
    api
      .get<{ orders: GiftOrder[] }>(`/api/affiliates/${affiliateId}/wardrobe/orders`)
      .then((body) => { if (live) setOrders(body.orders); })
      .catch((caught) => { if (live) setError(caught instanceof Error ? caught.message : "Could not load the orders."); });
    return () => { live = false; };
  }, [affiliateId, reload, retry]);

  return <>
    <div className="profile__subhead profile__subhead--gap">
      <h2>Orders placed for {name}</h2>
      {orders && <span>{orders.length} {orders.length === 1 ? "order" : "orders"}</span>}
    </div>
    <div className="surface">
      {error ? (
        <p className="notice notice--refused" role="alert">
          {error} <button type="button" className="button" onClick={() => setRetry((n) => n + 1)}>Retry</button>
        </p>
      ) : orders === null ? (
        <p className="empty">Loading orders…</p>
      ) : orders.length === 0 ? (
        <p className="empty">No gift order has been placed for {name} yet.</p>
      ) : (
        <ul className="profile__pending profile__gift-orders">
          {orders.map((order) => {
            const state = STATE[order.state] ?? STATE.processing;
            return (
              <li key={order.shopify_order_id}>
                <span>
                  {order.admin_url
                    ? <a className="pay-detail__link" href={order.admin_url} target="_blank" rel="noreferrer">{order.order_number}</a>
                    : <strong>{order.order_number}</strong>}
                  {order.placed_at && <span className="profile__gift-order-date"> · {day(order.placed_at)}</span>}
                  <span className="profile__piece-size">{order.items.map(piece).join(", ")}</span>
                </span>
                <span className={`profile__tone--${state.tone}`}>{state.label}</span>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  </>;
}
