/**
 * What one month's targets look like, wherever they are shown.
 *
 * The month card (`MyMonth`) and the Targets tab (`MyTargets`) draw the same
 * two bars from the same server fields, and they are one implementation
 * because the rules underneath them are subtle enough that a second copy would
 * eventually disagree with the first — about a zero, or about a month before
 * the platform.
 *
 * Both of those are decided here, once. The *words* beside the bars live in
 * `lib/targets`, where they can be tested exhaustively.
 */
import type { MonthTargets } from "../lib/portal";
import "./TargetProgress.css";

/**
 * The two bars, or the sentence that replaces them.
 *
 * ADR 0036: a month from before the platform has an outcome and no counts,
 * because the old dashboard never kept them. Two bars drawn against a missing
 * requirement would read as *nothing was asked of you and you did nothing*,
 * which is the opposite of what the chip says — so the bars give way.
 */
export function TargetBars({ target }: { target: MonthTargets }) {
  if (target.numbers_kept === false) {
    return (
      <div className="targets__list">
        <div className="targets__row">
          <div className="targets__top">
            <span>Videos and stories</span>
            <span className="code targets__figures">—</span>
          </div>
        </div>
        <p className="targets__unkept">
          The counts for this month were not kept, so there are none to show.
          Whether you met the target was recorded, and that is what decided your
          pay.
        </p>
      </div>
    );
  }

  return (
    <div className="targets__list">
      <TargetRow
        label="Videos"
        required={target.required_videos}
        actual={target.actual_videos}
      />
      <TargetRow
        label="Stories"
        required={target.required_stories}
        actual={target.actual_stories}
      />
    </div>
  );
}

/**
 * One line: what was asked, what is counted, and how close that is.
 *
 * ## Three things that are not zero
 *
 * **Nothing asked** (`required` null or 0) draws no bar and says so. AC30 is
 * about exactly this: a bar of `0 / 0` is arithmetic nobody wants to look at,
 * an empty track under "0 of 0" reads as a failure, and a full one claims an
 * achievement. Nothing was asked, so nothing is drawn.
 *
 * **Nothing counted** (`actual` null) is an em dash, not a zero. A zero is a
 * claim about her work and this is a statement about HBA's — and on a
 * guaranteed minimum the difference is the difference between a month that is
 * waiting and a month that is lost (§11.3).
 *
 * **More than asked** fills the bar and no further. Nine of six videos is more
 * than was asked, not 150% of a bar.
 */
function TargetRow({
  label,
  required,
  actual,
}: {
  label: string;
  required: number | null;
  actual: number | null;
}) {
  if (!required) {
    return (
      <div className="targets__row">
        <div className="targets__top">
          <span>{label}</span>
          <span className="targets__figures">none asked</span>
        </div>
      </div>
    );
  }

  const done = actual === null ? 0 : Math.min(actual / required, 1);

  return (
    <div className="targets__row">
      <div className="targets__top">
        <span>{label}</span>
        <span className="code targets__figures">
          {actual === null ? "—" : actual} of {required}
        </span>
      </div>
      <div className="targets__track">
        <span className="targets__fill" style={{ width: `${done * 100}%` }} />
      </div>
    </div>
  );
}
