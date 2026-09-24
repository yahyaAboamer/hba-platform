import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

// Self-hosted, so a month-end tool does not depend on a font CDN being up,
// and so a phone opening this over Egyptian mobile data makes no third-party
// request. Latin only, and the four weights the approved references load
// (`Inter:wght@400;500;600;700`): without 700 a `<strong>` - which the admin
// export does use in prose - was drawn from the 600 face instead.
//
// **Inter, and only Inter** (ADR 0039). It is the face the redesign was drawn
// in, and the approved references declare it for body and heading alike.
//
// This used to be three families. IBM Plex Sans went when the two halves
// stopped looking different; IBM Plex Mono went when the business ended
// ADR 0027's rule that an agreed figure wears a different face - a signal
// nobody had told the models how to read.
import "@fontsource/inter/latin-400.css";
import "@fontsource/inter/latin-500.css";
import "@fontsource/inter/latin-600.css";
import "@fontsource/inter/latin-700.css";

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
