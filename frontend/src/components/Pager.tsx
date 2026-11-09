import "./Pager.css";

/**
 * *Rows per page [50] · 1–50 of 1103 · ‹ ›* — the owner's pager (9 November
 * 2026, from his screenshot). `page` is zero-based.
 */
export function Pager({ page, size, total, sizes = [10, 25, 50, 100], suffix, onPage, onSize }: {
  page: number; size: number; total: number; sizes?: number[];
  /** After the count, e.g. " matching" while a search is on. */
  suffix?: string;
  onPage: (page: number) => void; onSize: (size: number) => void;
}) {
  const first = total === 0 ? 0 : page * size + 1;
  const last = Math.min(total, (page + 1) * size);
  return (
    <div className="pager" role="navigation" aria-label="Pages">
      <label className="pager__size">
        <span>Rows per page</span>
        <select value={size} onChange={(event) => onSize(Number(event.target.value))}>
          {sizes.map((each) => <option key={each} value={each}>{each}</option>)}
        </select>
      </label>
      <span className="pager__range">{first}–{last} of {total}{suffix ?? ""}</span>
      <span className="pager__acts">
        <button type="button" className="pager__step" aria-label="Previous page"
          disabled={page === 0} onClick={() => onPage(page - 1)}>‹</button>
        <button type="button" className="pager__step" aria-label="Next page"
          disabled={last >= total} onClick={() => onPage(page + 1)}>›</button>
      </span>
    </div>
  );
}
