// @vitest-environment jsdom
/**
 * Who reaches the Inbox, and what else they can reach (ADR 0059; ADR 0068).
 *
 * Customer service holds the Inbox and nothing else. The operations manager
 * holds it beside Operations; the admin holds every department.
 */
import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import App from "../App";
import { asked, serve, sessionOf } from "./frameHarness";

beforeEach(() => window.history.pushState({}, "", "/"));
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const sidebar = () => screen.getByRole("navigation", { name: "Departments" });
const names = () =>
  within(sidebar())
    .getAllByRole("button")
    .map((row) => row.querySelector(".frame__dept-name")?.textContent);

describe("customer service", () => {
  it("starts on Chats, with the Inbox's two sections", async () => {
    serve(sessionOf("customer_service"));
    render(<App />);

    expect(await screen.findByRole("heading", { name: "Chats" })).toBeTruthy();
    expect(window.location.pathname).toBe("/inbox/chats");
    const links = within(sidebar()).getAllByRole("link");
    expect(links.map((link) => link.getAttribute("href"))).toEqual(["/inbox/chats", "/inbox/confirmations"]);
    expect(links[0].getAttribute("aria-current")).toBe("page");
  });

  it("holds one department, so sees nothing of the others and asks them nothing", async () => {
    serve(sessionOf("customer_service"));
    render(<App />);
    await screen.findByRole("heading", { name: "Chats" });

    for (const name of ["Operations", "Affiliates"]) {
      expect(screen.queryByRole("button", { name })).toBeNull();
    }
    for (const name of ["Shopify", "Models", "Payments", "Settings"]) {
      expect(screen.queryByRole("link", { name })).toBeNull();
    }
    const strayed = asked().filter(
      (url) =>
        url.includes("/api/affiliates") || url.includes("/api/operations/") || url.includes("/api/order-ops"),
    );
    expect(strayed).toEqual([]);
  });

  it("is told an address outside the Inbox is not hers, inside the frame", async () => {
    window.history.pushState({}, "", "/payments");
    serve(sessionOf("customer_service"));
    render(<App />);

    expect(await screen.findByRole("heading", { name: "Not available" })).toBeTruthy();
    expect(window.location.pathname).toBe("/affiliates/payments");
    expect(screen.getByText(/This page is in Affiliates, which your access does not include\./)).toBeTruthy();
    expect(screen.getByRole("link", { name: "Go to your start" }).getAttribute("href")).toBe("/inbox/chats");
    expect(sidebar()).toBeTruthy();
  });

  it("sees how many chats are unread beside Chats", async () => {
    serve(sessionOf("customer_service"));
    render(<App />);

    const chats = await screen.findByRole("link", { name: /^Chats/ });
    await within(chats).findByText("4");
    expect(chats.textContent).toContain("4 chats waiting for a reply");
  });

  it("reaches Confirmations", async () => {
    window.history.pushState({}, "", "/inbox/confirmations");
    serve(sessionOf("customer_service"));
    render(<App />);

    expect(await screen.findByRole("heading", { name: "Confirmations" })).toBeTruthy();
  });
});

describe("the operations manager", () => {
  it("holds Operations and the Inbox, and no further", async () => {
    window.history.pushState({}, "", "/operations/whatsapp");
    serve(sessionOf("operations_manager"));
    render(<App />);

    await screen.findByRole("heading", { name: "WhatsApp" });
    expect(names()).toEqual(["Inbox", "Operations"]);
    expect(screen.queryByRole("button", { name: /Affiliates/ })).toBeNull();
  });

  it("reaches the Inbox, and Operations is one press away", async () => {
    window.history.pushState({}, "", "/inbox/confirmations");
    serve(sessionOf("operations_manager"));
    render(<App />);

    expect(await screen.findByRole("heading", { name: "Confirmations" })).toBeTruthy();
    expect(screen.getByRole("button", { name: /^Operations/ }).getAttribute("aria-expanded")).toBe("false");
  });
});

describe("the admin", () => {
  it("holds all three departments, the Inbox first", async () => {
    window.history.pushState({}, "", "/inbox/confirmations");
    serve(sessionOf("owner"));
    render(<App />);

    await screen.findByRole("heading", { name: "Confirmations" });
    expect(names()).toEqual(["Inbox", "Operations", "Affiliates"]);
    expect(within(sidebar()).getAllByRole("button")[0].getAttribute("aria-expanded")).toBe("true");
    expect(screen.getByRole("link", { name: "Confirmations" }).getAttribute("aria-current")).toBe("page");
  });
});

describe("the other managers", () => {
  it("have no way into the Inbox", async () => {
    window.history.pushState({}, "", "/inbox/chats");
    serve(sessionOf("affiliate_manager"));
    render(<App />);

    expect(await screen.findByRole("heading", { name: "Not available" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: /Inbox/ })).toBeNull();
    expect(screen.queryByRole("heading", { name: "Chats" })).toBeNull();
    await waitFor(() => expect(asked().length).toBeGreaterThan(0));
    expect(asked().filter((url) => url.includes("/api/inbox"))).toEqual([]);
  });
});
