import { Link } from "react-router-dom";

import { can } from "../lib/api";
import type { Session } from "../lib/api";

/** The three dashboards, and what somebody must hold to be shown each. */
const DASHBOARDS = [
  { key: "affiliates", label: "Affiliates", to: "/", holds: "affiliates.view" },
  { key: "operations", label: "Operations", to: "/operations", holds: "order_ops.view" },
  { key: "inbox", label: "Inbox", to: "/inbox", holds: "inbox.use" },
] as const;

export type Dashboard = (typeof DASHBOARDS)[number]["key"];

/**
 * The way between the dashboards (ADR 0057 and ADR 0059; the approved mockups
 * `docs/design/operations-dashboard-2026-10-03.html` and
 * `docs/design/whatsapp-inbox-2026-10-11.html`, frame 5).
 *
 * It sits under the brand so each dashboard's own sections stay as the
 * approved designs draw them. It shows only the dashboards a person holds:
 * the admin all three, the operations manager Operations and Inbox. Somebody
 * who holds one - customer service, the affiliate side's managers - sees no
 * switch at all.
 */
export function DashboardSwitch({ session, current }: { session: Session; current: Dashboard }) {
  const held = DASHBOARDS.filter((dashboard) => can(session, dashboard.holds));
  if (held.length < 2) return null;
  return (
    <div
      className={held.length > 2 ? "layout__switch layout__switch--three" : "layout__switch"}
      role="group"
      aria-label="Dashboard"
    >
      {held.map((dashboard) => (
        <Link
          key={dashboard.key}
          to={dashboard.to}
          aria-current={current === dashboard.key ? "page" : undefined}
        >
          {dashboard.label}
        </Link>
      ))}
    </div>
  );
}
