// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { Session } from "../../lib/api";
import { InboxFeedbackSettings, replyHoursProblem, reviewLinkProblem } from "../InboxFeedbackSettings";

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
let saved: { method: string; body: Record<string, unknown> }[] = [];

function serve(read: unknown = SETTINGS, put: (body: Record<string, unknown>) => [number, unknown] = () => [200, {}]) {
  saved = [];
  fetchMock.mockImplementation((_url: string, init?: RequestInit) => {
    if (init?.method === "PUT") {
      const body = JSON.parse(String(init.body));
      saved.push({ method: "PUT", body });
      const [status, answer] = put(body);
      return reply(status, answer);
    }
    return Array.isArray(read) ? reply(read[0], read[1]) : reply(200, read);
  });
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

describe("Feedback questions in Settings", () => {
  it("says whether they are on and since when, whether codes can be made, and what is set", async () => {
    serve();
    render(<InboxFeedbackSettings session={OWNER} />);

    const region = await card();
    expect(within(region).getByText("On · asking since 5 Nov")).toBeTruthy();
    expect(within(region).getByText("Reward codes cannot be made yet. No permission yet.")).toBeTruthy();
    expect(within(region).getByText(/Review link: not set/)).toBeTruthy();
    expect(within(region).getByText(/promised a reply within 24 hours/)).toBeTruthy();
    // The switch is the server's: nothing here turns it.
    expect(within(region).queryByRole("checkbox")).toBeNull();
    expect(within(region).getByText(/is done on the server, not here/)).toBeTruthy();
    expect(fetchMock.mock.calls[0][0]).toBe("/api/inbox/feedback/settings");
  });

  it("says when they are off, and when codes are ready", async () => {
    serve({
      enabled: false,
      started_at: null,
      review_url: "https://g.page/r/hba/review",
      reply_hours: 1,
      codes_ready: { ready: true, reason: null },
    });
    render(<InboxFeedbackSettings session={OWNER} />);

    const region = await card();
    expect(within(region).getByText("Off · nothing is being sent")).toBeTruthy();
    expect(within(region).getByText("Reward codes can be made.")).toBeTruthy();
    expect(within(region).getByText(/Review link: https:\/\/g\.page\/r\/hba\/review/)).toBeTruthy();
    expect(within(region).getByText(/within 1 hour$/)).toBeTruthy();
  });

  it("is not shown to anyone but the owner, and does not even ask", () => {
    serve();
    const { container } = render(<InboxFeedbackSettings session={STAFF} />);

    expect(container.textContent).toBe("");
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("says so when the settings could not be read", async () => {
    serve([403, { detail: "Only an admin can see this." }]);
    render(<InboxFeedbackSettings session={OWNER} />);

    const region = await card();
    expect(within(region).getByText("Only an admin can see this.")).toBeTruthy();
    expect(within(region).queryByRole("button", { name: "Change" })).toBeNull();
  });

  it("opens the two fields with what is saved, and sends only what was changed", async () => {
    serve(SETTINGS, () => [
      200,
      { enabled: true, started_at: SETTINGS.started_at, review_url: "https://g.page/r/hba/review", reply_hours: 24 },
    ]);
    render(<InboxFeedbackSettings session={OWNER} />);
    const region = await card();

    fireEvent.click(within(region).getByRole("button", { name: "Change" }));
    const link = within(region).getByLabelText("Review link") as HTMLInputElement;
    const hours = within(region).getByLabelText(/Reply time promised/) as HTMLInputElement;
    expect(link.value).toBe("");
    expect(hours.value).toBe("24");
    // Nothing changed yet: nothing to save.
    expect((within(region).getByRole("button", { name: "Save" }) as HTMLButtonElement).disabled).toBe(true);

    fireEvent.change(link, { target: { value: " https://g.page/r/hba/review " } });
    fireEvent.click(within(region).getByRole("button", { name: "Save" }));

    await waitFor(() => expect(saved).toHaveLength(1));
    expect(saved[0].body).toEqual({ review_url: "https://g.page/r/hba/review" });
    expect(await within(region).findByText("Saved.")).toBeTruthy();
    expect(within(region).getByText(/Review link: https:\/\/g\.page\/r\/hba\/review/)).toBeTruthy();
    // A save does not ask Shopify again: the last answer about codes stays.
    expect(within(region).getByText("Reward codes cannot be made yet. No permission yet.")).toBeTruthy();
    expect(within(region).queryByLabelText("Review link")).toBeNull();
  });

  it("changes the promised hours, and clears the link with an empty one", async () => {
    serve({ ...SETTINGS, review_url: "https://g.page/r/hba/review" }, () => [
      200,
      { enabled: true, started_at: null, review_url: null, reply_hours: 12 },
    ]);
    render(<InboxFeedbackSettings session={OWNER} />);
    const region = await card();

    fireEvent.click(within(region).getByRole("button", { name: "Change" }));
    fireEvent.change(within(region).getByLabelText("Review link"), { target: { value: "" } });
    fireEvent.change(within(region).getByLabelText(/Reply time promised/), { target: { value: "12" } });
    fireEvent.click(within(region).getByRole("button", { name: "Save" }));

    await waitFor(() => expect(saved).toHaveLength(1));
    expect(saved[0].body).toEqual({ review_url: "", reply_hours: 12 });
    expect(await within(region).findByText(/Review link: not set/)).toBeTruthy();
    expect(within(region).getByText(/within 12 hours/)).toBeTruthy();
  });

  it("holds back a link that is not https, and hours outside 1 to 72, before sending anything", async () => {
    serve();
    render(<InboxFeedbackSettings session={OWNER} />);
    const region = await card();
    fireEvent.click(within(region).getByRole("button", { name: "Change" }));
    const save = within(region).getByRole("button", { name: "Save" }) as HTMLButtonElement;

    const link = within(region).getByLabelText("Review link") as HTMLInputElement;
    fireEvent.change(link, { target: { value: "http://g.page/r/hba" } });
    expect(within(region).getByText("The review link must start with https:// and be a single link.")).toBeTruthy();
    expect(link.getAttribute("aria-invalid")).toBe("true");
    expect(link.getAttribute("aria-describedby")).toBeTruthy();
    expect(save.disabled).toBe(true);

    fireEvent.change(link, { target: { value: "https://g.page/r/hba" } });
    expect(link.getAttribute("aria-invalid")).toBe("false");
    expect(save.disabled).toBe(false);

    const hours = within(region).getByLabelText(/Reply time promised/) as HTMLInputElement;
    for (const bad of ["0", "73", "soon", ""]) {
      fireEvent.change(hours, { target: { value: bad } });
      expect(within(region).getByText("Enter a whole number of hours from 1 to 72.")).toBeTruthy();
      expect(hours.getAttribute("aria-invalid")).toBe("true");
      expect(save.disabled).toBe(true);
    }

    fireEvent.submit(save.closest("form") as HTMLFormElement);
    expect(saved).toHaveLength(0);
  });

  it("gives the server's own words when it refuses a change, and keeps what was typed", async () => {
    serve(SETTINGS, () => [422, { detail: "The review link can be at most 500 characters." }]);
    render(<InboxFeedbackSettings session={OWNER} />);
    const region = await card();

    fireEvent.click(within(region).getByRole("button", { name: "Change" }));
    fireEvent.change(within(region).getByLabelText(/Reply time promised/), { target: { value: "48" } });
    fireEvent.click(within(region).getByRole("button", { name: "Save" }));

    expect((await within(region).findByRole("alert")).textContent).toBe(
      "The review link can be at most 500 characters.",
    );
    expect((within(region).getByLabelText(/Reply time promised/) as HTMLInputElement).value).toBe("48");
    expect(within(region).queryByText("Saved.")).toBeNull();
  });

  it("closes without saving on Cancel", async () => {
    serve();
    render(<InboxFeedbackSettings session={OWNER} />);
    const region = await card();

    fireEvent.click(within(region).getByRole("button", { name: "Change" }));
    fireEvent.change(within(region).getByLabelText(/Reply time promised/), { target: { value: "48" } });
    fireEvent.click(within(region).getByRole("button", { name: "Cancel" }));

    expect(within(region).queryByLabelText(/Reply time promised/)).toBeNull();
    expect(within(region).getByText(/within 24 hours/)).toBeTruthy();
    expect(saved).toHaveLength(0);
  });
});
