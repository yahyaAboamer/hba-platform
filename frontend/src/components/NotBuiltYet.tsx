import "./NotBuiltYet.css";

/**
 * A destination the approved navigation has and the platform does not.
 *
 * The redesign gives both halves tabs for things that do not exist yet —
 * Products, Wardrobe, Ranking. They are in the navigation because the
 * navigation was approved as a whole and a tab bar that grows a slot every
 * few weeks moves everything under somebody's thumb each time. They are
 * **not** pretending to work.
 *
 * ## Why this is not an empty state
 *
 * §S06: loading, empty, unavailable, stale and not-built are five different
 * facts, and the one thing they must never do is look alike. "No products
 * yet" on a Products screen that has no backend at all would be a lie with a
 * plausible shape — somebody would wait for products to appear.
 *
 * So this says the thing outright, names the phase that builds it, and is
 * drawn as a notice rather than as a page. Nobody should be able to mistake
 * it for a screen that is merely quiet today.
 *
 * It fetches nothing, so there is no request to fail and nothing here can
 * report a state it has not checked.
 */
export function NotBuiltYet({
  title,
  phase,
  what,
}: {
  /** The destination's own name, as the navigation says it. */
  title: string;
  /** Which batch builds it, so the answer to "when" is not "soon". */
  phase: string;
  /** One sentence on what it will do, in the reader's terms. */
  what: string;
}) {
  return (
    <section className="unbuilt" aria-labelledby="unbuilt-title">
      <p className="unbuilt__flag">Not built yet</p>
      <h1 id="unbuilt-title" className="unbuilt__title">
        {title}
      </h1>
      <p className="unbuilt__what">{what}</p>
      <p className="unbuilt__phase">
        This screen is built in <strong>{phase}</strong>. Nothing here is
        connected to real data, and nothing is missing from the platform
        because of it — the tab is in place early so the navigation stops
        moving.
      </p>
    </section>
  );
}
