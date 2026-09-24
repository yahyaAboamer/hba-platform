import { formatMonth } from "../lib/money";
import "./MonthPicker.css";

/** How a month is marked, or `null` for an ordinary open month. */
export type MonthLock = "historical" | "approved" | "future" | null;

type Props = {
  value: string;
  onChange: (month: string) => void;
  /** The months offered, newest first - `platformMonths(session.platform)`
   *  on a screen, or a narrower window the screen owns. */
  months: string[];
  /** How a month is marked. Read only when one is chosen, so the page can say
   *  why (`onLockedClick`); the export's `<select>` marks nothing in the list. */
  lockFor?: (month: string) => MonthLock;
  /**
   * Called as well as `onChange` when a marked month is chosen, so the page can
   * say why it is marked. It does **not** prevent the choice - see below.
   */
  onLockedClick?: (month: string, lock: MonthLock) => void;
  /** `section` is the export's in-page control (a model's profile, 36px at
   *  13px); the default is the top bar's (38px at 13.5px). */
  size?: "bar" | "section";
  /** The word in front of it. Off where a field label already names it. */
  label?: boolean;
};

/**
 * The month control on every admin screen: the export's word *Month* and a
 * native `<select>` (`monthly` in the top bar, `mMonth` on a model's profile).
 *
 * It was a twelve-month grid with marks and a legend. The export draws a
 * select everywhere except terms editing, where choosing several months at
 * once is the task - that grid is `Compensation.tsx`'s own, not this one.
 *
 * **A mark is information, not a prohibition.** Every month offered can be
 * looked at - a historical month shows its sales, an approved one what was
 * agreed, a month still running shows it forming. What a mark still does is
 * let the page explain the month it opened (`onLockedClick`); refusal belongs
 * where something is actually refused, the approve button (§11.3).
 */
export function MonthPicker({
  value,
  onChange,
  months,
  lockFor,
  onLockedClick,
  size = "bar",
  label = true,
}: Props) {
  // The month on screen is always in the list, even one reached from a link
  // outside the range, so the control never claims a month it is not on.
  const options = months.includes(value)
    ? months
    : [...months, value].sort().reverse();

  function choose(month: string) {
    onChange(month);
    const lock = lockFor?.(month) ?? null;
    if (lock) onLockedClick?.(month, lock);
  }

  const select = (
    <select
      className="month-picker__select"
      value={value}
      onChange={(event) => choose(event.target.value)}
    >
      {options.map((month) => (
        <option key={month} value={month}>
          {formatMonth(month)}
        </option>
      ))}
    </select>
  );
  // Without its own word it sits inside a field's `<label>`, and a label
  // inside a label is not one the browser will associate.
  return label ? (
    <label className={`month-picker month-picker--${size}`}>
      <span className="month-picker__label">Month</span>
      {select}
    </label>
  ) : (
    <span className={`month-picker month-picker--${size}`}>{select}</span>
  );
}
