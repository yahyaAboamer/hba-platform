import { useState } from "react";
import type { DestinationCard } from "../lib/payouts";

/**
 * Where a model's money goes, in full, with a copy button on each line and
 * the InstaPay address she submitted behind a button.
 *
 * **The approved export's `destinationCard`, drawn once.** It lived inside
 * `PaymentDetail` while the model's own profile a click away still showed
 * `InstaPay · …291` - the same fact, to the same person, with the same
 * permission, written two different ways. ADR 0042 is about a screen being
 * usable by somebody working down a list of transfers with a banking app
 * open; a profile that makes them go back to the desk to read a number is the
 * same problem in a different place.
 *
 * The server decides who gets a card at all: it is served only where
 * `payments.record` holds, and everybody else receives `null` and sees the
 * shortened sentence. Nothing here re-decides that.
 *
 * **The link is never rebuilt from the number** (§13.1). A phone hands the
 * submitted address straight to the InstaPay app, and an address assembled
 * from a phone number is an address that belongs to whoever owns that handle.
 */
export function DestinationDetails({ card }: { card: DestinationCard }) {
  const [copied, setCopied] = useState<string | null>(null);

  async function copy(label: string, value: string) {
    try {
      await navigator.clipboard.writeText(value);
      setCopied(label);
      window.setTimeout(() => setCopied(null), 2000);
    } catch {
      // A browser that refuses the clipboard is not an error worth a banner:
      // the value is on the screen and can be selected by hand, which is what
      // somebody does anyway when the button is not there.
    }
  }

  return (
    <>
      {card.rows
        .filter((entry) => entry.value)
        .map((entry) => (
          <div key={entry.label} className="pay-detail__dest">
            <span className="pay-detail__dest-text">
              <span className="pay-detail__dest-label">{entry.label}</span>
              <span className="pay-detail__dest-value">{entry.value}</span>
            </span>
            {entry.copy && (
              <button
                type="button"
                className="button button--quiet"
                onClick={() => copy(entry.label, entry.value ?? "")}
              >
                {copied === entry.label ? "Copied" : "Copy"}
              </button>
            )}
          </div>
        ))}
      {card.link && (
        <a
          className="button pay-detail__instapay"
          href={card.link}
          target="_blank"
          rel="noreferrer noopener"
        >
          Open InstaPay
        </a>
      )}
    </>
  );
}
