import { Navigate, Route } from "react-router-dom";

import { can } from "../../lib/api";
import type { Department } from "../types";
import { OperationsDashboard } from "./OperationsDashboard";
import { OPERATIONS_SECTIONS } from "./sections";

export { OPERATIONS_SECTIONS };

/** Sections that read from a source whose freshness the sidebar watches. */
const SOURCES = new Set(["shopify", "bosta", "estebdal"]);

/**
 * Operations (ADR 0057), for the operations manager and for whoever else
 * holds `order_ops.view`. `/operations` opens on Shopify. Customer service
 * holds its Khazenly section alone (`khazenly.use`, ADR 0072), and opens on it.
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
    holds: "holds" in section ? section.holds : undefined,
  })),
  routes: (session) => {
    // Every tab with `order_ops.view`; otherwise only those whose own
    // permission they hold (as `departmentsFor` shows them).
    const slugs = OPERATIONS_SECTIONS.filter(
      (section) => can(session, "order_ops.view") || ("holds" in section && can(session, section.holds)),
    ).map((section) => section.slug);
    return (
      <>
        <Route index element={<Navigate to={slugs[0] ?? "shopify"} replace />} />
        <Route path=":tab" element={<OperationsDashboard slugs={slugs} />} />
      </>
    );
  },
  moved: [],
};
