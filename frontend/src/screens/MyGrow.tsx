import { useState } from "react";

import "./MyGrow.css";

/**
 * The code, and what to do with it.
 *
 * **There is no share link.** The design offered
 * `hbawear.store/?code=HBA15`, and that is not how the storefront applies a
 * discount. A link that quietly failed to apply the code would produce orders
 * that never counted, which is the single worst bug this screen could carry.
 * The code is copied instead, from here and from the header of every screen.
 *
 * **The month's targets are not here.** They were, briefly, and they were on
 * the Month screen at the same time - the same two numbers on two tabs, which
 * makes a reader stop and check whether they agree. They belong beside the
 * figure they can change, so Month keeps them and this screen does not repeat
 * them.
 *
 * **What sells under the code** is the card this screen is still missing. It
 * needs Shopify line items, which §10.2's index deliberately does not store,
 * so it waits for phase 6 - a placeholder promising it would be a promise on
 * somebody's earnings screen.
 */
export function MyGrow({
  codes,
}: {
  codes: { code: string; verified: boolean }[];
}) {
  const [copied, setCopied] = useState<string | null>(null);

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
    </>
  );
}
