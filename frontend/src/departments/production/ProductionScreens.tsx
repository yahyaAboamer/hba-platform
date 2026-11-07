import { useEffect, useRef, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";

/** Where Production's own build is served (`app/main.py`, `production-ui/`). */
export const APP_BASE = "/production-app";

/** "/production/suppliers?x=1" → "/production-app/suppliers?x=1". */
export function appSource(pathname: string, search: string): string {
  const rest = pathname.replace(/^\/production/, "") || "/";
  return `${APP_BASE}${rest}${search}`;
}

/**
 * Production's screens, exactly as they are, in a frame of their own
 * (ADR 0076, decision 6): a separate document, so its styles and HBA's can
 * never reach each other. It tells this page when its address changes, and
 * the address bar follows (`/production/suppliers`) without reloading it.
 */
export function ProductionScreens() {
  const { pathname, search } = useLocation();
  const navigate = useNavigate();
  const wanted = appSource(pathname, search);
  const [source, setSource] = useState(wanted);
  // The address Production last said it was showing.
  const shown = useRef(wanted);

  useEffect(() => {
    function onMessage(event: MessageEvent) {
      if (event.origin !== window.location.origin) return;
      const data = event.data as { type?: string; path?: string } | null;
      if (data?.type !== "production:path" || typeof data.path !== "string" || !data.path.startsWith("/")) return;
      shown.current = `${APP_BASE}${data.path}`;
      navigate(`/production${data.path === "/" ? "" : data.path}`, { replace: true });
    }
    window.addEventListener("message", onMessage);
    return () => window.removeEventListener("message", onMessage);
  }, [navigate]);

  // Moved here from outside Production (the strip, a link): show that address.
  useEffect(() => {
    if (wanted.split("?")[0] !== shown.current.split("?")[0]) {
      shown.current = wanted;
      setSource(wanted);
    }
  }, [wanted]);

  return <iframe className="frame__production" title="Production" src={source} />;
}
