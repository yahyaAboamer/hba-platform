import { Navigate, Route, useParams } from "react-router-dom";

import { Onward } from "../../../frame/Onward";
import type { Session } from "../../../lib/api";
import { IncomingScreen } from "./IncomingScreen";
import { LibraryList } from "./LibraryList";
import { LibraryPage } from "./LibraryPage";
import { NewOrder } from "./NewOrder";
import { OrderList } from "./OrderList";
import { OrderPage } from "./OrderPage";
import { OverviewScreen } from "./OverviewScreen";
import { PaymentScreen } from "./PaymentScreen";
import { ProductionLayout } from "./ProductionLayout";
import { StageDays } from "./StageDays";
import { SupplierPage } from "./SupplierPage";
import { SupplierScreen } from "./SupplierScreen";
import { TaskScreen } from "./TaskScreen";

/**
 * The pages of the old framed Production (`production-ui`, retired in the
 * switch-over, ADR 0085) and the nearest page each has now: orders to Orders,
 * tasks, samples and problems to Tasks, receiving to Incoming, suppliers to
 * Suppliers, products to the Library, and every other page (costs, reports, ...) to the
 * Overview. Bookmarks and emails keep working; nothing of the old app is left
 * to answer them. `suppliers`, `suppliers/:code`, `payments` and `settings` exist here
 * too, so they are screens and not in this list.
 */
export const OLD_PAGES: Readonly<Record<string, string>> = {
  "production-orders": "orders",
  "drop-phases": "orders",
  "production-tracker": "orders",
  "production-kanban": "orders",
  "production-calendar": "orders",
  "production-timeline": "orders",
  "production-tasks": "tasks",
  samples: "tasks",
  problems: "tasks",
  "warehouse-receiving": "incoming",
  "supplier-portal": "suppliers",
  dashboard: "overview",
  login: "overview",
  products: "library",
  materials: "overview",
  bom: "overview",
  "route-templates": "overview",
  "quality-control": "overview",
  costs: "overview",
  reports: "overview",
  notifications: "overview",
  documents: "overview",
  users: "overview",
  "audit-logs": "overview",
};

/** `/production/next/<page>`: the same page without `next`. */
function NextOnward() {
  const rest = useParams()["*"] ?? "";
  return <Onward to={`/production/${rest || "overview"}`} />;
}

/**
 * Production's screens (ADR 0084, 0085), at `/production/*`: Overview,
 * Orders, Tasks, Incoming, Suppliers and Stage days, with the order and
 * supplier pages under them. The old addresses (`/production/next/*`, the
 * framed app's pages) go on to the same or the nearest page.
 */
export function productionRoutes(session: Session) {
  return (
    <>
      <Route path="next" element={<Onward to="/production/overview" />} />
      <Route path="next/*" element={<NextOnward />} />
      {Object.entries(OLD_PAGES).map(([from, to]) => (
        <Route key={from} path={`${from}/*`} element={<Onward to={`/production/${to}`} />} />
      ))}
      <Route element={<ProductionLayout />}>
        <Route index element={<Navigate to="overview" replace />} />
        <Route path="overview" element={<OverviewScreen session={session} />} />
        <Route path="orders" element={<OrderList session={session} />} />
        <Route path="orders/new" element={<NewOrder session={session} />} />
        <Route path="orders/:id" element={<OrderPage session={session} />} />
        <Route path="tasks" element={<TaskScreen session={session} />} />
        <Route path="library" element={<LibraryList session={session} />} />
        <Route path="library/:id" element={<LibraryPage session={session} />} />
        <Route path="incoming" element={<IncomingScreen session={session} />} />
        <Route path="suppliers" element={<SupplierScreen session={session} />} />
        <Route path="suppliers/:id" element={<SupplierPage session={session} />} />
        <Route path="payments" element={<PaymentScreen session={session} />} />
        <Route path="settings" element={<StageDays session={session} />} />
      </Route>
    </>
  );
}
