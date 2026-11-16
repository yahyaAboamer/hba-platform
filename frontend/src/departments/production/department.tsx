import type { Department } from "../types";
import { productionRoutes } from "./screens/routes";

/**
 * Production (ADR 0069, 0084, 0085): a department like the others, in the
 * platform's own frame, look and sidebar. Its sections are Overview, Orders,
 * Tasks, Incoming, Suppliers and Stage days; an order and a supplier's page
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
    { slug: "incoming", label: "Incoming", to: "/production/incoming" },
    { slug: "suppliers", label: "Suppliers", to: "/production/suppliers" },
    { slug: "stage-days", label: "Stage days", to: "/production/settings" },
  ],
  routes: productionRoutes,
  moved: [],
};
