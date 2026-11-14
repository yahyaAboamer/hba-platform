import { useCallback, useEffect, useId, useLayoutEffect, useMemo, useRef, useState, useSyncExternalStore } from "react";

import { ApiError, api } from "../../lib/api";
import {
  duplicateOptions,
  effective,
  fillTemplate,
  isChanged,
  isEdited,
  messagesOf,
  savedWords,
  tidy,
  usedOn,
  wordingProblem,
} from "../../lib/feedbackMessages";
import type { FlowStep, WordingBody, WordingItem } from "../../lib/feedbackMessages";
import { useUnsavedGuard } from "../../lib/useUnsavedGuard";
import { InboxIcon } from "./InboxIcon";
import { PhonePreview, StepPreview } from "./FeedbackPreview";
import type { PreviewData } from "./FeedbackPreview";
import "./FeedbackSetup.css";

/**
 * The wording of every message the feedback feature sends, edited where the
 * customer's path can be seen (ADR 0083, decision 3).
 *
 * Three paths (what she answered first), each the conversation top to bottom.
 * Desktop: the fields on the left and a phone on the right that follows what
 * is typed. Phone: one column, each message's preview under its field.
 *
 * Nothing is sent until Save, and only what changed. What cannot be saved
 * (too long, a missing word that must be there, two options the same) is said
 * under the field and holds Save; the server checks all of it again.
 */

const WIDE = "(min-width: 1100px)";

/** Two columns where the screen is wide; wide too where the browser cannot say (jsdom). */
function useWide(): boolean {
  const supported = typeof window.matchMedia === "function";
  return useSyncExternalStore(
    (notify) => {
      if (!supported) return () => undefined;
      const query = window.matchMedia(WIDE);
      query.addEventListener("change", notify);
      return () => query.removeEventListener("change", notify);
    },
    () => !supported || window.matchMedia(WIDE).matches,
    () => true,
  );
}

/** The wording read, and read again on request. */
export function useWording() {
  const [body, setBody] = useState<WordingBody | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [tries, setTries] = useState(0);

  useEffect(() => {
    let current = true;
    setError(null);
    api
      .get<WordingBody>("/api/inbox/feedback/messages")
      .then((found) => {
        if (current) setBody(found);
      })
      .catch((caught) => {
        if (current) {
          setError(caught instanceof ApiError ? caught.message : "The wording could not be read.");
        }
      });
    return () => {
      current = false;
    };
  }, [tries]);

  return { body, setBody, error, retry: () => setTries((count) => count + 1) };
}

const plural = (count: number, one: string, many: string) => `${count} ${count === 1 ? one : many}`;

function draftsFrom(body: WordingBody): Record<string, string> {
  return Object.fromEntries(body.items.map((item) => [item.key, savedWords(item)]));
}

// ── One field ───────────────────────────────────────────────────────────────

type FieldProps = {
  item: WordingItem;
  draft: string;
  /** What is wrong with it, in words: ours first, then the server's. */
  problem: string | null;
  readOnly: boolean;
  /** The paths that use it, when more than this one. */
  alsoOn: string[];
  showHelp: boolean;
  onChange: (words: string) => void;
  onInsert: (name: string) => void;
  onReset: () => void;
  register: (element: HTMLTextAreaElement | HTMLInputElement | null) => void;
};

function counterTone(length: number, max: number): string {
  if (length > max) return "fbs-count fbs-count--over";
  if (length >= max * 0.9) return "fbs-count fbs-count--near";
  return "fbs-count";
}

function WordingField({ item, draft, problem, readOnly, alsoOn, showHelp, onChange, onInsert, onReset, register }: FieldProps) {
  const id = `fbs-f-${item.key}`;
  const edited = isEdited(item, draft);
  const changed = isChanged(item, draft);
  const length = tidy(draft).length;
  const describedBy = [
    showHelp ? `${id}-help` : null,
    `${id}-count`,
    problem ? `${id}-problem` : null,
    alsoOn.length > 0 ? `${id}-also` : null,
  ]
    .filter(Boolean)
    .join(" ");
  const counter = (
    <span id={`${id}-count`} className={counterTone(length, item.max)}>
      {length} / {item.max}
      <span className="visually-hidden"> characters</span>
    </span>
  );
  const grow = useRef<HTMLTextAreaElement | null>(null);

  // A message grows with its words, so none of it is hidden behind a scroll bar.
  useLayoutEffect(() => {
    const area = grow.current;
    if (!area) return;
    area.style.height = "auto";
    area.style.height = `${area.scrollHeight}px`;
  }, [draft]);

  const shared = {
    id,
    value: draft,
    readOnly,
    dir: "auto" as const,
    spellCheck: true,
    "aria-invalid": problem !== null,
    "aria-describedby": describedBy,
    onChange: (event: React.ChangeEvent<HTMLTextAreaElement | HTMLInputElement>) => onChange(event.target.value),
  };

  return (
    <div className={`fbs-field${changed ? " fbs-field--changed" : ""}${problem ? " fbs-field--bad" : ""}${item.kind === "label" ? " fbs-field--label" : ""}`}>
      <div className="fbs-field__top">
        <label className="fbs-field__label" htmlFor={id}>
          {item.label}
        </label>
        {edited && <span className="fbs-chip">Edited</span>}
        {changed && <span className="fbs-chip fbs-chip--quiet">Not saved yet</span>}
        {item.kind === "label" && <span className="fbs-field__topcount">{counter}</span>}
      </div>
      {showHelp && (
        <p className="fbs-field__help" id={`${id}-help`}>
          {item.help}
        </p>
      )}
      {item.kind === "text" ? (
        <textarea
          {...shared}
          className="input fbs-textarea"
          rows={3}
          ref={(element) => {
            grow.current = element;
            register(element);
          }}
        />
      ) : (
        <input {...shared} className="input" type="text" autoComplete="off" ref={register} />
      )}
      <div className="fbs-field__bar">
        {!readOnly && item.kind === "text" && item.placeholders.length > 0 && (
          <div className="fbs-insert" role="group" aria-label={`Add words to “${item.label}”`}>
            <span className="fbs-insert__lead">Add</span>
            {item.placeholders.map((placeholder) => (
              <button
                key={placeholder.name}
                type="button"
                className="fbs-insert__button"
                title={`Adds {${placeholder.name}}, which becomes “${placeholder.example}” here`}
                // Keep the cursor where it was, so the words land there.
                onMouseDown={(event) => event.preventDefault()}
                onClick={() => onInsert(placeholder.name)}
              >
                {placeholder.meaning}
                {placeholder.required && (
                  <>
                    {" "}
                    <span className="fbs-insert__needed">(needed)</span>
                  </>
                )}
              </button>
            ))}
          </div>
        )}
        <div className="fbs-field__foot">
          {item.kind === "text" && counter}
          {!readOnly && edited && (
            <button type="button" className="fbs-link" onClick={onReset}>
              Use the original wording
              <span className="visually-hidden"> for “{item.label}”</span>
            </button>
          )}
        </div>
      </div>
      <p className="fbs-error" id={`${id}-problem`} aria-live="polite" hidden={!problem}>
        {problem}
      </p>
      {alsoOn.length > 0 && (
        <p className="fbs-field__also" id={`${id}-also`}>
          Also used on: {alsoOn.join(", ")}
        </p>
      )}
    </div>
  );
}

// ── The editor ──────────────────────────────────────────────────────────────

type EditorProps = {
  body: WordingBody;
  onSaved: (next: WordingBody) => void;
};

export function FeedbackMessages({ body, onSaved }: EditorProps) {
  const wide = useWide();
  const readOnly = !body.can_edit;
  const paths = useMemo(
    () =>
      Object.keys(body.flows).map((id) => ({
        id,
        title: body.groups.find((group) => group.id === id)?.title ?? id,
      })),
    [body],
  );
  const used = useMemo(() => usedOn(body.flows), [body.flows]);
  const itemByKey = useMemo(() => new Map(body.items.map((item) => [item.key, item])), [body.items]);
  const titleOf = useCallback((id: string) => paths.find((path) => path.id === id)?.title ?? id, [paths]);

  const [path, setPath] = useState(paths[0]?.id ?? "");
  const [drafts, setDrafts] = useState<Record<string, string>>(() => draftsFrom(body));
  const [serverErrors, setServerErrors] = useState<Record<string, string>>({});
  const [withName, setWithName] = useState(true);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [justSaved, setJustSaved] = useState(false);
  const [focusKey, setFocusKey] = useState<{ key: string; n: number } | null>(null);

  // What the server answers replaces what is shown: the state comes from the
  // response, in the same render, so a saved field never shows its old text.
  const [seen, setSeen] = useState(body);
  if (seen !== body) {
    setSeen(body);
    setDrafts(draftsFrom(body));
  }

  const fields = useRef(new Map<string, HTMLTextAreaElement | HTMLInputElement>());
  const caret = useRef<{ key: string; at: number } | null>(null);

  const changed = useMemo(() => body.items.filter((item) => isChanged(item, drafts[item.key] ?? savedWords(item))), [body.items, drafts]);
  const clientErrors = useMemo(() => {
    const found: Record<string, string> = {};
    for (const item of body.items) {
      const problem = wordingProblem(item, drafts[item.key] ?? savedWords(item));
      if (problem) found[item.key] = problem;
    }
    for (const [key, problem] of Object.entries(duplicateOptions(body.items, drafts))) {
      found[key] ??= problem;
    }
    return found;
  }, [body.items, drafts]);
  const problemOf = (key: string) => clientErrors[key] ?? serverErrors[key] ?? null;
  const blocked = Object.keys(clientErrors).length;
  const dirty = changed.length > 0;

  useUnsavedGuard(dirty, "You have changes that are not saved. Leave without saving them?");

  // The "Saved" line is quiet: it goes by itself.
  useEffect(() => {
    if (!justSaved) return;
    const timer = window.setTimeout(() => setJustSaved(false), 6000);
    return () => window.clearTimeout(timer);
  }, [justSaved]);

  // After an insert, the cursor goes back after the new word.
  useLayoutEffect(() => {
    const wanted = caret.current;
    if (!wanted) return;
    caret.current = null;
    const element = fields.current.get(wanted.key);
    if (!element) return;
    element.focus();
    element.setSelectionRange(wanted.at, wanted.at);
  });

  // After a refused save, the first field that was refused takes the focus.
  useEffect(() => {
    if (!focusKey) return;
    const element = fields.current.get(focusKey.key);
    if (!element) return;
    element.scrollIntoView?.({ block: "center" });
    element.focus();
  }, [focusKey, path]);

  const edit = useCallback((key: string, words: string) => {
    setDrafts((now) => ({ ...now, [key]: words }));
    setServerErrors((now) => {
      if (!(key in now)) return now;
      const { [key]: _gone, ...rest } = now;
      return rest;
    });
    setJustSaved(false);
    setSaveError(null);
  }, []);

  function insert(item: WordingItem, name: string) {
    const element = fields.current.get(item.key);
    const value = drafts[item.key] ?? savedWords(item);
    const start = element?.selectionStart ?? value.length;
    const end = element?.selectionEnd ?? start;
    const word = `{${name}}`;
    caret.current = { key: item.key, at: start + word.length };
    edit(item.key, value.slice(0, start) + word + value.slice(end));
  }

  function discard() {
    setDrafts(draftsFrom(body));
    setServerErrors({});
    setSaveError(null);
  }

  async function save() {
    if (saving || !dirty || blocked > 0) return;
    setSaving(true);
    setSaveError(null);
    setServerErrors({});
    // Only what changed. Wording back at the original goes as null, which clears it.
    const values: Record<string, string | null> = {};
    for (const item of changed) {
      const words = effective(item, drafts[item.key] ?? savedWords(item));
      values[item.key] = words === item.default ? null : words;
    }
    try {
      const next = await api.put<WordingBody>("/api/inbox/feedback/messages", { values });
      onSaved(next);
      setJustSaved(true);
    } catch (caught) {
      if (caught instanceof ApiError && caught.fieldErrors) {
        const errors = caught.fieldErrors;
        setServerErrors(errors);
        const keys = Object.keys(errors);
        const first =
          body.items.find((item) => keys.includes(item.key) && (used[item.key] ?? []).includes(path)) ??
          body.items.find((item) => keys.includes(item.key));
        if (first) {
          const home = (used[first.key] ?? []).includes(path) ? path : (used[first.key] ?? [path])[0];
          setPath(home);
          setFocusKey({ key: first.key, n: Date.now() });
        }
        setSaveError(
          `${plural(keys.length, "message", "messages")} could not be saved. Nothing was changed; fix ${keys.length === 1 ? "it" : "them"} and save again.`,
        );
      } else {
        setSaveError(caught instanceof ApiError ? caught.message : "The wording was not saved. Try again.");
      }
    } finally {
      setSaving(false);
    }
  }

  // ── Tabs: arrow keys move between the three paths, as any tab list does.
  const tabs = useRef(new Map<string, HTMLButtonElement>());
  function onTabKey(event: React.KeyboardEvent) {
    const at = paths.findIndex((candidate) => candidate.id === path);
    let next = at;
    if (event.key === "ArrowRight") next = (at + 1) % paths.length;
    else if (event.key === "ArrowLeft") next = (at - 1 + paths.length) % paths.length;
    else if (event.key === "Home") next = 0;
    else if (event.key === "End") next = paths.length - 1;
    else return;
    event.preventDefault();
    setPath(paths[next].id);
    tabs.current.get(paths[next].id)?.focus();
  }

  const panelId = useId();
  const steps = body.flows[path] ?? [];
  const data: PreviewData = { path, body, drafts, withName };
  const changedOn = (id: string) =>
    changed.filter((item) => (used[item.key] ?? []).includes(id)).length;

  const renderField = (key: string, showHelp: boolean) => {
    const item = itemByKey.get(key);
    if (!item) return null;
    const draft = drafts[key] ?? savedWords(item);
    return (
      <WordingField
        key={key}
        item={item}
        draft={draft}
        problem={problemOf(key)}
        readOnly={readOnly}
        alsoOn={(used[key] ?? []).filter((other) => other !== path).map(titleOf)}
        showHelp={showHelp}
        onChange={(words) => edit(key, words)}
        onInsert={(name) => insert(item, name)}
        onReset={() => edit(key, item.default)}
        register={(element) => {
          if (element) fields.current.set(key, element);
          else fields.current.delete(key);
        }}
      />
    );
  };

  const renderStep = (step: FlowStep, index: number) => {
    if (step.type === "template") {
      const template = body.templates.find((candidate) => candidate.name === step.ref);
      return (
        <div className="fbs-step" key={`${step.ref}-${index}`}>
          <p className="fbs-step__when">{step.when}</p>
          <div className="fbs-locked">
            <p className="fbs-locked__title">
              <InboxIcon name="lock" />
              {index === 0 ? "The first question" : "Was your issue solved?"}
              <span className="fbs-chip">Approved by Meta</span>
            </p>
            {template && (
              <p className="fbs-locked__body" dir="auto">
                {fillTemplate(template.body, body.sample)}
              </p>
            )}
            {template && template.buttons.length > 0 && (
              <p className="fbs-locked__buttons">Buttons: {template.buttons.join(" · ")}</p>
            )}
            {index > 0 && (
              <p className="fbs-locked__why">
                This goes out instead of the question above when more than 24 hours have passed since her
                last message.
              </p>
            )}
            {template && <p className="fbs-locked__note">{template.note}</p>}
          </div>
          {/* The locked block above already shows its words. */}
        </div>
      );
    }
    const isList = step.button !== null;
    return (
      <div className="fbs-step" key={`${step.ref}-${index}`}>
        <p className="fbs-step__when">{step.when}</p>
        {renderField(step.ref, true)}
        {step.button && renderField(step.button, true)}
        {step.options.length > 0 && (
          <fieldset className="fbs-options">
            <legend>{isList ? "The choices she can pick" : "The buttons under it"}</legend>
            <p className="fbs-field__help">
              Only the words change. What each one records for the Feedback sheet does not.
            </p>
            <div className="fbs-options__grid">{step.options.map((key) => renderField(key, false))}</div>
          </fieldset>
        )}
        {!wide && <StepPreview step={step} data={data} joined={step.with_previous} />}
      </div>
    );
  };

  return (
    <section className="fbs-editor" aria-labelledby="fbs-editor-title">
      <div className="fbs-editor__head">
        <h2 id="fbs-editor-title">What customers are sent</h2>
        <p>
          Pick the answer she gave, then edit the words she receives next. The preview shows what her
          WhatsApp will show, updated as you type.
        </p>
      </div>

      <div className="fbs-tabs" role="tablist" aria-label="The answer she gave" onKeyDown={onTabKey}>
        {paths.map((candidate) => {
          const count = changedOn(candidate.id);
          const selected = candidate.id === path;
          return (
            <button
              key={candidate.id}
              type="button"
              role="tab"
              id={`${panelId}-tab-${candidate.id}`}
              aria-selected={selected}
              aria-controls={`${panelId}-panel`}
              tabIndex={selected ? 0 : -1}
              className="fbs-tab"
              ref={(element) => {
                if (element) tabs.current.set(candidate.id, element);
                else tabs.current.delete(candidate.id);
              }}
              onClick={() => setPath(candidate.id)}
            >
              {candidate.title}
              {count > 0 && (
                <span className="fbs-tab__count">
                  {count}
                  <span className="visually-hidden"> changed</span>
                </span>
              )}
            </button>
          );
        })}
      </div>

      <div className={wide ? "fbs-split" : "fbs-split fbs-split--one"}>
        <div
          className="fbs-flow"
          role="tabpanel"
          id={`${panelId}-panel`}
          aria-labelledby={`${panelId}-tab-${path}`}
        >
          {messagesOf(steps).map((group, index) => (
            <div key={`${group[0].ref}-${index}`} className={group.length > 1 ? "fbs-turn fbs-turn--joined" : "fbs-turn"}>
              {group.length > 1 && (
                <p className="fbs-turn__joined">
                  These lines go out together as one message, one under the other.
                </p>
              )}
              {group.map((step) => renderStep(step, steps.indexOf(step)))}
            </div>
          ))}
        </div>

        {wide && (
          <aside className="fbs-side" aria-label="Preview">
            <label className="fbs-side__toggle">
              <input type="checkbox" checked={!withName} onChange={(event) => setWithName(!event.target.checked)} />
              Show it as if we do not know her name
            </label>
            <PhonePreview data={data} />
          </aside>
        )}
      </div>

      {!wide && (
        <label className="fbs-side__toggle">
          <input type="checkbox" checked={!withName} onChange={(event) => setWithName(!event.target.checked)} />
          Show previews as if we do not know her name
        </label>
      )}

      <div className="visually-hidden" role="status">
        {justSaved ? "Saved." : ""}
      </div>

      {!readOnly && (dirty || saveError || justSaved) && (
        <div className="fbs-bar" role="region" aria-label="Unsaved changes">
          <div className="fbs-bar__text">
            {dirty ? (
              <b>{plural(changed.length, "message changed", "messages changed")}</b>
            ) : justSaved ? (
              <b>Saved. Customers get this wording from now on.</b>
            ) : null}
            {dirty && blocked > 0 && (
              <span className="fbs-bar__bad">
                {" · "}
                {plural(blocked, "needs fixing before it can be saved", "need fixing before they can be saved")}
              </span>
            )}
            {saveError && (
              <span className="fbs-bar__bad" role="alert">
                {dirty ? " · " : ""}
                {saveError}
              </span>
            )}
          </div>
          {dirty && (
            <div className="fbs-bar__actions">
              <button type="button" className="inbox-btn inbox-btn--quiet" onClick={discard} disabled={saving}>
                Discard
              </button>
              <button type="button" className="inbox-btn" onClick={() => void save()} disabled={saving || blocked > 0}>
                {saving ? "Saving…" : "Save"}
              </button>
            </div>
          )}
        </div>
      )}
    </section>
  );
}
