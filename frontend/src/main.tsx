import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

// Self-hosted, so a month-end tool does not depend on a font CDN being up.
// ADR 0027: two faces from one superfamily, drawn together.
import "@fontsource/ibm-plex-sans/400.css";
import "@fontsource/ibm-plex-sans/500.css";
import "@fontsource/ibm-plex-sans/600.css";
import "@fontsource/ibm-plex-mono/400.css";
import "@fontsource/ibm-plex-mono/500.css";

import "./styles/tokens.css";
import "./styles/base.css";
import "./screens/Overview.css";
import "./screens/Affiliates.css";
import "./screens/AffiliateDetail.css";
import App from "./App";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
