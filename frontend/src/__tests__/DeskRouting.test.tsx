// @vitest-environment jsdom
/**
 * Where a person lands is decided by what they may do, never by a role's name
 * (ADR 0067, decision 9), and what they get is the one frame with the
 * departments they hold (ADR 0068).
 *
 * Every role that existed before several roles per person must land exactly
 * where it did then; a person holding two roles gets the departments of both;
 * and a role's name, whatever it says, changes nothing.
 */
import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import App from "../App";
import { deskFor, roleLabel } from "../lib/api";
import { HELD, asked, serve, sessionOf } from "./frameHarness";
import type { Kind } from "./frameHarness";

beforeEach(() => window.history.pushState({}, "", "/"));
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

/** The department rows in the sidebar, in order, with whether each is open. */
function departments(): [string, boolean][] {
  const nav = screen.getByRole("navigation", { name: "Departments" });
  return within(nav)
    .getAllByRole("button")
    .map((row) => [
      row.querySelector(".frame__dept-name")?.textContent ?? "",
      row.getAttribute("aria-expanded") === "true",
    ]);
}

describe("deskFor", () => {
  it("gives every role with a staff permission the frame, and a model her portal", () => {
    for (const kind of Object.keys(HELD) as Kind[]) {
      expect(deskFor(sessionOf(kind)), kind).toBe(kind === "model" ? "portal" : "staff");
    }
  });

  it("never reads a role's name", () => {
    // Names that would once have chosen another tree change nothing.
    const named = (roles: string[], permissions: string[]) => ({
      ...sessionOf("model"),
      actor: { ...sessionOf("model").actor, roles },
      permissions,
    });
    expect(deskFor(named(["operations_manager"], [...HELD.content_manager.permissions]))).toBe("staff");
    expect(deskFor(named(["admin"], []))).toBe("portal");
    expect(deskFor(named(["affiliate"], ["inbox.use"]))).toBe("staff");
  });

  it("gives a model, and somebody invited to become one, the portal", () => {
    expect(deskFor(sessionOf("model"))).toBe("portal");
    expect(deskFor({ ...sessionOf("model"), actor: { ...sessionOf("model").actor, roles: [] } })).toBe("portal");
  });

  it("names a person by the widest role they hold", () => {
    expect(roleLabel(sessionOf("operations_manager").actor)).toBe("operations manager");
    expect(roleLabel({ ...sessionOf("model").actor, roles: [] })).toBe("");
  });
});

describe("each kind of person: the departments they hold, and where they start", () => {
  const cases: [Kind, [string, boolean][], string][] = [
    ["owner", [["Inbox", false], ["Operations", false], ["Affiliates", true]], "/affiliates/overview"],
    ["affiliate_manager", [["Affiliates", true]], "/affiliates/overview"],
    ["content_manager", [["Affiliates", true]], "/affiliates/overview"],
    ["operations_manager", [["Inbox", false], ["Operations", true]], "/operations/shopify"],
    ["operations_only", [["Operations", true]], "/operations/shopify"],
    ["customer_service", [["Inbox", true]], "/inbox/chats"],
  ];

  it.each(cases)("%s", async (kind, rows, start) => {
    serve(sessionOf(kind));
    render(<App />);

    await screen.findByRole("navigation", { name: "Departments" });
    await waitFor(() => expect(window.location.pathname).toBe(start));
    await waitFor(() => expect(departments()).toEqual(rows));
  });
});

describe("a person holding two roles", () => {
  it("is offered the Inbox beside the affiliate side", async () => {
    serve({ ...sessionOf("content_manager"), permissions: [...HELD.content_manager.permissions, "inbox.use"] });
    render(<App />);

    await screen.findByRole("navigation", { name: "Departments" });
    expect(departments().map(([name]) => name)).toEqual(["Inbox", "Affiliates"]);
  });

  it("reaches the Inbox at its own address", async () => {
    window.history.pushState({}, "", "/inbox/confirmations");
    serve({ ...sessionOf("content_manager"), permissions: [...HELD.content_manager.permissions, "inbox.use"] });
    render(<App />);

    expect(await screen.findByRole("heading", { name: "Confirmations" })).toBeTruthy();
  });
});

describe("the operations manager, now two roles", () => {
  it("still starts on Operations and asks the affiliate side nothing", async () => {
    serve(sessionOf("operations_manager"));
    render(<App />);

    expect(await screen.findByRole("heading", { name: "Shopify" })).toBeTruthy();
    expect(window.location.pathname).toBe("/operations/shopify");
    expect(
      asked().filter((url) => url.includes("/api/affiliates") || url.endsWith("/api/operations/counts")),
    ).toEqual([]);
  });
});

describe("a model", () => {
  it.each(["/payments", "/targets"])("stays in her portal at %s, whatever staff addresses are", async (address) => {
    // Links in the emails she is sent: her portal's own addresses.
    window.history.pushState({}, "", address);
    serve(sessionOf("model"));
    render(<App />);

    await screen.findByRole("alert");
    expect(window.location.pathname).toBe(address);
    expect(screen.queryByRole("navigation", { name: "Departments" })).toBeNull();
  });
});
