import { useState } from "react";
import { Link } from "react-router-dom";

import { signOutAndLeave } from "../lib/api";
import { storeTheme } from "../lib/theme";
import type { Theme } from "../lib/theme";
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
  theme,
  onTheme,
}: {
  me: Me;
  onChanged: () => void | Promise<void>;
  /**
   * Absent on the screen shown to somebody whose application is still being
   * checked. They are not on the programme yet, so that screen is one
   * paragraph and their details - no navigation, and nothing to configure.
   */
  theme?: Theme;
  onTheme?: (theme: Theme) => void;
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
    <>
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

      {/*
       * **The way the portal looks, and the way out of it.**
       *
       * Both used to sit in the header of every screen, where they wrapped
       * into the model's name on a phone - the M1 walkthrough caught "What
       * these words mean" breaking across four lines beside a truncated
       * email. They belong here: this is the screen somebody opens when they
       * are looking for something *about their account* rather than about
       * their money.
       */}
      {onTheme && (
        <section className="panel affiliate__panel">
          <h2 className="panel__title">How this looks</h2>
          <div className="pref">
            <span className="pref__label">Dark</span>
            <button
              type="button"
              className="pref__switch"
              role="switch"
              aria-checked={theme === "dark"}
              aria-label="Dark theme"
              onClick={() => {
                const next: Theme = theme === "dark" ? "light" : "dark";
                storeTheme(next);
                onTheme(next);
              }}
            >
              <span className="pref__knob" />
            </button>
          </div>
        </section>
      )}

      {onTheme && (
        <nav className="panel menu" aria-label="About your account">
          {/*
           * Only once they are actually on the programme. Somebody still
           * waiting to be approved has never seen a figure, so a glossary of
           * carried-forward and guaranteed-minimum explains words they have
           * no use for yet.
           */}
          {me.state === "active" && (
            <Link className="menu__row" to="/glossary">
              <span>What these words mean</span>
              <span className="menu__go">→</span>
            </Link>
          )}
          <button
            type="button"
            className="menu__row"
            onClick={signOutAndLeave}
          >
            <span>Sign out</span>
            <span className="menu__go menu__go--quiet">→</span>
          </button>
        </nav>
      )}
    </>
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
