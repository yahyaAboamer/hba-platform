/**
 * Operations' five sections (ADR 0057; the approved mockup
 * `docs/design/operations-dashboard-2026-10-03.html`. WhatsApp is the fourth,
 * ADR 0059 and `docs/design/whatsapp-inbox-2026-10-11.html`, frame 4;
 * Khazenly the fifth, ADR 0071, with no frame of its own). The
 * slug is the address and what the dashboard reads to know which tab is open.
 */
export const OPERATIONS_SECTIONS = [
  { slug: "shopify", label: "Shopify" },
  { slug: "bosta", label: "Bosta" },
  { slug: "estebdal", label: "E-stebdal" },
  { slug: "whatsapp", label: "WhatsApp" },
  // Customer service holds this one section and nothing else of Operations
  // (ADR 0072).
  { slug: "khazenly", label: "Khazenly", holds: "khazenly.use" },
] as const;
