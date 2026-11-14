import { Route } from "react-router-dom";

import type { Department } from "../types";
import { productionNextRoutes } from "./next/routes";
import { ProductionScreens } from "./ProductionScreens";

/**
 * Production (ADR 0069, ADR 0076): its own screens, in its own look, inside
 * HBA's frame. It has its own sidebar, so HBA's row for it is a link and has
 * no sections; while it is open HBA's sidebar is the narrow strip.
 *
 * `/production/next/*` is the rebuilt Production (ADR 0084), native screens in
 * the platform's own look; everything else is still the frame until the
 * switch-over batch.
 */
export const production: Department = {
  key: "production",
  name: "Production",
  icon: "scissors",
  holds: "production.view",
  base: "/production",
  sections: [],
  own: true,
  routes: (session) => (
    <>
      {/* Native screens (ADR 0084) ahead of the frame's catch-all. */}
      {productionNextRoutes(session)}
      <Route index element={<ProductionScreens />} />
      <Route path="*" element={<ProductionScreens />} />
    </>
  ),
  moved: [],
};
