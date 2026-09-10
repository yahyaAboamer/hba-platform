import { useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";

import { api, can } from "../lib/api";
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
  feature_request: { message: string; visible: boolean } | null;
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

/**
 * One product: who has it, and what marketing asks about it.
 *
 * The roster is W02's four groups in W02's order — **Received, Processing,
 * Needs checking, Not sent** — and it lists every model rather than only those
 * who received something, because the question the screen answers is *who
 * could I ask*.
 *
 * Rows are deliberately thin: a name and a link. W02 asks for concise rows and
 * warns against duplicating status, size, quantity and date columns that the
 * group heading and the shared profile already carry.
 */
export function ProductDetail({ session }: { session: Session }) {
  const { id = "" } = useParams();
  const [detail, setDetail] = useState<Detail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [draft, setDraft] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  const load = useCallback(() => {
    api
      .get<Detail>(`/api/products/${id}`)
      .then(setDetail)
      .catch((caught) => setError(caught.message));
  }, [id]);

  useEffect(load, [load]);

  async function removeRequest() {
    setSaving(true);
    try {
      // W09 lists removing separately from hiding, and they are not the same:
      // hiding keeps the wording for later, removing withdraws it.
      await api.del(`/api/products/${id}/feature-request`);
      setDraft(null);
      load();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Could not remove it.");
    } finally {
      setSaving(false);
    }
  }

  async function saveRequest(visible: boolean | null, message?: string) {
    setSaving(true);
    try {
      await api.put(`/api/products/${id}/feature-request`, {
        ...(message !== undefined ? { message } : {}),
        ...(visible !== null ? { visible } : {}),
      });
      setDraft(null);
      load();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Could not save.");
    } finally {
      setSaving(false);
    }
  }

  if (error && !detail) {
    return (
      <p className="notice notice--refused" role="alert">
        {error}
      </p>
    );
  }
  if (!detail) return <p className="empty">Loading…</p>;

  const groups: [string, RosterEntry[]][] = [
    ["Received", detail.roster.received],
    ["Processing", detail.roster.processing],
    ["Needs checking", detail.roster.needs_checking],
    ["Not sent", detail.roster.not_sent],
  ];
  const audience =
    detail.roster.received.length + detail.roster.processing.length;

  return (
    <>
      <div className="page__head">
        <div className="page__title">
          <p className="crumb">
            <Link to="/products">Products</Link>
          </p>
          <h1>{detail.title}</h1>
          <span className="page__subtitle">
            {detail.sizes.map((size) => size.title).join(" · ") || "no sizes"}
          </span>
        </div>
      </div>

      {error && (
        <p className="notice notice--refused" role="alert">
          {error}
        </p>
      )}

      {/*
       * W09: passive guidance. No completion tracking, no acknowledgement, no
       * target moves — a model reads it and decides.
       *
       * The audience is stated because W10 makes it non-obvious: only models
       * who have the product see it, so a request written for a garment nobody
       * has is a request nobody reads.
       */}
      <section className="panel products__panel">
        <div className="panel__head">
          <h2 className="panel__title">Ask models to feature this</h2>
        </div>
        <div className="products__request">
          {draft === null ? (
            <>
              <p className="products__ask">
                {detail.feature_request?.message ?? (
                  <span className="detail__note">Nothing asked yet.</span>
                )}
              </p>
              <p className="detail__note">
                {detail.feature_request?.visible
                  ? `Visible to the ${audience} model${audience === 1 ? "" : "s"} who ${audience === 1 ? "has" : "have"} it.`
                  : "Hidden. Nobody sees it."}{" "}
                A model who never received it never sees it, however it is set.
              </p>
              {can(session, "affiliates.manage") && (
                <div className="products__actions">
                  <button
                    type="button"
                    className="button"
                    onClick={() =>
                      setDraft(detail.feature_request?.message ?? "")
                    }
                  >
                    {detail.feature_request ? "Change it" : "Write one"}
                  </button>
                  {detail.feature_request && (
                    <>
                      <button
                        type="button"
                        className="button"
                        disabled={saving}
                        onClick={() =>
                          saveRequest(!detail.feature_request?.visible)
                        }
                      >
                        {detail.feature_request.visible ? "Hide it" : "Show it"}
                      </button>
                      {/*
                       * Outlined and last. Hiding is the ordinary pause;
                       * removing throws the wording away, and W09 keeps them
                       * separate because they are different intentions.
                       */}
                      <button
                        type="button"
                        className="button button--danger"
                        disabled={saving}
                        onClick={removeRequest}
                      >
                        Remove it
                      </button>
                    </>
                  )}
                </div>
              )}
            </>
          ) : (
            <>
              <textarea
                className="input products__textarea"
                value={draft}
                rows={3}
                onChange={(event) => setDraft(event.target.value)}
                placeholder="Wear it with the wide-leg trousers if you have them."
              />
              <div className="products__actions">
                <button
                  type="button"
                  className="button button--primary"
                  disabled={saving || !draft.trim()}
                  onClick={() => saveRequest(null, draft)}
                >
                  {saving ? "Saving…" : "Save"}
                </button>
                <button
                  type="button"
                  className="button"
                  disabled={saving}
                  onClick={() => setDraft(null)}
                >
                  Cancel
                </button>
              </div>
            </>
          )}
        </div>
      </section>

      <section className="panel products__panel">
        <div className="panel__head">
          <h2 className="panel__title">Who has it</h2>
        </div>
        {groups.map(([label, entries]) => (
          <div key={label} className="products__group">
            <h3 className="products__group-title">
              {label}
              <span className="products__count">{entries.length}</span>
            </h3>
            {entries.length === 0 ? (
              <p className="detail__note">None.</p>
            ) : (
              <ul className="products__models">
                {entries.map((entry) => (
                  <li key={entry.affiliate_id}>
                    {/*
                     * The one shared profile (A03). Every screen that names a
                     * model reaches the same page.
                     */}
                    <Link to={`/affiliates/${entry.affiliate_id}`}>
                      {entry.name}
                    </Link>
                  </li>
                ))}
              </ul>
            )}
          </div>
        ))}
      </section>
    </>
  );
}
