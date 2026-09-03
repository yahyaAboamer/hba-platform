import { useEffect, useState } from "react";

import { usePortal } from "../components/AffiliateLayout";
import { api } from "../lib/api";
import { formatMonth } from "../lib/money";
import type { MyEarnings } from "../lib/portal";
import "./MyGrow.css";

/**
 * The code, and what HBA asked for this month.
 *
 * **There is no share link.** The design offered
 * `hbawear.store/?code=HBA15`, and that is not how the storefront applies a
 * discount. A link that quietly failed to apply the code would produce orders
 * that never counted, which is the single worst bug this screen could carry.
 * The code is copied instead, from here and from the header of every screen.
 *
 * **What sells under the code** is the third card this screen will have, and
 * it is not here yet: it needs Shopify line items, which §10.2's index
 * deliberately does not store. That is phase 6, and a placeholder promising it
 * would be a promise on somebody's earnings screen.
 */
export function MyGrow({ codes }: { codes: { code: string; verified: boolean }[] }) {
  const { month } = usePortal();
  const [copied, setCopied] = useState<string | null>(null);
  const [targets, setTargets] = useState<MyEarnings["targets"]>(null);

  useEffect(() => {
    let current = true;
    api
      .get<MyEarnings>(`/api/me/earnings/${month}`)
      .then((body) => {
        if (current) setTargets(body.targets);
      })
      .catch(() => {
        // Silently. The code is the reason this screen exists and it is
        // already on the page; failing to load a progress bar is not worth an
        // error banner over the thing they came for.
      });
    return () => {
      current = false;
    };
  }, [month]);

  async function copy(code: string) {
    try {
      await navigator.clipboard.writeText(code);
      setCopied(code);
      window.setTimeout(
        () => setCopied((was) => (was === code ? null : was)),
        1400,
      );
    } catch {
      // Denied, or an insecure context. The code is on screen in a size
      // nobody has to squint at, so the button quietly does nothing.
    }
  }

  if (!codes.length) {
    return (
      <p className="empty">
        Your code appears here once HBA has set one up for you.
      </p>
    );
  }

  return (
    <>
      {codes.map((entry) => (
        <section className="panel grow__card" key={entry.code}>
          <span className="grow__label">Your code</span>
          <p className="grow__code">{entry.code}</p>
          <p className="grow__note">
            {entry.verified
              ? "This is what a customer types at checkout. Every order that uses it is counted against your month."
              : "HBA is checking this against the shop. Orders that use it are still being recorded while that happens."}
          </p>
          <button
            type="button"
            className="grow__copy"
            onClick={() => copy(entry.code)}
          >
            {copied === entry.code ? "Copied" : "Copy my code"}
          </button>
        </section>
      ))}

      {/*
       * **What was asked, and where they are against it.**
       *
       * The same numbers the Month screen carries, on the screen about what
       * to do rather than the screen about what they are owed. Bars, because
       * "4 of 6" answers *how many* and a bar answers *how close*, and the
       * second is the question somebody opens this tab with.
       */}
      {targets && (
        <section className="panel grow__card">
          <div className="grow__head">
            <h2 className="panel__title">{formatMonth(month)} asks</h2>
          </div>
          <Ask
            label="Videos"
            required={targets.required_videos}
            actual={targets.actual_videos}
          />
          <Ask
            label="Stories"
            required={targets.required_stories}
            actual={targets.actual_stories}
          />
          {/*
           * Driven by the same flag the Month screen's sentence is, so the
           * two cannot come to disagree: targets decide money on a guaranteed
           * minimum and on nothing else. Where they do not, this card says
           * nothing about pay at all rather than reassuring somebody about a
           * risk they were never under.
           */}
          {targets.determines_pay && (
            <p className="grow__foot">
              These decide whether your guaranteed minimum applies this month.
            </p>
          )}
          {targets.actual_videos === null && (
            <p className="grow__foot">
              HBA records these. Nothing has been recorded for{" "}
              {formatMonth(month)} yet.
            </p>
          )}
        </section>
      )}
    </>
  );
}

/**
 * One target, as a count and a bar.
 *
 * `actual` is `null` when nobody has recorded the month yet, which is a third
 * state and not a zero — an empty bar under "0 of 6" would be an accusation,
 * where "— of 6" is the truth.
 */
function Ask({
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
    <div className="ask">
      <div className="ask__row">
        <span>{label}</span>
        <span className="ask__count">
          {actual === null ? "—" : actual} of {required}
        </span>
      </div>
      <div className="ask__track">
        <span className="ask__fill" style={{ width: `${done * 100}%` }} />
      </div>
    </div>
  );
}
