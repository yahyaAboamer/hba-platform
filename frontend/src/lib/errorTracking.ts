/**
 * Reports uncaught browser errors to Sentry, and only when the server says to.
 *
 * **Off unless the server provides a DSN.** The page asks
 * `GET /api/client-config` (same origin, no sign-in) for the DSN, the
 * environment and the release. No DSN, a failed request or a non-200 answer
 * all mean the same thing - do nothing - so a local checkout, the test
 * database and a Sentry-less deployment send nothing anywhere, and nothing
 * here can stop the app from drawing.
 *
 * **The SDK is loaded only when it will be used.** It is a dynamic import
 * after the DSN arrives, so a deployment with tracking off does not carry it
 * in the main bundle, and the first render never waits for any of this.
 *
 * ## What is scrubbed, and why
 *
 * `/reset-password?token=...` and `/accept-invitation?token=...` carry a
 * live, single-use token in the address. A report that kept the URL would be
 * a copy of a password reset link sitting in a third party's database. So
 * every URL that leaves the browser loses its query string and its
 * `#fragment` first - on the event itself and on every navigation, fetch and
 * xhr breadcrumb. The path stays: it is what tells us which screen broke.
 *
 * The event also loses `user`, cookies and headers, and console breadcrumbs
 * are dropped whole, because a `console.log` can hold anything a screen
 * happened to print (a name, an amount, a phone number).
 *
 * Error *messages* lose the same things: an address quoted inside a message
 * ("Failed to fetch /api/...?token=...") is cut at its `?` or `#`, and any
 * `token=` value is blanked. The platform does not put personal data in the
 * messages it throws; this is the lock for the day a message quotes a link.
 *
 * No tracing, no session replay and no profiling: the SDK's defaults do not
 * start them, and this module adds none of their integrations.
 */

import type { Breadcrumb, ErrorEvent } from "@sentry/react";

interface ClientConfig {
  sentry_dsn: string | null;
  environment: string | null;
  release: string | null;
}

/** Everything before the first `?` or `#`: the path, without its secrets. */
export function stripQueryAndFragment(url: string): string {
  const cut = url.search(/[?#]/);
  return cut === -1 ? url : url.slice(0, cut);
}

/**
 * The same for free text: every address quoted in it loses its query string
 * and fragment, and every `token=` value is blanked.
 */
export function scrubText(text: string): string {
  return text
    .replace(/((?:https?:\/\/|\/)[^\s?#"'<>]*)[?#][^\s"'<>]*/g, "$1")
    .replace(/(token=)[^\s&"'<>]+/gi, "$1[removed]");
}

/** Removes what must never leave the browser from an outgoing error event. */
export function scrubEvent<T extends ErrorEvent>(event: T): T {
  delete event.user;
  if (typeof event.message === "string") event.message = scrubText(event.message);
  for (const value of event.exception?.values ?? []) {
    if (value.value) value.value = scrubText(value.value);
  }
  if (event.request) {
    if (event.request.url) {
      event.request.url = stripQueryAndFragment(event.request.url);
    }
    delete event.request.query_string;
    delete event.request.cookies;
    delete event.request.headers;
  }
  return event;
}

/** Drops console breadcrumbs; strips the URLs from the rest. */
export function scrubBreadcrumb(crumb: Breadcrumb): Breadcrumb | null {
  if (crumb.category === "console") return null;
  if (crumb.message) crumb.message = scrubText(crumb.message);
  const data = crumb.data;
  if (data) {
    // navigation: from / to; fetch and xhr: url.
    for (const key of ["url", "from", "to"]) {
      if (typeof data[key] === "string") {
        data[key] = stripQueryAndFragment(data[key]);
      }
    }
  }
  return crumb;
}

/**
 * Starts error tracking if the server asked for it. Never throws, and a
 * caller need not await it.
 */
export async function initErrorTracking(): Promise<void> {
  try {
    const response = await fetch("/api/client-config", {
      credentials: "same-origin",
    });
    if (!response.ok) return;
    const config = (await response.json()) as Partial<ClientConfig>;
    if (!config.sentry_dsn) return;

    const Sentry = await import("@sentry/react");
    Sentry.init({
      dsn: config.sentry_dsn,
      environment: config.environment ?? undefined,
      release: config.release ?? undefined,
      // Version 11 replaced `sendDefaultPii` with per-category switches. All
      // off: no user, cookies, headers, query parameters or bodies. The
      // scrubbers below are the second lock on the same door.
      dataCollection: {
        userInfo: false,
        cookies: false,
        httpHeaders: false,
        httpBodies: [],
        urlQueryParams: false,
      },
      beforeSend: scrubEvent,
      beforeBreadcrumb: scrubBreadcrumb,
    });
  } catch {
    // Reporting must never be the reason a screen does not load.
  }
}
