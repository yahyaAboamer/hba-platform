import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";

import { signOutAndLeave } from "../lib/api";
import { formatMonth } from "../lib/money";
import { PAY_TYPE, describeDestination } from "../lib/payouts";
import { storeTheme } from "../lib/theme";
import type { Theme } from "../lib/theme";
import { Measurements, Notifications, ShippingAddress } from "./MyDetails";
import type { Me } from "./MyDetails";
import { MyPayout } from "./MyPayout";
import "./MyYou.css";

/**
 * Her account, and the way in to everything about it.
 *
 * `vYou` in the approved portal (lines 418–465), and the structural change it
 * asks for: what used to be one long screen — payout details, address,
 * measurements, notification switches, theme and sign-out stacked on top of
 * each other — is a short page of rows, each opening the one thing it names.
 * On a phone that is the difference between reading a screen and scrolling
 * past four forms to reach the fifth.
 *
 * Nothing here decides money. §6.5: she may correct how to reach her and
 * where to send it, and nothing that changes what she is owed.
 */

/** What each arrangement means, in her words. §9.3–9.5. */
const ARRANGEMENT_NOTE: Record<string, string> = {
  commission: "You are paid a share of what your code sells.",
  fixed_plus_commission:
    "You are paid a fixed amount every month and a share of what your code sells — both, not whichever is larger.",
  base_guarantee:
    "You are paid whichever is larger: your commission, or your guaranteed minimum in a month where your content targets were recorded as met.",
};

export function MyYou({
  me,
  theme,
  onTheme,
}: {
  me: Me;
  theme: Theme;
  onTheme: (theme: Theme) => void;
}) {
  const active = me.state === "active";

  function pick(next: Theme) {
    storeTheme(next);
    onTheme(next);
  }

  return (
    <div className="you">
      <header className="you__hero">
        <span className="you__avatar" aria-hidden="true">
          {me.name.trim().charAt(0).toUpperCase() || "·"}
        </span>
        <span className="you__who">
          <span className="you__name">{me.name}</span>
          <span className="you__since">
            HBA ambassador{me.since ? ` since ${formatMonth(me.since)}` : ""}
          </span>
        </span>
      </header>

      {/*
       * Which of the three she is on, said plainly and attributed. She cannot
       * change it here and there is no control suggesting she can — the note
       * ends with who set it, which is the whole answer to the question the
       * card raises.
       */}
      <section className="you__card">
        <div className="you__card-label">Your arrangement</div>
        <div className="you__card-line">
          {me.arrangement ? (PAY_TYPE[me.arrangement] ?? me.arrangement) : "Not set yet"}
        </div>
        <p className="you__card-note">
          {me.arrangement
            ? `${ARRANGEMENT_NOTE[me.arrangement] ?? ""} Set by HBA.`
            : "Nobody has recorded your terms yet. Ask HBA — until they are set, a month cannot be worked out."}
        </p>
      </section>

      <section className="you__card you__appearance">
        <span>Appearance</span>
        <span className="seg">
          <label className="seg-opt">
            <input
              type="radio"
              name="portal-theme"
              checked={theme === "dark"}
              onChange={() => pick("dark")}
            />
            <span>Dark</span>
          </label>
          <label className="seg-opt">
            <input
              type="radio"
              name="portal-theme"
              checked={theme === "light"}
              onChange={() => pick("light")}
            />
            <span>Light</span>
          </label>
        </span>
      </section>

      <nav className="you__rows" aria-label="About your account">
        {active && (
          <Row to="/payments" label="What you have been paid" hint="Every transfer HBA has recorded" />
        )}
        <Row
          to="/you/payout"
          label="Payment details"
          hint={describeDestination(me.payout_destination)}
        />
        <Row
          to="/you/details"
          label="Personal details"
          hint={
            me.shipping.shipping_line1
              ? [me.shipping.shipping_line1, me.shipping.shipping_city].filter(Boolean).join(", ")
              : "No address yet"
          }
        />
        {active && (
          <Row
            to="/you/sizes"
            label="Height and weight"
            hint={
              me.height_cm || me.weight_kg
                ? `${me.height_cm ? `${me.height_cm} cm` : "no height"} · ${me.weight_kg ? `${me.weight_kg} kg` : "no weight"}`
                : "Not given — they are optional"
            }
          />
        )}
        {active && (
          <Row to="/you/notifications" label="Notifications" hint="What HBA writes to you about" />
        )}
        {active && (
          <Row to="/glossary" label="Help" hint="What these words mean" />
        )}
      </nav>

      <SignOut />
    </div>
  );
}

function Row({ to, label, hint }: { to: string; label: string; hint: string }) {
  return (
    <Link className="you__row" to={to}>
      <span>
        {label}
        <span className="you__hint">{hint}</span>
      </span>
      <span className="you__go" aria-hidden="true">→</span>
    </Link>
  );
}

/**
 * Signing out, with the question asked first.
 *
 * The export asks it, and it is worth asking on a phone: the row above it
 * opens her payment details, and a mis-tap that ends the session costs her a
 * password she may not have to hand.
 */
function SignOut() {
  const [asking, setAsking] = useState(false);

  if (!asking) {
    return (
      <button type="button" className="you__signout" onClick={() => setAsking(true)}>
        Sign out
      </button>
    );
  }

  return (
    <div className="you__confirm">
      <div className="you__confirm-question">Sign out of the HBA dashboard?</div>
      <div className="you__confirm-actions">
        <button type="button" className="you__stay" onClick={() => setAsking(false)}>
          Stay signed in
        </button>
        <button type="button" className="you__leave" onClick={signOutAndLeave}>
          Sign out
        </button>
      </div>
    </div>
  );
}

/**
 * The four views the account rows open.
 *
 * Thin on purpose: the panels themselves are the ones that were already on
 * this screen and already exercised, so this splits where they are reached
 * from without rewriting what they do. Each returns to You when it is
 * finished, which is where the person pressing Save came from.
 */
export function YouPayout({ me, onChanged }: { me: Me; onChanged: () => void | Promise<void> }) {
  const navigate = useNavigate();
  return (
    <MyPayout
      current={me.payout_destination}
      required={me.required_fields}
      onChanged={async () => {
        // The record first, so You is already showing the new destination
        // when it comes back into view.
        await onChanged();
        navigate("/you");
      }}
      onCancel={() => navigate("/you")}
    />
  );
}

export function YouDetails({ me, onChanged }: { me: Me; onChanged: () => void }) {
  return <ShippingAddress me={me} onChanged={onChanged} />;
}

export function YouSizes({ me, onChanged }: { me: Me; onChanged: () => void }) {
  return <Measurements me={me} onChanged={onChanged} />;
}

export function YouNotifications() {
  return <Notifications />;
}
