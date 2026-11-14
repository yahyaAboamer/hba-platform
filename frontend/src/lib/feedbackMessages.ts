/**
 * The wording of the feedback messages (ADR 0083, decision 3): the types the
 * server answers with (`GET /api/inbox/feedback/messages`), and the small
 * rules the editor mirrors so a slip is caught before it is sent.
 *
 * **The server decides.** Everything checked here is checked again there
 * (`app/modules/inbox/services/feedback_messages.py`); this only saves the
 * owner a round trip and keeps him from sending what WhatsApp would refuse.
 */

export type WordingPlaceholder = {
  name: string;
  /** In words for the owner: "Her first name". */
  meaning: string;
  required: boolean;
  example: string;
};

export type WordingItem = {
  key: string;
  group: string;
  label: string;
  help: string;
  /** "text" is a message's words; "label" is a button or a list row (one line). */
  kind: "text" | "label";
  default: string;
  /** What an admin saved; null while the built-in wording is in use. */
  value: string | null;
  max: number;
  placeholders: WordingPlaceholder[];
};

export type WordingTemplate = {
  name: string;
  body: string;
  buttons: string[];
  note: string;
};

export type FlowStep = {
  type: "template" | "message";
  /** An item key for a message, a template name for a template. */
  ref: string;
  /** In words: when this is sent. */
  when: string;
  /** Item keys: the list rows or reply buttons under the message. */
  options: string[];
  /** Item key of the button that opens the list, when it is a list. */
  button: string | null;
  /** Joined, with a blank line, into the same WhatsApp message as the step before. */
  with_previous: boolean;
};

export type WordingSample = {
  name: string;
  order: string;
  code: string;
  percent: number;
  days: number;
  hours: number;
  url: string | null;
};

export type WordingBody = {
  can_edit: boolean;
  groups: { id: string; title: string }[];
  items: WordingItem[];
  templates: WordingTemplate[];
  flows: Record<string, FlowStep[]>;
  sample: WordingSample;
};

/** The longest each word can come out, as the server counts it (`_WORST`). */
const WORST: Record<string, number> = { name: 40, code: 20, percent: 3, days: 3, hours: 3, url: 500 };

const IDENT = /\{([A-Za-z_][A-Za-z0-9_]*)\}/g;
const NAME_AFTER_TEXT = /(?:, | )\{name\}/g;
const NAME_AT_START = /^\{name\}(?:, | )?/;

/** Words as the server keeps them: no outer spaces, plain line ends. */
export function tidy(words: string): string {
  return words.replace(/\r\n/g, "\n").trim();
}

/**
 * One message as the customer gets it: the same substitution the server makes
 * (`feedback_messages.text`). Her name, when she has none, goes with the comma
 * or space before it; any other brace is left as typed.
 */
export function fill(words: string, values: Partial<Record<string, string | number | null>>): string {
  let out = words;
  if (!values.name) {
    out = out.replace(NAME_AT_START, "");
    out = out.replace(NAME_AFTER_TEXT, "");
    out = out.split("{name}").join("");
  }
  return out.replace(IDENT, (found, name: string) => {
    const value = values[name];
    return value === undefined || value === null ? found : String(value);
  });
}

/** The words as the preview should show them: blank means the built-in words. */
export function effective(item: WordingItem, draft: string): string {
  const words = tidy(draft);
  return words === "" ? item.default : words;
}

/** The words the server holds now. */
export function savedWords(item: WordingItem): string {
  return item.value ?? item.default;
}

/** Whether this wording differs from the built-in one. */
export function isEdited(item: WordingItem, draft: string): boolean {
  return effective(item, draft) !== item.default;
}

/** Whether this wording differs from what is saved. */
export function isChanged(item: WordingItem, draft: string): boolean {
  return effective(item, draft) !== tidy(savedWords(item));
}

function listed(names: string[]): string {
  const shown = names.map((name) => `{${name}}`);
  return shown.length === 1 ? shown[0] : `${shown.slice(0, -1).join(", ")} and ${shown[shown.length - 1]}`;
}

/** Why this wording cannot be used for this message, or null. Mirrors `_check`. */
export function wordingProblem(item: WordingItem, draft: string): string | null {
  const words = tidy(draft);
  if (words === "") return null; // blank: the built-in wording
  if (item.kind === "label" && /[\n\r]/.test(words)) return "This must be on one line.";
  if (words.length > item.max) {
    return `This is ${words.length - item.max} ${words.length - item.max === 1 ? "character" : "characters"} too long. WhatsApp allows at most ${item.max} here.`;
  }
  const allowed = item.placeholders.map((placeholder) => placeholder.name);
  const used = [...new Set([...words.matchAll(IDENT)].map((found) => found[1]))];
  for (const name of used) {
    if (!allowed.includes(name)) {
      return allowed.length > 0
        ? `{${name}} cannot be used here; this message can use ${listed(allowed)}.`
        : `{${name}} cannot be used here; this one is plain words.`;
    }
  }
  for (const placeholder of item.placeholders) {
    if (placeholder.required && !words.includes(`{${placeholder.name}}`)) {
      return `This message must contain {${placeholder.name}}, or ${
        placeholder.name === "code"
          ? "the customer never sees her code"
          : placeholder.name === "url"
            ? "the customer never sees your review link"
            : "it loses its meaning"
      }.`;
    }
  }
  const longest = words.replace(IDENT, (_found, name: string) => "x".repeat(WORST[name] ?? 0));
  if (longest.length > item.max) {
    return `Too long once her name, code or link are filled in. Keep it to ${item.max} characters even then; this comes to ${longest.length}.`;
  }
  return null;
}

/**
 * Two options in one list that read the same (WhatsApp refuses that). Returns
 * `{key: why}` for the options that were typed over; the built-in titles of
 * the ones left alone count too.
 */
export function duplicateOptions(items: WordingItem[], drafts: Record<string, string>): Record<string, string> {
  const lists = new Map<string, WordingItem[]>();
  for (const item of items) {
    if (!item.key.includes("_option.")) continue;
    const list = item.key.slice(0, item.key.lastIndexOf("."));
    lists.set(list, [...(lists.get(list) ?? []), item]);
  }
  const found: Record<string, string> = {};
  for (const members of lists.values()) {
    const titles = new Map<string, WordingItem[]>();
    for (const member of members) {
      const title = effective(member, drafts[member.key] ?? savedWords(member)).toLowerCase();
      titles.set(title, [...(titles.get(title) ?? []), member]);
    }
    for (const same of titles.values()) {
      if (same.length < 2) continue;
      for (const member of same) {
        const words = effective(member, drafts[member.key] ?? savedWords(member));
        if (isEdited(member, drafts[member.key] ?? savedWords(member))) {
          found[member.key] = `Another option in this list is already called “${words}”. WhatsApp does not allow two the same.`;
        }
      }
    }
  }
  return found;
}

/** Every key a path uses: its messages, their buttons and their options. */
export function keysOf(steps: FlowStep[]): string[] {
  const keys: string[] = [];
  for (const step of steps) {
    if (step.type !== "message") continue;
    keys.push(step.ref, ...(step.button ? [step.button] : []), ...step.options);
  }
  return keys;
}

/** `{key: [path ids]}`: where each message is used. */
export function usedOn(flows: Record<string, FlowStep[]>): Record<string, string[]> {
  const found: Record<string, string[]> = {};
  for (const [path, steps] of Object.entries(flows)) {
    for (const key of new Set(keysOf(steps))) found[key] = [...(found[key] ?? []), path];
  }
  return found;
}

/** A path's steps in WhatsApp messages: a step joined to the one before is in the same one. */
export function messagesOf(steps: FlowStep[]): FlowStep[][] {
  const out: FlowStep[][] = [];
  for (const step of steps) {
    if (step.with_previous && out.length > 0) out[out.length - 1].push(step);
    else out.push([step]);
  }
  return out;
}

/**
 * Whether a line would go out for the sample customer, and if not, why, for
 * the preview. The server decides this when it sends; these are the few
 * conditions the preview can show from what it already knows.
 */
export function lineSent(
  path: string,
  step: FlowStep,
  sample: WordingSample,
): { sent: boolean; note: string | null } {
  if (step.ref === "review_line" && !sample.url) {
    return { sent: false, note: "Not sent until a review link is set" };
  }
  if (step.ref === "invitation" && path === "loved" && sample.url) {
    return { sent: false, note: "Not sent while a review link is set: the review request takes its place" };
  }
  if (step.ref === "tell_us") {
    return { sent: false, note: "Only sent if she chose “Something else”" };
  }
  return { sent: true, note: null };
}

/** What the preview fills in: the sample, and an example link where none is set. */
export function previewValues(sample: WordingSample, withName: boolean): Record<string, string | number> {
  return {
    name: withName ? sample.name : "",
    code: sample.code,
    percent: sample.percent,
    days: sample.days,
    hours: sample.hours,
    url: sample.url ?? "https://example.com/review",
  };
}

/** A template's body with its numbered slots filled from the sample. */
export function fillTemplate(body: string, sample: WordingSample): string {
  // The first template greets her by name and names the order; the second names only the order.
  const slots = body.includes("{{2}}") ? [sample.name, sample.order] : [sample.order];
  return body.replace(/\{\{(\d+)\}\}/g, (found, index: string) => slots[Number(index) - 1] ?? found);
}
