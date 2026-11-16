/** Small pieces the production screens share. Class names are `prod-*`, from `prod.css`. */
import { useEffect, useId, useRef, useState, useSyncExternalStore } from "react";
import type { ReactNode } from "react";

import { stepsSentence } from "./format";
import type { Counts, ReasonRow } from "./logic";
import { blankReason, totalOf } from "./logic";
import type { OrderAnswer, OrderRow, Size } from "./types";
import { SIZES } from "./types";

/** The breakpoint below which the list is cards and forms are one column (the mockup's 860px). */
const NARROW = "(max-width: 860px)";

/**
 * Whether the viewport is too narrow for a table. JavaScript, not a CSS
 * `display:none`, because which of the two layouts is *rendered* is component
 * state (the reason `Affiliates.tsx`'s `useIsNarrow` gives).
 */
export function useIsNarrow(): boolean {
  return useSyncExternalStore(
    (notify) => {
      const query = window.matchMedia(NARROW);
      query.addEventListener("change", notify);
      return () => query.removeEventListener("change", notify);
    },
    () => window.matchMedia(NARROW).matches,
    () => false,
  );
}

/** A refusal or a mistake, next to what caused it, and announced. */
export function Problem({ children }: { children: ReactNode }) {
  return (
    <p className="notice notice--refused prod-problem" role="alert">
      {children}
    </p>
  );
}

/** The ten-step bar. Says in words what it draws. */
export function Steps({ steps }: { steps: OrderRow["steps"] }) {
  return (
    <div className="prod-steps" role="img" aria-label={stepsSentence(steps)}>
      {steps.map((step, index) => (
        <i key={index} className={step === "done" ? "d" : step === "skipped" ? "s" : undefined} />
      ))}
    </div>
  );
}

/** Six boxes, one per size, and the running total beneath them. */
export function SizeInputs({
  legend,
  counts,
  onChange,
  hints,
  sizes = SIZES,
  total,
  disabled,
  children,
}: {
  legend: string;
  counts: Counts;
  onChange: (size: Size, value: string) => void;
  /** Small words under a size's box, such as "planned 150". */
  hints?: Partial<Record<Size, string>>;
  sizes?: readonly Size[];
  total?: string;
  disabled?: boolean;
  children?: ReactNode;
}) {
  const id = useId();
  return (
    <fieldset className="prod-fieldset prod-wide">
      <legend className="field__label">{legend}</legend>
      <div className="prod-sizes">
        {sizes.map((size) => (
          <div key={size} className="prod-size">
            <label htmlFor={`${id}-${size}`}>{size}</label>
            <input
              id={`${id}-${size}`}
              className="input"
              inputMode="numeric"
              autoComplete="off"
              value={counts[size]}
              disabled={disabled}
              aria-describedby={hints?.[size] ? `${id}-${size}-hint` : undefined}
              onChange={(event) => onChange(size, event.target.value)}
            />
            {hints?.[size] && (
              <span id={`${id}-${size}-hint`} className="prod-size__hint">
                {hints[size]}
              </span>
            )}
          </div>
        ))}
      </div>
      <p className="prod-total" aria-live="polite">
        {total ?? `Total ${totalOf(counts).toLocaleString("en-GB")}`}
      </p>
      {children}
    </fieldset>
  );
}

/** Reasons, each a few words and a number of pieces, as many as are needed. */
export function ReasonRows({
  legend,
  rows,
  onChange,
  summary,
  tone,
  noun = "Reason",
}: {
  legend: string;
  rows: ReasonRow[];
  /** What one row is called to somebody who cannot see the layout: "Reason", "Rejected reason". */
  noun?: string;
  onChange: (rows: ReasonRow[]) => void;
  /** The running check, such as "Reasons add up to 10 of 28". */
  summary?: string;
  tone?: "ok" | "late";
}) {
  const set = (index: number, patch: Partial<ReasonRow>) =>
    onChange(rows.map((row, at) => (at === index ? { ...row, ...patch } : row)));
  const shown = rows.length ? rows : [blankReason()];
  return (
    <fieldset className="prod-fieldset prod-wide">
      <legend className="field__label">{legend}</legend>
      {shown.map((row, index) => (
        <div key={index} className="prod-reason">
          <input
            className="input"
            aria-label={`${noun} ${index + 1}`}
            placeholder="Why, in a few words"
            value={row.reason}
            maxLength={200}
            onChange={(event) => (rows.length ? set(index, { reason: event.target.value }) : onChange([{ ...row, reason: event.target.value }]))}
          />
          <input
            className="input prod-reason__n"
            aria-label={`Pieces for ${noun.toLowerCase()} ${index + 1}`}
            placeholder="Pieces"
            inputMode="numeric"
            autoComplete="off"
            value={row.quantity}
            onChange={(event) => (rows.length ? set(index, { quantity: event.target.value }) : onChange([{ ...row, quantity: event.target.value }]))}
          />
          {shown.length > 1 && (
            <button type="button" className="button button--quiet" onClick={() => onChange(rows.filter((_, at) => at !== index))}>
              Remove<span className="prod-sr"> {noun.toLowerCase()} {index + 1}</span>
            </button>
          )}
        </div>
      ))}
      <div className="prod-reason__foot">
        <button type="button" className="button button--row" onClick={() => onChange([...(rows.length ? rows : [blankReason()]), blankReason()])}>
          Add a reason
        </button>
        {summary && (
          <span className={`prod-sum${tone ? ` prod-sum--${tone}` : ""}`} aria-live="polite">
            {summary}
          </span>
        )}
      </div>
    </fieldset>
  );
}

/**
 * An inline panel on the order page: opened from the next-action bar or a
 * section's button, scrolled into view with focus on its heading, closed with
 * its button or Esc. Used instead of a dialog, which this platform has no
 * generic component for.
 */
export function PanelShell({
  title,
  intro,
  onClose,
  children,
}: {
  title: string;
  intro?: ReactNode;
  onClose: () => void;
  children: ReactNode;
}) {
  const heading = useRef<HTMLHeadingElement>(null);
  const id = useId();
  useEffect(() => {
    const node = heading.current;
    if (!node) return;
    node.closest("section")?.scrollIntoView?.({ block: "nearest" });
    node.focus({ preventScroll: true });
  }, []);
  return (
    <section
      className="prod-panel"
      aria-labelledby={id}
      onKeyDown={(event) => {
        if (event.key === "Escape") onClose();
      }}
    >
      <div className="prod-panel__head">
        <h2 id={id} ref={heading} tabIndex={-1}>
          {title}
        </h2>
        <button type="button" className="button button--quiet" onClick={onClose}>
          Close
        </button>
      </div>
      {intro && <p className="prod-panel__intro">{intro}</p>}
      {children}
    </section>
  );
}

/** A date box. A native date input: the value is the `YYYY-MM-DD` the server wants. */
export function DateBox({
  label,
  value,
  onChange,
  max,
  min,
  hint,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  max?: string;
  min?: string;
  hint?: string;
}) {
  const id = useId();
  return (
    <div className="prod-field">
      <label className="field__label" htmlFor={id}>
        {label}
      </label>
      <input
        id={id}
        className="input"
        type="date"
        value={value}
        max={max}
        min={min}
        aria-describedby={hint ? `${id}-hint` : undefined}
        onChange={(event) => onChange(event.target.value)}
      />
      {hint && (
        <span id={`${id}-hint`} className="field__hint">
          {hint}
        </span>
      )}
    </div>
  );
}

/** A labelled text box or area. */
export function TextBox({
  label,
  value,
  onChange,
  area,
  hint,
  max,
  wide,
  inputMode,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  area?: boolean;
  hint?: string;
  max?: number;
  wide?: boolean;
  /** `decimal` for an amount in pounds, so a phone offers the number pad. */
  inputMode?: "decimal" | "numeric" | "tel";
}) {
  const id = useId();
  const common = {
    id,
    className: "input",
    value,
    maxLength: max,
    inputMode,
    autoComplete: inputMode ? "off" : undefined,
    "aria-describedby": hint ? `${id}-hint` : undefined,
  };
  return (
    <div className={`prod-field${wide ? " prod-wide" : ""}`}>
      <label className="field__label" htmlFor={id}>
        {label}
      </label>
      {area ? (
        <textarea {...common} rows={3} onChange={(event) => onChange(event.target.value)} />
      ) : (
        <input {...common} onChange={(event) => onChange(event.target.value)} />
      )}
      {hint && (
        <span id={`${id}-hint`} className="field__hint">
          {hint}
        </span>
      )}
    </div>
  );
}

/** A labelled choice from a short list. */
export function SelectBox({
  label,
  value,
  onChange,
  options,
  wide,
  hint,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  options: readonly { value: string; label: string }[];
  wide?: boolean;
  hint?: string;
}) {
  const id = useId();
  return (
    <div className={`prod-field${wide ? " prod-wide" : ""}`}>
      <label className="field__label" htmlFor={id}>
        {label}
      </label>
      <select id={id} className="input" value={value} aria-describedby={hint ? `${id}-hint` : undefined} onChange={(event) => onChange(event.target.value)}>
        {options.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>
      {hint && (
        <span id={`${id}-hint`} className="field__hint">
          {hint}
        </span>
      )}
    </div>
  );
}

/** The submit row every panel ends in: the problem, the primary button, and what else is offered. */
export function Actions({
  error,
  busy,
  label,
  working,
  extra,
}: {
  error: string | null;
  busy: boolean;
  label: string;
  working: string;
  extra?: ReactNode;
}) {
  return (
    <div className="prod-wide">
      {error && <Problem>{error}</Problem>}
      <div className="prod-actions">
        <button type="submit" className="button button--primary" disabled={busy}>
          {busy ? working : label}
        </button>
        {extra}
      </div>
    </div>
  );
}

/**
 * What a panel calls to write: it sends the request, and on success the order
 * on the page is replaced with the answer and the panel closes. A refusal
 * comes back as the server's own words, for the panel to show.
 */
export type Run<A = OrderAnswer> = (request: () => Promise<A>, done: string) => Promise<string | null>;

/** A panel's one submission: a check made before sending, then the request, then the refusal if there is one. */
export function useSubmit<A = OrderAnswer>(run: Run<A>) {
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  // A second press while a save is still going is ignored, before the button has had time to redraw as disabled.
  const flying = useRef(false);
  /** Resolves `true` when the order was saved, `false` when a check or the server refused. */
  async function submit(problem: string | null, request: () => Promise<A>, done: string): Promise<boolean> {
    if (flying.current) return false;
    if (problem) {
      setError(problem);
      return false;
    }
    setError(null);
    flying.current = true;
    setBusy(true);
    let refused: string | null;
    try {
      refused = await run(request, done);
    } finally {
      flying.current = false;
    }
    setBusy(false);
    if (refused) setError(refused);
    return refused === null;
  }
  return { error, busy, submit };
}
