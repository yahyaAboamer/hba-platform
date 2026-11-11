import { Navigate, useParams } from "react-router-dom";

import { can } from "../../lib/api";
import type { Session } from "../../lib/api";
import { OPERATIONS_SECTIONS } from "./sections";
import { OperationsBosta } from "./OperationsBosta";
import { OperationsEstebdal } from "./OperationsEstebdal";
import { OperationsKhazenly } from "./OperationsKhazenly";
import { OperationsReturns } from "./OperationsReturns";
import { OperationsShopify } from "./OperationsShopify";
import { OperationsWhatsApp } from "./OperationsWhatsApp";

/**
 * Operations: one tab each for Shopify, Bosta and E-stebdal (ADR 0057),
 * WhatsApp (ADR 0059), Khazenly (ADR 0071) and Returns (ADR 0079).
 *
 * The tab is the address (`/operations/<slug>`); anything else lands on
 * the first tab this person sees - Shopify, or for customer service, who
 * see Khazenly alone (ADR 0072), Khazenly.
 *
 * Every Operations level sees every tab (ADR 0079); what changes something
 * is offered only to whoever holds its permission. The server checks again.
 */
export function OperationsDashboard({ slugs, session }: { slugs: readonly string[]; session: Session | null }) {
  const { tab } = useParams();
  const section = OPERATIONS_SECTIONS.find((candidate) => candidate.slug === tab && slugs.includes(candidate.slug));
  if (!section) return <Navigate to={`/operations/${slugs[0] ?? "shopify"}`} replace />;

  if (section.slug === "bosta") return <OperationsBosta />;
  if (section.slug === "estebdal") return <OperationsEstebdal />;
  if (section.slug === "whatsapp") return <OperationsWhatsApp />;
  if (section.slug === "khazenly") return <OperationsKhazenly canBuild={can(session, "khazenly.use")} />;
  if (section.slug === "returns") return <OperationsReturns canEdit={can(session, "returns.edit")} />;
  return <OperationsShopify />;
}
