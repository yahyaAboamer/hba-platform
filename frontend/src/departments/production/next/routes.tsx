import { Navigate, Route } from "react-router-dom";

import type { Session } from "../../../lib/api";
import { IncomingScreen } from "./IncomingScreen";
import { NewOrder } from "./NewOrder";
import { NextLayout } from "./NextLayout";
import { OrderList } from "./OrderList";
import { OrderPage } from "./OrderPage";
import { StageDays } from "./StageDays";
import { TaskScreen } from "./TaskScreen";

/**
 * Production's native screens (ADR 0084), at `/production/next/*`, beside the
 * framed Production that still answers every other address until the
 * switch-over batch. Listed before the department's catch-all route.
 */
export function productionNextRoutes(session: Session) {
  return (
    <Route path="next" element={<NextLayout />}>
      <Route index element={<Navigate to="orders" replace />} />
      <Route path="orders" element={<OrderList session={session} />} />
      <Route path="orders/new" element={<NewOrder session={session} />} />
      <Route path="orders/:id" element={<OrderPage session={session} />} />
      <Route path="tasks" element={<TaskScreen session={session} />} />
      <Route path="incoming" element={<IncomingScreen session={session} />} />
      <Route path="settings" element={<StageDays session={session} />} />
    </Route>
  );
}
