import { Outlet } from "react-router-dom";

import type { Session } from "../lib/api";
import { SideShell } from "./SideShell";

/**
 * Operations' four sections (ADR 0057; the approved mockup
 * `docs/design/operations-dashboard-2026-10-03.html`. WhatsApp is the fourth,
 * ADR 0059 and `docs/design/whatsapp-inbox-2026-10-11.html`, frame 4). The
 * slug is the address and what the dashboard reads to know which tab is open.
 */
export const OPERATIONS_SECTIONS = [
  { slug: "shopify", label: "Shopify" },
  { slug: "bosta", label: "Bosta" },
  { slug: "estebdal", label: "E-stebdal" },
  { slug: "whatsapp", label: "WhatsApp" },
] as const;

const SECTIONS = OPERATIONS_SECTIONS.map((section) => ({
  to: `/operations/${section.slug}`,
  label: section.label,
}));

/**
 * The shell the operations manager signs in to, and the admin switches to:
 * Shopify, Bosta, E-stebdal and WhatsApp, and nothing else.
 */
export function OperationsLayout({ session }: { session: Session }) {
  return (
    <SideShell
      session={session}
      dashboard="operations"
      name="Operations"
      home="/operations"
      sections={SECTIONS}
    >
      <Outlet />
    </SideShell>
  );
}
