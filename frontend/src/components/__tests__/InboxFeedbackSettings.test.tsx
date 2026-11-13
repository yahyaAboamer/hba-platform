// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
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
let saved: { method: string; body: Record<string, unknown> }[] = [];
let posted: { url: string; body: Record<string, unknown> }[] = [];

function serve(
  read: unknown = SETTINGS,
  put: (body: Record<string, unknown>) => [number, unknown] = () => [200, {}],
  post: (body: Record<string, unknown>) => [number, unknown] = () => [200, {}],
) {
  saved = [];
  posted = [];
  fetchMock.mockImplementation((url: string, init?: RequestInit) => {
    if (init?.method === "POST") {
      const body = JSON.parse(String(init.body));
      posted.push({ url, body });
      const [status, answer] = post(body);
      return reply(status, answer);
    }
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

describe("Send a test", () => {
  const renderCard = (session = OWNER) =>
    render(
      <MemoryRouter>
        <InboxFeedbackSettings session={session} />
      </MemoryRouter>,
    );
  const phoneField = (region: HTMLElement) => within(region).getByLabelText("Send a test") as HTMLInputElement;
  const sendButton = (region: HTMLElement) =>
    within(region).getByRole("button", { name: "Send a test to this number" }) as HTMLButtonElement;

  it("explains itself and waits for a number", async () => {
    serve();
    renderCard();
    const region = await card();

    expect(phoneField(region).placeholder).toBe("01xxxxxxxxx");
    expect(
      within(region).getByText(
        "Sends the real first question to this number now, even while questions are switched off. Answer it on that phone to try each path. Tests are not counted in the sheet.",
      ),
    ).toBeTruthy();
    expect(sendButton(region).disabled).toBe(true);
  });

  it("sends the number, and says where it went with a link to the chat", async () => {
    serve(SETTINGS, () => [200, {}], () => [200, { sent: true, phone: "201005550188", conversation_id: 42 }]);
    renderCard();
    const region = await card();

    fireEvent.change(phoneField(region), { target: { value: " 010 0555 0188 " } });
    fireEvent.click(sendButton(region));

    await waitFor(() => expect(posted).toHaveLength(1));
    expect(posted[0]).toEqual({ url: "/api/inbox/feedback/test", body: { phone: "010 0555 0188" } });
    expect(await within(region).findByText(/Sent to \+20 100 555 0188\./)).toBeTruthy();
    const link = within(region).getByRole("link", { name: "Open the chat" });
    expect(link.getAttribute("href")).toBe("/inbox/chats/42");
    expect(within(region).queryByRole("alert")).toBeNull();
  });

  it("holds back a number that is not an Egyptian mobile, before sending anything", async () => {
    serve();
    renderCard();
    const region = await card();

    const field = phoneField(region);
    fireEvent.change(field, { target: { value: "12345" } });
    expect(within(region).getByText("That is not an Egyptian mobile number. Write it like 01xxxxxxxxx.")).toBeTruthy();
    expect(field.getAttribute("aria-invalid")).toBe("true");
    expect(sendButton(region).disabled).toBe(true);

    fireEvent.submit(field.closest("form") as HTMLFormElement);
    expect(posted).toHaveLength(0);

    fireEvent.change(field, { target: { value: "01005550188" } });
    expect(field.getAttribute("aria-invalid")).toBe("false");
    expect(sendButton(region).disabled).toBe(false);
  });

  it("gives the server's own words when it refuses, and offers no chat", async () => {
    serve(SETTINGS, () => [200, {}], () => [409, { detail: "Sending is turned off." }]);
    renderCard();
    const region = await card();

    fireEvent.change(phoneField(region), { target: { value: "01005550188" } });
    fireEvent.click(sendButton(region));

    expect((await within(region).findByRole("alert")).textContent).toBe("Sending is turned off.");
    expect(within(region).queryByRole("link", { name: "Open the chat" })).toBeNull();
    // What was typed stays, so it can be sent again.
    expect(phoneField(region).value).toBe("01005550188");
  });

  it("forgets an earlier success when the next test is refused", async () => {
    const answers: [number, unknown][] = [
      [200, { sent: true, phone: "201005550188", conversation_id: 42 }],
      [409, { detail: "WhatsApp did not take it." }],
    ];
    serve(SETTINGS, () => [200, {}], () => answers.shift() as [number, unknown]);
    renderCard();
    const region = await card();

    fireEvent.change(phoneField(region), { target: { value: "01005550188" } });
    fireEvent.click(sendButton(region));
    await within(region).findByRole("link", { name: "Open the chat" });

    fireEvent.click(sendButton(region));
    expect((await within(region).findByRole("alert")).textContent).toBe("WhatsApp did not take it.");
    expect(within(region).queryByRole("link", { name: "Open the chat" })).toBeNull();
  });

  it("is not there for anyone but the owner", () => {
    serve();
    const { container } = renderCard(STAFF);

    expect(container.textContent).toBe("");
    expect(screen.queryByLabelText("Send a test")).toBeNull();
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
