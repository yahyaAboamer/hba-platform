import { Route } from "react-router-dom";

import type { Department } from "../types";
import { ProductionScreens } from "./ProductionScreens";

/**
 * Production (ADR 0069, ADR 0076): its own screens, in its own look, inside
 * HBA's frame. It has its own sidebar, so HBA's row for it is a link and has
 * no sections; while it is open HBA's sidebar is the narrow strip.
 */
export const production: Department = {
  key: "production",
  name: "Production",
  icon: "scissors",
  holds: "production.view",
  base: "/production",
  sections: [],
  own: true,
  routes: () => (
    <>
      <Route index element={<ProductionScreens />} />
      <Route path="*" element={<ProductionScreens />} />
    </>
  ),
  moved: [],
};
