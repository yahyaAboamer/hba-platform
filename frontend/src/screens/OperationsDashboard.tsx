import { Navigate, useParams } from "react-router-dom";

import { NotBuiltYet } from "../components/NotBuiltYet";
import { OPERATIONS_SECTIONS } from "../components/OperationsLayout";
import { OperationsEstebdal } from "./OperationsEstebdal";
import { OperationsShopify } from "./OperationsShopify";

/**
 * Operations: one tab each for Shopify, Bosta and E-stebdal (ADR 0057).
 *
 * The cards arrive tab by tab (`.claude/plans/operations-dashboard.plan.md`):
 * Shopify and E-stebdal are built; until Bosta is, it says so
 * outright rather than drawing an empty dashboard that could be read as
 * "nothing waiting".
 */
const COMING: Record<string, { phase: string; what: string }> = {
  bosta: {
    phase: "phase 5 of the operations build",
    what: "Orders waiting for pickup, not printed, awaiting your action or late in delivery, the last seven days of pickups, and the success rate for any range.",
  },
};

export function OperationsDashboard() {
  const { tab } = useParams();
  const section = OPERATIONS_SECTIONS.find((candidate) => candidate.slug === tab);
  if (!section) return <Navigate to="/operations/shopify" replace />;

  if (section.slug === "shopify") return <OperationsShopify />;
  if (section.slug === "estebdal") return <OperationsEstebdal />;

  const coming = COMING[section.slug];
  return <NotBuiltYet title={section.label} phase={coming.phase} what={coming.what} />;
}
