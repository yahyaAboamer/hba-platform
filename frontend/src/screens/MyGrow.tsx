import { useState } from "react";

import "./MyGrow.css";

/**
 * The code, and what to do with it.
 *
 * **Phase 1 of this screen is deliberately one card.** The design it comes
 * from also carries this month's content asks and a breakdown of what sells
 * under the code; the first needs the targets wiring, and the second needs
 * Shopify line items the platform does not store yet (phase 6). Shipping the
 * tab with only the part that works beats shipping a tab that is mostly
 * promises — and the code alone is the thing they open this screen for.
 *
 * **There is no share link.** The design offered
 * `hbawear.store/?code=HBA15`, and that is not how the storefront applies a
 * discount. A link that quietly fails to apply the code would produce orders
 * that never counted, which is the single worst bug this screen could carry.
 * The code is copied instead, from here and from the header of every screen.
 */
export function MyGrow({ codes }: { codes: { code: string; verified: boolean }[] }) {
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
