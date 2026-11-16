// @vitest-environment jsdom
/**
 * Where a factory's own login lands (batch 6b). It holds no permission, like a
 * model, so a rule that read only permissions would have sent it to a model's
 * portal. It is told apart by what the server says the account is, goes to
 * `/factory` and nowhere else, and a staff member or a model never reaches
 * `/factory`.
 */
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import App from "../App";
import { deskFor } from "../lib/api";
import type { Session } from "../lib/api";
import { factorySession } from "../factory/__tests__/fixtures";
import { asked, reply, serve, sessionOf } from "./frameHarness";

beforeEach(() => window.history.pushState({}, "", "/"));
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

/** The factory's session, and the one call its list makes. */
function serveFactory(address: string) {
  window.history.pushState({}, "", address);
  const requested: string[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
      requested.push(url);
      if (url.endsWith("/api/auth/me")) return reply(200, factorySession());
      if (url.endsWith("/api/factory/orders")) return reply(200, { orders: [] });
      return reply(403, { detail: "Not for you." });
    }),
  );
  return requested;
}

describe("deskFor, with the factory", () => {
  it("gives a factory account its own desk, ahead of the permission rule that would make it a model's", () => {
    expect(factorySession().permissions).toEqual([]);
    expect(deskFor(factorySession())).toBe("factory");
  });

  it("leaves staff and models where they were", () => {
    expect(deskFor(sessionOf("owner"))).toBe("staff");
    expect(deskFor(sessionOf("production_staff"))).toBe("staff");
    expect(deskFor(sessionOf("model"))).toBe("portal");
    const notFactory: Session = { ...sessionOf("model"), actor: { ...sessionOf("model").actor, is_factory: false } };
    expect(deskFor(notFactory)).toBe("portal");
  });
});

describe("a factory account", () => {
  it("lands on its orders, with no frame, no departments and no staff call", async () => {
    const requested = serveFactory("/");
    render(<App />);

    expect(await screen.findByRole("heading", { level: 1, name: "Your orders" })).toBeTruthy();
    await waitFor(() => expect(window.location.pathname).toBe("/factory"));
    expect(screen.queryByRole("navigation", { name: "Departments" })).toBeNull();
    expect(requested.some((url) => url.includes("/api/today") || url.includes("/api/staff") || url.includes("/api/me/"))).toBe(false);
  });

  it.each(["/production/orders", "/settings", "/affiliates/overview", "/orders", "/you", "/sign-in", "/factory/nonsense"])(
    "is sent from %s to /factory",
    async (address) => {
      serveFactory(address);
      render(<App />);

      expect(await screen.findByRole("heading", { level: 1, name: "Your orders" })).toBeTruthy();
      await waitFor(() => expect(window.location.pathname).toBe("/factory"));
    },
  );

  it("reaches one of its orders at its own address", async () => {
    serveFactory("/factory/orders/2");
    render(<App />);
    // The stub refuses the order; the point is that the order screen, not the list, was reached.
    expect((await screen.findByRole("alert")).textContent).toBe("Not for you.");
    expect(window.location.pathname).toBe("/factory/orders/2");
    expect(screen.getByRole("link", { name: "← Your orders" })).toBeTruthy();
  });
});

describe("staff and models never see /factory", () => {
  it("shows an owner who opens it the staff frame's own page for an address that is not hers, and asks nothing of the factory", async () => {
    window.history.pushState({}, "", "/factory");
    serve(sessionOf("owner"));
    render(<App />);

    await screen.findByRole("navigation", { name: "Departments" });
    expect(screen.queryByRole("heading", { name: "Your orders" })).toBeNull();
    expect(asked().some((url) => url.includes("/api/factory"))).toBe(false);
  });

  it("keeps a model in her portal at /factory", async () => {
    window.history.pushState({}, "", "/factory");
    serve(sessionOf("model"));
    render(<App />);

    await screen.findByRole("alert");
    expect(window.location.pathname).toBe("/factory");
    expect(screen.queryByRole("heading", { name: "Your orders" })).toBeNull();
    expect(asked().some((url) => url.includes("/api/factory"))).toBe(false);
  });
});
