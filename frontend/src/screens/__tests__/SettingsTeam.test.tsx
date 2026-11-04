// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { historicalState } from "../../departments/affiliates/HistoricalSetup";
import { HistoricalSetup } from "../../departments/affiliates/HistoricalSetup";
import { Team } from "../settings/Team";
import type { Session } from "../../lib/api";
import { NONE, ROLE_PERMISSIONS, person, roster } from "./teamFixture";

const reply = (status: number, body: unknown) =>
  Promise.resolve({
    ok: status < 400, status,
    headers: { get: () => "application/json" },
    json: () => Promise.resolve(body),
    text: () => Promise.resolve(JSON.stringify(body)),
  } as unknown as Response);

function session(role = "admin"): Session {
  return {
    actor: { id: 1, email: "yahya@hbawear.store", display_name: "Yahya", roles: [role], is_staff: true, is_model: false },
    permissions: ROLE_PERMISSIONS[role],
    platform: { go_live_month: "2026-10" },
  } as unknown as Session;
}

type Call = { url: string; method: string; body: any };
let calls: Call[];
let routes: (url: string, method: string, body: any) => Promise<Response> | undefined;
let data: ReturnType<typeof roster>;

beforeEach(() => {
  calls = [];
  data = roster();
  routes = () => undefined;
  vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    const method = init?.method ?? "GET";
    const body = init?.body ? JSON.parse(String(init.body)) : undefined;
    calls.push({ url, method, body });
    const custom = routes(url, method, body);
    if (custom) return custom;
    if (url === "/api/staff") return reply(200, data);
    if (url.endsWith("/sessions")) return reply(200, { sessions: [] });
    if (url.endsWith("/trusted-browsers")) return reply(200, { browsers: [] });
    if (url === "/api/payroll/historical/review") return reply(200, { totals: { ready: 0, blocked: 0 } });
    return reply(200, {});
  }));
});
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

const called = (method: string, url: string) => calls.find((c) => c.method === method && c.url === url);

const renderAt = (entry = "/settings/team", who = "admin") =>
  render(<MemoryRouter initialEntries={[entry]}><Team session={session(who)} /></MemoryRouter>);

const seg = (department: string) => screen.getByRole("radiogroup", { name: `${department} access` });
const radio = (department: string, level: RegExp | string) => within(seg(department)).getByRole("radio", { name: level });

describe("Settings → Team and access, the page", () => {
  it("lists the people with their access in words, and the invitations waiting", async () => {
    renderAt();
    const list = await screen.findByRole("region", { name: "People" });
    expect(within(list).getByText("Owner")).toBeTruthy();
    expect(within(list).getByText("Inbox staff")).toBeTruthy();
    expect(within(list).getByText("Affiliates manager · Inbox staff")).toBeTruthy();
    expect(within(list).getByText("Invited, not joined yet")).toBeTruthy();
    expect(within(list).getByText("hassan@hbawear.store")).toBeTruthy();
    expect(within(list).getByText("Inbox staff · sent today")).toBeTruthy();
    expect(screen.getByText("3 people · 1 invitation waiting")).toBeTruthy();
    // A lock only where two-step sign-in is on.
    expect(within(list).getAllByLabelText(/Two-step sign-in on/)).toHaveLength(2);
    // The old words are nowhere.
    expect(screen.queryByText(/Content manager|Customer service|Affiliate manager\b/)).toBeNull();
  });

  it("opens the first person, and the one named in the address", async () => {
    const first = renderAt();
    expect((await screen.findByRole("heading", { name: /Yahya/ })).textContent).toContain("You");
    first.unmount();
    renderAt("/settings/team?person=2");
    expect(await screen.findByRole("heading", { name: "Mona" })).toBeTruthy();
    expect(screen.getByText(/mona@hbawear\.store · joined 3 September/)).toBeTruthy();
    expect(screen.getByRole("link", { name: /Mona/, current: true })).toBeTruthy();
  });

  it("choosing someone in the list opens their page", async () => {
    renderAt();
    fireEvent.click(await screen.findByRole("link", { name: /Dina/ }));
    expect(await screen.findByRole("heading", { name: "Dina" })).toBeTruthy();
    expect(radio("Affiliates", "Manager").getAttribute("aria-checked")).toBe("true");
    expect(radio("Inbox", "Staff").getAttribute("aria-checked")).toBe("true");
    expect(radio("Operations", "No access").getAttribute("aria-checked")).toBe("true");
  });

  it("draws the three departments, and no Production or Finance", async () => {
    renderAt("/settings/team?person=2");
    await screen.findByRole("heading", { name: "Mona" });
    expect(screen.getAllByRole("radiogroup").map((group) => group.getAttribute("aria-label")))
      .toEqual(["Inbox access", "Operations access", "Affiliates access"]);
  });

  it("says what a person's levels give, with what they do not", async () => {
    renderAt("/settings/team?person=2");
    const gives = (await screen.findByText(/What this gives Mona:/)).closest("p")!;
    expect(gives.textContent).toContain("reading and replying to customers");
    expect(gives.textContent).toContain("No Operations dashboard, no pay figures, no payroll or payments, no way to change a model");
  });

  it("on a phone, the list is the page and a chosen person has a way back", async () => {
    const view = renderAt();
    await screen.findByRole("heading", { name: /Yahya/ });
    expect(view.container.querySelector(".team")!.classList.contains("team--chosen")).toBe(false);
    cleanup();
    const chosen = renderAt("/settings/team?person=2");
    await screen.findByRole("heading", { name: "Mona" });
    expect(chosen.container.querySelector(".team")!.classList.contains("team--chosen")).toBe(true);
    expect(screen.getByRole("link", { name: /Team and access/ })).toBeTruthy();
  });

  it("keeps the owner line: gives ownership after asking", async () => {
    renderAt("/settings/team?person=2");
    await screen.findByRole("heading", { name: "Mona" });
    fireEvent.click(screen.getByRole("button", { name: "Make owner" }));
    const dialog = await screen.findByRole("dialog");
    expect(dialog.textContent).toContain("Make Mona the owner?");
    fireEvent.click(within(dialog).getByRole("button", { name: "Make owner" }));
    await waitFor(() => expect(called("POST", "/api/staff/2/roles")?.body).toEqual({ role: "admin" }));
  });

  it("disables every department row for an owner, and says why", async () => {
    data.staff.push(person(4, "Karim", ["admin"], NONE));
    renderAt("/settings/team?person=4");
    await screen.findByRole("heading", { name: "Karim" });
    expect(screen.getAllByText("The owner reaches every department.")).toHaveLength(3);
    for (const button of screen.getAllByRole("radio")) expect((button as HTMLButtonElement).disabled).toBe(true);
    fireEvent.click(screen.getByRole("button", { name: "Take ownership" }));
    const dialog = await screen.findByRole("dialog");
    fireEvent.click(within(dialog).getByRole("button", { name: "Take ownership" }));
    await waitFor(() => expect(called("POST", "/api/staff/4/roles/admin/remove")).toBeTruthy());
  });

  it("shows your own page and changes none of it", async () => {
    renderAt();
    await screen.findByRole("heading", { name: /Yahya/ });
    expect(screen.getByText(/You cannot change your own access/)).toBeTruthy();
    for (const button of screen.getAllByRole("radio")) expect((button as HTMLButtonElement).disabled).toBe(true);
    expect(screen.queryByRole("button", { name: /Suspend/ })).toBeNull();
    expect(screen.queryByRole("button", { name: "Make owner" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Take ownership" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Sign out of every device" })).toBeNull();
  });
});

describe("Settings → Team and access, choosing a level", () => {
  it("cannot choose a level that is not offered yet", async () => {
    renderAt("/settings/team?person=2");
    await screen.findByRole("heading", { name: "Mona" });
    const viewer = radio("Inbox", /Viewer/) as HTMLButtonElement;
    expect(viewer.disabled).toBe(true);
    expect(viewer.title).toBe("Not offered yet");
    expect(viewer.textContent).toContain("Not offered yet");
    fireEvent.click(viewer);
    expect(screen.queryByRole("dialog")).toBeNull();
    // Operations offers only none and manager.
    expect((radio("Operations", /Staff/) as HTMLButtonElement).disabled).toBe(true);
    expect((radio("Operations", "Manager") as HTMLButtonElement).disabled).toBe(false);
  });

  it("asks first, naming what changes, then calls the server and shows the result", async () => {
    const after = person(2, "Mona", ["customer_service", "affiliate_manager"], { ...NONE, inbox: "staff", affiliates: "manager" });
    routes = (url, method) => url === "/api/staff/2/access/affiliates" && method === "PUT" ? reply(200, after) : undefined;
    renderAt("/settings/team?person=2");
    await screen.findByRole("heading", { name: "Mona" });
    fireEvent.click(radio("Affiliates", "Manager"));
    const dialog = await screen.findByRole("dialog");
    expect(dialog.textContent).toContain("Give Mona Affiliates manager access?");
    expect(dialog.textContent).toContain("Can now: approve a month's pay");
    expect(dialog.textContent).toContain("Keeps: Inbox staff.");
    expect(called("PUT", "/api/staff/2/access/affiliates")).toBeUndefined();
    fireEvent.click(within(dialog).getByRole("button", { name: "Give access" }));
    await waitFor(() => expect(called("PUT", "/api/staff/2/access/affiliates")?.body).toEqual({ level: "manager" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(radio("Affiliates", "Manager").getAttribute("aria-checked")).toBe("true");
    expect(screen.getByText(/What this gives Mona:/).closest("p")!.textContent).toContain("approving a month's pay");
    // The list line follows the answer.
    expect(within(screen.getByRole("region", { name: "People" })).getByText("Inbox staff · Affiliates manager")).toBeTruthy();
  });

  it("names a change of level as a change", async () => {
    renderAt("/settings/team?person=3");
    await screen.findByRole("heading", { name: "Dina" });
    fireEvent.click(radio("Affiliates", "Staff"));
    const dialog = await screen.findByRole("dialog");
    expect(dialog.textContent).toContain("Change Dina to Affiliates staff?");
    expect(dialog.textContent).toContain("Can no longer: approve a month's pay");
    expect(within(dialog).getByRole("button", { name: "Change access" })).toBeTruthy();
  });

  it("takes a department away with No access", async () => {
    renderAt("/settings/team?person=3");
    await screen.findByRole("heading", { name: "Dina" });
    fireEvent.click(radio("Inbox", "No access"));
    const dialog = await screen.findByRole("dialog");
    expect(dialog.textContent).toContain("Take Inbox access from Dina?");
    expect(dialog.textContent).toContain("Keeps: Affiliates manager.");
    fireEvent.click(within(dialog).getByRole("button", { name: "Remove access" }));
    await waitFor(() => expect(called("PUT", "/api/staff/3/access/inbox")?.body).toEqual({ level: "none" }));
  });

  it("shows the server's refusal in the dialog and changes nothing", async () => {
    routes = (_url, method) => method === "PUT"
      ? reply(409, { detail: "This is the only access Mona has. Give them other access first, or suspend the account." })
      : undefined;
    renderAt("/settings/team?person=2");
    await screen.findByRole("heading", { name: "Mona" });
    fireEvent.click(radio("Inbox", "No access"));
    const dialog = await screen.findByRole("dialog");
    fireEvent.click(within(dialog).getByRole("button", { name: "Remove access" }));
    expect((await within(dialog).findByRole("alert")).textContent).toContain("This is the only access Mona has");
    expect(radio("Inbox", "Staff").getAttribute("aria-checked")).toBe("true");
  });

  it("moves between levels with the arrow keys, and only to ones that can be chosen", async () => {
    renderAt("/settings/team?person=2");
    await screen.findByRole("heading", { name: "Mona" });
    const staff = radio("Inbox", "Staff");
    staff.focus();
    fireEvent.keyDown(staff, { key: "ArrowRight" });
    // Manager is not offered in Inbox, so the next stop wraps to No access.
    expect(document.activeElement).toBe(radio("Inbox", "No access"));
  });

  it("leaves a suspended person's rows alone, and offers to reactivate", async () => {
    data.staff[1] = person(2, "Mona", [], NONE, { status: "suspended" });
    renderAt("/settings/team?person=2");
    await screen.findByRole("heading", { name: /Mona/ });
    for (const button of screen.getAllByRole("radio")) expect((button as HTMLButtonElement).disabled).toBe(true);
    fireEvent.click(screen.getByRole("button", { name: "Reactivate Mona" }));
    const dialog = await screen.findByRole("dialog");
    expect(dialog.textContent).toContain("gives no access");
  });
});

describe("Settings → Team and access, two-step reminder", () => {
  it("sends a reminder to somebody whose two-step sign-in is off", async () => {
    routes = (url, method) => url === "/api/staff/2/two-step/remind" && method === "POST" ? reply(201, { emailed: true }) : undefined;
    renderAt("/settings/team?person=2");
    await screen.findByRole("heading", { name: "Mona" });
    expect(screen.getByText(/Not required for Mona's access/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Send a reminder" }));
    await waitFor(() => expect(called("POST", "/api/staff/2/two-step/remind")).toBeTruthy());
    expect(await screen.findByText("A reminder was emailed to Mona.")).toBeTruthy();
  });

  it("shows the server's words when a reminder went already, and offers none to yourself", async () => {
    routes = (url) => url === "/api/staff/2/two-step/remind" ? reply(429, { detail: "A reminder was sent at 09:10." }) : undefined;
    const view = renderAt("/settings/team?person=2");
    await screen.findByRole("heading", { name: "Mona" });
    fireEvent.click(screen.getByRole("button", { name: "Send a reminder" }));
    expect((await screen.findByRole("alert")).textContent).toBe("A reminder was sent at 09:10.");
    view.unmount();
    renderAt("/settings/team?person=1");
    await screen.findByRole("heading", { name: /Yahya/ });
    expect(screen.queryByRole("button", { name: "Send a reminder" })).toBeNull();
  });
});

describe("Settings → Team and access, waiting invitations", () => {
  it("opens an invitation's page, with Resend and Withdraw", async () => {
    renderAt();
    fireEvent.click(await screen.findByRole("link", { name: /hassan@hbawear\.store/ }));
    expect(await screen.findByRole("heading", { name: "hassan@hbawear.store" })).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Resend" }));
    await waitFor(() => expect(called("POST", "/api/staff/invitations/11/resend")).toBeTruthy());
    fireEvent.click(screen.getByRole("button", { name: "Withdraw" }));
    await waitFor(() => expect(called("POST", "/api/staff/invitations/11/revoke")).toBeTruthy());
  });
});

describe("Settings → Team and access, inviting someone", () => {
  const open = async () => {
    renderAt();
    fireEvent.click(await screen.findByRole("button", { name: "Invite someone" }));
    return screen.findByRole("dialog");
  };
  const invitations = () => calls.filter((c) => c.url === "/api/auth/invitations" && c.method === "POST");
  const accepting = () => {
    routes = (url, method) => url === "/api/auth/invitations" && method === "POST"
      ? reply(201, { token: "t0k3n", link: "https://hba.test/accept-invitation?token=t0k3n", emailed: false, invitation: {} })
      : undefined;
  };

  it("invites by department and level, sending that level's role, and shows the link once", async () => {
    accepting();
    const dialog = await open();
    fireEvent.change(within(dialog).getByLabelText("Email"), { target: { value: "new@hbawear.store" } });
    fireEvent.change(within(dialog).getByLabelText("Department"), { target: { value: "affiliates" } });
    // Only offered levels: no Viewer, no "No access".
    expect(within(within(dialog).getByLabelText("Level")).getAllByRole("option").map((o) => o.textContent)).toEqual(["Staff", "Manager"]);
    fireEvent.change(within(dialog).getByLabelText("Level"), { target: { value: "manager" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Send invitation" }));
    await waitFor(() => expect(invitations()[0]?.body).toEqual({ email: "new@hbawear.store", role: "affiliate_manager" }));
    expect((await within(dialog).findByRole("status")).textContent).toContain("https://hba.test/accept-invitation?token=t0k3n");
    expect(within(dialog).getByRole("button", { name: "Copy link" })).toBeTruthy();
  });

  it("sends a department's first offered level by default, and the owner as admin", async () => {
    accepting();
    const dialog = await open();
    fireEvent.change(within(dialog).getByLabelText("Email"), { target: { value: "a@hbawear.store" } });
    fireEvent.change(within(dialog).getByLabelText("Department"), { target: { value: "inbox" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Send invitation" }));
    await waitFor(() => expect(invitations()[0]?.body).toEqual({ email: "a@hbawear.store", role: "customer_service" }));

    fireEvent.change(within(dialog).getByLabelText("Email"), { target: { value: "b@hbawear.store" } });
    fireEvent.change(within(dialog).getByLabelText("Department"), { target: { value: "owner" } });
    expect(within(dialog).queryByLabelText("Level")).toBeNull();
    fireEvent.click(within(dialog).getByRole("button", { name: "Send invitation" }));
    await waitFor(() => expect(invitations()[1]?.body).toEqual({ email: "b@hbawear.store", role: "admin" }));
  });

  it("offers only the levels whose role the inviter may give", async () => {
    data = roster({ invitable_roles: ["customer_service"] });
    const dialog = await open();
    expect(within(within(dialog).getByLabelText("Department")).getAllByRole("option").map((o) => o.textContent)).toEqual(["Inbox"]);
  });
});

describe("Settings → Team and access, review fixes", () => {
  it("takes 'required' from the server's own answer", async () => {
    data.staff[1] = person(2, "Mona", ["customer_service"], { ...NONE, inbox: "staff" }, { two_step_required: true });
    renderAt("/settings/team?person=2");
    expect(await screen.findByText(/Required for Mona's access/)).toBeTruthy();
  });

  it("does not claim an email when the server sent none", async () => {
    routes = (url, method) => url === "/api/staff/2/two-step/remind" && method === "POST" ? reply(201, { emailed: false }) : undefined;
    renderAt("/settings/team?person=2");
    await screen.findByRole("heading", { name: "Mona" });
    fireEvent.click(screen.getByRole("button", { name: "Send a reminder" }));
    expect(await screen.findByText("Saved, but this server sends no email.")).toBeTruthy();
  });

  it("reloads the roster after a refused change", async () => {
    routes = (_url, method) => method === "PUT" ? reply(409, { detail: "No." }) : undefined;
    renderAt("/settings/team?person=2");
    await screen.findByRole("heading", { name: "Mona" });
    const before = calls.filter((c) => c.url === "/api/staff").length;
    fireEvent.click(radio("Inbox", "No access"));
    fireEvent.click(within(await screen.findByRole("dialog")).getByRole("button", { name: "Remove access" }));
    await waitFor(() => expect(calls.filter((c) => c.url === "/api/staff").length).toBe(before + 1));
  });

  it("says an Operations manager invitation brings Inbox staff too", async () => {
    renderAt();
    fireEvent.click(await screen.findByRole("button", { name: "Invite someone" }));
    const dialog = await screen.findByRole("dialog");
    fireEvent.change(within(dialog).getByLabelText("Department"), { target: { value: "operations" } });
    expect(dialog.textContent).toContain("will have Operations manager and Inbox staff access");
  });

  it("orders the list: owners, then sidebar order of departments, then level, then name", async () => {
    data.staff = [
      person(1, "Yahya", ["admin"], NONE),
      person(5, "Rana", ["content_manager"], { ...NONE, affiliates: "staff" }),
      person(6, "Dina", ["affiliate_manager"], { ...NONE, affiliates: "manager" }),
      person(4, "Omar", ["customer_service"], { ...NONE, inbox: "staff" }),
      person(3, "Karim", ["operations_manager", "customer_service"], { ...NONE, inbox: "staff", operations: "manager" }),
      person(7, "Zed", [], NONE, { status: "suspended" }),
    ];
    renderAt();
    const list = await screen.findByRole("region", { name: "People" });
    expect(within(list).getAllByRole("link").map((a) => a.querySelector("b")!.textContent).slice(0, 6))
      .toEqual(["Yahya", "Karim", "Omar", "Dina", "Rana", "Zed"]);
  });

  it("keeps only the label of 'What this gives' in the heavier weight", async () => {
    renderAt("/settings/team?person=2");
    const label = await screen.findByText("What this gives Mona:");
    expect(label.className).toBe("gives__label");
    expect(label.closest("p")!.querySelector("b")).toBeNull();
  });
});

describe("The role words", () => {
  it("uses the new words in the dialogs", async () => {
    renderAt("/settings/team?person=2");
    await screen.findByRole("heading", { name: "Mona" });
    fireEvent.click(radio("Operations", "Manager"));
    const dialog = await screen.findByRole("dialog");
    expect(dialog.textContent).toContain("Give Mona Operations manager access?");
    expect(dialog.textContent).not.toMatch(/Customer service|Content manager|Admin\b/);
  });
});

describe("Historical setup (Affiliates)", () => {
  it("says so once every month before go-live is final", async () => {
    render(<MemoryRouter initialEntries={["/affiliates/historical"]}><HistoricalSetup session={session("admin")} /></MemoryRouter>);
    expect(await screen.findByText(/History is complete: every month before October 2026 is final\./)).toBeTruthy();
  });
});

describe("Historical setup's state", () => {
  const row = (setup: object | null) => ({ id: 7, name: "Aya", account_kind: "model", status: "active", historical_setup: setup as never });
  const text = (node: React.ReactNode) => render(<MemoryRouter>{node}</MemoryRouter>).container.textContent;

  it("splits the months at go-live, so the row and the review agree", () => {
    expect(text(historicalState(row({ eligible: 9, ready: 0, blocking: 9, blocking_before_go_live: 5, first_gap: "2026-01", start_is_recorded: true }))))
      .toContain("5 months before go-live · 4 after cannot be calculated");
  });

  it("sends a model with no start to where it is recorded", () => {
    expect(text(historicalState(row({ eligible: 0, ready: 0, blocking: 0, first_gap: null, start_is_recorded: false }))))
      .toContain("Record her start month");
  });
});
