import { useCallback, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";

import { Pager } from "../../../components/Pager";
import { api, can } from "../../../lib/api";
import type { Session } from "../../../lib/api";
import { LIBRARY_SEARCH_HINT, STATUS_WORDS, libraryMatches, missingWords, sizesWords } from "./libraryLogic";
import type { LibraryRow, ProductStatus } from "./types";
import { Problem, SearchBox, StylePhoto, useIsNarrow } from "./ui";

type Show = "all" | ProductStatus;
const SHOWS: Show[] = ["all", "active", "draft", "archived"];
const PAGE_SIZES = [25, 50, 100];

function Name({ row }: { row: LibraryRow }) {
  return (
    <div className="prod-with-photo">
      <StylePhoto url={row.image_url} />
      <div>
        <Link className="prod-rowlink" to={`/production/library/${row.id}`}>
          {row.title}
        </Link>
        <div className="prod-small">
          <span className={`prod-pill${row.status === "active" ? " prod-pill--ok" : ""}`}>{STATUS_WORDS[row.status]}</span>
        </div>
      </div>
    </div>
  );
}

function Missing({ row, withMoney }: { row: LibraryRow; withMoney: boolean }) {
  const missing = missingWords(row, withMoney);
  return missing ? <span className="prod-warn">Missing: {missing}</span> : <span className="prod-ok">All added</span>;
}

const ordersWords = (count: number) => (count === 0 ? "None yet" : `${count} order${count === 1 ? "" : "s"}`);

/**
 * `/production/library` (ADR 0087): every HBA product, drafts and archived ones too, with what Shopify
 * knows and what HBA has added. Each opens on its own page.
 */
export function LibraryList({ session }: { session: Session }) {
  const withMoney = can(session, "production.owner");
  const narrow = useIsNarrow();
  const [rows, setRows] = useState<LibraryRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [show, setShow] = useState<Show>("all");
  const [query, setQuery] = useState("");
  const [page, setPage] = useState(0);
  const [pageSize, setPageSize] = useState(PAGE_SIZES[0]);

  const load = useCallback(() => {
    setError(null);
    api.get<{ products: LibraryRow[] }>("/api/prod/library")
      .then((answer) => setRows(answer.products))
      .catch((caught) => setError(caught instanceof Error ? caught.message : "The library could not be loaded."));
  }, []);
  useEffect(load, [load]);

  const count = (status: Show) => (rows ?? []).filter((row) => status === "all" || row.status === status).length;
  const shown = useMemo(
    () => (rows ?? []).filter((row) => (show === "all" || row.status === show) && libraryMatches(row, query)),
    [rows, show, query],
  );
  const lastPage = Math.max(0, Math.ceil(shown.length / pageSize) - 1);
  const shownPage = Math.min(page, lastPage);
  const pageRows = shown.slice(shownPage * pageSize, (shownPage + 1) * pageSize);
  const searching = query.trim() !== "";

  return (
    <>
      <div className="page__head">
        <div className="page__title">
          <h1>Library</h1>
          <span className="page__subtitle">
            {rows ? `${rows.length} product${rows.length === 1 ? "" : "s"} from Shopify, drafts included` : "Loading"}
          </span>
        </div>
      </div>

      {error && (
        <div>
          <Problem>{error}</Problem>
          <button type="button" className="button" onClick={load}>
            Try again
          </button>
        </div>
      )}

      {!error && rows === null && <p className="loading" role="status">Loading the library…</p>}

      {rows && (
        <>
          <SearchBox
            label="Search the library"
            hint={LIBRARY_SEARCH_HINT}
            value={query}
            onChange={(value) => {
              setQuery(value);
              setPage(0);
            }}
          />
          <div className="prod-chips" role="group" aria-label="Show">
            {SHOWS.map((key) => (
              <button
                key={key}
                type="button"
                className={`chip${show === key ? " chip--on" : ""}`}
                aria-pressed={show === key}
                onClick={() => {
                  setShow(key);
                  setPage(0);
                }}
              >
                {key === "all" ? "All" : STATUS_WORDS[key]} · {count(key)}
              </button>
            ))}
          </div>

          {shown.length === 0 ? (
            <p className="empty">
              {rows.length === 0
                ? "No product has come from Shopify yet."
                : searching
                  ? "No product matches."
                  : "No product here."}
            </p>
          ) : narrow ? (
            <div className="prod-cards">
              {pageRows.map((row) => (
                <article key={row.id} className="prod-card">
                  <Name row={row} />
                  <div className="prod-small">
                    {sizesWords(row.sizes)} · {ordersWords(row.orders)}
                  </div>
                  <div className="prod-small">
                    <Missing row={row} withMoney={withMoney} />
                  </div>
                </article>
              ))}
            </div>
          ) : (
            <div className="surface prod-list">
              <table className="table">
                <thead>
                  <tr>
                    <th scope="col">Product</th>
                    <th scope="col">Sizes</th>
                    <th scope="col">Added by HBA</th>
                    <th scope="col">Production orders</th>
                  </tr>
                </thead>
                <tbody>
                  {pageRows.map((row) => (
                    <tr key={row.id}>
                      <td>
                        <Name row={row} />
                      </td>
                      <td>{sizesWords(row.sizes)}</td>
                      <td>
                        <Missing row={row} withMoney={withMoney} />
                      </td>
                      <td>{ordersWords(row.orders)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          {shown.length > PAGE_SIZES[0] && (
            <Pager
              page={shownPage}
              size={pageSize}
              total={shown.length}
              sizes={PAGE_SIZES}
              suffix={searching ? " matching" : ""}
              onPage={setPage}
              onSize={(size) => {
                setPageSize(size);
                setPage(0);
              }}
            />
          )}
        </>
      )}
    </>
  );
}
