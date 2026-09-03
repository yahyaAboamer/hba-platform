import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

// Self-hosted, so a month-end tool does not depend on a font CDN being up.
// ADR 0027: two faces from one superfamily, drawn together.
import "@fontsource/ibm-plex-sans/400.css";
import "@fontsource/ibm-plex-sans/500.css";
import "@fontsource/ibm-plex-sans/600.css";
import "@fontsource/ibm-plex-mono/400.css";
import "@fontsource/ibm-plex-mono/500.css";
// Inter, for the affiliate portal alone (`portal.css` scopes it to
// `.affiliate`). It is the face the redesign was drawn in, and it replaced
// Fraunces - the portal's old serif display face - which nothing asks for any
// more now that headings carry weight and size rather than a second voice.
//
// Self-hosted like the rest, for the same reason: latin only, three weights,
// and no third-party request on a phone opening this over Egyptian mobile
// data.
import "@fontsource/inter/latin-400.css";
import "@fontsource/inter/latin-500.css";
import "@fontsource/inter/latin-600.css";

import "./styles/tokens.css";
import "./styles/base.css";
// Scoped to `.affiliate`, so no maintainer screen can be reached by it.
import "./styles/portal.css";
// The whole brand decision, in eight declarations. Loaded after `portal.css`
// so the accent it defines is available to every rule that consumes it.
import "./styles/portal-accent.css";
import "./screens/Overview.css";
import "./screens/Affiliates.css";
import "./screens/AffiliateDetail.css";
import App from "./App";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
