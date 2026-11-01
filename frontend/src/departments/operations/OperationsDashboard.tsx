import { Navigate, useParams } from "react-router-dom";

import { OPERATIONS_SECTIONS } from "./sections";
import { OperationsBosta } from "./OperationsBosta";
import { OperationsEstebdal } from "./OperationsEstebdal";
import { OperationsKhazenly } from "./OperationsKhazenly";
import { OperationsShopify } from "./OperationsShopify";
import { OperationsWhatsApp } from "./OperationsWhatsApp";

/**
 * Operations: one tab each for Shopify, Bosta and E-stebdal (ADR 0057),
 * WhatsApp (ADR 0059) and Khazenly (ADR 0071).
 *
 * The tab is the address (`/operations/<slug>`); anything else lands on
 * the first tab this person sees - Shopify, or for customer service, who
 * see Khazenly alone (ADR 0072), Khazenly.
 */
export function OperationsDashboard({ slugs }: { slugs: readonly string[] }) {
  const { tab } = useParams();
  const section = OPERATIONS_SECTIONS.find((candidate) => candidate.slug === tab && slugs.includes(candidate.slug));
  if (!section) return <Navigate to={`/operations/${slugs[0] ?? "shopify"}`} replace />;

  if (section.slug === "bosta") return <OperationsBosta />;
  if (section.slug === "estebdal") return <OperationsEstebdal />;
  if (section.slug === "whatsapp") return <OperationsWhatsApp />;
  if (section.slug === "khazenly") return <OperationsKhazenly />;
  return <OperationsShopify />;
}
