import { useEffect, useState } from "react";

import { api } from "../lib/api";
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
  /**
   * Where HBA sends her things (D11).
   *
   * **Both sides edit this**, unlike her measurements: HBA types it into the
   * order, so the person shipping to her needs the current one without having
   * to ask her to update it first.
   */
  shipping: {
    shipping_name: string | null;
    shipping_phone: string | null;
    shipping_line1: string | null;
    shipping_line2: string | null;
    shipping_city: string | null;
    shipping_governorate: string | null;
    shipping_notes: string | null;
  };
  status: string;
  state: string;
  /**
   * Which of the three arrangements she is on this month, raw, labelled by
   * the screen through `PAY_TYPE`. `null` means nobody has set her terms —
   * not commission, which is an arrangement somebody would have had to agree.
   */
  arrangement: string | null;
  /** `YYYY-MM` she started with HBA, where anybody recorded it. */
  since: string | null;
  codes: { code: string; verified: boolean }[];
  payout_destination: Record<string, string | null> | null;
  /**
   * She applied from outside Egypt and HBA arranges her payment directly
   * (ADR 0046) - why `payout_destination` is empty, when it is.
   */
  payout_abroad?: boolean;
  required_fields: Record<string, string[]>;
};


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

export function Reveal() {
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
 * Where HBA sends her things.
 *
 * D11: **both sides edit this.** Her measurements are hers alone; this is not,
 * because staff type it into an order and a model who has moved should not be
 * a parcel that cannot be sent.
 *
 * The phone is checked as an Egyptian mobile before it saves, and the reason
 * is worth knowing: it is the number a parcel is matched back to her by, so a
 * number that cannot be read is a delivery that never reaches her wardrobe.
 */
export function ShippingAddress({ me, onChanged }: { me: Me; onChanged: () => void }) {
  const [open, setOpen] = useState(false);
  const [draft, setDraft] = useState(me.shipping);
  const [saving, setSaving] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);

  const lines = [
    me.shipping.shipping_line1,
    me.shipping.shipping_line2,
    me.shipping.shipping_city,
    me.shipping.shipping_governorate,
  ].filter(Boolean);

  async function save() {
    setSaving(true);
    setProblem(null);
    try {
      await api.put("/api/me/shipping-address", draft);
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

  const FIELDS: [keyof Me["shipping"], string][] = [
    ["shipping_name", "Name on the parcel"],
    ["shipping_phone", "Phone the courier calls"],
    ["shipping_line1", "Street and number"],
    ["shipping_line2", "Flat, floor"],
    ["shipping_city", "Area"],
    ["shipping_governorate", "Governorate"],
    ["shipping_notes", "Anything else the courier needs"],
  ];

  return (
    <section className="panel affiliate__panel">
      <h2 className="panel__title">Where we send things</h2>
      {!open ? (
        <>
          <p className="affiliate__lead">
            {lines.length > 0
              ? lines.join(", ")
              : "You have not given us an address. We cannot send you anything without one."}
          </p>
          <button
            type="button"
            className="button"
            onClick={() => {
              setDraft(me.shipping);
              setProblem(null);
              setOpen(true);
            }}
          >
            {lines.length > 0 ? "Change it" : "Add it"}
          </button>
        </>
      ) : (
        <>
          {problem && (
            <p className="notice notice--refused" role="alert">
              {problem}
            </p>
          )}
          <div className="address">
            {FIELDS.map(([field, label]) => (
              <label key={field} className="field">
                <span className="field__label">{label}</span>
                <input
                  className="input"
                  type={field === "shipping_phone" ? "tel" : "text"}
                  inputMode={field === "shipping_phone" ? "tel" : undefined}
                  value={draft[field] ?? ""}
                  onChange={(event) =>
                    setDraft({ ...draft, [field]: event.target.value })
                  }
                />
              </label>
            ))}
          </div>
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
export function Measurements({ me, onChanged }: { me: Me; onChanged: () => void }) {
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


export function Notifications() {
  const [preferences, setPreferences] = useState<Preference[] | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadFailed, setLoadFailed] = useState(false);
  const [retry, setRetry] = useState(0);

  useEffect(() => {
    let current = true;
    setLoading(true);
    setLoadFailed(false);
    api
      .get<{ preferences: Preference[] }>("/api/me/notifications")
      .then((body) => {
        if (current) {
          setPreferences(body.preferences);
          setLoading(false);
        }
      })
      .catch(() => {
        if (current) {
          setLoadFailed(true);
          setLoading(false);
        }
      });
    return () => {
      current = false;
    };
  }, [retry]);

  if (loading) return <section className="panel affiliate__panel notifications__loading" role="status" aria-label="Loading notification choices">
    <div className="you__placeholder you__placeholder--name" />
    <div className="you__placeholder you__placeholder--line" />
    <div className="you__placeholder you__placeholder--line" />
  </section>;

  if (loadFailed || preferences === null) return <section className="panel affiliate__panel notifications__failure" role="alert">
    <h2 className="panel__title">Could not load your choices</h2>
    <p>Check your connection and try again. Your existing choices have not changed.</p>
    <button type="button" className="button" onClick={() => setRetry((was) => was + 1)}>Try again</button>
  </section>;

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
      <div className="notifications__head">
        <h2 className="panel__title">Tell me when</h2>
        <p>These choices save as soon as you switch them.</p>
      </div>
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
      <div className="notifications__foot">
        <strong>Messages that always arrive</strong>
        <p>Password, security and payment-destination-change messages cannot be switched off here. There is no email for every order.</p>
      </div>
    </section>
  );
}
