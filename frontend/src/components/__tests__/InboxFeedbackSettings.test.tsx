// @vitest-environment jsdom
import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { MemoryRouter } from "react-router-dom";

import type { Session } from "../../lib/api";
import {
  InboxFeedbackSettings,
  replyHoursProblem,
  reviewLinkProblem,
  testPhoneProblem,
} from "../InboxFeedbackSettings";

const reply = (status: number, body: unknown) =>
  Promise.resolve({
    ok: status < 400,
    status,
    headers: { get: () => "application/json" },
    json: () => Promise.resolve(body),
    text: () => Promise.resolve(JSON.stringify(body)),
  } as unknown as Response);

const sessionWith = (permissions: string[]) =>
  ({
    actor: { id: 1, email: "owner@example.test", display_name: "Owner", roles: ["admin"], is_staff: true, is_model: false },
    permissions,
    platform: { working_month: "2026-11", go_live_month: "2026-10", start_month: "2026-01" },
  }) as Session;

const OWNER = sessionWith(["settings.manage", "inbox.use"]);
const STAFF = sessionWith(["inbox.use"]);

const SETTINGS = {
  enabled: true,
  started_at: "2026-11-05T09:00:00+00:00",
  review_url: null,
  reply_hours: 24,
  codes_ready: { ready: false, reason: "No permission yet." },
};

let fetchMock: ReturnType<typeof vi.fn>;

function serve(read: unknown = SETTINGS) {
  fetchMock.mockImplementation(() => (Array.isArray(read) ? reply(read[0], read[1]) : reply(200, read)));
}

beforeEach(() => {
  fetchMock = vi.fn();
  vi.stubGlobal("fetch", fetchMock);
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const card = () => screen.findByRole("region", { name: "Feedback questions" });

describe("the rules for the two fields", () => {
  it("accepts an empty review link, or one https link, and nothing else", () => {
    expect(reviewLinkProblem("")).toBeNull();
    expect(reviewLinkProblem("  ")).toBeNull();
    expect(reviewLinkProblem("https://g.page/r/hba-wear/review")).toBeNull();
    expect(reviewLinkProblem("http://g.page/r/hba")).toMatch(/must start with https:\/\//);
    expect(reviewLinkProblem("g.page/r/hba")).toMatch(/must start with https:\/\//);
    expect(reviewLinkProblem("https://")).toMatch(/must start with https:\/\//);
    expect(reviewLinkProblem("https://g.page/a b")).toMatch(/single link/);
    expect(reviewLinkProblem(`https://g.page/${"a".repeat(500)}`)).toMatch(/at most 500 characters/);
  });

  it("accepts a whole number of hours from 1 to 72", () => {
    for (const fine of ["1", "24", "72", " 12 "]) expect(replyHoursProblem(fine)).toBeNull();
    for (const bad of ["", "0", "73", "1.5", "-3", "abc", "2 hours"]) {
      expect(replyHoursProblem(bad)).toBe("Enter a whole number of hours from 1 to 72.");
    }
  });
});

describe("Feedback questions in Settings → Integrations", () => {
  const renderCard = (session = OWNER) =>
    render(
      <MemoryRouter>
        <InboxFeedbackSettings session={session} />
      </MemoryRouter>,
    );

  it("is short: whether they are on and since when, and the way to the setup page", async () => {
    serve();
    renderCard();

    const region = await card();
    expect(within(region).getByText("On · asking since 5 Nov")).toBeTruthy();
    const link = within(region).getByRole("link", { name: "Open feedback setup" });
    expect(link.getAttribute("href")).toBe("/inbox/feedback/setup");
    // The forms moved to the setup page: nothing to type or switch here.
    expect(within(region).queryByRole("button")).toBeNull();
    expect(within(region).queryByRole("textbox")).toBeNull();
    expect(within(region).queryByRole("checkbox")).toBeNull();
    expect(within(region).queryByText(/Review link/)).toBeNull();
    expect(fetchMock.mock.calls[0][0]).toBe("/api/inbox/feedback/settings");
  });

  it("says when reward codes cannot be made, because that is a connection fault", async () => {
    serve();
    renderCard();

    const region = await card();
    expect(within(region).getByText("Reward codes cannot be made yet. No permission yet.")).toBeTruthy();
  });

  it("says nothing about codes when they can be made, and says when they are off", async () => {
    serve({
      enabled: false,
      started_at: null,
      review_url: null,
      reply_hours: 24,
      codes_ready: { ready: true, reason: null },
    });
    renderCard();

    const region = await card();
    expect(within(region).getByText("Off · nothing is being sent")).toBeTruthy();
    expect(within(region).queryByText(/Reward codes/)).toBeNull();
  });

  it("is not shown to anyone but the owner, and does not even ask", () => {
    serve();
    const { container } = renderCard(STAFF);

    expect(container.textContent).toBe("");
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("says so when the settings could not be read", async () => {
    serve([403, { detail: "Only an admin can see this." }]);
    renderCard();

    const region = await card();
    expect(within(region).getByText("Only an admin can see this.")).toBeTruthy();
    expect(within(region).queryByRole("link")).toBeNull();
  });
});

describe("the rule for a test's number", () => {
  it("accepts an Egyptian mobile written any usual way, and nothing else", () => {
    for (const fine of ["01005550188", "+20 100 555 0188", "0020 100 555 0188", "1005550188", "+20 0100 555 0188", "01155550188", "01255550188", "01555550188"]) {
      expect(testPhoneProblem(fine)).toBeNull();
    }
    for (const bad of ["", "12345", "0100555018", "010055501888", "+44 7700 900123", "02 2575 0000", "01355550188", "abc"]) {
      expect(testPhoneProblem(bad)).toBe("That is not an Egyptian mobile number. Write it like 01xxxxxxxxx.");
    }
  });
});
