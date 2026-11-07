/**
 * Production's entry (ADR 0076). Not part of the screens ChatGPT wrote: it
 * does what their Next.js page and server used to do before the first draw.
 *
 * 1. Outside HBA's frame, go to the framed address instead.
 * 2. Ask who is signed in. Production uses HBA's sign-in (ADR 0076,
 *    decision 4): without an HBA session, or without Production access, the
 *    person is sent to HBA's start page, which signs them in or lands them
 *    where they belong.
 * 3. Load the fixed content into the lists the screens import.
 * 4. Give every write HBA's CSRF token (below).
 * 5. Draw the screens, unchanged.
 */
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { HbaApp } from "@/components/hba-app";
import { applyFixtures } from "@/lib/demo-data";
import { applyFixtureTexts } from "@/lib/fixtures";
import { appPath } from "@/lib/base-path";
import "./fonts.css";
import "./globals.css";

/**
 * HBA refuses a write without its CSRF token (`app/shared/api/deps.py`).
 * Production's screens call `fetch` themselves, so every same-origin write
 * gets the token here, read as HBA's own client reads it
 * (`frontend/src/lib/api.ts`): the `hba_csrf` cookie, else the tab's copy.
 */
function csrfToken(): string | null {
  for (const part of document.cookie.split(";")) {
    const entry = part.trim();
    if (entry.startsWith("hba_csrf=")) return decodeURIComponent(entry.slice("hba_csrf=".length)) || null;
  }
  try {
    return sessionStorage.getItem("hba.csrf");
  } catch {
    return null;
  }
}

const send = window.fetch.bind(window);
window.fetch = (input: RequestInfo | URL, init: RequestInit = {}) => {
  const method = (init.method ?? (input instanceof Request ? input.method : "GET")).toUpperCase();
  const url = new URL(input instanceof Request ? input.url : String(input), window.location.href);
  const token = csrfToken();
  if (method !== "GET" && method !== "HEAD" && url.origin === window.location.origin && token) {
    const headers = new Headers(init.headers ?? (input instanceof Request ? input.headers : undefined));
    headers.set("x-csrf-token", token);
    return send(input, { ...init, headers });
  }
  return send(input, init);
};

function leave(to: string) {
  (window.top ?? window).location.replace(to);
}

async function start() {
  if (window.top === window) {
    leave(`/production${appPath(window.location.pathname) === "/" ? "" : appPath(window.location.pathname)}${window.location.search}`);
    return;
  }
  const session = await fetch("/api/production/session", { cache: "no-store" });
  if (session.status === 401 || session.status === 403) {
    leave("/");
    return;
  }
  const { user } = (await session.json()) as { user: { name: string; username: string } };
  const fixtures = await fetch("/api/production/fixtures", { cache: "no-store" });
  if (fixtures.ok) {
    const data = (await fixtures.json()) as { lists: Record<string, unknown>; texts: Record<string, string>; textLists: Record<string, string[]> };
    applyFixtures(data.lists);
    applyFixtureTexts(data);
  }
  createRoot(document.getElementById("root")!).render(
    <StrictMode>
      <HbaApp userName={user.name} userEmail={user.username} />
    </StrictMode>,
  );
}

void start();
