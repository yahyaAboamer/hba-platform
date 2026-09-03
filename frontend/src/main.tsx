import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

// Self-hosted, so a month-end tool does not depend on a font CDN being up.
// ADR 0027: two faces from one superfamily, drawn together.
import "@fontsource/ibm-plex-sans/400.css";
import "@fontsource/ibm-plex-sans/500.css";
import "@fontsource/ibm-plex-sans/600.css";
import "@fontsource/ibm-plex-mono/400.css";
import "@fontsource/ibm-plex-mono/500.css";
// One weight, latin only. The portal's display face carries headings and the
// single large figure and nothing else, so a second weight would be bytes
// spent on nothing - and the fallback stack is a real serif on every platform
// the models use.
import "@fontsource/fraunces/latin-600.css";

import "./styles/tokens.css";
import "./styles/base.css";
// Scoped to `.affiliate`, so no maintainer screen can be reached by it.
import "./styles/portal.css";
import "./screens/Overview.css";
import "./screens/Affiliates.css";
import "./screens/AffiliateDetail.css";
import { initTheme } from "./lib/theme";
import App from "./App";

// Re-applies the stored preference (and follows the device while Auto) — the
// inline script in index.html already painted, so this only catches up.
initTheme();
createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
