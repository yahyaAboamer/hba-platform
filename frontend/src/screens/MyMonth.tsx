import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { usePortal } from "../components/AffiliateLayout";
import { Money } from "../components/Money";
import { api } from "../lib/api";
import { formatMonth } from "../lib/money";
import type { MyEarnings } from "../lib/portal";
import "./MyMonth.css";

/**
 * What she has earned this month, and whether that figure is settled.
 *
 * §11.1 is the whole screen. A month still open is a working number that will
 * move because orders are still arriving; a month agreed is what she is owed
 * and cannot move. She is the one who screenshots a figure in the third week
 * and asks why it changed, so the distinction is said in words as well as
 * carried by the typeface (ADR 0027).
 *
 * Nothing here is calculated in the browser. The server sends the figure, the
 * breakdown and the total; adding them up on this side would be a second
 * implementation of what she is owed, and the two would eventually disagree in
 * front of her.
 */
export function MyMonth() {
  const { month } = usePortal();
  const [body, setBody] = useState<MyEarnings | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setBody(null);
    setError(null);
    api
      .get<MyEarnings>(`/api/me/earnings/${month}`)
      .then(setBody)
      .catch((caught) => setError(caught.message));
  }, [month]);

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
            <p className="figure__state">Before the platform</p>
            <p className="figure__note">{body.note}</p>
          </>
        ) : body.not_started ? (
          /*
           * The first thing twenty people will see. A model invited on the
           * 31st of August opens on September, and September has nothing in
           * it - "Still adding up, E£0.00" is true and lands as though the
           * platform is broken or she has earned nothing.
           */
          <>
            <p className="figure__state">Not started yet</p>
            <p className="figure__note figure__note--lead">
              {formatMonth(body.month)} has not begun. Once it does, everything
              your code sells will appear here as it happens — you do not need
              to do anything.
            </p>
          </>
        ) : (
          <>
            <p className="figure__state">
              {settled ? "Agreed — this is yours" : "Still adding up"}
            </p>
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
          </>
        )}
      </section>

      {/*
       * Whose move it is, in words. Every blocker the platform has is HBA's
       * own work, and `targets_achieved_but_not_verified` in particular reads
       * as an accusation when it means she hit them and somebody here is slow.
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
       * §9.5. The one figure she signed for, on the months where the platform
       * could not apply it. Without this the screen shows her commission and
       * never names the minimum, and the honest reading of that is that HBA
       * has forgotten it.
       */}
      {body.guarantee && !body.guarantee.applied && (
        <p className="notice guarantee">
          Your guaranteed minimum is{" "}
          <Money piastres={body.guarantee.piastres} className="guarantee__amount" />.{" "}
          {describeGuarantee(body.guarantee)}
        </p>
      )}

      {body.makeup.length > 0 && !body.not_started && (
        <section className="panel makeup">
          <div className="panel__head">
            <h2 className="panel__title">How this adds up</h2>
          </div>
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
        </section>
      )}

      {/*
       * §15, and it lives here rather than on a tab of its own because the
       * guarantee note above already refers to it. Splitting the question from
       * its answer across two screens is how somebody ends up asking HBA.
       */}
      {body.targets && (
        <section className="panel targets">
          <div className="panel__head">
            <h2 className="panel__title">What you were asked for</h2>
          </div>
          <dl className="targets__list">
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
          </dl>
          <p className="targets__note">{describeTargets(body.targets)}</p>
        </section>
      )}

      {!body.not_started && (
      <section className="panel sales">
        <div className="panel__head">
          <h2 className="panel__title">Your sales</h2>
        </div>
        <dl className="sales__list">
          <div>
            <dt>Counted</dt>
            <dd>
              <Money
                piastres={body.sales.earned_piastres}
                kind={settled ? "agreed" : "provisional"}
              />
              <span className="sales__count">
                {counted === 1 ? "1 order" : `${counted} orders`}
              </span>
            </dd>
          </div>
          {/*
           * Shown, never hidden. An order still in transit makes her month
           * look smaller than it is, and hiding it produces exactly the
           * question this platform exists to stop her having to ask.
           */}
          {body.orders.pending > 0 && (
            <div>
              <dt>On its way</dt>
              <dd>
                <Money piastres={body.sales.pending_piastres} />
                <span className="sales__count">
                  {body.orders.pending === 1
                    ? "1 order not delivered yet"
                    : `${body.orders.pending} orders not delivered yet`}
                </span>
                {/*
                 * §11.4, before the carry has happened. Without this she is
                 * looking at a settled figure and a second, larger figure with
                 * no stated relationship to it - which reads either as money
                 * she has lost or as money she is about to be paid twice.
                 */}
                <span className="sales__fate">
                  {settled
                    ? "This month is closed, so these will be paid with a later month — still at this month's rate."
                    : "If they arrive before HBA closes the month they count here. If not, they are paid with the next one — still at this month's rate."}
                </span>
              </dd>
            </div>
          )}
        </dl>
        <Link to="/orders" className="sales__link">
          See every order →
        </Link>
      </section>
      )}

      {/*
       * §11.4, her side of it. She counted this month's orders herself and the
       * total is short by one - this is the line that closes the gap, and
       * without it her arithmetic cannot arrive at her own payment.
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
 * Why the guaranteed minimum is not in this month's figure.
 *
 * Three answers, because §15 has three states and they mean different things
 * to her: nobody has recorded her month, she missed her targets, or she met
 * them and is waiting on HBA. Only the middle one is about her, and it is the
 * one that must not sound like a penalty - a missed target costs her the
 * guarantee and nothing else, and she is paid her commission promptly either
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

function TargetRow({
  label,
  required,
  actual,
}: {
  label: string;
  required: number;
  actual: number | null;
}) {
  return (
    <div className="targets__row">
      <dt>{label}</dt>
      <dd>
        <span className="code targets__figures">
          {actual === null ? "—" : actual} of {required}
        </span>
      </dd>
    </div>
  );
}

/**
 * What her targets mean for her pay this month.
 *
 * §15 splits on one thing: a target decides money **only** on a guaranteed
 * minimum. On commission or salary-plus-commission it is a record, and a model
 * who reads a missed target as money gone has been told something untrue by a
 * screen that could not tell the two apart.
 *
 * Where it does decide money, the missed case is the one to be careful with.
 * It costs her the guarantee and nothing else - she is paid her commission,
 * promptly, and the month closes (§11.3). Any wording that makes that sound
 * like a penalty is wrong about the rule as well as unkind.
 */
function describeTargets(targets: {
  achieved: boolean | null;
  verified: boolean;
  determines_pay: boolean;
}): string {
  if (!targets.determines_pay) {
    return "These are for HBA's records. What you are paid is your commission either way.";
  }
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
