import { Navigate, Route } from "react-router-dom";

import type { Session } from "../lib/api";
import { FactoryLayout } from "./FactoryLayout";
import { FactoryOrderScreen } from "./FactoryOrder";
import { FactoryOrders } from "./FactoryOrders";

/** The only address a factory account has. */
export const FACTORY_HOME = "/factory";

/**
 * The factory's screens (batch 6b): its own orders and one order. Every other
 * address goes home to the list, so a factory account never lands on a screen
 * built for staff or for a model, and never sees the staff frame.
 */
export function factoryRoutes(session: Session) {
  return (
    <Route element={<FactoryLayout session={session} />}>
      <Route path={FACTORY_HOME} element={<FactoryOrders />} />
      <Route path={`${FACTORY_HOME}/orders/:id`} element={<FactoryOrderScreen />} />
      <Route path="*" element={<Navigate to={FACTORY_HOME} replace />} />
    </Route>
  );
}
