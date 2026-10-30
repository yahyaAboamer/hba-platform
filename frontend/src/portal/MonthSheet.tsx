import { useEffect, useRef } from "react";

import { formatMonth } from "../lib/money";
import type { MonthListState } from "../lib/portal";
import "./MonthSheet.css";

/** Her months, in the words the portal uses for where each has got to. */
const WORD: Record<MonthListState, string> = {
  open: "In progress",
  approved: "Approved",
  paid: "Paid",
  settled: "Settled",
};

/**
 * Choosing a month, from the bottom of the screen (batch L).
 *
 * It was a list that dropped under the header and pushed the page down,
 * opened from a three-letter control in the corner - the month then appeared
 * three times on Home. A sheet is where a phone expects a choice like this:
 * in reach of the thumb, over the page rather than shoving it, and gone the
 * moment she picks.
 *
 * Escape and a tap outside both close it, and focus goes to the month she is
 * on, so a keyboard or a screen reader lands somewhere that makes sense.
 */
export function MonthSheet({
  months,
  current,
  states,
  onPick,
  onClose,
}: {
  /** Newest first; the first is the month still being earned. */
  months: string[];
  current: string;
  states: Record<string, MonthListState> | null;
  onPick: (month: string) => void;
  onClose: () => void;
}) {
  /**
   * *In progress* only for the month still running. An ended month nobody has
   * approved yet was also called in progress, which reads as "still earning"
   * when it is waiting on HBA - the owner met it as August on staging.
   */
  const word = (month: string, state: MonthListState) =>
    state === "open" && month !== months[0] ? "Awaiting approval" : WORD[state];
  const currentRef = useRef<HTMLButtonElement | null>(null);

  useEffect(() => {
    currentRef.current?.focus();
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <div className="msheet">
      <button type="button" className="msheet__scrim" aria-label="Close" onClick={onClose} />
      <div className="msheet__panel" role="dialog" aria-modal="true" aria-label="Choose a month">
        <span className="msheet__grabber" aria-hidden="true" />
        <span className="msheet__title">Your months</span>
        <div className="msheet__list">
          {months.map((month) => {
            const state = states?.[month];
            const on = month === current;
            return (
              <button
                key={month}
                ref={on ? currentRef : undefined}
                type="button"
                className={on ? "msheet__month msheet__month--on" : "msheet__month"}
                aria-current={on ? "true" : undefined}
                onClick={() => onPick(month)}
              >
                <span className="msheet__name">
                  <span className="msheet__check" aria-hidden="true">
                    {on && (
                      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.6" strokeLinecap="round" strokeLinejoin="round">
                        <path d="M5 12.5 10 17.5 19 7" />
                      </svg>
                    )}
                  </span>
                  {formatMonth(month)}
                </span>
                {state && (
                  <span className={`msheet__state msheet__state--${state}`}>{word(month, state)}</span>
                )}
              </button>
            );
          })}
        </div>
      </div>
    </div>
  );
}
