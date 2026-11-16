// @vitest-environment jsdom
/**
 * The supplier page's "Factory login" card (batch 6b): drawn only for somebody
 * who holds `production.suppliers`, and only when the server sent the key; one
 * state at a time (none, invited, active, off); switching off asks first.
 */
import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { Session } from "../../../../lib/api";
import type { FactoryLogin, SupplierView } from "../types";
import { mockApi, narrowScreen, owner, qc, renderAt, reply } from "./fixtures";
import type { Call } from "./fixtures";
import { SECTIONS, makeSupplierList, makeSupplierPage } from "./supplierFixtures";

const ADDRESS = "/production/next/suppliers/fac";
const BASE = "/api/prod/suppliers/fac/factory-login";

/** Somebody who manages suppliers: not the owner, no money. */
const manager = (): Session => {
  const session = qc();
  session.permissions = ["production.view", "production.edit", "production.suppliers"];
  return session;
};
const reader = (): Session => {
  const session = qc();
  session.permissions = ["production.view"];
  return session;
};

const writes = (calls: Call[]) => calls.filter((call) => call.method !== "GET");
const click = (name: string | RegExp) => fireEvent.click(screen.getByRole("button", { name }));
const type = (label: string, value: string) => fireEvent.change(screen.getByLabelText(label), { target: { value } });
const card = (): HTMLElement => screen.getByRole("heading", { name: "Factory login", level: 2 }).closest("section")!;

const invited: FactoryLogin = { state: "invited", email: "main@factory.example", invited_at: "2030-11-12T10:00:00Z", last_seen_at: null };
const active: FactoryLogin = { state: "active", email: "main@factory.example", invited_at: "2030-11-12T10:00:00Z", last_seen_at: "2030-11-13T08:30:00Z" };
const off: FactoryLogin = { state: "off", email: "main@factory.example", invited_at: "2030-11-12T10:00:00Z", last_seen_at: "2030-11-13T08:30:00Z" };

/** The page as the server keeps it: `state.page` is what the next read answers. */
function serve(page: SupplierView, money: boolean, extra: Record<string, unknown> = {}) {
  const state = { page };
  const calls = mockApi({
    "GET /api/prod/suppliers/fac": () => ({ supplier: state.page }),
    "GET /api/prod/suppliers": makeSupplierList([], money, SECTIONS),
    "GET /api/prod/orders": { orders: [] },
    ...extra,
  });
  return { calls, state };
}

beforeEach(() => {
  narrowScreen(false);
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(new Date("2030-11-13T10:00:00Z"));
});
afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("who sees the card", () => {
  it("shows it to the owner and to a supplier manager, when the server sent the key", async () => {
    serve(makeSupplierPage({ factory_login: null }), true);
    renderAt(ADDRESS, owner());
    await screen.findByRole("heading", { level: 1, name: "Main factory" });
    expect(card()).toBeTruthy();
    cleanup();

    serve(makeSupplierPage({ factory_login: null }, false), false);
    renderAt(ADDRESS, manager());
    await screen.findByRole("heading", { level: 1, name: "Main factory" });
    expect(card()).toBeTruthy();
  });

  it("does not draw it for somebody who only reads, whose page has no such key", async () => {
    serve(makeSupplierPage({}, false), false);
    renderAt(ADDRESS, reader());
    await screen.findByRole("heading", { level: 1, name: "Main factory" });
    expect(screen.queryByRole("heading", { name: "Factory login" })).toBeNull();
    expect(document.body.textContent).not.toMatch(/Factory login|Switch off/);
  });

  it("does not draw it for a manager whose page has no key, nor for a reader whose page somehow has one", async () => {
    serve(makeSupplierPage({}, false), false);
    renderAt(ADDRESS, manager());
    await screen.findByRole("heading", { level: 1, name: "Main factory" });
    expect(screen.queryByRole("heading", { name: "Factory login" })).toBeNull();
    cleanup();

    serve(makeSupplierPage({ factory_login: active }, false), false);
    renderAt(ADDRESS, reader());
    await screen.findByRole("heading", { level: 1, name: "Main factory" });
    expect(screen.queryByRole("heading", { name: "Factory login" })).toBeNull();
  });
});

describe("no login yet", () => {
  it("asks for an email and a name, and sends them as the invitation", async () => {
    const { calls, state } = serve(makeSupplierPage({ factory_login: null }, false), false, {
      "POST /api/prod/suppliers/fac/factory-login": () => {
        state.page = makeSupplierPage({ factory_login: invited }, false);
        return { supplier: state.page };
      },
    });
    renderAt(ADDRESS, manager());
    await screen.findByRole("heading", { level: 1, name: "Main factory" });
    expect(within(card()).getByText(/sees only its own orders/)).toBeTruthy();

    // Both are asked for, and the address must look like one.
    click("Send the invitation");
    expect((await within(card()).findByRole("alert")).textContent).toBe("Give the factory's email address.");
    type("Email", "main@factory");
    click("Send the invitation");
    expect((await within(card()).findByRole("alert")).textContent).toBe("Give the factory's email address.");
    type("Email", " main@factory.example ");
    click("Send the invitation");
    expect((await within(card()).findByRole("alert")).textContent).toBe("Give a name for the person who will sign in.");
    expect(writes(calls)).toHaveLength(0);

    type("Name", "Karim");
    click("Send the invitation");
    await waitFor(() => expect(writes(calls)).toHaveLength(1));
    expect(writes(calls)[0]).toMatchObject({ method: "POST", path: BASE, body: { email: "main@factory.example", name: "Karim" } });

    expect(await screen.findByText("Invitation sent to main@factory.example.")).toBeTruthy();
    expect(within(card()).getByText("main@factory.example")).toBeTruthy();
    expect(within(card()).getByText(/Waiting for them to accept/)).toBeTruthy();
    expect(screen.queryByLabelText("Email")).toBeNull();
  });

  it("shows the server's own words when it refuses, and reads the page again when it answers with nothing to draw", async () => {
    let posted = 0;
    const { state } = serve(makeSupplierPage({ factory_login: null }, false), false, {
      "POST /api/prod/suppliers/fac/factory-login": () => {
        if (++posted === 1) return reply(422, { detail: "That email already belongs to an account." });
        state.page = makeSupplierPage({ factory_login: invited }, false);
        return { ok: true };
      },
    });
    renderAt(ADDRESS, manager());
    await screen.findByRole("heading", { level: 1, name: "Main factory" });

    type("Email", "karim@hba.example");
    type("Name", "Karim");
    click("Send the invitation");
    expect((await within(card()).findByRole("alert")).textContent).toBe("That email already belongs to an account.");
    // What was typed is kept for the second try.
    expect((screen.getByLabelText("Email") as HTMLInputElement).value).toBe("karim@hba.example");

    click("Send the invitation");
    expect(await within(card()).findByText(/Waiting for them to accept/)).toBeTruthy();
  });
});

describe("invited", () => {
  it("says who and when, resends, and does not offer the form", async () => {
    const { calls } = serve(makeSupplierPage({ factory_login: invited }, false), false, {
      "POST /api/prod/suppliers/fac/factory-login/resend": () => ({ ok: true }),
    });
    renderAt(ADDRESS, manager());
    await screen.findByRole("heading", { level: 1, name: "Main factory" });

    expect(card().textContent).toContain("Invited main@factory.example on 12 Nov. Waiting for them to accept.");
    expect(screen.queryByLabelText("Email")).toBeNull();

    click("Resend the invitation");
    await waitFor(() => expect(writes(calls)).toHaveLength(1));
    expect(writes(calls)[0]).toMatchObject({ method: "POST", path: `${BASE}/resend` });
    expect(await screen.findByText("Invitation sent again to main@factory.example.")).toBeTruthy();
  });
});

describe("active", () => {
  it("says when the factory was last seen, and has no resend", async () => {
    serve(makeSupplierPage({ factory_login: active }, false), false);
    renderAt(ADDRESS, manager());
    await screen.findByRole("heading", { level: 1, name: "Main factory" });
    expect(card().textContent).toContain("main@factory.example can sign in. Last seen 13 Nov.");
    expect(within(card()).queryByRole("button", { name: "Resend the invitation" })).toBeNull();
    cleanup();

    serve(makeSupplierPage({ factory_login: { ...active, last_seen_at: null } }, false), false);
    renderAt(ADDRESS, manager());
    await screen.findByRole("heading", { level: 1, name: "Main factory" });
    expect(card().textContent).toContain("Last seen never.");
  });

  it("asks before switching off, and does nothing if it is kept", async () => {
    const { calls } = serve(makeSupplierPage({ factory_login: active }, false), false);
    renderAt(ADDRESS, manager());
    await screen.findByRole("heading", { level: 1, name: "Main factory" });

    click("Switch off");
    const ask = within(card()).getByRole("alertdialog");
    expect(ask.textContent).toContain("Switch off the login for main@factory.example? It is signed out at once");
    click("Keep it");
    expect(within(card()).queryByRole("alertdialog")).toBeNull();
    expect(writes(calls)).toHaveLength(0);
  });

  it("switches off when confirmed, and then offers to invite again", async () => {
    const { calls, state } = serve(makeSupplierPage({ factory_login: active }, false), false, {
      "DELETE /api/prod/suppliers/fac/factory-login": () => {
        state.page = makeSupplierPage({ factory_login: off }, false);
        return { supplier: state.page };
      },
      "POST /api/prod/suppliers/fac/factory-login": () => {
        state.page = makeSupplierPage({ factory_login: { ...invited, email: "new@factory.example" } }, false);
        return { supplier: state.page };
      },
    });
    renderAt(ADDRESS, manager());
    await screen.findByRole("heading", { level: 1, name: "Main factory" });

    click("Switch off");
    click("Yes, switch it off");
    await waitFor(() => expect(writes(calls)).toHaveLength(1));
    expect(writes(calls)[0]).toMatchObject({ method: "DELETE", path: BASE });
    expect(await screen.findByText("The factory login is switched off.")).toBeTruthy();
    expect(card().textContent).toContain("The login for main@factory.example is switched off. It cannot sign in. To invite the factory again, use another email address.");
    expect(within(card()).queryByRole("button", { name: "Switch off" })).toBeNull();

    // Inviting again is the same form, and ends in a new invitation.
    type("Email", "new@factory.example");
    type("Name", "Hana");
    click("Invite again");
    await waitFor(() => expect(writes(calls)).toHaveLength(2));
    expect(writes(calls)[1]).toMatchObject({ method: "POST", path: BASE, body: { email: "new@factory.example", name: "Hana" } });
    expect(await within(card()).findByText(/Waiting for them to accept/)).toBeTruthy();
  });

  it("shows the server's own words when switching off is refused", async () => {
    serve(makeSupplierPage({ factory_login: active }, false), false, {
      "DELETE /api/prod/suppliers/fac/factory-login": () => reply(409, { detail: "There is no live login to switch off." }),
    });
    renderAt(ADDRESS, manager());
    await screen.findByRole("heading", { level: 1, name: "Main factory" });
    click("Switch off");
    click("Yes, switch it off");
    expect((await within(card()).findByRole("alert")).textContent).toBe("There is no live login to switch off.");
  });
});

describe("an invitation not yet accepted", () => {
  it("is switched off with its own words, and the link stops working", async () => {
    const { calls } = serve(makeSupplierPage({ factory_login: invited }, false), false, {
      "DELETE /api/prod/suppliers/fac/factory-login": () => ({ ok: true }),
    });
    renderAt(ADDRESS, manager());
    await screen.findByRole("heading", { level: 1, name: "Main factory" });
    click("Switch off");
    expect(within(card()).getByRole("alertdialog").textContent).toContain("The link in the email stops working.");
    click("Yes, switch it off");
    await waitFor(() => expect(writes(calls)).toHaveLength(1));
  });
});
