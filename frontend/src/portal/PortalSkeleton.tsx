import "./PortalSkeleton.css";

type Screen = "wardrobe" | "targets" | "ranking";

/** Keep each portal tab's structure visible while its first read completes. */
export function PortalSkeleton({ screen }: { screen: Screen }) {
  return (
    <div className={`portal-skeleton portal-skeleton--${screen}`} role="status" aria-busy="true" aria-label={`Loading ${screen}`}>
      <h1>{screen === "wardrobe" ? "Wardrobe" : screen === "targets" ? "Targets" : "Ranking"}</h1>
      <div className="portal-skeleton__bar portal-skeleton__intro" aria-hidden="true" />
      {screen === "wardrobe" && <div aria-hidden="true">
        <div className="portal-skeleton__chips"><i /><i /><i /></div>
        <h2>In your wardrobe</h2>
        <div className="portal-skeleton__tiles"><div /><div /></div>
        <h2>HBA would like you to feature</h2>
        <div className="portal-skeleton__row" />
        <h2>Your best sellers</h2>
        <div className="portal-skeleton__row" /><div className="portal-skeleton__row" />
      </div>}
      {screen === "targets" && <div aria-hidden="true">
        <div className="portal-skeleton__card portal-skeleton__target-card"><i /><i /><i /></div>
        <div className="portal-skeleton__note"><i /><i /></div>
        <h2>Earlier months</h2>
        <div className="portal-skeleton__row" /><div className="portal-skeleton__row" />
      </div>}
      {screen === "ranking" && <div aria-hidden="true">
        <div className="portal-skeleton__card portal-skeleton__rank-card"><i /><i /><i /></div>
        <h2>All models</h2>
        <div className="portal-skeleton__row" /><div className="portal-skeleton__row" />
        <div className="portal-skeleton__row" /><div className="portal-skeleton__row" />
      </div>}
    </div>
  );
}
