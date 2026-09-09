import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

// Self-hosted, so a month-end tool does not depend on a font CDN being up,
// and so a phone opening this over Egyptian mobile data makes no third-party
// request. Latin only, three weights.
//
// **Inter carries both halves now** (ADR 0039). It is the face the redesign
// was drawn in, and the approved references declare it for body and heading
// alike; it used to be scoped to the portal, beside IBM Plex Sans on the
// maintainer's screens. Plex Sans is gone with that split.
import "@fontsource/inter/latin-400.css";
import "@fontsource/inter/latin-500.css";
import "@fontsource/inter/latin-600.css";
// Plex Mono stays, for the one thing it still says: ADR 0027's rule that an
// agreed figure wears a different face from a working one.
import "@fontsource/ibm-plex-mono/400.css";
import "@fontsource/ibm-plex-mono/500.css";

import "./styles/tokens.css";
import "./styles/base.css";
// Scoped to `.affiliate`, so no maintainer screen can be reached by it.
import "./styles/portal.css";
// The whole brand decision, in eight declarations. Loaded last so the accent
// it defines is available to every rule that consumes it.
import "./styles/accent.css";
import "./screens/Overview.css";
import "./screens/Affiliates.css";
import "./screens/AffiliateDetail.css";
import App from "./App";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
