import { Navigate, useParams } from "react-router-dom";

import { OPERATIONS_SECTIONS } from "./OperationsLayout";
import { OperationsBosta } from "./OperationsBosta";
import { OperationsEstebdal } from "./OperationsEstebdal";
import { OperationsShopify } from "./OperationsShopify";
import { OperationsWhatsApp } from "./OperationsWhatsApp";

/**
 * Operations: one tab each for Shopify, Bosta and E-stebdal (ADR 0057), and
 * WhatsApp (ADR 0059).
 *
 * The tab is the address (`/operations/<slug>`); anything else lands on
 * Shopify, the first of them.
 */
export function OperationsDashboard() {
  const { tab } = useParams();
  const section = OPERATIONS_SECTIONS.find((candidate) => candidate.slug === tab);
  if (!section) return <Navigate to="/operations/shopify" replace />;

  if (section.slug === "bosta") return <OperationsBosta />;
  if (section.slug === "estebdal") return <OperationsEstebdal />;
  if (section.slug === "whatsapp") return <OperationsWhatsApp />;
  return <OperationsShopify />;
}
