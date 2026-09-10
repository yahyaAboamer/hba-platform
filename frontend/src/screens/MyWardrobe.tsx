import { useEffect, useState } from "react";

import { api } from "../lib/api";
import "./MyWardrobe.css";

type Item = {
  shopify_product_id: string | null;
  title: string;
  size: string | null;
  quantity: number;
  state: string;
  image_url: string | null;
  shopify_order_id: string;
};

type Request = {
  shopify_product_id: string;
  message: string;
  title: string | null;
  image_url: string | null;
};

type Wardrobe = {
  received: Item[];
  processing: Item[];
  failed: Item[];
  feature_requests: Request[];
};

/**
 * What HBA has sent her.
 *
 * W08 sets the shape: **Received first, with images and sizes**, then a
 * compact area for what has not arrived. The two are not the same kind of
 * thing and the layout says so — a grid of things she owns, and a short list
 * of things that are still in the post or did not make it.
 *
 * ## What is deliberately absent
 *
 * **Nothing she bought** (D05, 10 September 2026). The wardrobe is a record of
 * what the business gave her, not an inventory of her cupboard.
 *
 * **No Done button** on a feature request (W09). It is passive guidance:
 * marketing would like something said, she reads it and decides. The moment it
 * gains a state per model it becomes a task list, and targets already are one.
 *
 * **No arrival estimates** (W07). Shopify does not tell us when a parcel will
 * land, and a date invented here is a promise HBA cannot keep.
 */
export function MyWardrobe() {
  const [body, setBody] = useState<Wardrobe | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    api
      .get<Wardrobe>("/api/me/wardrobe")
      .then((found) => {
        if (live) setBody(found);
      })
      .catch((caught) => {
        // **Never rendered as an empty wardrobe** (§S06). A failed request and
        // "HBA has not sent you anything" are different facts, and one of them
        // is alarming to be told wrongly.
        if (live) setError(caught.message);
      });
    return () => {
      live = false;
    };
  }, []);

  if (error) {
    return (
      <p className="notice notice--refused" role="alert">
        {error}
      </p>
    );
  }

  if (body === null) return <p className="empty">Loading…</p>;

  const waiting = [...body.processing, ...body.failed];
  const nothingAtAll =
    body.received.length === 0 && waiting.length === 0;

  return (
    <div className="wardrobe">
      {nothingAtAll && (
        <p className="empty">
          HBA has not sent you anything yet. When they do, it appears here with
          its size.
        </p>
      )}

      {body.received.length > 0 && (
        <section className="wardrobe__block">
          <h2 className="wardrobe__title">Yours</h2>
          <ul className="wardrobe__grid">
            {body.received.map((item) => (
              <li key={item.shopify_order_id + item.title} className="wardrobe__item">
                <Picture item={item} />
                <span className="wardrobe__name">{item.title}</span>
                {item.size && <span className="wardrobe__size">{item.size}</span>}
              </li>
            ))}
          </ul>
        </section>
      )}

      {/*
       * Compact, and below what she owns (W08). These are two different states
       * sharing one area because they answer one question — *what is not here
       * yet* — and each row says which it is rather than leaving her to infer
       * it from a colour.
       */}
      {waiting.length > 0 && (
        <section className="wardrobe__block">
          <h2 className="wardrobe__title">Not with you yet</h2>
          <ul className="wardrobe__waiting">
            {waiting.map((item) => (
              <li key={item.shopify_order_id + item.title}>
                <span className="wardrobe__name">{item.title}</span>
                {item.size && (
                  <span className="wardrobe__size">{item.size}</span>
                )}
                <span
                  className={
                    item.state === "failed"
                      ? "wardrobe__state wardrobe__state--failed"
                      : "wardrobe__state"
                  }
                >
                  {item.state === "failed"
                    ? "did not arrive — HBA is looking into it"
                    : "on its way"}
                </span>
              </li>
            ))}
          </ul>
        </section>
      )}

      {/*
       * Only where she actually has the product, decided on the server (W10).
       * The header and the cards appear and disappear together — an empty
       * section with a heading is a section that looks broken.
       */}
      {body.feature_requests.length > 0 && (
        <section className="wardrobe__block">
          <h2 className="wardrobe__title">HBA would love to see</h2>
          <ul className="wardrobe__requests">
            {body.feature_requests.map((request) => (
              <li key={request.shopify_product_id}>
                {request.title && (
                  <span className="wardrobe__name">{request.title}</span>
                )}
                <p className="wardrobe__ask">{request.message}</p>
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}

/**
 * A picture, or an honest gap.
 *
 * A product deleted from Shopify takes its image with it, and the line item
 * still carries the title and size — so the entry is real and only the
 * photograph is missing. A broken frame would say something went wrong;
 * this says the picture is gone and the garment is not.
 */
function Picture({ item }: { item: Item }) {
  if (!item.image_url) {
    return <span className="wardrobe__nopic" aria-hidden="true" />;
  }
  return (
    <img className="wardrobe__pic" src={item.image_url} alt="" loading="lazy" />
  );
}
