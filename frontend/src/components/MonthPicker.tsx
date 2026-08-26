import { useState } from "react";

import { currentMonth, formatMonth, shortMonth } from "../lib/money";
import "./MonthPicker.css";

/** How a month is marked, or `null` for an ordinary open month. */
export type MonthLock = "historical" | "approved" | "future" | null;

type Props = {
  value: string;
  onChange: (month: string) => void;
  /** How a month is marked. The grid shows it before it is clicked (§12.4). */
  lockFor?: (month: string) => MonthLock;
  /**
   * Called as well as `onChange` when a marked month is chosen, so the page can
   * say why it is marked. It does **not** prevent the choice - see below.
   */
  onLockedClick?: (month: string, lock: MonthLock) => void;
};

const LOCK_TEXT: Record<string, string> = {
  historical: "Settled before the platform",
  approved: "Approved — reopen to change it",
  future: "Not started yet",
};

/**
 * A month grid. §12.4.
 *
 * The native `<input type="month">` is replaced because it selects whole words,
 * ignores typing, maps digits to month positions, and gives no indication that
 * a month cannot be chosen.
 *
 * **Months are marked before they are clicked**, which is the whole point:
 * finding out a month is unusable by clicking it is the behaviour being
 * replaced.
 *
 * The marks do not prevent selection. Every month can be *looked at* — that is
 * how somebody sees a historical month's sales, or a payroll still forming.
 * What a mark prevents is a surprise, and choosing a marked month explains it.
 *
 * Reopening approved payroll stays where it belongs: a high-weight act needing
 * a reason and an impact preview, never a one-click button inside a date
 * picker.
 */
export function MonthPicker({ value, onChange, lockFor, onLockedClick }: Props) {
  const [year, setYear] = useState(() => Number(value.split("-")[0]));
  const [open, setOpen] = useState(false);
  const thisMonth = currentMonth();

  function choose(month: string) {
    const lock = lockFor?.(month) ?? null;
    // **A mark is information, not a prohibition.** Every month can be looked
    // at - a historical month shows sales, an approved one shows what was
    // agreed, a month still running shows it forming. Refusing selection was
    // the first version, and on 26 August with a go-live of September it left
    // every month in the grid unselectable and the tool looking broken.
    //
    // Refusal belongs where something is actually refused: the approve button
    // (§11.3), which knows what it would be approving.
    onChange(month);
    if (lock) onLockedClick?.(month, lock);
    setOpen(false);
  }

  return (
    <div className="month-picker">
      <button
        type="button"
        className="month-picker__trigger"
        onClick={() => setOpen((was) => !was)}
        aria-expanded={open}
      >
        <span className="month-picker__value">{formatMonth(value)}</span>
        <span aria-hidden="true" className="month-picker__caret">
          ▾
        </span>
      </button>

      {open && (
        <div className="month-picker__panel" role="dialog" aria-label="Choose a month">
          <div className="month-picker__years">
            <button
              type="button"
              className="month-picker__year-step"
              onClick={() => setYear((y) => y - 1)}
              aria-label="Previous year"
            >
              ←
            </button>
            <span className="month-picker__year">{year}</span>
            <button
              type="button"
              className="month-picker__year-step"
              onClick={() => setYear((y) => y + 1)}
              aria-label="Next year"
            >
              →
            </button>
          </div>

          <div className="month-picker__grid">
            {Array.from({ length: 12 }, (_, index) => {
              const month = `${year}-${String(index + 1).padStart(2, "0")}`;
              const lock = lockFor?.(month) ?? (month > thisMonth ? "future" : null);
              const selected = month === value;

              return (
                <button
                  key={month}
                  type="button"
                  className={[
                    "month-picker__month",
                    lock ? `month-picker__month--${lock}` : "",
                    selected ? "month-picker__month--selected" : "",
                  ]
                    .filter(Boolean)
                    .join(" ")}
                  onClick={() => choose(month)}
                  aria-current={selected ? "true" : undefined}
                  title={lock ? LOCK_TEXT[lock] : undefined}
                >
                  {shortMonth(month)}
                  {lock && (
                    <span className="month-picker__mark-text">
                      {LOCK_TEXT[lock]}
                    </span>
                  )}
                </button>
              );
            })}
          </div>

          {/*
           * A legend, because "locked" alone is not an answer. §12.4 wants the
           * three kinds distinguished — a month settled before the platform and
           * a month already approved are locked for entirely different reasons,
           * and only one of them can be undone.
           */}
          <ul className="month-picker__legend">
            <li>
              <span className="month-picker__swatch month-picker__swatch--historical" />
              Before the platform
            </li>
            <li>
              <span className="month-picker__swatch month-picker__swatch--approved" />
              Approved
            </li>
            <li>
              <span className="month-picker__swatch month-picker__swatch--future" />
              Not started
            </li>
          </ul>
        </div>
      )}
    </div>
  );
}
