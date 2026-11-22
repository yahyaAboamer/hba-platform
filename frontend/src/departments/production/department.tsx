import type { Department } from "../types";
import { productionRoutes } from "./screens/routes";

/**
 * Production (ADR 0069, 0084, 0085): a department like the others, in the
 * platform's own frame, look and sidebar. Its sections are Overview, Orders,
 * Tasks, Library (ADR 0087), Fabric, Incoming, Suppliers, Billing (owner only, ADR 0089), Payments (owner only) and Stage days; an order and a supplier's page
 * show their parent as the current section.
 *
 * `/production/next/*` and the old framed app's pages redirect (see
 * `screens/routes.tsx`), so no address that was shared stops working.
 */
export const production: Department = {
  key: "production",
  name: "Production",
  icon: "scissors",
  holds: "production.view",
  base: "/production",
  sections: [
    { slug: "overview", label: "Overview", to: "/production/overview" },
    { slug: "orders", label: "Orders", to: "/production/orders" },
    { slug: "tasks", label: "Tasks", to: "/production/tasks" },
    { slug: "library", label: "Library", to: "/production/library" },
    { slug: "fabric", label: "Fabric", to: "/production/fabric" },
    { slug: "incoming", label: "Incoming", to: "/production/incoming" },
    { slug: "suppliers", label: "Suppliers", to: "/production/suppliers" },
    // Money: only for `production.owner` (ADR 0089), like Payments.
    { slug: "billing", label: "Billing", to: "/production/billing", only: "production.owner" },
    // Money: only for `production.owner` (the admin and the production manager, ADR 0086).
    { slug: "payments", label: "Payments", to: "/production/payments", only: "production.owner" },
    { slug: "stage-days", label: "Stage days", to: "/production/settings" },
  ],
  routes: productionRoutes,
  moved: [],
};
