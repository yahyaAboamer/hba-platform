import { Link, useParams } from "react-router-dom";

import { formatMonth } from "../lib/money";
import "./Payroll.css";

/**
 * Reopening an agreed month — **retired in 05B**.
 *
 * ## What this screen used to do, and why it is gone
 *
 * It returned an approved month to draft: the state went back, the orders that
 * snapshot had settled were released, and the next approval wrote a new
 * version over the top. Everything about that was recoverable except the one
 * thing that mattered — **money already paid against the old figure**. The
 * ledger kept the payment; the month it was paid against no longer existed in
 * the same form; and a whole reconciliation screen existed to help somebody
 * work out afterwards what had happened to a model's pay.
 *
 * §11.5 named the danger itself: *the dangerous state is not reopening, it is
 * forgetting*. A month left reopened and never agreed again is a model with no
 * figure at all, which is why the platform needed a diagnostic to find them.
 *
 * An agreed month is now what its name says, and what changes after it is
 * recorded **against** it rather than replacing it.
 *
 * ## Why the page is still here rather than deleted
 *
 * The route is linked from the payroll screen's history, from bookmarks and
 * from at least one email. A page that has stopped existing says *you are
 * lost*; this one says what replaced it, which is the thing somebody arriving
 * here actually needs. It is also where the reopened months that already exist
 * are explained, because those are still real and still need agreeing again.
 */
export function PayrollReopen() {
  const { month = "" } = useParams();

  return (
    <>
      <div className="page__head">
        <div className="page__title">
          <p className="crumb">
            <Link to="/payroll">Payroll</Link>
          </p>
          <h1>Reopening {formatMonth(month)}</h1>
        </div>
      </div>

      <section className="panel">
        <div className="panel__head">
          <h2 className="panel__title">Agreed months are not reopened</h2>
        </div>
        <div className="reopen__explains">
          <p>
            Once {formatMonth(month)} is agreed, the figure stands. It is not
            returned to draft and recalculated, because somebody may already
            have been paid against it — and a payment does not un-happen
            because a calculation was revisited.
          </p>
          <p>
            When something changes after a month is agreed — an order refused
            on delivery, a correction to what was counted — it is recorded
            against that month rather than replacing it. The original
            agreement, and what was paid against it, stay exactly as they were.
          </p>
          <p className="detail__note">
            Months that were reopened before this changed are still listed on
            the <Link to="/payroll">payroll screen</Link>, and still need
            agreeing again.
          </p>
        </div>
      </section>
    </>
  );
}
