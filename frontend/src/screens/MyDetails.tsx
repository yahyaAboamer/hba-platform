import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { api, signOutAndLeave } from "../lib/api";
import { describeDestination } from "../lib/payouts";
import { storeTheme } from "../lib/theme";
import type { Theme } from "../lib/theme";
import { MyPayout } from "./MyPayout";
import "./Apply.css";

export type Me = {
  name: string;
  phone: string | null;
  /**
   * **Her one email** (D07). It is what she signs in with *and* where HBA
   * writes to her; there is no second contact address, so every screen that
   * shows it says which it is rather than calling it "email".
   */
  email: string;
  /** Hers to change (A05). `null` means she has not said, which is fine. */
  height_cm: number | null;
  weight_kg: number | null;
  status: string;
  state: string;
  codes: { code: string; verified: boolean }[];
  payout_destination: Record<string, string | null> | null;
  required_fields: Record<string, string[]>;
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
        {/*
         * **"You sign in with"**, not "Email" (D07). She has one address and
         * it is her login; a screen that calls it a contact detail is a screen
         * somebody eventually edits as one, and the first anybody learns of
         * that is a model who cannot get in.
         *
         * Shown and not editable here. Moving a login is a real change and it
         * is not something to do by tabbing past it on a settings screen.
         */}
        <div>
          <dt>You sign in with</dt>
          <dd>{me.email}</dd>
        </div>
      </dl>
      {/*
       * Shortened even to them. They supplied it, so it tells them nothing they
       * do not know - and a screen printing a full account number is one
       * worth photographing over their shoulder on a bus.
       */}
      <Reveal />
      <button type="button" className="button" onClick={() => setChanging(true)}>
        Change where I am paid
      </button>
    </section>

      {/*
       * A05: hers to write, and staff read them. There is no admin control
       * anywhere for these - not a disabled one, none - and this is the only
       * way they ever change.
       *
       * Only once she is actually on the programme. Somebody still waiting to
       * be approved has a screen whose whole job is the waiting.
       */}
      {onTheme && me.state === "active" && (
        <Measurements me={me} onChanged={onChanged} />
      )}

      {onTheme && <Notifications />}

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
          {/*
           * Payments moved off the tab bar and behind the avatar in the
           * redesign (S03), so this row is now the way to it. First in the
           * menu because it is the one thing here somebody actually comes
           * looking for; the rest of this list is settings.
           */}
          {me.state === "active" && (
            <Link className="menu__row" to="/payments">
              <span>What you have been paid</span>
              <span className="menu__go">→</span>
            </Link>
          )}
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


/**
 * Their payout details, shortened, with a way to see them in full.
 *
 * **Masked at rest is right; masked with no way to look is not.** Somebody
 * who mistyped a digit had no way to find out except by not being paid — and
 * they are the one person entitled to read back what they typed.
 *
 * Behind a press, so the screen sitting open on a table is still the
 * shortened one. Fetched rather than held: the full number should not be in
 * the page before somebody asks for it.
 */
type FullDestination = Record<string, string | null>;

function Reveal() {
  const [full, setFull] = useState<FullDestination | null>(null);
  const [working, setWorking] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);

  if (full) {
    return (
      <>
        <dl className="affiliate__list affiliate__full">
          {Object.entries(full)
            .filter(([field, value]) => field !== "method" && value)
            .map(([field, value]) => (
              <div key={field}>
                <dt>{FULL_LABEL[field] ?? field}</dt>
                <dd className="code">{value}</dd>
              </div>
            ))}
        </dl>
        <button
          type="button"
          className="affiliate__reveal"
          onClick={() => setFull(null)}
        >
          Hide them again
        </button>
      </>
    );
  }

  return (
    <>
      <p className="affiliate__note">
        Shortened on purpose. You gave us these, so this is only here for you to
        recognise which account it is.
      </p>
      {problem && (
        <p className="notice notice--refused" role="alert">
          {problem}
        </p>
      )}
      <button
        type="button"
        className="affiliate__reveal"
        disabled={working}
        onClick={async () => {
          setWorking(true);
          setProblem(null);
          try {
            setFull(await api.get<FullDestination>("/api/me/payout-destination"));
          } catch (caught) {
            setProblem(
              caught instanceof Error
                ? caught.message
                : "Could not read them back. Try again.",
            );
          } finally {
            setWorking(false);
          }
        }}
      >
        {working ? "Reading…" : "Show them in full"}
      </button>
    </>
  );
}

const FULL_LABEL: Record<string, string> = {
  instapay_address_url: "InstaPay payment address",
  instapay_phone: "InstaPay number",
  bank_name: "Bank",
  bank_account_holder: "Account holder",
  bank_account_number: "Card number",
  wallet_provider: "Wallet",
  wallet_phone: "Wallet number",
};

type Preference = { kind: string; label: string; enabled: boolean };

/**
 * The two messages a model may turn off.
 *
 * **Two, and a third was cut before it was built.** The design offered an
 * alert for every order that counts; twenty models on a busy month is an
 * email an order, which is the volume that gets a sending domain marked as
 * spam and takes the two useful messages down with it.
 *
 * Nothing about security is here. An invitation, a password reset and the
 * notice that somebody moved where your money goes are not news, and there is
 * no switch for them.
 *
 * Saved on the press, one switch per request — two tabs open on this screen
 * cannot then write over each other's other switch.
 */
/**
 * Her height and her weight.
 *
 * **Optional in both directions**, which is the part worth building carefully.
 * A05 makes them optional at every point in her life with the business, not
 * only on the day she applied - so taking one back has to be as ordinary as
 * giving it, and Save with a field emptied clears it rather than being read as
 * "she did not mention it".
 *
 * No password. The payout screen asks for one because that is where money
 * goes; a height is not that, and asking for a password every time she
 * corrects a number she volunteered teaches her to type it into anything.
 */
function Measurements({ me, onChanged }: { me: Me; onChanged: () => void }) {
  const [open, setOpen] = useState(false);
  const [height, setHeight] = useState("");
  const [weight, setWeight] = useState("");
  const [saving, setSaving] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);

  function start() {
    // From the server's values, so Cancel discards the draft rather than
    // whatever was typed last time (M03).
    setHeight(me.height_cm ? String(me.height_cm) : "");
    setWeight(me.weight_kg ? String(me.weight_kg) : "");
    setProblem(null);
    setOpen(true);
  }

  async function save() {
    setSaving(true);
    setProblem(null);
    try {
      await api.put("/api/me/measurements", {
        // `_set` on both, always: this form is the whole of what she is
        // saying, so an emptied field means "take it off" rather than
        // "unchanged". The flags are what let the server tell those apart.
        height_cm: height.trim() ? Number(height) : null,
        height_cm_set: true,
        weight_kg: weight.trim() ? Number(weight) : null,
        weight_kg_set: true,
      });
      setOpen(false);
      onChanged();
    } catch (caught) {
      setProblem(
        caught instanceof Error ? caught.message : "Could not save that.",
      );
    } finally {
      setSaving(false);
    }
  }

  return (
    <section className="panel affiliate__panel">
      <h2 className="panel__title">Your size</h2>
      {!open ? (
        <>
          <p className="affiliate__lead">
            {me.height_cm || me.weight_kg ? (
              <>
                {me.height_cm ? `${me.height_cm} cm` : "No height"} ·{" "}
                {me.weight_kg ? `${me.weight_kg} kg` : "no weight"}
              </>
            ) : (
              "You have not given these. They are optional — HBA only uses them to send you things that fit."
            )}
          </p>
          <button type="button" className="button" onClick={start}>
            {me.height_cm || me.weight_kg ? "Change these" : "Add them"}
          </button>
        </>
      ) : (
        <>
          {problem && (
            <p className="notice notice--refused" role="alert">
              {problem}
            </p>
          )}
          <div className="sizes">
            <label className="sizes__field">
              <span className="sizes__label">Height</span>
              <input
                className="input"
                type="number"
                inputMode="numeric"
                min={100}
                max={250}
                value={height}
                onChange={(event) => setHeight(event.target.value)}
                placeholder="cm"
              />
            </label>
            <label className="sizes__field">
              <span className="sizes__label">Weight</span>
              <input
                className="input"
                type="number"
                inputMode="numeric"
                min={30}
                max={250}
                value={weight}
                onChange={(event) => setWeight(event.target.value)}
                placeholder="kg"
              />
            </label>
          </div>
          <p className="affiliate__lead">
            Leave either one empty to take it off your record.
          </p>
          <div className="sizes__actions">
            <button
              type="button"
              className="button button--primary"
              disabled={saving}
              onClick={save}
            >
              {saving ? "Saving…" : "Save"}
            </button>
            <button
              type="button"
              className="button"
              disabled={saving}
              onClick={() => setOpen(false)}
            >
              Cancel
            </button>
          </div>
        </>
      )}
    </section>
  );
}


function Notifications() {
  const [preferences, setPreferences] = useState<Preference[] | null>(null);
  const [problem, setProblem] = useState<string | null>(null);

  useEffect(() => {
    let current = true;
    api
      .get<{ preferences: Preference[] }>("/api/me/notifications")
      .then((body) => {
        if (current) setPreferences(body.preferences);
      })
      .catch(() => {
        // Quietly. The switches are a convenience; failing to load them is
        // not worth an error banner on somebody's account page.
      });
    return () => {
      current = false;
    };
  }, []);

  if (preferences === null) return null;

  async function toggle(preference: Preference) {
    setProblem(null);
    // Moved at once, so the switch answers the finger rather than the
    // network. Put back if the write fails.
    setPreferences((was) =>
      (was ?? []).map((p) =>
        p.kind === preference.kind ? { ...p, enabled: !p.enabled } : p,
      ),
    );
    try {
      const body = await api.put<{ preferences: Preference[] }>(
        "/api/me/notifications",
        { kind: preference.kind, enabled: !preference.enabled },
      );
      setPreferences(body.preferences);
    } catch {
      setPreferences((was) =>
        (was ?? []).map((p) =>
          p.kind === preference.kind ? { ...p, enabled: preference.enabled } : p,
        ),
      );
      setProblem("That did not save. Check your connection and try again.");
    }
  }

  return (
    <section className="panel affiliate__panel">
      <h2 className="panel__title">Tell me when</h2>
      {problem && (
        <p className="notice notice--refused" role="alert">
          {problem}
        </p>
      )}
      {preferences.map((preference) => (
        <button
          key={preference.kind}
          type="button"
          className="pref pref--row"
          role="switch"
          aria-checked={preference.enabled}
          onClick={() => toggle(preference)}
        >
          <span className="pref__label">{preference.label}</span>
          <span className="pref__switch" aria-hidden="true">
            <span className="pref__knob" />
          </span>
        </button>
      ))}
      <p className="affiliate__note">
        Two, on purpose. An alert for every single order would be an email an
        order.
      </p>
    </section>
  );
}
