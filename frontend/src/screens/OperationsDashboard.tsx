import { Navigate, useParams } from "react-router-dom";

import { NotBuiltYet } from "../components/NotBuiltYet";
import { OPERATIONS_SECTIONS } from "../components/OperationsLayout";

/**
 * Operations: one tab each for Shopify, Bosta and E-stebdal (ADR 0057).
 *
 * The cards arrive tab by tab in the next phases of the build plan
 * (`.claude/plans/operations-dashboard.plan.md`); until then each tab says so
 * outright rather than drawing an empty dashboard that could be read as
 * "nothing waiting".
 */
const COMING: Record<string, { phase: string; what: string }> = {
  shopify: {
    phase: "phase 3 of the operations build",
    what: "Open orders not shipped yet, counted by their tags - confirmed, no answer, WhatsApp, Bosta sync failed, compression and cancelled - each opening its list of orders.",
  },
  estebdal: {
    phase: "phase 4 of the operations build",
    what: "Return and exchange requests waiting for review, each opening in E-stebdal.",
  },
  bosta: {
    phase: "phase 5 of the operations build",
    what: "Orders waiting for pickup, not printed, awaiting your action or late in delivery, the last seven days of pickups, and the success rate for any range.",
  },
};

export function OperationsDashboard() {
  const { tab } = useParams();
  const section = OPERATIONS_SECTIONS.find((candidate) => candidate.slug === tab);
  if (!section) return <Navigate to="/operations/shopify" replace />;

  const coming = COMING[section.slug];
  return <NotBuiltYet title={section.label} phase={coming.phase} what={coming.what} />;
}
