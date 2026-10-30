// @vitest-environment jsdom
/**
 * The frame (Phase 2, Batch 2.1; ADR 0068): the old addresses and where they
 * went, the pages a person is told are not theirs, and the sidebar and the
 * phone's menu as the approved mockup draws them.
 */
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import App from "../App";
import { movedAddress } from "../frame/moved";
import { DEPARTMENTS } from "../departments";
import { previewFrameFor } from "../departments/affiliates/PortalPreview";
import { serve, sessionOf } from "./frameHarness";
import type { Answers, Kind } from "./frameHarness";

beforeEach(() => window.history.pushState({}, "", "/"));
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  document.body.style.overflow = "";
});

async function open(address: string, kind: Kind = "owner", answers: Answers = {}) {
  window.history.pushState({}, "", address);
  serve(sessionOf(kind), answers);
  render(<App />);
  await screen.findByRole("navigation", { name: "Departments" });
}

const row = (name: RegExp | string) => screen.getByRole("button", { name });
const here = () => window.location.pathname + window.location.search + window.location.hash;

describe("old addresses go to their new ones, keeping the rest, the query and the hash", () => {
  const table: [string, string][] = [
    ["/affiliates", "/affiliates/overview"],
    ["/affiliates/invite?email=a%40b.c#top", "/affiliates/models/invite?email=a%40b.c#top"],
    ["/affiliates/12", "/affiliates/models/12"],
    ["/affiliates/12/compensation?month=2026-09#terms", "/affiliates/models/12/compensation?month=2026-09#terms"],
    ["/affiliates/12/payments", "/affiliates/models/12/payments"],
    ["/affiliates/12/payout-destination", "/affiliates/models/12/payout-destination"],
    ["/affiliates/12/portal", "/affiliates/models/12/portal"],
    ["/products", "/affiliates/products"],
    ["/products/track-jacket?view=promotion#x", "/affiliates/products/track-jacket?view=promotion#x"],
    ["/targets?month=2026-09", "/affiliates/targets?month=2026-09"],
    ["/payments", "/affiliates/payments"],
    ["/payments/2026-09/12/record?x=1", "/affiliates/payments/2026-09/12/record?x=1"],
    ["/payroll", "/affiliates/payroll"],
    ["/payroll/2026-09/approve#now", "/affiliates/payroll/2026-09/approve#now"],
    ["/orders", "/affiliates/orders"],
    ["/orders/1001?month=2026-09", "/affiliates/orders/1001?month=2026-09"],
    ["/operations", "/operations/shopify"],
    ["/inbox", "/inbox/chats"],
    ["/?month=2026-08#h", "/affiliates/overview?month=2026-08#h"],
  ];

  it.each(table)("%s", async (old, current) => {
    window.history.pushState({}, "", old);
    serve(sessionOf("owner"));
    render(<App />);

    await waitFor(() => expect(here()).toBe(current));
  });

  it("knows an id is only digits: any other word is not moved", () => {
    const rules = DEPARTMENTS.flatMap((department) => department.moved);
    expect(movedAddress("/affiliates/12", rules)).toBe("/affiliates/models/12");
    expect(movedAddress("/affiliates/abc", rules)).toBeNull();
    expect(movedAddress("/affiliates/models/12", rules)).toBeNull();
    expect(movedAddress("/affiliates/payments", rules)).toBeNull();
  });

  it("says Nothing here at /affiliates/abc, inside the frame", async () => {
    await open("/affiliates/abc");

    expect(await screen.findByRole("heading", { name: "Nothing here" })).toBeTruthy();
    expect(here()).toBe("/affiliates/abc");
    expect(screen.getByRole("navigation", { name: "Departments" })).toBeTruthy();
  });

  it("says Nothing here at an address that is no screen at all", async () => {
    await open("/nowhere-at-all", "customer_service");

    expect(await screen.findByRole("heading", { name: "Nothing here" })).toBeTruthy();
    expect(screen.getByRole("link", { name: "Home" }).getAttribute("href")).toBe("/inbox/chats");
  });
});

describe("a department the person does not hold", () => {
  it("is called Not available, in plain words, with a way back to their start", async () => {
    await open("/affiliates/models/12", "operations_only");

    expect(await screen.findByRole("heading", { name: "Not available" })).toBeTruthy();
    expect(screen.getByText(/This page is in Affiliates, which your access does not include\./)).toBeTruthy();
    expect(screen.getByRole("link", { name: "Go to your start" }).getAttribute("href")).toBe("/operations/shopify");
  });

  it("covers Settings too: customer service has no Settings row, and no Settings page", async () => {
    await open("/settings", "customer_service");

    expect(await screen.findByText(/This page is in Settings, which your access does not include\./)).toBeTruthy();
    expect(screen.queryByRole("link", { name: "Settings" })).toBeNull();
  });
});

describe("the preview frame of her portal", () => {
  it("is recognised at its new address and at the old one", () => {
    expect(previewFrameFor("/affiliates/models/12/portal/frame")).toBe(12);
    expect(previewFrameFor("/affiliates/12/portal/frame")).toBe(12);
    expect(previewFrameFor("/affiliates/models/12/portal")).toBeNull();
    expect(previewFrameFor("/affiliates/models/abc/portal/frame")).toBeNull();
  });
});

describe("Settings and the glossary", () => {
  it("is a row at the foot, for whoever can open it, and the glossary counts as Settings", async () => {
    await open("/glossary", "affiliate_manager");

    const settings = screen.getByRole("link", { name: "Settings" });
    expect(settings.getAttribute("href")).toBe("/settings");
    expect(settings.getAttribute("aria-current")).toBe("page");
    expect(screen.getByText("Settings", { selector: ".frame__role" })).toBeTruthy();
  });
});

describe("the sidebar", () => {
  it("opens the department you are in and folds the others", async () => {
    await open("/operations/bosta");

    expect(row(/^Operations/).getAttribute("aria-expanded")).toBe("true");
    expect(row(/^Inbox/).getAttribute("aria-expanded")).toBe("false");
    expect(row(/^Affiliates/).getAttribute("aria-expanded")).toBe("false");
    expect(screen.getByRole("link", { name: "Bosta" }).getAttribute("aria-current")).toBe("page");
    expect(screen.getByRole("link", { name: "Shopify" }).getAttribute("aria-current")).toBeNull();
    expect(screen.getByText("Operations", { selector: ".frame__role" })).toBeTruthy();
  });

  it("shows a page off the sidebar under its parent section", async () => {
    await open("/affiliates/models/12/payments");
    expect(screen.getByRole("link", { name: /^Models/ }).getAttribute("aria-current")).toBe("page");
    cleanup();

    await open("/affiliates/payroll/2026-10/approve");
    expect(screen.getByRole("link", { name: /^Payments/ }).getAttribute("aria-current")).toBe("page");
    cleanup();

    await open("/affiliates/orders/1001");
    expect(screen.getByRole("link", { name: "Overview" }).getAttribute("aria-current")).toBe("page");
  });

  it("shows what waits in a folded department, with a sentence for whoever cannot see it", async () => {
    await open("/operations/shopify", "owner", {
      unread: 6,
      counts: { models_awaiting_approval: 2, payments_awaiting_approval: 3 },
    });

    const inbox = row(/^Inbox/);
    await waitFor(() => expect(inbox.textContent).toContain("6 chats waiting for a reply"));
    expect(within(inbox).getByText("6")).toBeTruthy();
    // A folded department adds up its sections.
    const affiliates = row(/^Affiliates/);
    await waitFor(() => expect(within(affiliates).getByText("5")).toBeTruthy());
    expect(affiliates.textContent).toContain("2 models awaiting approval");
    expect(affiliates.textContent).toContain("3 payments awaiting approval");
  });

  it("shows each count beside its own section once the department is open", async () => {
    await open("/affiliates/overview", "owner", {
      counts: { models_awaiting_approval: 2, payments_awaiting_approval: 3 },
    });

    const models = screen.getByRole("link", { name: /^Models/ });
    await within(models).findByText("2");
    const payments = screen.getByRole("link", { name: /^Payments/ });
    await within(payments).findByText("3");
    expect(payments.querySelector(".frame__count--settled")).not.toBeNull();
    expect(models.querySelector(".frame__count--settled")).toBeNull();
  });

  it("draws no count at 0", async () => {
    await open("/operations/shopify", "owner", {
      unread: 0,
      counts: { models_awaiting_approval: 0, payments_awaiting_approval: 0 },
    });

    await waitFor(() => expect(document.querySelector(".frame__count")).toBeNull());
    await new Promise((resolve) => setTimeout(resolve, 50));
    expect(document.querySelector(".frame__count")).toBeNull();
  });

  it("draws nothing, never a 0, when a read fails or is refused", async () => {
    await open("/operations/shopify", "owner", { unread: null, counts: null, freshness: null });

    await new Promise((resolve) => setTimeout(resolve, 50));
    expect(document.querySelector(".frame__count")).toBeNull();
    expect(document.querySelector(".frame__alert")).toBeNull();
    expect(row(/^Inbox/).textContent).toBe("Inbox");
  });

  it("puts a red dot on a failed source, saying since when, in Cairo time", async () => {
    await open("/operations/shopify", "owner", {
      freshness: { shopify: { state: "failed", failing_since: "2026-01-15T10:05:00+00:00" } },
    });

    const shopify = screen.getByRole("link", { name: /^Shopify/ });
    await waitFor(() => expect(shopify.querySelector(".frame__alert")).not.toBeNull());
    expect(shopify.textContent).toContain("Could not be read since 12:05");
    expect(screen.getByRole("link", { name: /^Bosta/ }).querySelector(".frame__alert")).toBeNull();
  });

  it("puts the dot on the folded Operations row too, and not when nothing failed", async () => {
    await open("/affiliates/overview", "owner", {
      freshness: { bosta: { state: "failed", failing_since: "2026-01-15T10:05:00+00:00" } },
    });

    const operations = row(/^Operations/);
    await waitFor(() => expect(operations.querySelector(".frame__alert")).not.toBeNull());
    expect(operations.textContent).toContain("Bosta could not be read since 12:05");
    cleanup();

    await open("/affiliates/overview", "owner", { freshness: { shopify: { state: "stale" } } });
    await new Promise((resolve) => setTimeout(resolve, 50));
    expect(row(/^Operations/).querySelector(".frame__alert")).toBeNull();
  });

  it("opens a folded department in place, without going anywhere, and folds it again", async () => {
    await open("/operations/shopify");
    const before = here();

    fireEvent.click(row(/^Inbox/));
    expect(row(/^Inbox/).getAttribute("aria-expanded")).toBe("true");
    expect(row(/^Operations/).getAttribute("aria-expanded")).toBe("false");
    expect(screen.getByRole("link", { name: /^Chats/ })).toBeTruthy();
    expect(here()).toBe(before);

    fireEvent.click(row(/^Inbox/));
    expect(row(/^Inbox/).getAttribute("aria-expanded")).toBe("false");
    expect(screen.queryByRole("link", { name: /^Chats/ })).toBeNull();
    expect(here()).toBe(before);
  });

  it("goes back to the department of the address when the address changes", async () => {
    await open("/operations/shopify");
    fireEvent.click(row(/^Affiliates/));
    expect(row(/^Affiliates/).getAttribute("aria-expanded")).toBe("true");

    act(() => {
      window.history.pushState({}, "", "/inbox/confirmations");
      window.dispatchEvent(new PopStateEvent("popstate"));
    });

    await waitFor(() => expect(row(/^Inbox/).getAttribute("aria-expanded")).toBe("true"));
    expect(row(/^Affiliates/).getAttribute("aria-expanded")).toBe("false");
  });
});

describe("the account", () => {
  it("opens a menu with the theme, Team and access, and Sign out", async () => {
    await open("/affiliates/overview", "owner");

    const account = screen.getByRole("button", { name: /Nour/ });
    expect(account.getAttribute("aria-expanded")).toBe("false");
    fireEvent.click(account);

    expect(account.getAttribute("aria-expanded")).toBe("true");
    const theme = screen.getByRole("group", { name: "Theme" });
    expect(within(theme).getAllByRole("button").map((button) => button.textContent)).toEqual([
      "Dark",
      "Light",
      "Match my device",
    ]);
    expect(screen.getByRole("link", { name: "Team and access" }).getAttribute("href")).toBe("/settings?section=team");
    expect(screen.getByRole("button", { name: "Sign out" })).toBeTruthy();

    fireEvent.keyDown(account, { key: "Escape" });
    expect(account.getAttribute("aria-expanded")).toBe("false");
  });

  it("offers no Team and access to somebody who cannot open Settings", async () => {
    await open("/inbox/chats", "customer_service");

    fireEvent.click(screen.getByRole("button", { name: /Nour/ }));
    expect(screen.queryByRole("link", { name: "Team and access" })).toBeNull();
    expect(screen.getByRole("button", { name: "Sign out" })).toBeTruthy();
  });
});

describe("the phone's menu", () => {
  it("has a bar with the menu button and the section's name, and opens a full-screen dialog", async () => {
    await open("/operations/bosta");

    expect(screen.queryByRole("dialog")).toBeNull();
    expect(document.querySelector(".frame__pbar-title")?.textContent).toBe("Bosta");
    const menu = screen.getByRole("button", { name: "Open the menu" });
    fireEvent.click(menu);

    const dialog = screen.getByRole("dialog");
    expect(dialog.getAttribute("aria-modal")).toBe("true");
    expect(dialog.getAttribute("aria-label")).toBeTruthy();
    expect(document.activeElement).toBe(within(dialog).getByRole("button", { name: "Close the menu" }));
    expect(document.body.style.overflow).toBe("hidden");
    // The same departments, the Settings row and the account.
    expect(within(dialog).getByRole("navigation", { name: "Departments" })).toBeTruthy();
    expect(within(dialog).getByRole("link", { name: "Settings" })).toBeTruthy();
    expect(within(dialog).getByRole("button", { name: /Nour/ })).toBeTruthy();
  });

  it("closes with Escape, and focus goes back to the menu button", async () => {
    await open("/operations/bosta");
    const menu = screen.getByRole("button", { name: "Open the menu" });
    fireEvent.click(menu);

    fireEvent.keyDown(screen.getByRole("dialog"), { key: "Escape" });

    expect(screen.queryByRole("dialog")).toBeNull();
    expect(document.activeElement).toBe(menu);
    expect(document.body.style.overflow).toBe("");
  });

  it("closes with the close button", async () => {
    await open("/operations/bosta");
    fireEvent.click(screen.getByRole("button", { name: "Open the menu" }));

    fireEvent.click(screen.getByRole("button", { name: "Close the menu" }));

    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("closes on choosing a section, and goes there", async () => {
    await open("/operations/bosta");
    fireEvent.click(screen.getByRole("button", { name: "Open the menu" }));

    fireEvent.click(within(screen.getByRole("dialog")).getByRole("link", { name: /^WhatsApp/ }));

    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(here()).toBe("/operations/whatsapp");
  });

  it("closes on choosing the section you are already in", async () => {
    await open("/operations/bosta");
    fireEvent.click(screen.getByRole("button", { name: "Open the menu" }));

    fireEvent.click(within(screen.getByRole("dialog")).getByRole("link", { name: /^Bosta/ }));

    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  });

  it("takes the whole display, with no bar, for an open chat", async () => {
    await open("/inbox/chats/42", "customer_service");

    expect(document.querySelector(".frame--immersive")).not.toBeNull();
  });
});
