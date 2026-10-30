import { Navigate, Route } from "react-router-dom";

import type { Department } from "../types";
import { OperationsDashboard } from "./OperationsDashboard";
import { OPERATIONS_SECTIONS } from "./sections";

export { OPERATIONS_SECTIONS };

/** Sections that read from a source whose freshness the sidebar watches. */
const SOURCES = new Set(["shopify", "bosta", "estebdal"]);

/**
 * Operations (ADR 0057), for the operations manager and for whoever else
 * holds `order_ops.view`. `/operations` opens on Shopify.
 */
export const operations: Department = {
  key: "operations",
  name: "Operations",
  icon: "truck",
  holds: "order_ops.view",
  base: "/operations",
  sections: OPERATIONS_SECTIONS.map((section) => ({
    slug: section.slug,
    label: section.label,
    to: `/operations/${section.slug}`,
    alert: SOURCES.has(section.slug) ? section.slug : undefined,
  })),
  routes: () => (
    <>
      <Route index element={<Navigate to="shopify" replace />} />
      <Route path=":tab" element={<OperationsDashboard />} />
    </>
  ),
  moved: [],
};
