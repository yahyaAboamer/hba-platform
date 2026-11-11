// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { Session } from "../../../lib/api";
import { Targets, changesFor, describeYear, paceWords, problems, savedLine, WHOLE } from "../Targets";

/**
 * The Targets refinement of 10 November 2026 (docs/design-refinement/targets).
 * Each test names the finding it holds in place.
 */

const reply = (status: number, body: unknown) =>
  Promise.resolve({
    ok: status < 400,
    status,
    headers: { get: () => "application/json" },
    json: () => Promise.resolve(body),
    text: () => Promise.resolve(JSON.stringify(body)),
  } as unknown as Response);

type RowIn = Record<string, unknown>;
const row = (extra: RowIn): RowIn => ({
  affiliate_id: 1,
  name: "Hana Wagih",
  account_kind: "model",
  determines_pay: false,
  required_videos: 6,
  required_stories: 12,
  actual_videos: 6,
  actual_stories: 12,
  achieved: true,
  arrangement: "commission",
  recorded_at: "2026-11-10T10:00:00Z",
  start_month: "2026-01",
  before_start: false,
  agreed: false,
  pace: { state: "on_track", week: 2, required: 18, expected_by_now: 9, done: 18, week_started: "2026-11-08" },
  ...extra,
});

const session = {
  permissions: ["targets.record"],
  platform: { start_month: "2026-01", working_month: "2026-11", go_live_month: "2026-06" },
} as unknown as Session;

let grids: Record<string, unknown>;
let writes: { url: string; body: unknown }[];
beforeEach(() => {
  vi.useFakeTimers({ toFake: ["Date"], now: new Date("2026-11-10T10:00:00Z") });
  grids = {};
  writes = [];
  vi.stubGlobal("fetch", vi.fn((url: string, init?: RequestInit) => {
    if (init?.method && init.method !== "GET") {
      writes.push({ url: String(url), body: JSON.parse(String(init.body ?? "null")) });
      return reply(200, { saved: 0, revision: "r2", applied_to_year: [] });
    }
    const path = String(url).split("?")[0];
    if (path in grids) return reply(200, grids[path]);
    return reply(500, { detail: "no such grid" });
  }));
});
afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

const open = (month: string, rows: RowIn[]) => {
  grids[`/api/targets/${month}`] = { month, revision: "r1", rows };
  return render(
    <MemoryRouter initialEntries={[`/affiliates/targets?month=${month}`]}>
      <Routes>
        <Route path="/affiliates/targets" element={<Targets session={session} />} />
      </Routes>
    </MemoryRouter>,
  );
};

describe("T1-T3: pace only while the month runs, in plain words", () => {
  it("never shows a pace line on a finished month, so it cannot contradict the outcome", async () => {
    open("2026-10", [row({ name: "Laila Mostafa", actual_videos: 8, actual_stories: 10, achieved: false,
      pace: { state: "on_track", week: 4, required: 18, expected_by_now: 18, done: 18, week_started: "2026-10-22" } })]);
    await screen.findByText("Below target");
    expect(screen.queryByText(/on pace/i)).toBeNull();
  });

  it("says the week and how many short, not a sum that reads like the requirement", () => {
    const pace = { state: "behind", week: 2, required: 18, expected_by_now: 9, done: 6, week_started: "2026-11-08" };
    expect(paceWords(pace, false)).toBe("Week 2 · 3 short");
    expect(paceWords({ ...pace, state: "on_track", done: 12 }, false)).toBe("Week 2 · on pace");
    // A month already met cannot fall behind; the line would only repeat it.
    expect(paceWords({ ...pace, state: "on_track", done: 18 }, true)).toBeNull();
    expect(paceWords({ ...pace, state: "not_recorded_this_week" }, false)).toBe("Not updated in week 2");
    expect(paceWords(pace, null)).toBeNull();
  });
});

describe("T4-T8: a box only where a save could keep it", () => {
  it("locks a month before the platform and says why, with no false *of 0*", async () => {
    open("2026-05", [row({ required_videos: null, required_stories: null, actual_videos: null, actual_stories: null })]);
    await screen.findByText(/before the platform/);
    expect(screen.queryByRole("textbox", { name: /videos achieved/ })).toBeNull();
    expect(screen.queryByText("of 0")).toBeNull();
    expect(screen.queryByRole("button", { name: /Save/ })).toBeNull();
  });

  it("locks an agreed month's row and names it, instead of refusing the whole save", async () => {
    open("2026-10", [row({ agreed: true })]);
    await screen.findByText("Agreed in payroll");
    expect(screen.queryByRole("textbox", { name: /Hana Wagih videos/ })).toBeNull();
    expect(screen.queryByRole("button", { name: "Take a confirmation back" })).toBeNull();
  });

  it("offers no counts for a month that has not started, and points to requirements", async () => {
    open("2026-12", [row({ actual_videos: null, actual_stories: null, achieved: null })]);
    await screen.findByText(/hasn't started/);
    expect(screen.queryByRole("textbox", { name: /videos achieved/ })).toBeNull();
    expect(screen.getByText("Not started")).toBeTruthy();
    expect(screen.queryByText("No record yet")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Set requirements" }));
    expect(await screen.findByRole("textbox", { name: "Hana Wagih videos required" })).toBeTruthy();
  });

  it("asks for requirements first instead of dropping counts typed for nobody's target", async () => {
    open("2026-11", [row({ name: "Ziad Nabil", required_videos: null, required_stories: null,
      actual_videos: null, actual_stories: null, achieved: null })]);
    const act = await screen.findByRole("button", { name: "Set requirements first" });
    expect(screen.queryByRole("textbox", { name: /Ziad Nabil videos achieved/ })).toBeNull();
    fireEvent.click(act);
    expect(await screen.findByRole("textbox", { name: "Ziad Nabil videos required" })).toBeTruthy();
  });
});

describe("T11: the bad box is marked where it is", () => {
  it("marks a box that is not a whole number as it is typed", async () => {
    open("2026-11", [row({})]);
    const box = await screen.findByRole("textbox", { name: "Hana Wagih videos achieved" });
    fireEvent.change(box, { target: { value: "x" } });
    expect(box.getAttribute("aria-invalid")).toBe("true");
    const said = document.getElementById(box.getAttribute("aria-describedby")!);
    expect(said?.textContent).toBe(WHOLE);
  });

  it("refuses half a month before sending anything", async () => {
    open("2026-11", [row({ actual_videos: null, actual_stories: null, achieved: null })]);
    const box = await screen.findByRole("textbox", { name: "Hana Wagih videos achieved" });
    fireEvent.change(box, { target: { value: "3" } });
    fireEvent.click(screen.getByRole("button", { name: "Save changes" }));
    expect(await screen.findByText("Type both, or clear both")).toBeTruthy();
    expect(writes).toEqual([]);
    await new Promise((done) => requestAnimationFrame(() => requestAnimationFrame(() => done(null))));
    expect(document.activeElement?.getAttribute("aria-label")).toBe("Hana Wagih stories achieved");
  });

  it("will not let a requirement be emptied in silence", () => {
    const draft = { 1: { required_videos: "", required_stories: "", actual_videos: "", actual_stories: "" } };
    expect(problems([{ affiliate_id: 1, required_videos: 6, required_stories: 12 }], draft))
      .toEqual({ "1:required_videos": "Type 0 for nothing asked" });
  });

  it("refuses a box mistyped in the other mode instead of sending it as 0", async () => {
    open("2026-11", [row({ actual_videos: null, actual_stories: null, achieved: null })]);
    fireEvent.click(await screen.findByText("Set requirements", { exact: true }));
    fireEvent.change(screen.getByRole("textbox", { name: "Hana Wagih videos required" }), { target: { value: "8x" } });
    fireEvent.click(screen.getByText("Record achieved"));
    fireEvent.change(screen.getByRole("textbox", { name: "Hana Wagih videos achieved" }), { target: { value: "3" } });
    fireEvent.change(screen.getByRole("textbox", { name: "Hana Wagih stories achieved" }), { target: { value: "5" } });
    fireEvent.click(screen.getByRole("button", { name: "Save changes" }));
    expect(await screen.findByText("Nothing saved. Hana Wagih: whole numbers only.")).toBeTruthy();
    expect(writes).toEqual([]);
    // Taken to the box, in its own mode.
    const box = await screen.findByRole("textbox", { name: "Hana Wagih videos required" });
    expect(box.getAttribute("aria-invalid")).toBe("true");
  });

  it("still sends requirements typed before switching to Record achieved", async () => {
    open("2026-11", [row({ name: "Ziad Nabil", required_videos: null, required_stories: null,
      actual_videos: null, actual_stories: null, achieved: null })]);
    fireEvent.click(await screen.findByText("Set requirements", { exact: true }));
    fireEvent.change(screen.getByRole("textbox", { name: "Ziad Nabil videos required" }), { target: { value: "4" } });
    fireEvent.change(screen.getByRole("textbox", { name: "Ziad Nabil stories required" }), { target: { value: "8" } });
    fireEvent.click(screen.getByText("Record achieved"));
    fireEvent.click(screen.getByRole("button", { name: "Save changes" }));
    fireEvent.click(await screen.findByRole("button", { name: "Save 2 changes" }));
    await vi.waitFor(() => expect(writes.length).toBe(1));
    expect((writes[0].body as { rows: unknown[] }).rows).toEqual([expect.objectContaining({
      required_videos: 4, required_stories: 8, actual_videos: null, actual_stories: null })]);
  });

  it("clears a search that hides the marked box", async () => {
    open("2026-11", [row({}), row({ affiliate_id: 2, name: "Sara Edrees" })]);
    fireEvent.change(await screen.findByRole("textbox", { name: "Sara Edrees videos achieved" }), { target: { value: "abc" } });
    fireEvent.change(screen.getByPlaceholderText("Search model names"), { target: { value: "hana" } });
    expect(screen.queryByRole("textbox", { name: "Sara Edrees videos achieved" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Save changes" }));
    expect(await screen.findByRole("textbox", { name: "Sara Edrees videos achieved" })).toBeTruthy();
    expect(screen.getByText("Nothing saved. Sara Edrees: whole numbers only.")).toBeTruthy();
  });
});

describe("T12-T15: the export's words", () => {
  it("says a search found nobody, not that nobody is on the list", async () => {
    open("2026-11", [row({})]);
    fireEvent.change(await screen.findByPlaceholderText("Search model names"), { target: { value: "zzz" } });
    expect(screen.getByText("No model matches that search.")).toBeTruthy();
    expect(screen.queryByText(/programme/)).toBeNull();
  });

  it("says what was saved, for which month", () => {
    expect(savedLine("required", "2026-11")).toBe("Requirements saved for November 2026");
    expect(savedLine("achieved", "2026-11")).toBe("Achieved counts recorded for November 2026");
    expect(describeYear("2026", [])).toBeNull();
    expect(describeYear("2026", [{ name: "A", applied: ["2026-01", "2026-02"], skipped: [{ month: "2026-03" }] }]))
      .toBe("Requirements saved across 2 months of 2026. 1 left alone — already agreed, before the platform, or before her start.");
  });

  it("says what *Whole year* rewrites, beside the save that does it", async () => {
    open("2026-11", [row({})]);
    fireEvent.click(await screen.findByText("Set requirements"));
    fireEvent.click(screen.getByLabelText("Whole year"));
    expect(screen.getByText(/past ones included/)).toBeTruthy();
    expect(screen.getByRole("button", { name: "Save for all of 2026" })).toBeTruthy();
  });
});

describe("ADR 0081: recording is the confirmation", () => {
  it("has no confirm step anywhere", async () => {
    open("2026-11", [row({ determines_pay: true, arrangement: "base_guarantee" })]);
    await screen.findByText("Target met");
    expect(within(screen.getByRole("table")).queryByRole("checkbox")).toBeNull();
    expect(screen.queryByRole("button", { name: /Confirm/ })).toBeNull();
    expect(screen.queryByText(/Take a confirmation back|Not confirmed/)).toBeNull();
  });

  it("lists every change, and what it does, before writing anything", async () => {
    open("2026-10", [row({ determines_pay: true, arrangement: "base_guarantee" })]);
    fireEvent.change(await screen.findByRole("textbox", { name: "Hana Wagih videos achieved" }), { target: { value: "4" } });
    fireEvent.click(screen.getByRole("button", { name: "Save changes" }));

    const dialog = await screen.findByRole("dialog", { name: "Save 1 change to October 2026?" });
    expect(within(dialog).getByText("Videos achieved 6 → 4")).toBeTruthy();
    expect(within(dialog).getByText("Target met → Below target · her guaranteed minimum no longer applies")).toBeTruthy();
    expect(writes).toEqual([]);

    fireEvent.click(within(dialog).getByRole("button", { name: "Save 1 change" }));
    await vi.waitFor(() => expect(writes.length).toBe(1));
  });

  it("goes back with every box as typed, and writes nothing, on Keep editing", async () => {
    open("2026-10", [row({})]);
    const box = await screen.findByRole("textbox", { name: "Hana Wagih videos achieved" });
    fireEvent.change(box, { target: { value: "4" } });
    fireEvent.click(screen.getByRole("button", { name: "Save changes" }));
    fireEvent.click(await screen.findByRole("button", { name: "Keep editing" }));

    expect(screen.queryByRole("dialog")).toBeNull();
    expect((screen.getByRole("textbox", { name: "Hana Wagih videos achieved" }) as HTMLInputElement).value).toBe("4");
    expect(writes).toEqual([]);
  });

  it("asks the browser to hold a tab closed over unsaved figures", async () => {
    open("2026-11", [row({})]);
    const leaving = new Event("beforeunload", { cancelable: true });
    window.dispatchEvent(leaving);
    expect(leaving.defaultPrevented).toBe(false);

    fireEvent.change(await screen.findByRole("textbox", { name: "Hana Wagih videos achieved" }), { target: { value: "5" } });
    const again = new Event("beforeunload", { cancelable: true });
    window.dispatchEvent(again);
    expect(again.defaultPrevented).toBe(true);
  });

  it("names only real changes, and a turn only where the record turns", () => {
    const base = row({ actual_videos: null, actual_stories: null, achieved: null }) as never;
    const draft = { 1: { required_videos: "8", required_stories: "12", actual_videos: "", actual_stories: "" } };
    expect(changesFor([base], draft, "2026-10", "2026-11")).toEqual([
      { id: 1, name: "Hana Wagih", lines: ["Videos required 6 → 8"], turn: null },
    ]);
    // Typed back to what it was: nothing to say.
    const same = { 1: { required_videos: "06", required_stories: "12", actual_videos: "", actual_stories: "" } };
    expect(changesFor([base], same, "2026-10", "2026-11")).toEqual([]);
    // Clearing a recorded month.
    const met = row({}) as never;
    const cleared = { 1: { required_videos: "6", required_stories: "12", actual_videos: "", actual_stories: "" } };
    expect(changesFor([met], cleared, "2026-10", "2026-11")[0].turn).toBe("Target met → No record yet");
  });
});
