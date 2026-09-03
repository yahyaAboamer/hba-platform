import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { usePortal } from "../components/AffiliateLayout";
import { Money } from "../components/Money";
import { api } from "../lib/api";
import { formatDay, formatEgp, formatMonth } from "../lib/money";
import type { MyEarnings } from "../lib/portal";
import "./MyMonth.css";

/**
 * What they have earned this month, and whether that figure is settled.
 *
 * §11.1 is the whole screen. A month still open is a working number that will
 * move because orders are still arriving; a month agreed is what they are owed
 * and cannot move. They are the one who screenshots a figure in the third week
 * and asks why it changed, so the distinction is said in words as well as
 * carried by the typeface (ADR 0027).
 *
 * Nothing here is calculated in the browser. The server sends the figure, the
 * breakdown and the total; adding them up on this side would be a second
 * implementation of what they are owed, and the two would eventually disagree in
 * front of them.
 */
export function MyMonth() {
  const { month, setMonthState } = usePortal();
  const [body, setBody] = useState<MyEarnings | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setBody(null);
    setError(null);
    api
      .get<MyEarnings>(`/api/me/earnings/${month}`)
      .then((loaded) => {
        setBody(loaded);
        // The bar sits above every screen and has no figure of its own, so
        // the screen that fetched one tells it what to say.
        setMonthState?.(
          loaded.state === "agreed"
            ? "agreed · paid"
            : loaded.not_started
              ? "not started"
              : "open · still adding up",
        );
      })
      .catch((caught) => setError(caught.message));

    // Cleared on the way out, so the Orders tab does not inherit a label
    // describing a month it is not showing.
    return () => setMonthState?.(null);
  }, [month, setMonthState]);

  if (error) {
    return (
      <p className="notice notice--refused" role="alert">
        {error}
      </p>
    );
  }

  if (body === null) return <p className="empty">Loading…</p>;

  const settled = body.state === "agreed";
  const counted = body.orders.earned;

  return (
    <>
      <section className="figure">
        {body.state === "historical" ? (
          <>
            <p className="figure__state">
              <span className="figure__pip figure__pip--agreed" />
              Paid the old way
            </p>
            <p className="figure__note figure__note--lead">{body.note}</p>
          </>
        ) : body.not_started ? (
          /*
           * The first thing twenty people will see. A model invited on the
           * 31st of August opens on September, and September has nothing in
           * it - "Still adding up, E£0.00" is true and lands as though the
           * platform is broken or they have earned nothing.
           */
          <>
            <p className="figure__state">
              <span className="figure__pip" />
              Not started yet
            </p>
            <p className="figure__note figure__note--lead">
              {formatMonth(body.month)} has not begun. Once it does, everything
              your code sells will appear here as it happens — you do not need
              to do anything.
            </p>
          </>
        ) : (
          <>
            {/*
             * **The figure sits in a card**, with its state on a chip beside
             * it rather than only in a line of prose above. Loose on the page
             * it read as a heading; in a card it reads as the one thing the
             * screen is about, and the chip answers "is this final?" without
             * anybody reading a sentence.
             */}
            <div className="headline">
              <div className="headline__top">
                <p className="figure__state">
                  <span
                    className={
                      settled ? "figure__pip figure__pip--agreed" : "figure__pip"
                    }
                  />
                  {settled ? "Agreed — this is yours" : "Still adding up"}
                </p>
                <span className={settled ? "chip chip--ok" : "chip"}>
                  {settled ? "final" : "open"}
                </span>
              </div>
              <Money
                piastres={body.amount_piastres ?? 0}
                kind={settled ? "agreed" : "provisional"}
                className="figure__amount"
              />
            <p className="figure__note">
              {settled
                ? "This month is closed. The figure will not change again."
                : "Orders are still arriving, so this will move. It becomes final when HBA closes the month."}
            </p>
            {/*
             * **When it lands.** The first question is how much; the second
             * is when, and this screen had no answer to it anywhere. A figure
             * captioned "still adding up" with no closing date reads as a
             * number that might move for ever.
             *
             * Only on a month that is open and has started. On an agreed
             * month the figure is final and a progress bar at 100% is a
             * decoration; on a month that has not begun there is nothing to
             * be part-way through.
             */}
            {!settled && (
              <div className="window">
                <div
                  className="window__track"
                  role="img"
                  aria-label={`${body.window.progress_pct}% of ${formatMonth(body.month)} gone`}
                >
                  <span
                    className="window__fill"
                    style={{ width: `${body.window.progress_pct}%` }}
                  />
                </div>
                <p className="window__ends">
                  <span>{formatDay(body.window.opens)}</span>
                  <span className="window__closes">
                    closes {formatDay(body.window.closes)}
                    {body.window.days_left !== null &&
                      (body.window.days_left === 0
                        ? " · last day"
                        : body.window.days_left === 1
                          ? " · 1 day to go"
                          : ` · ${body.window.days_left} days to go`)}
                  </span>
                </p>
              </div>
            )}

            {/*
             * §16, Phase 10 Batch C. Named, not restated - the rules a month
             * was calculated under can matter later even when they never
             * change, and the day they do change this is the sentence that
             * says a September figure still means what it meant in September.
             */}
            {body.policy_version && (
              <p className="figure__note">
                Calculated under the rules in force since{" "}
                {formatMonth(body.policy_version.effective_month)}.{" "}
                <Link to={`/policy/${body.policy_version.id}`}>Read them</Link>
              </p>
            )}

            {/*
             * **A figure that changed after it was agreed says so, here, on
             * the month that changed.** A settled month is meant to be final,
             * so the number quietly becoming a different number is the worst
             * way for somebody to find out. Both figures are given: "it
             * changed" without the old one is not something anybody can check
             * against their own record.
             */}
            {body.recalculated && (
              <p className="figure__note figure__note--changed">
                This month was looked at again and recalculated. It was{" "}
                <strong>{formatEgp(body.recalculated.was_piastres)}</strong>;
                it is now{" "}
                <strong>{formatEgp(body.recalculated.now_piastres)}</strong>.
                HBA emailed you about this.
              </p>
            )}

            {/*
             * A separate sentence on a separate month, deliberately. This one
             * is not about *this* month changing - it is about this month
             * carrying money earned in another. Folding both into one notice
             * would leave the earlier month showing a changed figure with
             * nothing attached to it.
             */}
            {body.credited_from.map((credit) => (
              <p className="figure__note" key={credit.month}>
                Includes <strong>{formatEgp(credit.piastres)}</strong> from{" "}
                {formatMonth(credit.month)}, after that month was corrected.
              </p>
            ))}
            </div>
          </>
        )}
      </section>

      {/*
       * Whose move it is, in words. Every blocker the platform has is HBA's
       * own work, and `targets_achieved_but_not_verified` in particular reads
       * as an accusation when it means they hit them and somebody here is slow.
       */}
      {body.waiting_on.map((item) => (
        <p key={item.text} className="notice waiting">
          {item.text}
          {item.who === "hba" && (
            <span className="waiting__who">Nothing for you to do.</span>
          )}
        </p>
      ))}

      {/*
       * §9.5. The one figure they signed for, on the months where the platform
       * could not apply it. Without this the screen shows their commission and
       * never names the minimum, and the honest reading of that is that HBA
       * has forgotten it.
       */}
      {body.guarantee && !body.guarantee.applied && (
        <p className="notice guarantee">
          Your{" "}
          <Link to="/glossary#guaranteed-minimum">guaranteed minimum</Link> is{" "}
          <Money piastres={body.guarantee.piastres} className="guarantee__amount" />.{" "}
          {describeGuarantee(body.guarantee)}
        </p>
      )}

      {body.makeup.length > 0 && !body.not_started && (
        <details className="panel makeup" open>
          {/*
           * **Open by default, and foldable.** The arithmetic is the reason
           * this screen can be trusted, so hiding it by default would be
           * hiding the evidence. But somebody who has read it once, and reads
           * it every month after, should be able to put it away - especially
           * on the arrangements where it runs to four or five lines.
           */}
          <summary className="panel__head makeup__head">
            <h2 className="panel__title">How this adds up</h2>
            <span className="makeup__toggle" aria-hidden="true" />
          </summary>
          <dl className="makeup__lines">
            {body.makeup.map((line) => (
              <div key={line.label} className="makeup__line">
                <dt>
                  {line.label}
                  {line.detail && (
                    <span className="makeup__detail">{line.detail}</span>
                  )}
                </dt>
                <dd>
                  <Money
                    piastres={line.piastres}
                    kind={settled ? "agreed" : "provisional"}
                  />
                </dd>
              </div>
            ))}
            <div className="makeup__line makeup__line--total">
              <dt>{settled ? "Agreed" : "So far"}</dt>
              <dd>
                <Money
                  piastres={body.amount_piastres ?? 0}
                  kind={settled ? "agreed" : "provisional"}
                />
              </dd>
            </div>
          </dl>
        </details>
      )}

      {/*
       * §15, and it lives here rather than on a tab of its own because the
       * guarantee note above already refers to it. Splitting the question from
       * its answer across two screens is how somebody ends up asking HBA.
       */}
      {body.targets && (
        <section className="panel targets">
          <div className="panel__head">
            <h2 className="panel__title">Targets</h2>
            {targetChip(body.targets) && (
              <span className={targetChip(body.targets)!.className}>
                {targetChip(body.targets)!.text}
              </span>
            )}
          </div>
          <div className="targets__list">
            <TargetRow
              label="Videos"
              required={body.targets.required_videos}
              actual={body.targets.actual_videos}
            />
            <TargetRow
              label="Stories"
              required={body.targets.required_stories}
              actual={body.targets.actual_stories}
            />
          </div>
          {/*
           * Only where it decides money. A commission or salary model already
           * knows targets do not change their pay, and being told so every month
           * is noise - the business said exactly that. On a guaranteed minimum
           * it is the sentence the whole card exists for.
           */}
          {body.targets.determines_pay && (
            <p className="targets__note">{describeTargets(body.targets)}</p>
          )}
        </section>
      )}

      {/*
       * Shown on a historical month too. The orders are real and the counting
       * is real - only the payment happened elsewhere - so it behaves like any
       * other month rather than like a month that did not happen.
       */}
      {!body.not_started && (
        <>
          {/*
           * **Two tiles, side by side.** Counted and average answer the same
           * question - *how is my code selling* - and a stacked list made
           * them look like two unrelated facts. Shown on a historical month
           * too: the orders are real and the counting is real, only the
           * payment happened elsewhere.
           */}
          <div className="tiles">
            <div className="tile">
              <span className="tile__label">Counted sales</span>
              <Money
                piastres={body.sales.earned_piastres}
                kind={settled ? "agreed" : "provisional"}
                className="tile__figure"
              />
              <span className="tile__sub">
                {counted === 1 ? "1 order counted" : `${counted} orders counted`}
              </span>
            </div>
            {/*
             * Absent rather than zero where nothing has counted yet -
             * `average_order` is `null` there, because there is nothing to
             * average, and a zero would claim a typical order is worth
             * nothing.
             */}
            {body.sales.average_order !== null && (
              <div className="tile">
                <span className="tile__label">Average order</span>
                <Money
                  piastres={body.sales.average_order_piastres ?? 0}
                  kind={settled ? "agreed" : "provisional"}
                  className="tile__figure"
                />
                <span className="tile__sub">across counted orders</span>
              </div>
            )}
          </div>

          {/*
           * **Its own outlined box**, not a third row in a list. An order
           * still travelling is a different kind of fact from one that has
           * counted - it is a promise, not money - and outlining rather than
           * filling it says so before anybody reads the label.
           *
           * Shown, never hidden: hiding it makes their month look smaller
           * than it is, which produces exactly the question this platform
           * exists to stop them having to ask.
           */}
          {body.orders.pending > 0 && (
            <div className="coming">
              <div className="coming__top">
                <div>
                  <span className="tile__label">On its way</span>
                  <Money
                    piastres={body.sales.pending_piastres}
                    className="coming__figure"
                  />
                </div>
                {/*
                 * §11.4, behind an ⓘ rather than on the page. The business's
                 * own reasoning, and a better rule than mine: *an information
                 * button makes it like, okay, there is something I need to
                 * know about.*
                 */}
                <details className="expl">
                  <summary aria-label="What happens to these orders">
                    <span className="info" aria-hidden="true">i</span>
                  </summary>
                  <div className="expl__body">
                    An order counts once it reaches the customer.{" "}
                    {settled
                      ? "This month is closed, so these will be paid with a later month — still at this month's rate. Nothing is lost."
                      : "If they arrive before HBA closes the month they count here. If not, they are paid with the next one — still at this month's rate."}
                  </div>
                </details>
              </div>
              <span className="tile__sub">
                {body.orders.pending === 1
                  ? "1 order not delivered yet"
                  : `${body.orders.pending} orders not delivered yet`}
              </span>
            </div>
          )}

          {/*
           * A block, not a link in the corner of a card. It is the one thing
           * to do from this screen, and a thumb finds a full-width target
           * without aiming.
           */}
          <Link to="/orders" className="block">
            <span>See every order</span>
            <em>→</em>
          </Link>
        </>
      )}

      {/*
       * §11.4, their side of it. They counted this month's orders themselves and the
       * total is short by one - this is the line that closes the gap, and
       * without it their arithmetic cannot arrive at their own payment.
       */}
      {body.carried_out.map((line) => (
        <p key={line.to_month} className="notice carried">
          {line.orders === 1
            ? "One order you sold this month"
            : `${line.orders} orders you sold this month`}{" "}
          arrived after it closed, so {line.orders === 1 ? "it was" : "they were"}{" "}
          paid with {formatMonth(line.to_month)} instead — at this month's rate,
          not that one's.
        </p>
      ))}
    </>
  );
}

/**
 * The card's own state, at a glance.
 *
 * One chip at most, and only where the numbers above it do not already say it.
 * A model who met their targets sees so from the figures; what they cannot see is
 * whether anybody has confirmed them.
 */
function targetChip(targets: {
  achieved: boolean | null;
  verified: boolean;
  determines_pay: boolean;
}): { text: string; className: string } | null {
  if (targets.achieved === null) {
    return { text: "Not recorded yet", className: "chip chip--quiet" };
  }
  if (!targets.achieved) {
    return { text: "Short this month", className: "chip chip--quiet" };
  }
  if (targets.determines_pay && !targets.verified) {
    return { text: "Waiting to be confirmed", className: "chip" };
  }
  return { text: "Met", className: "chip chip--ok" };
}

/**
 * Why the guaranteed minimum is not in this month's figure.
 *
 * Three answers, because §15 has three states and they mean different things
 * to them: nobody has recorded their month, they missed their targets, or they met
 * them and is waiting on HBA. Only the middle one is about them, and it is the
 * one that must not sound like a penalty - a missed target costs them the
 * guarantee and nothing else, and they are paid their commission promptly either
 * way (§11.3).
 */
function describeGuarantee(guarantee: {
  targets_achieved: boolean | null;
  targets_verified: boolean;
}): string {
  if (guarantee.targets_achieved === null) {
    return "Whether it applies this month depends on your targets, and nobody has recorded them yet.";
  }
  if (!guarantee.targets_achieved) {
    return "It applies in a month where your targets are met. They were not this month, so you are paid your commission instead.";
  }
  if (!guarantee.targets_verified) {
    return "You met your targets, so it applies as soon as HBA confirms the numbers.";
  }
  return "Your commission came to more than it this month, so you are paid the larger of the two.";
}

/**
 * One target, as a count **and** a bar.
 *
 * "4 of 6" answers *how many*; the bar answers *how close*, and the second is
 * the question somebody actually has. Grow had the bars and Month did not,
 * which left the same two numbers looking like two different facts on two
 * screens.
 *
 * `actual` is `null` when nobody has recorded the month yet — a third state,
 * not a zero. An empty bar under "0 of 6" is an accusation; "— of 6" is the
 * truth.
 */
function TargetRow({
  label,
  required,
  actual,
}: {
  label: string;
  required: number;
  actual: number | null;
}) {
  // Capped at the full bar. Somebody who posted nine of six videos has done
  // more than was asked, not 150% of a bar.
  const done = actual === null ? 0 : Math.min(actual / Math.max(required, 1), 1);

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

/**
 * What their targets mean for their pay this month.
 *
 * §15 splits on one thing: a target decides money **only** on a guaranteed
 * minimum. On commission or salary-plus-commission it is a record, and a model
 * who reads a missed target as money gone has been told something untrue by a
 * screen that could not tell the two apart.
 *
 * Where it does decide money, the missed case is the one to be careful with.
 * It costs them the guarantee and nothing else - they are paid their commission,
 * promptly, and the month closes (§11.3). Any wording that makes that sound
 * like a penalty is wrong about the rule as well as unkind.
 *
 * **Only called where `determines_pay` is true**, which is why there is no
 * branch for the other arrangements. There used to be one, and it read *"what
 * you are paid is your commission either way"* - unreachable, but wrong twice
 * over if anybody ever reached it: a `fixed_plus_commission` model is paid
 * their salary *and* their commission, so the sentence would have quietly
 * dropped half their money. A branch that can only ever be wrong is better
 * deleted than corrected.
 */
function describeTargets(targets: {
  achieved: boolean | null;
  verified: boolean;
}): string {
  if (targets.achieved === null) {
    return "Nobody has recorded what you posted yet, so it is not settled whether your guaranteed minimum applies.";
  }
  if (!targets.achieved) {
    return "Short this month, so your guaranteed minimum does not apply and you are paid your commission.";
  }
  if (!targets.verified) {
    return "Met. Your guaranteed minimum applies as soon as HBA confirms the numbers.";
  }
  return "Met and confirmed, so your guaranteed minimum applies.";
}
