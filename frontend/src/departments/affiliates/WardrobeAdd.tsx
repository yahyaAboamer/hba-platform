import { useEffect, useState } from "react";
import { api } from "../../lib/api";

type Found = { shopify_product_id: string; title: string; image_url: string | null };
type Picked = Found & { sizes: { title: string }[] };

/**
 * *Add a product* on a model's Wardrobe (ADR 0061, from her side).
 *
 * The product page's *Assign manually* answers "who has this piece"; this
 * answers "what does she have", for a model whose wardrobe is missing a piece
 * she received without a gift order matched to her. It saves the same hand
 * assignment, so the product's coverage and her wardrobe agree.
 */
export function WardrobeAdd({ affiliateId, name, owned, onDone, onCancel }: {
  affiliateId: number; name: string;
  /** Products already received, which are shown but cannot be picked. */
  owned: Set<string>;
  onDone: () => void; onCancel: () => void;
}) {
  const [search, setSearch] = useState("");
  const [found, setFound] = useState<Found[] | null>(null);
  const [picked, setPicked] = useState<Picked | null>(null);
  const [size, setSize] = useState("");
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState<string | null>(null);

  useEffect(() => {
    const needle = search.trim();
    if (!needle) { setFound(null); return; }
    let live = true;
    const timer = window.setTimeout(() => {
      // Archived and draft products too: a piece she has may no longer be on sale.
      api.get<{ products: Found[] }>(`/api/products?all_products=true&limit=20&search=${encodeURIComponent(needle)}`)
        .then((body) => { if (live) setFound(body.products); })
        .catch((caught) => { if (live) setFailure(caught instanceof Error ? caught.message : "Could not search."); });
    }, 250);
    return () => { live = false; window.clearTimeout(timer); };
  }, [search]);

  async function choose(product: Found) {
    setBusy(true);
    setFailure(null);
    try {
      const detail = await api.get<{ sizes: { title: string }[] }>(`/api/products/${product.shopify_product_id}`);
      setPicked({ ...product, sizes: detail.sizes ?? [] });
      setSize("");
    } catch (caught) {
      setFailure(caught instanceof Error ? caught.message : "Could not open that product.");
    } finally { setBusy(false); }
  }

  async function save() {
    if (!picked) return;
    setBusy(true);
    setFailure(null);
    try {
      await api.post(`/api/products/${picked.shopify_product_id}/manual-assignments`, {
        affiliate_ids: [affiliateId], ...(size ? { size } : {}),
      });
      onDone();
    } catch (caught) {
      setFailure(caught instanceof Error ? caught.message : "Could not save.");
      setBusy(false);
    }
  }

  return <section className="surface wardrobe-add" aria-label="Add a product">
    <h3 className="wardrobe-add__title">Add a product</h3>
    <p className="wardrobe-add__note">For a piece {name} has that no gift order shows, such as one collected from the warehouse or sent to a number not on her profile. It shows as received here, in her wardrobe and on the product.</p>
    {failure && <p className="notice notice--refused" role="alert">{failure}</p>}

    {picked ? <>
      <div className="wardrobe-add__chosen">
        {picked.image_url
          ? <img className="profile__piece-image" src={picked.image_url} alt="" />
          : <span className="profile__piece-image profile__piece-image--none">image</span>}
        <span className="profile__piece-name">{picked.title}</span>
        <button type="button" className="button" disabled={busy} onClick={() => setPicked(null)}>Change</button>
      </div>
      {picked.sizes.length > 0 && (
        <select className="wardrobe-add__size" aria-label="Size" value={size} disabled={busy} onChange={(event) => setSize(event.target.value)}>
          <option value="">Size not known</option>
          {picked.sizes.map((each) => <option key={each.title} value={each.title}>{each.title}</option>)}
        </select>
      )}
    </> : <>
      <input className="input wardrobe-add__search" aria-label="Search products" placeholder="Search products by name"
        value={search} autoFocus onChange={(event) => setSearch(event.target.value)} />
      {found && (found.length === 0
        ? <p className="empty">No products match.</p>
        : <ul className="wardrobe-add__list">
            {found.map((product) => {
              const has = owned.has(product.shopify_product_id);
              return <li key={product.shopify_product_id}>
                <button type="button" className="wardrobe-add__option" disabled={busy || has} onClick={() => choose(product)}>
                  {product.image_url
                    ? <img className="wardrobe-add__thumb" src={product.image_url} alt="" loading="lazy" />
                    : <span className="wardrobe-add__thumb profile__piece-image--none" />}
                  <span>{product.title}</span>
                  {has && <span className="wardrobe-add__has">Already received</span>}
                </button>
              </li>;
            })}
          </ul>)}
    </>}

    <div className="wardrobe-add__acts">
      <button type="button" className="button button--primary" disabled={busy || !picked} onClick={save}>
        {busy && picked ? "Saving…" : "Add to wardrobe"}
      </button>
      <button type="button" className="button" disabled={busy} onClick={onCancel}>Cancel</button>
    </div>
  </section>;
}
