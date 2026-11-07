/**
 * Where Production lives on HBA's domain (ADR 0076, decision 3).
 *
 * Its screens still think in their own addresses ("/suppliers"); the page is
 * served under `/production-app/`, inside HBA's frame at `/production/`. These
 * turn one into the other, and tell the frame when the address changes so the
 * address bar shows `/production/suppliers`.
 */
export const APP_BASE = "/production-app";

/** "/production-app/suppliers" → "/suppliers". */
export function appPath(pathname: string): string {
  if (pathname === APP_BASE || pathname === `${APP_BASE}/`) return "/";
  return pathname.startsWith(`${APP_BASE}/`) ? pathname.slice(APP_BASE.length) : pathname || "/";
}

/** "/suppliers" → "/production-app/suppliers". */
export function appUrl(path: string): string {
  return path === "/" ? `${APP_BASE}/` : `${APP_BASE}${path}`;
}

/** A file from `public/`, at its served address. */
export function appAsset(path: string): string {
  return `${APP_BASE}${path}`;
}

/** Tells HBA's frame which Production address is showing. */
export function announcePath(path: string) {
  if (window.parent !== window) {
    window.parent.postMessage({ type: "production:path", path }, window.location.origin);
  }
}
