// @vitest-environment jsdom
/**
 * Inbox → Feedback setup (ADR 0083): the status and settings at the top, and
 * the editor for the wording of every message. Every name, number and word
 * here is made up; the shape is what `GET /api/inbox/feedback/messages`
 * answers.
 */
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { FlowStep, WordingBody, WordingItem } from "../../../lib/feedbackMessages";
import { FeedbackSetup } from "../FeedbackSetup";

const reply = (status: number, body: unknown) =>
  Promise.resolve({
    ok: status < 400,
    status,
    headers: { get: () => "application/json" },
    json: () => Promise.resolve(body),
    text: () => Promise.resolve(JSON.stringify(body)),
  } as unknown as Response);

const NAME = { name: "name", meaning: "Her first name", required: false, example: "Sara" };
const CODE = { name: "code", meaning: "Her personal code", required: true, example: "FB-7K2M9Q" };
const URL_ = { name: "url", meaning: "Your review link", required: true, example: "https://example.com/review" };
const PERCENT = { name: "percent", meaning: "The discount, in percent", required: false, example: "20" };

function item(
  key: string,
  group: string,
  label: string,
  defaultWords: string,
  extra: Partial<WordingItem> = {},
): WordingItem {
  return {
    key,
    group,
    label,
    help: `About ${label}.`,
    kind: "text",
    default: defaultWords,
    value: null,
    max: 1000,
    placeholders: [],
    ...extra,
  };
}

const ITEMS: WordingItem[] = [
  item("reason_question.loved", "loved", "Question: what she liked most", "What did you like most?", { max: 1024 }),
  item("reason_option.loved.quality", "loved", "List option: Quality", "Quality", { kind: "label", max: 24 }),
  item("reason_option.loved.fit", "loved", "List option: Fit", "Fit", { kind: "label", max: 24 }),
  item("thanks.loved", "loved", "Thank-you line", "Thank you, {name}! We're so glad you loved it.", {
    placeholders: [NAME],
  }),
  item("review_line", "loved", "Review request", "Would you share a review?\n{url}", {
    placeholders: [NAME, URL_],
  }),
  item("thanks.okay", "okay", "Thank-you line (okay)", "Thank you, {name}. Your answer helps.", {
    placeholders: [NAME],
  }),
  item("support", "unhappy", "Promise of a person", "We're sorry, {name}. Someone will write within 24 hours.", {
    placeholders: [NAME],
  }),
  item("list_label", "shared", "Button that opens the list", "Choose one", { kind: "label", max: 20 }),
  item("code_line", "shared", "Her code", "Here is {percent}% off:\n{code}", {
    placeholders: [NAME, PERCENT, CODE],
  }),
  item("invitation", "shared", "Invitation to write", "If there is anything we could do better, just reply here."),
];

const step = (ref: string, when: string, extra: Partial<FlowStep> = {}): FlowStep => ({
  type: "message",
  ref,
  when,
  options: [],
  button: null,
  with_previous: false,
  ...extra,
});
const first: FlowStep = {
  type: "template",
  ref: "order_feedback",
  when: "Two days after the order is delivered",
  options: [],
  button: null,
  with_previous: false,
};

function wording(extra: Partial<WordingBody> = {}, items: WordingItem[] = ITEMS): WordingBody {
  return {
    can_edit: true,
    groups: [
      { id: "loved", title: "Loved it" },
      { id: "okay", title: "It was okay" },
      { id: "unhappy", title: "Not happy" },
      { id: "shared", title: "Used on more than one path" },
    ],
    items,
    templates: [
      {
        name: "order_feedback",
        body: "Hi {{1}}, your HBA Wear order {{2}} has been delivered. How was it?",
        buttons: ["Loved it", "It was okay", "Not happy"],
        note: "Approved by Meta. It can only be changed in Meta's WhatsApp Manager.",
      },
      {
        name: "feedback_resolved",
        body: "About your HBA Wear order {{1}}: was your issue solved?",
        buttons: ["Yes", "No"],
        note: "Approved by Meta. It is sent instead of the chat question.",
      },
    ],
    flows: {
      loved: [
        first,
        step("reason_question.loved", "Right after her first answer", {
          options: ["reason_option.loved.quality", "reason_option.loved.fit"],
          button: "list_label",
        }),
        step("thanks.loved", "After she picks a reason"),
        step("code_line", "If her code could be made", { with_previous: true }),
        step("review_line", "Only if a review link is set", { with_previous: true }),
        step("invitation", "Unless a review link is set", { with_previous: true }),
      ],
      okay: [
        first,
        step("thanks.okay", "After she picks a reason"),
        step("code_line", "If her code could be made", { with_previous: true }),
        step("invitation", "Unless she chose Something else", { with_previous: true }),
      ],
      unhappy: [
        first,
        step("support", "After she picks a reason"),
        { ...first, ref: "feedback_resolved", when: "Instead of the question above, when her 24 hours have closed" },
      ],
    },
    sample: { name: "Sara", order: "#1234", code: "FB-7K2M9Q", percent: 20, days: 30, hours: 24, url: null },
    ...extra,
  };
}

const SETTINGS = {
  enabled: true,
  started_at: "2026-11-05T09:00:00+00:00",
  review_url: null,
  reply_hours: 24,
  codes_ready: { ready: false, reason: "No permission yet." },
};

let fetchMock: ReturnType<typeof vi.fn>;
let puts: { url: string; body: Record<string, unknown> }[] = [];
let posts: { url: string; body: Record<string, unknown> }[] = [];

type Routes = {
  messages?: [number, unknown];
  putMessages?: (body: { values: Record<string, string | null> }) => [number, unknown];
  settings?: [number, unknown];
  putSettings?: (body: Record<string, unknown>) => [number, unknown];
  post?: [number, unknown];
};

function serve(routes: Routes = {}) {
  puts = [];
  posts = [];
  fetchMock.mockImplementation((url: string, init?: RequestInit) => {
    const method = init?.method ?? "GET";
    const body = init?.body ? JSON.parse(String(init.body)) : undefined;
    if (url === "/api/inbox/feedback/messages") {
      if (method === "PUT") {
        puts.push({ url, body });
        const [status, answer] = routes.putMessages ? routes.putMessages(body) : [200, wording()];
        return reply(status, answer);
      }
      const [status, answer] = routes.messages ?? [200, wording()];
      return reply(status, answer);
    }
    if (url === "/api/inbox/feedback/settings") {
      if (method === "PUT") {
        puts.push({ url, body });
        const [status, answer] = routes.putSettings ? routes.putSettings(body) : [200, SETTINGS];
        return reply(status, answer);
      }
      const [status, answer] = routes.settings ?? [200, SETTINGS];
      return reply(status, answer);
    }
    if (url === "/api/inbox/feedback/test") {
      posts.push({ url, body });
      const [status, answer] = routes.post ?? [200, { sent: true, phone: "201005550188", conversation_id: 42 }];
      return reply(status, answer);
    }
    return reply(404, { detail: "no such route" });
  });
}

const renderPage = () =>
  render(
    <MemoryRouter initialEntries={["/inbox/feedback/setup"]}>
      <FeedbackSetup />
    </MemoryRouter>,
  );

beforeEach(() => {
  fetchMock = vi.fn();
  vi.stubGlobal("fetch", fetchMock);
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

const preview = () => screen.getByRole("group", { name: "How this path looks in WhatsApp" });
const field = (label: string) => screen.getByLabelText(label) as HTMLTextAreaElement | HTMLInputElement;
const ready = async () => {
  await screen.findByRole("tablist");
};
const type = (label: string, value: string) => fireEvent.change(field(label), { target: { value } });
const addButton = (label: string, name: RegExp | string) =>
  within(screen.getByRole("group", { name: `Add words to “${label}”` })).getByRole("button", { name });
const saveButton = () => screen.getByRole("button", { name: "Save" }) as HTMLButtonElement;

describe("the page", () => {
  it("shows status, then the review link, then the test, then the editor, in that order", async () => {
    serve();
    renderPage();
    await ready();

    const headings = screen.getAllByRole("heading", { level: 2 }).map((heading) => heading.textContent);
    expect(headings).toEqual(["Status", "Review link and reply time", "Send a test", "What customers are sent"]);
    expect(screen.getByRole("heading", { level: 1, name: "Feedback setup" })).toBeTruthy();
    expect(screen.getByRole("link", { name: /Back to the answers/ }).getAttribute("href")).toBe("/inbox/feedback");
    expect(screen.getByText("On · asking since 5 Nov")).toBeTruthy();
    expect(screen.getByText("Reward codes cannot be made yet. No permission yet.")).toBeTruthy();
  });

  it("is read-only for somebody who cannot edit: everything shown, nothing to change, one line saying why", async () => {
    serve({ messages: [200, wording({ can_edit: false })] });
    renderPage();
    await ready();

    expect(screen.getByText(/Only an admin can change these settings or send a test/)).toBeTruthy();
    expect(screen.queryByRole("button", { name: /^Change/ })).toBeNull();
    expect(screen.queryByRole("heading", { name: "Send a test" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Save" })).toBeNull();
    expect(screen.queryByRole("button", { name: /Her first name/ })).toBeNull();
    expect(field("Thank-you line").readOnly).toBe(true);
    // The wording itself is all there to read.
    expect(field("Thank-you line").value).toContain("so glad you loved it");
    expect(within(preview()).getByText(/Thank you, Sara! We're so glad/)).toBeTruthy();
  });

  it("says so, with a way to try again, when the wording cannot be read", async () => {
    serve({ messages: [500, { detail: "Something broke on our side." }] });
    renderPage();

    expect((await screen.findByRole("alert")).textContent).toContain("Something broke on our side.");
    serve();
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByRole("tablist")).toBeTruthy();
  });
});

describe("the three paths", () => {
  it("are tabs, in the order the server gives them, and each shows its own conversation", async () => {
    serve();
    renderPage();
    await ready();

    const tabs = screen.getAllByRole("tab").map((tab) => tab.textContent);
    expect(tabs).toEqual(["Loved it", "It was okay", "Not happy"]);
    expect(screen.getByRole("tab", { name: "Loved it" }).getAttribute("aria-selected")).toBe("true");
    expect(field("Question: what she liked most")).toBeTruthy();
    expect(screen.getAllByText("Right after her first answer").length).toBeGreaterThan(0);
    expect(screen.queryByLabelText("Promise of a person")).toBeNull();

    fireEvent.click(screen.getByRole("tab", { name: "Not happy" }));
    expect(field("Promise of a person")).toBeTruthy();
    expect(screen.queryByLabelText("Question: what she liked most")).toBeNull();
  });

  it("move with the arrow keys, Home and End", async () => {
    serve();
    renderPage();
    await ready();

    const list = screen.getByRole("tablist");
    fireEvent.keyDown(list, { key: "ArrowRight" });
    expect(screen.getByRole("tab", { name: "It was okay" }).getAttribute("aria-selected")).toBe("true");
    fireEvent.keyDown(list, { key: "End" });
    expect(screen.getByRole("tab", { name: "Not happy" }).getAttribute("aria-selected")).toBe("true");
    fireEvent.keyDown(list, { key: "ArrowRight" });
    expect(screen.getByRole("tab", { name: "Loved it" }).getAttribute("aria-selected")).toBe("true");
    fireEvent.keyDown(list, { key: "ArrowLeft" });
    expect(screen.getByRole("tab", { name: "Not happy" }).getAttribute("aria-selected")).toBe("true");
    // Only the chosen tab is in the tab order.
    expect(screen.getByRole("tab", { name: "Loved it" }).getAttribute("tabindex")).toBe("-1");
    expect(screen.getByRole("tabpanel").getAttribute("aria-labelledby")).toBe(
      screen.getByRole("tab", { name: "Not happy" }).id,
    );
  });

  it("show the two approved messages as locked, with their notes, and say when the second goes out", async () => {
    serve();
    renderPage();
    await ready();

    expect(screen.getByText(/Approved by Meta. It can only be changed in Meta's WhatsApp Manager/)).toBeTruthy();
    fireEvent.click(screen.getByRole("tab", { name: "Not happy" }));
    expect(screen.getByText(/Approved by Meta. It is sent instead of the chat question/)).toBeTruthy();
    expect(
      screen.getByText(/goes out instead of the question above when more than 24 hours have passed since her last message/),
    ).toBeTruthy();
    // Locked: no field for either.
    expect(screen.queryByLabelText(/Was your issue solved/)).toBeNull();
  });
});

describe("a field", () => {
  it("updates its counter and the preview as it is typed in", async () => {
    serve();
    renderPage();
    await ready();

    const area = field("Thank-you line");
    expect(within(preview()).getByText(/Thank you, Sara! We're so glad you loved it\./)).toBeTruthy();
    type("Thank-you line", "Wonderful, {name}!");
    expect(within(preview()).getByText("Wonderful, Sara!")).toBeTruthy();
    expect(area.value).toBe("Wonderful, {name}!");
    expect(document.getElementById("fbs-f-thanks.loved-count")?.textContent).toContain("18 / 1000");
    expect(screen.getAllByText("Edited").length).toBeGreaterThan(0);
  });

  it("warns near the limit and refuses over it, under the field", async () => {
    serve();
    renderPage();
    await ready();

    type("Button that opens the list", "x".repeat(19));
    expect(document.getElementById("fbs-f-list_label-count")?.className).toContain("fbs-count--near");
    type("Button that opens the list", "x".repeat(23));
    expect(document.getElementById("fbs-f-list_label-count")?.className).toContain("fbs-count--over");
    expect(screen.getByText(/3 characters too long. WhatsApp allows at most 20 here/)).toBeTruthy();
    expect(field("Button that opens the list").getAttribute("aria-invalid")).toBe("true");
    expect(saveButton().disabled).toBe(true);
  });

  it("puts a word in at the cursor, with her name as a button", async () => {
    serve();
    renderPage();
    await ready();

    const area = field("Thank-you line") as HTMLTextAreaElement;
    // "Thank you, {name}! ..." with the cursor after "Thank "
    area.setSelectionRange(6, 6);
    fireEvent.click(addButton("Thank-you line", /Her first name/));
    expect(area.value).toBe("Thank {name}you, {name}! We're so glad you loved it.");
    expect(area.selectionStart).toBe(6 + "{name}".length);
  });

  it("replaces what is selected when a word is put in", async () => {
    serve();
    renderPage();
    await ready();

    const area = field("Thank-you line") as HTMLTextAreaElement;
    area.setSelectionRange(11, 17); // "{name}" in "Thank you, {name}!"
    fireEvent.click(addButton("Thank-you line", /Her first name/));
    expect(area.value).toBe("Thank you, {name}! We're so glad you loved it.");
  });

  it("marks the words that must be there, and blocks Save when one is missing", async () => {
    serve();
    renderPage();
    await ready();

    const buttons = within(screen.getByRole("group", { name: "Add words to “Her code”" }));
    expect(buttons.getByRole("button", { name: /Her personal code \(needed\)/ })).toBeTruthy();
    expect(buttons.getByRole("button", { name: "Her first name" })).toBeTruthy();

    type("Her code", "Here is a discount for you.");
    expect(screen.getByText(/This message must contain \{code\}, or the customer never sees her code\./)).toBeTruthy();
    expect(field("Her code").getAttribute("aria-invalid")).toBe("true");
    expect(saveButton().disabled).toBe(true);
    expect(screen.getByText(/1 needs fixing before it can be saved/)).toBeTruthy();

    // The button puts it back.
    fireEvent.click(buttons.getByRole("button", { name: /Her personal code/ }));
    expect(saveButton().disabled).toBe(false);
  });

  it("refuses a word the message may not use", async () => {
    serve();
    renderPage();
    await ready();

    type("Thank-you line", "Thank you {nickname}");
    expect(screen.getByText(/\{nickname\} cannot be used here; this message can use \{name\}\./)).toBeTruthy();
    expect(saveButton().disabled).toBe(true);
  });

  it("refuses two options in one list that read the same", async () => {
    serve();
    renderPage();
    await ready();

    type("List option: Quality", "fit");
    expect(screen.getAllByText(/is already called “fit”/).length).toBeGreaterThan(0);
    expect(saveButton().disabled).toBe(true);
  });

  it("offers the original wording only when it differs, and putting it back sends null", async () => {
    serve({
      messages: [
        200,
        wording({}, ITEMS.map((entry) => (entry.key === "invitation" ? { ...entry, value: "Reply any time." } : entry))),
      ],
    });
    renderPage();
    await ready();

    // Edited already: it offers the way back, and the others do not.
    expect(screen.getAllByRole("button", { name: /Use the original wording/ })).toHaveLength(1);
    expect(field("Invitation to write").value).toBe("Reply any time.");
    fireEvent.click(screen.getByRole("button", { name: /Use the original wording/ }));
    expect(field("Invitation to write").value).toContain("If there is anything we could do better");
    expect(screen.queryByRole("button", { name: /Use the original wording/ })).toBeNull();

    fireEvent.click(saveButton());
    await waitFor(() => expect(puts).toHaveLength(1));
    expect(puts[0].body).toEqual({ values: { invitation: null } });
  });

  it("says where else a shared message is used", async () => {
    serve();
    renderPage();
    await ready();

    expect(screen.getAllByText("Also used on: It was okay").length).toBeGreaterThan(0);
    // Used on one path only: nothing said.
    const thanks = document.getElementById("fbs-f-thanks.loved");
    expect(thanks?.parentElement?.textContent).not.toContain("Also used on");
  });
});

describe("the preview", () => {
  it("joins lines sent together into one bubble, and dims what would not be sent", async () => {
    serve();
    renderPage();
    await ready();

    const bubbles = preview().querySelectorAll(".fbs-wa__bubble");
    // The first question (locked), the list question, then ONE bubble for thanks + code + review + invitation.
    expect(bubbles).toHaveLength(3);
    const joined = bubbles[2] as HTMLElement;
    expect(joined.querySelectorAll(".fbs-wa__line")).toHaveLength(4);
    expect(joined.textContent).toContain("Thank you, Sara!");
    expect(joined.textContent).toContain("Here is 20% off:");
    expect(joined.textContent).toContain("FB-7K2M9Q");
    // No review link is set: that line is shown, but not as one that goes out.
    const off = joined.querySelector(".fbs-wa__line--off") as HTMLElement;
    expect(off.textContent).toContain("Would you share a review?");
    expect(off.textContent).toContain("Not sent until a review link is set");
    // With no link the invitation does go out in its place.
    expect(joined.textContent).toContain("If there is anything we could do better");
  });

  it("shows the list question with its button and the choices under it", async () => {
    serve();
    renderPage();
    await ready();

    const view = within(preview());
    expect(view.getByText("What did you like most?")).toBeTruthy();
    expect(view.getAllByText("Choose one").length).toBeGreaterThan(0);
    expect(view.getByText("Quality")).toBeTruthy();
    expect(view.getByText("Fit")).toBeTruthy();
    type("List option: Quality", "Great quality");
    expect(view.getByText("Great quality")).toBeTruthy();
  });

  it("leaves her name out cleanly when we do not know it", async () => {
    serve();
    renderPage();
    await ready();

    fireEvent.click(screen.getByLabelText("Show it as if we do not know her name"));
    expect(within(preview()).getByText(/^Thank you! We're so glad you loved it\./)).toBeTruthy();
  });

  it("shows the approved first question filled in from the sample, locked", async () => {
    serve();
    renderPage();
    await ready();

    expect(within(preview()).getByText("Hi Sara, your HBA Wear order #1234 has been delivered. How was it?")).toBeTruthy();
    expect(within(preview()).getAllByText("Approved by Meta").length).toBeGreaterThan(0);
  });

  it("draws each message under its own field where the screen is narrow", async () => {
    vi.stubGlobal("matchMedia", () => ({ matches: false, addEventListener() {}, removeEventListener() {} }));
    serve();
    renderPage();
    await ready();

    expect(screen.queryByRole("group", { name: "How this path looks in WhatsApp" })).toBeNull();
    expect(document.querySelectorAll(".fbs-wa--inline").length).toBeGreaterThan(3);
  });

  it("uses a review link, when one is set, instead of the invitation", async () => {
    serve({
      messages: [
        200,
        wording({ sample: { name: "Sara", order: "#1234", code: "FB-1", percent: 20, days: 30, hours: 24, url: "https://g.page/hba" } }),
      ],
    });
    renderPage();
    await ready();

    const joined = preview().querySelectorAll(".fbs-wa__bubble")[2] as HTMLElement;
    expect(joined.textContent).toContain("https://g.page/hba");
    expect((joined.querySelector(".fbs-wa__line--off") as HTMLElement).textContent).toContain(
      "the review request takes its place",
    );
  });
});

describe("saving", () => {
  it("shows nothing to save until something changes, then counts the changes", async () => {
    serve();
    renderPage();
    await ready();

    expect(screen.queryByRole("button", { name: "Save" })).toBeNull();
    type("Thank-you line", "Hello {name}");
    type("Invitation to write", "Reply any time.");
    expect(screen.getByText("2 messages changed")).toBeTruthy();
    expect(screen.getByRole("tab", { name: /Loved it/ }).textContent).toContain("2");
  });

  it("sends only the keys that changed, and shows what the server answers", async () => {
    serve({
      putMessages: () => [
        200,
        wording({}, ITEMS.map((entry) => (entry.key === "thanks.loved" ? { ...entry, value: "Hello {name}" } : entry))),
      ],
    });
    renderPage();
    await ready();

    type("Thank-you line", "  Hello {name}  ");
    type("Invitation to write", "If there is anything we could do better, just reply here.");
    fireEvent.click(saveButton());

    await waitFor(() => expect(puts).toHaveLength(1));
    expect(puts[0].url).toBe("/api/inbox/feedback/messages");
    expect(puts[0].body).toEqual({ values: { "thanks.loved": "Hello {name}" } });
    expect(await screen.findByText(/Saved\. Customers get this wording from now on\./)).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Save" })).toBeNull();
    expect(field("Thank-you line").value).toBe("Hello {name}");
  });

  it("puts a field's server error under it, scrolls to it and focuses it, and keeps what was typed", async () => {
    const scroll = vi.fn();
    Element.prototype.scrollIntoView = scroll;
    serve({
      putMessages: () => [
        422,
        { detail: { errors: { "thanks.loved": "WhatsApp would refuse this one.", support: "And this one too." } } },
      ],
    });
    renderPage();
    await ready();

    type("Thank-you line", "Hello again {name}");
    fireEvent.click(saveButton());

    expect(await screen.findByText("WhatsApp would refuse this one.")).toBeTruthy();
    expect(field("Thank-you line").getAttribute("aria-invalid")).toBe("true");
    expect(document.getElementById("fbs-f-thanks.loved-problem")?.getAttribute("aria-live")).toBe("polite");
    expect(document.activeElement).toBe(field("Thank-you line"));
    expect(scroll).toHaveBeenCalled();
    expect(field("Thank-you line").value).toBe("Hello again {name}");
    expect(screen.getByRole("alert").textContent).toContain("2 messages could not be saved");

    // The one on another path is shown when she gets there.
    fireEvent.click(screen.getByRole("tab", { name: "Not happy" }));
    expect(screen.getByText("And this one too.")).toBeTruthy();

    // Typing in the refused field clears its error.
    fireEvent.click(screen.getByRole("tab", { name: /Loved it/ }));
    type("Thank-you line", "Hello again {name}!");
    expect(screen.queryByText("WhatsApp would refuse this one.")).toBeNull();
  });

  it("goes to the path that holds a refused message when it is not the one open", async () => {
    Element.prototype.scrollIntoView = vi.fn();
    serve({ putMessages: () => [422, { detail: { errors: { support: "Refused." } } }] });
    renderPage();
    await ready();

    type("Thank-you line", "Hello {name}");
    fireEvent.click(saveButton());

    await screen.findByText("Refused.");
    expect(screen.getByRole("tab", { name: /Not happy/ }).getAttribute("aria-selected")).toBe("true");
    await waitFor(() => expect(document.activeElement).toBe(field("Promise of a person")));
  });

  it("says what the server said when a save fails for any other reason", async () => {
    serve({ putMessages: () => [403, { detail: "Only an admin can do that." }] });
    renderPage();
    await ready();

    type("Thank-you line", "Hello {name}");
    fireEvent.click(saveButton());
    expect((await screen.findByRole("alert")).textContent).toContain("Only an admin can do that.");
  });

  it("discards back to what is saved", async () => {
    serve();
    renderPage();
    await ready();

    type("Thank-you line", "Hello {name}");
    fireEvent.click(screen.getByRole("button", { name: "Discard" }));
    expect(field("Thank-you line").value).toContain("so glad you loved it");
    expect(screen.queryByRole("button", { name: "Save" })).toBeNull();
    expect(puts).toHaveLength(0);
  });

  it("keeps edits when moving between the paths", async () => {
    serve();
    renderPage();
    await ready();

    type("Her code", "Take {percent}% off with {code}");
    fireEvent.click(screen.getByRole("tab", { name: /It was okay/ }));
    // The same message, on the other path, with the edit and a note that it is shared.
    expect(field("Her code").value).toBe("Take {percent}% off with {code}");
    expect(screen.getAllByText("Also used on: Loved it").length).toBeGreaterThan(0);
  });
});

describe("leaving with unsaved changes", () => {
  it("asks the browser before the tab closes, only while something is unsaved", async () => {
    serve();
    renderPage();
    await ready();

    const clean = new Event("beforeunload", { cancelable: true });
    window.dispatchEvent(clean);
    expect(clean.defaultPrevented).toBe(false);

    type("Thank-you line", "Hello {name}");
    const dirty = new Event("beforeunload", { cancelable: true });
    window.dispatchEvent(dirty);
    expect(dirty.defaultPrevented).toBe(true);
  });

  it("asks before a link inside the app is followed, and stays when the answer is no", async () => {
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(false);
    serve();
    renderPage();
    await ready();

    const back = screen.getByRole("link", { name: /Back to the answers/ });
    // Nothing unsaved: follows without asking.
    const free = new MouseEvent("click", { bubbles: true, cancelable: true, button: 0 });
    back.dispatchEvent(free);
    expect(confirm).not.toHaveBeenCalled();
    expect(free.defaultPrevented).toBe(true); // the router handled it, as it does

    type("Thank-you line", "Hello {name}");
    const click = new MouseEvent("click", { bubbles: true, cancelable: true, button: 0 });
    back.dispatchEvent(click);
    expect(confirm).toHaveBeenCalledTimes(1);
    expect(confirm.mock.calls[0][0]).toMatch(/not saved/);
    expect(click.defaultPrevented).toBe(true);
    expect(field("Thank-you line").value).toBe("Hello {name}");
  });

  it("lets the link through when the answer is yes", async () => {
    vi.spyOn(window, "confirm").mockReturnValue(true);
    serve();
    renderPage();
    await ready();

    type("Thank-you line", "Hello {name}");
    const back = screen.getByRole("link", { name: /Back to the answers/ });
    const seen = vi.fn((event: Event) => event.defaultPrevented);
    back.addEventListener("click", (event) => {
      seen(event);
      // The router's own handler would run here; jsdom has no navigation, so stop it.
      event.preventDefault();
    });
    act(() => {
      back.dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true, button: 0 }));
    });
    expect(seen).toHaveBeenCalled();
    expect(seen.mock.results[0].value).toBe(false);
  });
});

describe("the status and settings at the top", () => {
  const link = () => screen.getByLabelText("Review link") as HTMLInputElement;
  const hours = () => screen.getByLabelText(/Reply time promised/) as HTMLInputElement;
  const change = () => screen.getByRole("button", { name: /^Change/ });

  it("shows the review link and the promised reply time, and says when codes can be made", async () => {
    serve({
      settings: [
        200,
        { ...SETTINGS, review_url: "https://g.page/r/hba/review", reply_hours: 1, codes_ready: { ready: true, reason: null } },
      ],
    });
    renderPage();
    await ready();

    expect(await screen.findByText("https://g.page/r/hba/review")).toBeTruthy();
    expect(screen.getByText("1 hour")).toBeTruthy();
    expect(screen.getByText("Reward codes can be made.")).toBeTruthy();
    expect(screen.getByText(/is done on the server, not here/)).toBeTruthy();
  });

  it("opens the two fields with what is saved, and sends only what was changed", async () => {
    serve({
      putSettings: () => [
        200,
        { enabled: true, started_at: SETTINGS.started_at, review_url: "https://g.page/r/hba/review", reply_hours: 24 },
      ],
    });
    renderPage();
    await ready();
    await screen.findByText("not set");

    fireEvent.click(change());
    expect(link().value).toBe("");
    expect(hours().value).toBe("24");
    expect((screen.getByRole("button", { name: "Save" }) as HTMLButtonElement).disabled).toBe(true);

    fireEvent.change(link(), { target: { value: " https://g.page/r/hba/review " } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() => expect(puts).toHaveLength(1));
    expect(puts[0]).toEqual({ url: "/api/inbox/feedback/settings", body: { review_url: "https://g.page/r/hba/review" } });
    expect(await screen.findByText("Saved.")).toBeTruthy();
    expect(screen.getByText("https://g.page/r/hba/review")).toBeTruthy();
    // A save does not ask Shopify again: the last answer about codes stays.
    expect(screen.getByText("Reward codes cannot be made yet. No permission yet.")).toBeTruthy();
    expect(screen.queryByLabelText("Review link")).toBeNull();
  });

  it("holds back a link that is not https, and hours outside 1 to 72, before sending anything", async () => {
    serve();
    renderPage();
    await ready();
    await screen.findByText("not set");
    fireEvent.click(change());
    const save = screen.getByRole("button", { name: "Save" }) as HTMLButtonElement;

    fireEvent.change(link(), { target: { value: "http://g.page/r/hba" } });
    expect(screen.getByText("The review link must start with https:// and be a single link.")).toBeTruthy();
    expect(link().getAttribute("aria-invalid")).toBe("true");
    expect(save.disabled).toBe(true);
    fireEvent.change(link(), { target: { value: "https://g.page/r/hba" } });
    expect(save.disabled).toBe(false);

    for (const bad of ["0", "73", "soon", ""]) {
      fireEvent.change(hours(), { target: { value: bad } });
      expect(screen.getByText("Enter a whole number of hours from 1 to 72.")).toBeTruthy();
      expect(save.disabled).toBe(true);
    }
    fireEvent.submit(save.closest("form") as HTMLFormElement);
    expect(puts).toHaveLength(0);
  });

  it("gives the server's own words when it refuses a change, and closes without saving on Cancel", async () => {
    serve({ putSettings: () => [422, { detail: "The review link can be at most 500 characters." }] });
    renderPage();
    await ready();
    await screen.findByText("not set");

    fireEvent.click(change());
    fireEvent.change(hours(), { target: { value: "48" } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    expect((await screen.findByText("The review link can be at most 500 characters.")).getAttribute("role")).toBe("alert");
    expect(hours().value).toBe("48");

    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(screen.queryByLabelText(/Reply time promised/)).toBeNull();
    expect(screen.getByText("24 hours")).toBeTruthy();
  });

  it("sends a test to a number, says where it went, and gives the server's words when it refuses", async () => {
    serve();
    renderPage();
    await ready();

    const number = (await screen.findByLabelText("Number to send the test to")) as HTMLInputElement;
    const send = screen.getByRole("button", { name: "Send a test to this number" }) as HTMLButtonElement;
    expect(send.disabled).toBe(true);
    fireEvent.change(number, { target: { value: "12345" } });
    expect(screen.getByText("That is not an Egyptian mobile number. Write it like 01xxxxxxxxx.")).toBeTruthy();
    expect(send.disabled).toBe(true);

    fireEvent.change(number, { target: { value: " 010 0555 0188 " } });
    fireEvent.click(send);
    await waitFor(() => expect(posts).toHaveLength(1));
    expect(posts[0]).toEqual({ url: "/api/inbox/feedback/test", body: { phone: "010 0555 0188" } });
    expect(await screen.findByText(/Sent to \+20 100 555 0188\./)).toBeTruthy();
    expect(screen.getByRole("link", { name: "Open the chat" }).getAttribute("href")).toBe("/inbox/chats/42");

    serve({ post: [409, { detail: "Sending is turned off." }] });
    fireEvent.click(send);
    expect((await screen.findByText("Sending is turned off.")).getAttribute("role")).toBe("alert");
    expect(screen.queryByRole("link", { name: "Open the chat" })).toBeNull();
  });
});
