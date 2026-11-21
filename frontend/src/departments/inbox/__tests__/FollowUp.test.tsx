// @vitest-environment jsdom
/**
 * The follow-up of an unhappy answer (ADR 0087): its history, the waiting
 * clock and the three pop-ups. Every name, order and note here is made up.
 */
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { FollowUpActions, FollowUpHistory, WaitingClock } from "../FollowUp";
import type { FollowUpEntry } from "../../../lib/inbox";

const reply = (status: number, body: unknown) =>
  Promise.resolve({
    ok: status < 400,
    status,
    headers: { get: () => "application/json" },
    json: () => Promise.resolve(body),
    text: () => Promise.resolve(JSON.stringify(body)),
  } as unknown as Response);

let calls: { method: string; url: string; body: Record<string, unknown> | null }[] = [];

function serve(answer: (url: string) => [number, unknown] | Promise<[number, unknown]>) {
  calls = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      calls.push({ method: init?.method ?? "GET", url, body: init?.body ? JSON.parse(String(init.body)) : null });
      const [status, body] = await answer(url);
      return reply(status, body);
    }),
  );
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const survey = (extra: object = {}) => ({
  id: 7,
  order_name: "#7002",
  customer_name: "Nour Adel",
  rating: "unhappy" as const,
  reason_title: "Size / fit",
  no_answer_count: 0,
  message_sent: false,
  ...extra,
});

const entry = (id: number, extra: Partial<FollowUpEntry> = {}): FollowUpEntry => ({
  id,
  round: 0,
  kind: "no_answer",
  note: null,
  at: "2026-11-21T08:40:00+00:00",
  by_name: "Mona",
  ...extra,
});

describe("the pop-ups", () => {
  it("resolve needs a note before it can be saved", async () => {
    const updated = { id: 7, step: "reorder", follow_up_state: "resolved" };
    serve(() => [200, updated]);
    const onDone = vi.fn();
    render(<FollowUpActions survey={survey()} onDone={onDone} />);

    const opener = screen.getByRole("button", { name: "Resolved…" });
    fireEvent.click(opener);

    const dialog = screen.getByRole("dialog", { name: "Resolve #7002" });
    expect(within(dialog).getByText("Nour Adel · Not happy · Size / fit")).toBeTruthy();
    const note = within(dialog).getByLabelText(/What did you agree with her\?/);
    expect(document.activeElement).toBe(note);
    expect(dialog.textContent).toContain(
      "Tomorrow she'll get a WhatsApp message: \"Was your issue solved?\" If she says no, she comes back to To follow up.",
    );
    const save = within(dialog).getByRole("button", { name: "Save and resolve" }) as HTMLButtonElement;
    expect(save.disabled).toBe(true);
    fireEvent.change(note, { target: { value: "   " } });
    expect(save.disabled).toBe(true);
    fireEvent.change(note, { target: { value: "Exchange to L" } });
    expect(save.disabled).toBe(false);

    fireEvent.click(save);

    await waitFor(() => expect(onDone).toHaveBeenCalledWith(updated));
    expect(calls).toEqual([
      { method: "POST", url: "/api/inbox/feedback/7/resolve", body: { note: "Exchange to L" } },
    ]);
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(document.activeElement).toBe(opener);
  });

  it("the second no-answer warns about the WhatsApp message", async () => {
    serve(() => [200, { id: 7 }]);
    render(<FollowUpActions survey={survey({ no_answer_count: 1 })} onDone={() => {}} />);

    fireEvent.click(screen.getByRole("button", { name: "No answer" }));

    const dialog = screen.getByRole("dialog", { name: "No answer: #7002" });
    expect(within(dialog).getByText("This is call 2 for Nour Adel")).toBeTruthy();
    expect(within(dialog).getByLabelText("Note (optional)")).toBeTruthy();
    expect(dialog.textContent).toContain(
      "After this call she'll get a WhatsApp message from the platform: \"We tried to call you about order #7002. Reply here or tell us a good time to call.\"",
    );
    expect(within(dialog).queryByRole("checkbox")).toBeNull();
    // The note is optional: an empty one can be saved.
    fireEvent.click(within(dialog).getByRole("button", { name: "Save call" }));

    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(calls[0]).toEqual({
      method: "POST",
      url: "/api/inbox/feedback/7/no-answer",
      body: { note: null, close: false },
    });
  });

  it("the first no-answer says nothing will be sent and offers no closing", () => {
    serve(() => [200, {}]);
    render(<FollowUpActions survey={survey()} onDone={() => {}} />);
    fireEvent.click(screen.getByRole("button", { name: "No answer" }));

    const dialog = screen.getByRole("dialog", { name: "No answer: #7002" });
    expect(within(dialog).getByText("This is call 1 for Nour Adel")).toBeTruthy();
    expect(dialog.textContent).not.toContain("WhatsApp");
    expect(within(dialog).queryByRole("checkbox")).toBeNull();
  });

  it("the third offers couldn't reach, unticked", async () => {
    serve(() => [200, { id: 7, follow_up_state: "unreached" }]);
    render(<FollowUpActions survey={survey({ no_answer_count: 2, message_sent: true })} onDone={() => {}} />);

    fireEvent.click(screen.getByRole("button", { name: "No answer" }));

    const dialog = screen.getByRole("dialog", { name: "No answer: #7002" });
    expect(within(dialog).getByText("This is call 3 for Nour Adel")).toBeTruthy();
    expect(within(dialog).getByText("She has already been sent the WhatsApp message.")).toBeTruthy();
    const close = within(dialog).getByRole("checkbox", { name: /Close as Couldn't reach/ }) as HTMLInputElement;
    expect(close.checked).toBe(false);
    expect(close.closest("label")?.textContent).toBe(
      "Close as Couldn't reach. She won't be asked \"Was your issue solved?\". If she writes back within 14 days, it opens again.",
    );
    fireEvent.change(within(dialog).getByLabelText("Note (optional)"), { target: { value: " Off again " } });
    fireEvent.click(close);
    fireEvent.click(within(dialog).getByRole("button", { name: "Save call" }));

    await waitFor(() => expect(calls.length).toBe(1));
    expect(calls[0].body).toEqual({ note: "Off again", close: true });
  });

  it("add note needs words", async () => {
    serve(() => [200, { id: 7 }]);
    render(<FollowUpActions survey={survey()} onDone={() => {}} />);

    fireEvent.click(screen.getByRole("button", { name: "Add note" }));

    const dialog = screen.getByRole("dialog", { name: "Add a note: #7002" });
    const save = within(dialog).getByRole("button", { name: "Save note" }) as HTMLButtonElement;
    expect(save.disabled).toBe(true);
    fireEvent.change(within(dialog).getByLabelText(/^Note/), { target: { value: "Waiting on finance" } });
    fireEvent.click(save);

    await waitFor(() => expect(calls.length).toBe(1));
    expect(calls[0]).toEqual({
      method: "POST",
      url: "/api/inbox/feedback/7/note",
      body: { note: "Waiting on finance" },
    });
  });

  it("a refusal keeps the typed note and shows the server's words", async () => {
    serve(() => [422, { detail: "Only a follow-up that is still open can be updated." }]);
    const onDone = vi.fn();
    render(<FollowUpActions survey={survey()} onDone={onDone} />);
    fireEvent.click(screen.getByRole("button", { name: "Add note" }));
    const dialog = screen.getByRole("dialog");
    const note = within(dialog).getByLabelText(/^Note/) as HTMLTextAreaElement;
    fireEvent.change(note, { target: { value: "Spoke to her" } });

    fireEvent.click(within(dialog).getByRole("button", { name: "Save note" }));

    const alert = await within(dialog).findByRole("alert");
    expect(alert.textContent).toBe("Only a follow-up that is still open can be updated.");
    expect(note.value).toBe("Spoke to her");
    expect(note.getAttribute("aria-invalid")).toBe("true");
    expect(note.getAttribute("aria-describedby")).toContain(alert.id);
    expect((within(dialog).getByRole("button", { name: "Save note" }) as HTMLButtonElement).disabled).toBe(false);
    expect(onDone).not.toHaveBeenCalled();
  });

  it("disables both buttons while saving, and Escape or Cancel closes it", async () => {
    let finish: (value: [number, unknown]) => void = () => {};
    serve(() => new Promise((resolve) => (finish = resolve)));
    render(<FollowUpActions survey={survey()} onDone={() => {}} />);

    const opener = screen.getByRole("button", { name: "Add note" });
    fireEvent.click(opener);
    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(document.activeElement).toBe(opener);

    fireEvent.click(opener);
    fireEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Cancel" }));
    expect(screen.queryByRole("dialog")).toBeNull();

    fireEvent.click(opener);
    const dialog = screen.getByRole("dialog");
    fireEvent.change(within(dialog).getByLabelText(/^Note/), { target: { value: "Waiting" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Save note" }));

    const saving = within(dialog).getByRole("button", { name: "Saving…" }) as HTMLButtonElement;
    expect(saving.disabled).toBe(true);
    expect((within(dialog).getByRole("button", { name: "Cancel" }) as HTMLButtonElement).disabled).toBe(true);
    // Escape does not drop a save on the way.
    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.getByRole("dialog")).toBeTruthy();

    await act(async () => finish([200, { id: 7 }]));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  });
});

describe("the history", () => {
  it("history shows the newest three and opens to all", () => {
    const entries = [1, 2, 3, 4, 5].map((id) => entry(id, { note: `Call ${id}` }));
    render(<FollowUpHistory entries={entries} />);

    const items = () => screen.getAllByRole("listitem").map((item) => item.textContent);
    expect(items()).toHaveLength(3);
    expect(items()[0]).toContain("Call 3");
    expect(items()[2]).toContain("Call 5");

    fireEvent.click(screen.getByRole("button", { name: "Show all (5)" }));

    expect(items()).toHaveLength(5);
    expect(items()[0]).toContain("Call 1");
  });

  it("says each kind of entry in plain words", () => {
    const entries = [
      entry(1, { note: "Phone off" }),
      entry(2, { kind: "note", note: "Waiting on finance" }),
      entry(3, { kind: "message_sent", by_name: null }),
      entry(4, {
        kind: "message_failed",
        by_name: null,
        note: "Couldn't send the WhatsApp message: the template is not approved. Write to her yourself.",
      }),
      entry(5, { kind: "unreached" }),
      entry(6, { kind: "wrote_back", by_name: null }),
      entry(7, { kind: "returned", by_name: null, note: "The question could not be sent." }),
      entry(8, { kind: "resolved", note: "Exchange to L" }),
    ];
    render(<FollowUpHistory entries={entries} limit={20} />);

    const items = screen.getAllByRole("listitem").map((item) => item.textContent);
    expect(items).toEqual([
      "No answer · Mona · 21 Nov 10:40Phone off",
      "Note · Mona · 21 Nov 10:40Waiting on finance",
      "WhatsApp sent by the platform · 21 Nov 10:40",
      "Couldn't send the WhatsApp message: the template is not approved. Write to her yourself. · 21 Nov 10:40",
      "Closed: couldn't reach · Mona · 21 Nov 10:40",
      "She wrote back · 21 Nov 10:40",
      "Back to your team: The question could not be sent. · 21 Nov 10:40",
      "Resolved · Mona · 21 Nov 10:40Exchange to L",
    ]);
    // A send that failed is something a person must do: it is in the owed tone.
    expect(screen.getAllByRole("listitem")[3].className).toContain("inbox-fu-entry--owed");
  });

  it("a long Arabic note wraps and reads right to left", () => {
    const words = "المقاس طلع صغير جدا ومحتاجة أبدله\nاتصلت بيها مرتين والتليفون مقفول ".repeat(12).trim();
    render(<FollowUpHistory entries={[entry(1, { kind: "note", note: words })]} />);

    const note = screen.getByText((_, element) => element?.textContent === words && element.tagName === "Q");
    expect(note.getAttribute("dir")).toBe("auto");
    expect(note.className).toContain("inbox-fu-note");
  });

  it("shows nothing when nothing has been done yet", () => {
    const { container } = render(<FollowUpHistory entries={[]} />);
    expect(container.textContent).toBe("");
  });
});

describe("the waiting clock", () => {
  const now = Date.parse("2026-11-21T12:00:00+00:00");
  const ago = (minutes: number) => new Date(now - minutes * 60_000).toISOString();

  it("the clock turns past the promise after the promised hours", () => {
    const { rerender } = render(<WaitingClock since={ago(6 * 60)} hours={24} now={now} />);
    let clock = screen.getByText("Waiting 6 h · 18 h left");
    expect(clock.className).not.toContain("inbox-fu-clock--late");

    rerender(<WaitingClock since={ago(40)} hours={24} now={now} />);
    expect(screen.getByText("Waiting 40 min · 23 h left")).toBeTruthy();

    rerender(<WaitingClock since={ago(23 * 60 + 30)} hours={24} now={now} />);
    expect(screen.getByText("Waiting 23 h · 30 min left")).toBeTruthy();

    rerender(<WaitingClock since={ago(27 * 60)} hours={24} now={now} />);
    clock = screen.getByText("Waiting 27 h · past the 24 h promise");
    expect(clock.className).toContain("inbox-fu-clock--late");

    rerender(<WaitingClock since={ago(75 * 60)} hours={24} now={now} />);
    expect(screen.getByText("Waiting 3 days · past the 24 h promise")).toBeTruthy();
  });

  it("shows nothing without a start", () => {
    const { container } = render(<WaitingClock since={null} hours={24} now={now} />);
    expect(container.textContent).toBe("");
  });
});
