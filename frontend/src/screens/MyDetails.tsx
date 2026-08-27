import { useState } from "react";

import { MyPayout } from "./MyPayout";
import "./Apply.css";

export type Me = {
  name: string;
  phone: string | null;
  status: string;
  state: string;
  codes: { code: string; verified: boolean }[];
  payout_destination: Record<string, string | null> | null;
  required_fields: Record<string, string[]>;
};

const METHOD_LABEL: Record<string, string> = {
  instapay: "InstaPay",
  bank: "Bank transfer",
  wallet: "Mobile wallet",
};

/**
 * Her code and where her money goes. §6.4 and §6.5.
 *
 * The only things on the whole portal she can change, and deliberately so: she
 * may correct how to reach her, and nothing that decides what she is owed.
 */
export function MyDetails({ me, onChanged }: { me: Me; onChanged: () => void }) {
  const [changing, setChanging] = useState(false);

  if (changing) {
    return (
      <MyPayout
        current={me.payout_destination}
        required={me.required_fields}
        onChanged={() => {
          setChanging(false);
          onChanged();
        }}
        onCancel={() => setChanging(false)}
      />
    );
  }

  return (
    <section className="panel affiliate__panel affiliate__details">
      <h2 className="panel__title">Your details</h2>
      <dl className="affiliate__list">
        <div>
          <dt>Your code</dt>
          <dd>
            {me.codes.length === 0 ? (
              "—"
            ) : (
              me.codes.map((entry) => (
                <span key={entry.code} className="affiliate__code">
                  <span className="code">{entry.code}</span>
                  {!entry.verified && (
                    <span className="affiliate__pending-code">being checked</span>
                  )}
                </span>
              ))
            )}
          </dd>
        </div>
        <div>
          <dt>Paid to</dt>
          <dd>{describeDestination(me.payout_destination)}</dd>
        </div>
      </dl>
      {/*
       * Shortened even to her. She supplied it, so it tells her nothing she
       * does not know - and a screen printing a full account number is one
       * worth photographing over her shoulder on a bus.
       */}
      <p className="affiliate__note">
        Shortened on purpose. You gave us these, so this is only here for you to
        recognise which account it is.
      </p>
      <button type="button" className="button" onClick={() => setChanging(true)}>
        Change where I am paid
      </button>
    </section>
  );
}

function describeDestination(
  destination: Record<string, string | null> | null,
): string {
  if (!destination) return "Nothing on file yet";
  const method = destination.method ?? "";
  const shown =
    destination.instapay_address_url ??
    destination.bank_account_number ??
    destination.wallet_phone ??
    "";
  return `${METHOD_LABEL[method] ?? method} · ${shown}`;
}
