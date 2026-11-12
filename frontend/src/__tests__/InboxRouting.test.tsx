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
  it("starts on Chats, with the Inbox's three sections", async () => {
    serve(sessionOf("customer_service"));
    render(<App />);

    expect(await screen.findByRole("heading", { name: "Chats" })).toBeTruthy();
    expect(window.location.pathname).toBe("/inbox/chats");
    const links = within(sidebar()).getAllByRole("link");
    expect(links.map((link) => link.getAttribute("href"))).toEqual([
      "/inbox/chats",
      "/inbox/confirmations",
      "/inbox/feedback",
    ]);
    expect(links[0].getAttribute("aria-current")).toBe("page");
  });

  it("holds the Inbox and Operations' Khazenly alone, and asks nothing else", async () => {
    serve(sessionOf("customer_service"));
    render(<App />);
    await screen.findByRole("heading", { name: "Chats" });

    // Operations shows, with its Khazenly section only (ADR 0072).
    expect(screen.queryByRole("button", { name: /^Affiliates/ })).toBeNull();
    for (const name of ["Shopify", "Models", "Payments"]) {
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

  it("sees how many unhappy customers need a follow-up beside Feedback, not added to Chats", async () => {
    serve(sessionOf("customer_service"), { followUp: 2 });
    render(<App />);

    const feedback = await screen.findByRole("link", { name: /^Feedback/ });
    await within(feedback).findByText("2");
    expect(feedback.textContent).toContain("2 customers need a follow-up");
    // Chats still counts only what waits for a reply.
    const chats = screen.getByRole("link", { name: /^Chats/ });
    await within(chats).findByText("4");
    expect(chats.textContent).not.toContain("follow-up");
  });

  it("shows a newer follow-up number at once when the chat list reads one (Resolved was pressed)", async () => {
    window.history.pushState({}, "", "/inbox/chats");
    // The sidebar's own read is 30 seconds old and says 2; the list says 1.
    serve(sessionOf("customer_service"), { followUp: 2, listFollowUp: 1 });
    render(<App />);

    const feedback = await screen.findByRole("link", { name: /^Feedback/ });
    await waitFor(() => expect(feedback.textContent).toContain("1 customer needs a follow-up"));
    expect(feedback.textContent).not.toContain("2 customers");
  });

  it("says nothing beside Feedback when nobody needs a follow-up", async () => {
    serve(sessionOf("customer_service"), { followUp: 0 });
    render(<App />);

    const chats = await screen.findByRole("link", { name: /^Chats/ });
    await within(chats).findByText("4");
    expect(screen.getByRole("link", { name: "Feedback" }).textContent).toBe("Feedback");
  });

  it("reaches Feedback", async () => {
    window.history.pushState({}, "", "/inbox/feedback");
    serve(sessionOf("customer_service"));
    render(<App />);

    expect(await screen.findByRole("heading", { name: "Feedback" })).toBeTruthy();
    expect(screen.getByRole("link", { name: /^Feedback/ }).getAttribute("aria-current")).toBe("page");
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
