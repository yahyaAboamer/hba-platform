import type { Breadcrumb, ErrorEvent } from "@sentry/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const { init } = vi.hoisted(() => ({ init: vi.fn() }));
vi.mock("@sentry/react", () => ({ init }));

import {
  initErrorTracking,
  scrubBreadcrumb,
  scrubEvent,
  scrubText,
  stripQueryAndFragment,
} from "../errorTracking";

/**
 * **Nothing is sent unless the server provides a DSN, and a reset token never
 * leaves the browser.** `/reset-password?token=` and
 * `/accept-invitation?token=` carry live tokens, so the scrubbers are tested
 * on exactly those addresses.
 */

describe("stripQueryAndFragment", () => {
  it("keeps the path and drops the query and the fragment", () => {
    expect(stripQueryAndFragment("https://x.test/reset-password?token=abc#top")).toBe(
      "https://x.test/reset-password",
    );
    expect(stripQueryAndFragment("/accept-invitation?token=abc")).toBe("/accept-invitation");
    expect(stripQueryAndFragment("/a#frag?not-a-query")).toBe("/a");
    expect(stripQueryAndFragment("/plain")).toBe("/plain");
  });
});

describe("scrubText", () => {
  it("cuts addresses quoted in a message and blanks token values", () => {
    expect(scrubText("Failed to fetch /api/auth/password-reset/preview?token=SECRET")).toBe(
      "Failed to fetch /api/auth/password-reset/preview",
    );
    expect(scrubText("GET https://x.test/accept-invitation?token=SECRET#a failed")).toBe(
      "GET https://x.test/accept-invitation failed",
    );
    expect(scrubText("bad token=SECRET&next=1")).toBe("bad token=[removed]&next=1");
    expect(scrubText("Cannot read properties of undefined")).toBe(
      "Cannot read properties of undefined",
    );
  });
});

describe("scrubEvent", () => {
  it("scrubs the message and every exception value", () => {
    const event = {
      message: "load /reset-password?token=SECRET",
      exception: { values: [{ type: "Error", value: "GET /api/x?token=SECRET 500" }] },
    } as unknown as ErrorEvent;
    const out = scrubEvent(event);
    expect(out.message).toBe("load /reset-password");
    expect(out.exception?.values?.[0].value).toBe("GET /api/x 500");
    expect(JSON.stringify(out)).not.toContain("SECRET");
  });

  it("strips the request URL and removes user, cookies and headers", () => {
    const event = {
      user: { id: "7", email: "a@b.c" },
      request: {
        url: "https://x.test/reset-password?token=SECRET#x",
        query_string: "token=SECRET",
        cookies: { session: "s" },
        headers: { Cookie: "session=s", Authorization: "Bearer t" },
        method: "GET",
      },
    } as unknown as ErrorEvent;
    const out = scrubEvent(event);
    expect(out.request?.url).toBe("https://x.test/reset-password");
    expect(out.request?.method).toBe("GET");
    expect(out.user).toBeUndefined();
    expect(out.request?.cookies).toBeUndefined();
    expect(out.request?.headers).toBeUndefined();
    expect(out.request?.query_string).toBeUndefined();
    expect(JSON.stringify(out)).not.toContain("SECRET");
  });

  it("copes with an event that has no request or user", () => {
    expect(scrubEvent({} as ErrorEvent)).toEqual({});
  });
});

describe("scrubBreadcrumb", () => {
  it("drops console breadcrumbs entirely", () => {
    expect(scrubBreadcrumb({ category: "console", message: "phone 0100" })).toBeNull();
  });

  it("strips URLs in navigation, fetch and xhr breadcrumbs", () => {
    const nav = scrubBreadcrumb({
      category: "navigation",
      data: { from: "/login?next=1#a", to: "/accept-invitation?token=SECRET#b" },
    } as Breadcrumb);
    expect(nav?.data).toEqual({ from: "/login", to: "/accept-invitation" });

    for (const category of ["fetch", "xhr"]) {
      const out = scrubBreadcrumb({
        category,
        data: { url: "/api/auth/invitations/preview?token=SECRET", status_code: 200 },
      } as Breadcrumb);
      expect(out?.data).toEqual({
        url: "/api/auth/invitations/preview",
        status_code: 200,
      });
    }
  });

  it("passes a breadcrumb with no data through untouched", () => {
    const crumb = { category: "ui.click", message: "button" } as Breadcrumb;
    expect(scrubBreadcrumb(crumb)).toBe(crumb);
  });
});

describe("initErrorTracking", () => {
  const fetchMock = vi.fn();

  beforeEach(() => {
    init.mockReset();
    fetchMock.mockReset();
    vi.stubGlobal("fetch", fetchMock);
  });
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  const answer = (body: unknown, ok = true) =>
    fetchMock.mockResolvedValue({ ok, json: async () => body });

  it("does nothing when the server gives no DSN", async () => {
    answer({ sentry_dsn: null, environment: null, release: null });
    await initErrorTracking();
    expect(fetchMock).toHaveBeenCalledWith("/api/client-config", expect.anything());
    expect(init).not.toHaveBeenCalled();
  });

  it("does nothing, and does not throw, when the request fails", async () => {
    fetchMock.mockRejectedValue(new TypeError("offline"));
    await expect(initErrorTracking()).resolves.toBeUndefined();
    expect(init).not.toHaveBeenCalled();
  });

  it("does nothing, and does not throw, on a non-200 answer", async () => {
    answer({ sentry_dsn: "https://k@o.ingest.sentry.io/1" }, false);
    await expect(initErrorTracking()).resolves.toBeUndefined();
    expect(init).not.toHaveBeenCalled();
  });

  it("does not throw when the body is not JSON", async () => {
    fetchMock.mockResolvedValue({
      ok: true,
      json: async () => {
        throw new SyntaxError("bad json");
      },
    });
    await expect(initErrorTracking()).resolves.toBeUndefined();
    expect(init).not.toHaveBeenCalled();
  });

  it("starts Sentry with the given DSN, environment and release", async () => {
    answer({
      sentry_dsn: "https://k@o.ingest.sentry.io/1",
      environment: "staging",
      release: "abc123",
    });
    await initErrorTracking();
    expect(init).toHaveBeenCalledTimes(1);
    const options = init.mock.calls[0][0];
    expect(options).toMatchObject({
      dsn: "https://k@o.ingest.sentry.io/1",
      environment: "staging",
      release: "abc123",
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
    // No tracing, replay or profiling.
    for (const key of [
      "tracesSampleRate",
      "tracesSampler",
      "replaysSessionSampleRate",
      "replaysOnErrorSampleRate",
      "profilesSampleRate",
      "integrations",
    ]) {
      expect(options).not.toHaveProperty(key);
    }
  });
});
