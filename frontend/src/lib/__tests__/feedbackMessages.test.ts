// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiError, api } from "../api";
import {
  duplicateOptions,
  fill,
  fillTemplate,
  isChanged,
  isEdited,
  lineSent,
  messagesOf,
  usedOn,
  wordingProblem,
} from "../feedbackMessages";
import type { FlowStep, WordingItem } from "../feedbackMessages";

const placeholder = (name: string, required = false) => ({ name, meaning: name, required, example: "x" });
const item = (key: string, extra: Partial<WordingItem> = {}): WordingItem => ({
  key,
  group: "loved",
  label: key,
  help: "",
  kind: "text",
  default: "Default {name}",
  value: null,
  max: 100,
  placeholders: [placeholder("name")],
  ...extra,
});
const step = (ref: string, extra: Partial<FlowStep> = {}): FlowStep => ({
  type: "message",
  ref,
  when: "",
  options: [],
  button: null,
  with_previous: false,
  ...extra,
});

describe("fill: the preview makes the same substitution the server does", () => {
  it("replaces the words it knows, in one pass, and leaves any other brace alone", () => {
    expect(fill("Hi {name}, code {code} {other}", { name: "Sara", code: "FB-1" })).toBe("Hi Sara, code FB-1 {other}");
    // What is put in is never read as a word itself.
    expect(fill("{name}", { name: "{code}", code: "X" })).toBe("{code}");
  });

  it("drops her name with the comma or space before it when there is none", () => {
    expect(fill("Thank you, {name}! Glad.", { name: "" })).toBe("Thank you! Glad.");
    expect(fill("Thank you {name}.", { name: "" })).toBe("Thank you.");
    expect(fill("{name}, thank you", { name: "" })).toBe("thank you");
    expect(fill("{name} thank you", { name: null })).toBe("thank you");
    expect(fill("Hi {name}", {})).toBe("Hi");
  });

  it("fills the approved messages' numbered slots", () => {
    const sample = { name: "Sara", order: "#1234", code: "", percent: 20, days: 30, hours: 24, url: null };
    expect(fillTemplate("Hi {{1}}, your order {{2}} came.", sample)).toBe("Hi Sara, your order #1234 came.");
    expect(fillTemplate("About your order {{1}}: solved?", sample)).toBe("About your order #1234: solved?");
  });
});

describe("wordingProblem mirrors what the server refuses", () => {
  it("accepts the built-in words, an empty box, and words within the limit", () => {
    expect(wordingProblem(item("a"), "Default {name}")).toBeNull();
    expect(wordingProblem(item("a"), "   ")).toBeNull();
    expect(wordingProblem(item("a"), "Fine.")).toBeNull();
  });

  it("refuses too long, a word the message may not use, and a missing required one", () => {
    expect(wordingProblem(item("a", { max: 5 }), "abcdefgh")).toMatch(/3 characters too long/);
    expect(wordingProblem(item("a"), "Hi {nick}")).toMatch(/\{nick\} cannot be used here; this message can use \{name\}/);
    expect(wordingProblem(item("a", { placeholders: [] }), "Hi {name}")).toMatch(/this one is plain words/);
    const code = item("a", { placeholders: [placeholder("name"), placeholder("code", true)] });
    expect(wordingProblem(code, "No code")).toBe("This message must contain {code}, or the customer never sees her code.");
    expect(wordingProblem(code, "Yes {code}")).toBeNull();
  });

  it("counts the longest her name, code and link can come out", () => {
    // 9 characters typed, but {name} can be 40 long.
    expect(wordingProblem(item("a", { max: 30 }), "Hi {name}")).toMatch(
      /Too long once her name, code or link are filled in/,
    );
  });

  it("keeps a button or list row to one line", () => {
    expect(wordingProblem(item("a", { kind: "label", placeholders: [] }), "one\ntwo")).toBe("This must be on one line.");
  });
});

describe("what changed", () => {
  it("compares with the saved wording for changed and the built-in for edited", () => {
    const saved = item("a", { value: "Saved" });
    expect(isChanged(saved, "Saved")).toBe(false);
    expect(isChanged(saved, "  Saved \n")).toBe(false);
    expect(isChanged(saved, "Other")).toBe(true);
    expect(isEdited(saved, "Saved")).toBe(true);
    // Blank means the built-in wording.
    expect(isChanged(saved, "")).toBe(true);
    expect(isEdited(saved, "")).toBe(false);
    expect(isChanged(item("b"), "Default {name}")).toBe(false);
  });
});

describe("two options the same", () => {
  it("flags the option that was typed over, counting the built-in titles of the others", () => {
    const options = [
      item("reason_option.loved.a", { default: "Quality", kind: "label", placeholders: [] }),
      item("reason_option.loved.b", { default: "Fit", kind: "label", placeholders: [] }),
      item("reason_option.okay.a", { default: "Quality", kind: "label", placeholders: [] }),
    ];
    const found = duplicateOptions(options, {
      "reason_option.loved.a": "Quality",
      "reason_option.loved.b": "quality",
      "reason_option.okay.a": "Quality",
    });
    // Only the one typed over; and the same title in another list is fine.
    expect(Object.keys(found)).toEqual(["reason_option.loved.b"]);
  });
});

describe("the paths", () => {
  it("joins a step to the one before it, and says where each message is used", () => {
    const flows = {
      loved: [step("q", { options: ["o1"], button: "btn" }), step("thanks"), step("code", { with_previous: true })],
      okay: [step("thanks2"), step("code", { with_previous: true })],
    };
    expect(messagesOf(flows.loved).map((group) => group.map((one) => one.ref))).toEqual([["q"], ["thanks", "code"]]);
    expect(usedOn(flows)).toEqual({
      q: ["loved"],
      o1: ["loved"],
      btn: ["loved"],
      thanks: ["loved"],
      code: ["loved", "okay"],
      thanks2: ["okay"],
    });
  });

  it("knows which lines the sample customer would not be sent", () => {
    const sample = { name: "Sara", order: "#1", code: "C", percent: 20, days: 30, hours: 24, url: null };
    const linked = { ...sample, url: "https://g.page/x" };
    expect(lineSent("loved", step("review_line"), sample).sent).toBe(false);
    expect(lineSent("loved", step("review_line"), linked).sent).toBe(true);
    expect(lineSent("loved", step("invitation"), sample).sent).toBe(true);
    expect(lineSent("loved", step("invitation"), linked).sent).toBe(false);
    expect(lineSent("okay", step("invitation"), linked).sent).toBe(true);
    expect(lineSent("loved", step("tell_us"), sample).sent).toBe(false);
  });
});

describe("api: a refusal that names fields", () => {
  afterEach(() => vi.unstubAllGlobals());

  const answer = (status: number, body: unknown) =>
    vi.stubGlobal(
      "fetch",
      vi.fn(() =>
        Promise.resolve({
          ok: false,
          status,
          headers: { get: () => "application/json" },
          text: () => Promise.resolve(JSON.stringify(body)),
        }),
      ),
    );

  const refused = (): Promise<ApiError> =>
    api.put("/x", {}).then(
      () => {
        throw new Error("It was not refused.");
      },
      (error: ApiError) => error,
    );

  it("carries each field's reason on the error", async () => {
    answer(422, { detail: { errors: { a: "Too long.", b: "Not allowed." } } });
    const caught = await refused();
    expect(caught).toBeInstanceOf(ApiError);
    expect(caught.status).toBe(422);
    expect(caught.fieldErrors).toEqual({ a: "Too long.", b: "Not allowed." });
    expect(caught.message).toBe("Some of it could not be saved.");
  });

  it("changes nothing for the answers every other screen already reads", async () => {
    answer(422, { detail: "Plain words." });
    let caught = await refused();
    expect(caught.message).toBe("Plain words.");
    expect(caught.fieldErrors).toBeUndefined();

    answer(422, { detail: [{ loc: ["body"], msg: "bad" }] });
    caught = await refused();
    expect(caught.message).toBe("The platform returned 422.");
    expect(caught.fieldErrors).toBeUndefined();

    answer(500, { detail: { errors: { a: 5 } } });
    caught = await refused();
    expect(caught.message).toBe("The platform returned 500.");
    expect(caught.fieldErrors).toBeUndefined();
  });
});
