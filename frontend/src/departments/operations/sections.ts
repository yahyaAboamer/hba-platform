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
