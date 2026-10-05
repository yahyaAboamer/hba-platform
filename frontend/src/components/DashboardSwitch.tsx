import { Link } from "react-router-dom";

/**
 * The admin's way between the two dashboards (ADR 0057, the approved mockup
 * `docs/design/operations-dashboard-2026-10-03.html`).
 *
 * It sits under the brand so the six affiliate sections stay six, as the
 * approved export draws them. Only somebody who holds both sides is shown it;
 * the operations manager and the affiliate side's managers never are.
 */
export function DashboardSwitch({ current }: { current: "affiliates" | "operations" }) {
  return (
    <div className="layout__switch" role="group" aria-label="Dashboard">
      <Link to="/" aria-current={current === "affiliates" ? "page" : undefined}>
        Affiliates
      </Link>
      <Link to="/operations" aria-current={current === "operations" ? "page" : undefined}>
        Operations
      </Link>
    </div>
  );
}
