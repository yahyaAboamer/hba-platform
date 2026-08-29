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
 * Their code and where their money goes. §6.4 and §6.5.
 *
 * The only things on the whole portal they can change, and deliberately so: they
 * may correct how to reach them, and nothing that decides what they are owed.
 */
export function MyDetails({
  me,
  onChanged,
}: {
  me: Me;
  onChanged: () => void | Promise<void>;
}) {
  const [changing, setChanging] = useState(false);
  const [changed, setChanged] = useState(false);

  if (changing) {
    return (
      <MyPayout
        current={me.payout_destination}
        required={me.required_fields}
        onChanged={async () => {
          // Wait for the record to come back before closing the form, so the
          // panel behind it is already showing the new destination.
          await onChanged();
          setChanging(false);
          setChanged(true);
        }}
        onCancel={() => setChanging(false)}
      />
    );
  }

  return (
    <section className="panel affiliate__panel affiliate__details">
      <h2 className="panel__title">Your details</h2>

      {/*
       * Said out loud. Changing where your money goes with no confirmation is
       * the one place silence is unacceptable - the business changed it, saw
       * the form close and the old method still listed, and concluded nothing
       * had happened.
       */}
      {changed && (
        <p className="notice notice--settled">
          Changed. This is where your money will be sent from now on.
        </p>
      )}
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
       * Shortened even to them. They supplied it, so it tells them nothing they
       * do not know - and a screen printing a full account number is one
       * worth photographing over their shoulder on a bus.
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
