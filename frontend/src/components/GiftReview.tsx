import { useCallback, useEffect, useState } from "react";

import { api } from "../lib/api";

type Gift = {
  shopify_order_id: string;
  order_number: string;
  placed_at: string;
  discount_codes: string[];
  /** Read from Shopify when the list opens; null when it could not be. */
  recipient_name: string | null;
  phone: string | null;
  items: string[];
  /** Parcels to this number, this one included, that one answer moves. */
  same_number: number;
};

type Listing = {
  gifts: Gift[];
  total: number;
  models: { id: number; name: string }[];
  names_unavailable: boolean;
};


/**
 * *Gifts that reached no model* (ADR 0060).
 *
 * A parcel is a model's only when the phone on it is hers, and HBA ships many
 * gifts to a number that is not on her profile. Those were stored as
 * customers and appeared nowhere, so her wardrobe was missing them. Here a
 * person says whose each one is - the platform never decides from a name -
 * and the number is remembered for the next parcel.
 *
 * Its own read, so a failure here costs this list and not the panel.
 */
export function GiftReview({ onCount }: { onCount?: (count: number) => void } = {}) {
  const [listing, setListing] = useState<Listing | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [chosen, setChosen] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const load = useCallback(() => {
    api.get<Listing>("/api/operations/unclaimed-gifts")
      .then((found) => { setListing(found); onCount?.(found.total); })
      .catch((caught) => setLoadError(caught.message));
    // `onCount` is the parent's setter.
  }, []);

  useEffect(load, [load]);

  async function answer(gift: Gift, affiliateId: number | null) {
    setBusy(gift.shopify_order_id);
    setError(null);
    setNotice(null);
    try {
      const done = affiliateId === null
        ? await api.post<{ orders: string[] }>(`/api/operations/unclaimed-gifts/${gift.shopify_order_id}/dismiss`, {})
        : await api.post<{ orders: string[] }>(`/api/operations/unclaimed-gifts/${gift.shopify_order_id}/assign`, { affiliate_id: affiliateId });
      const count = done.orders.length;
      const parcels = `${count} parcel${count === 1 ? "" : "s"}`;
      if (affiliateId === null) {
        setNotice(`${gift.order_number}: marked as not a model (${parcels}).`);
      } else {
        const name = listing?.models.find((model) => model.id === affiliateId)?.name ?? "her";
        setNotice(`${parcels} attached to ${name}. What was in them shows in her wardrobe within the hour.`);
      }
      load();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "That did not save.");
    } finally {
      setBusy(null);
    }
  }

  if (loadError) {
    return (
      <div className="data__import">
        <h3 className="data__heading">Gifts that reached no model</h3>
        <p className="data__note" role="status">Could not load this list.</p>
      </div>
    );
  }
  if (listing === null || (listing.total === 0 && !notice)) return null;

  return (
    <div className="data__import">
      <h3 className="data__heading">Gifts that reached no model</h3>
      {listing.total > 0 && (
        <p className="data__note data__parcels-lede">
          <strong>
            {listing.total} free order{listing.total === 1 ? "" : "s"} with a discount code went to a
            number no model has on her profile,
          </strong>{" "}
          so {listing.total === 1 ? "it is" : "they are"} in nobody&apos;s wardrobe. Say whose each one
          is. Every other parcel to the same number goes with it, and the next one to that number is
          matched by itself.
          {listing.total > listing.gifts.length && ` Showing the newest ${listing.gifts.length}.`}
        </p>
      )}
      {listing.names_unavailable && (
        <p className="data__note" role="status">Shopify could not be read, so the names are missing. Try again later.</p>
      )}
      {error && <p className="sync__error" role="alert">{error}</p>}
      {notice && <p className="sync__notice" role="status">{notice}</p>}
      <ul className="data__parcels data__gifts">
        {listing.gifts.map((gift) => {
          const pick = chosen[gift.shopify_order_id] ?? "";
          const working = busy === gift.shopify_order_id;
          return (
            <li key={gift.shopify_order_id} className="data__gift">
              <div className="data__gift-what">
                <span className="data__gift-order">
                  {gift.order_number} · {day(gift.placed_at)}
                </span>
                <span>
                  {gift.recipient_name ?? "Name not read"}
                  {gift.phone && <span className="data__gift-phone"> · {gift.phone}</span>}
                  {gift.same_number > 1 && (
                    <span className="data__gift-more"> · {gift.same_number} parcels to this number</span>
                  )}
                </span>
                {gift.items.length > 0 && <span className="data__gift-items">{gift.items.join(", ")}</span>}
              </div>
              <div className="data__gift-actions">
                <select
                  aria-label={`Whose gift is ${gift.order_number}?`}
                  value={pick}
                  disabled={working}
                  onChange={(event) => setChosen({ ...chosen, [gift.shopify_order_id]: event.target.value })}
                >
                  <option value="">Choose a model</option>
                  {listing.models.map((model) => (
                    <option key={model.id} value={model.id}>{model.name}</option>
                  ))}
                </select>
                <button
                  type="button"
                  className="button button--row button--primary"
                  disabled={working || pick === ""}
                  onClick={() => answer(gift, Number(pick))}
                >
                  Attach
                </button>
                <button
                  type="button"
                  className="button button--row"
                  disabled={working}
                  onClick={() => answer(gift, null)}
                >
                  Not a model
                </button>
              </div>
            </li>
          );
        })}
      </ul>
    </div>
  );
}

/** *14 Aug 2026*, in Cairo. */
function day(iso: string): string {
  return new Date(iso).toLocaleDateString("en-GB", {
    timeZone: "Africa/Cairo",
    day: "numeric",
    month: "short",
    year: "numeric",
  });
}
