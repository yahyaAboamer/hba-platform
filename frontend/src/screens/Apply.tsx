import { useEffect, useState } from "react";

import instapayGuide from "../assets/instapay-link.png";
import { api } from "../lib/api";
import "./Apply.css";

type Mine = {
  applied: boolean;
  status: string | null;
  required_fields: Record<string, string[]>;
};

type Method = "instapay" | "bank" | "wallet";

/**
 * The same rule as `normalise_instapay_address` on the server, for immediate
 * feedback. **The server is the control; this is the courtesy.** It is
 * duplicated rather than fetched because a model typing into a field should
 * not wait on a round trip to be told she pasted her phone number.
 *
 * The host is checked and the path is not, for the reason the server gives:
 * no real address has ever been seen here, and refusing a genuine one because
 * its path looks unfamiliar would stop her joining at all.
 */
export function instapayProblem(value: string): string | null {
  const cleaned = value.trim();
  if (!cleaned) return null;

  if (/^[+\d][\d\s\-()]*$/.test(cleaned)) {
    return "That looks like your phone number — it goes in the field below. The payment address is a link starting https://ipn.eg/";
  }

  let host: string;
  try {
    host = new URL(cleaned.includes("://") ? cleaned : `https://${cleaned}`)
      .hostname.toLowerCase();
  } catch {
    return "That is not a link. Tap Link in InstaPay and copy what it gives you.";
  }

  if (host !== "ipn.eg" && !host.endsWith(".ipn.eg")) {
    return `An InstaPay payment address is a link on ipn.eg — that one points at ${host}.`;
  }

  return null;
}

const METHOD_LABEL: Record<Method, string> = {
  instapay: "InstaPay",
  bank: "Bank transfer",
  wallet: "Mobile wallet",
};

/**
 * §13 step 2. What a model fills in for herself.
 *
 * Phone-first (§12.5): the admin screens are used to reconcile twenty rows at
 * month end on a laptop; this one is filled in once, standing up, on a phone.
 *
 * **Nothing here decides what she is paid.** No rate, no salary, no targets —
 * §6.5. Their absence is enforced server-side; the form simply has nowhere to
 * put them.
 */
export function Apply({ onApplied }: { onApplied: () => void }) {
  const [mine, setMine] = useState<Mine | null>(null);
  const [name, setName] = useState("");
  const [phone, setPhone] = useState("");
  const [code, setCode] = useState("");
  const [method, setMethod] = useState<Method>("instapay");
  const [fields, setFields] = useState<Record<string, string>>({});
  const [error, setError] = useState<string | null>(null);
  const [working, setWorking] = useState(false);

  const addressProblem =
    method === "instapay" ? instapayProblem(fields.instapay_address_url ?? "") : null;

  useEffect(() => {
    api
      .get<Mine>("/api/applications/mine")
      .then(setMine)
      .catch((caught) => setError(caught.message));
  }, []);

  function set(field: string, value: string) {
    setFields((was) => ({ ...was, [field]: value }));
  }

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setWorking(true);
    setError(null);
    try {
      await api.post("/api/applications", {
        name: name.trim(),
        phone: phone.trim(),
        code: code.trim(),
        payout_method: method,
        ...fields,
      });
      onApplied();
    } catch (caught) {
      setError(
        caught instanceof Error ? caught.message : "Could not send that.",
      );
    } finally {
      setWorking(false);
    }
  }

  if (mine === null) {
    return (
      <main className="apply">
        {error ? (
          <p className="notice notice--refused" role="alert">
            {error}
          </p>
        ) : (
          <p className="empty">Loading…</p>
        )}
      </main>
    );
  }

  return (
    <main className="apply">
      <div className="apply__brand">
        <span className="apply__mark">HBA</span>
        <h1 className="apply__title">Your details</h1>
      </div>

      <p className="apply__lead">
        We need a few details before you can start earning. Your discount code
        is checked against the shop before you are approved, so type it exactly
        as it appears there.
      </p>

      {error && (
        <p className="notice notice--refused apply__error" role="alert">
          {error}
        </p>
      )}

      <form onSubmit={submit}>
        <label className="field">
          <span className="field__label">Your full name</span>
          <input
            className="input"
            required
            value={name}
            onChange={(event) => setName(event.target.value)}
          />
        </label>

        <label className="field">
          <span className="field__label">Phone number</span>
          <input
            className="input"
            type="tel"
            required
            value={phone}
            onChange={(event) => setPhone(event.target.value)}
          />
        </label>

        <label className="field">
          <span className="field__label">Your discount code</span>
          <input
            className="input apply__code"
            required
            value={code}
            onChange={(event) => setCode(event.target.value)}
            placeholder="NOUR10"
          />
          <span className="apply__hint">
            The code your customers type at checkout. If it does not match the
            shop exactly, your sales will not reach you.
          </span>
        </label>

        <fieldset className="apply__choice">
          <legend className="field__label">How should we pay you?</legend>
          {(Object.keys(METHOD_LABEL) as Method[]).map((option) => (
            <label
              key={option}
              className={
                method === option ? "apply__option apply__option--on" : "apply__option"
              }
            >
              <input
                type="radio"
                name="method"
                checked={method === option}
                onChange={() => {
                  setMethod(option);
                  setFields({});
                }}
              />
              {METHOD_LABEL[option]}
            </label>
          ))}
        </fieldset>

        {method === "instapay" && (
          <>
            {/*
             * §13.1's illustrated guide. The steps are written from what the
             * business observed doing it: tapping Link opens a share sheet
             * offering apps as well as Copy, and somebody following "tap Link"
             * alone can easily send it to WhatsApp instead of copying it. So
             * the instruction names Copy explicitly.
             */}
            <figure className="apply__guide">
              <img
                className="apply__guide-image"
                src={instapayGuide}
                alt="The InstaPay home screen, with the Link button under your account circled"
              />
              <figcaption className="apply__guide-steps">
                <strong>Where to find it</strong>
                <ol>
                  <li>Open InstaPay.</li>
                  <li>
                    Under your account, tap <strong>Link</strong> — circled
                    above.
                  </li>
                  <li>
                    Choose <strong>Copy</strong>. It will also offer to send it
                    through other apps; you want Copy.
                  </li>
                  <li>Paste it below.</li>
                </ol>
              </figcaption>
            </figure>

            <label className="field">
              <span className="field__label">Your InstaPay payment address</span>
              <input
                className="input"
                required
                value={fields.instapay_address_url ?? ""}
                onChange={(event) => set("instapay_address_url", event.target.value)}
                placeholder="https://ipn.eg/…"
                aria-invalid={addressProblem !== null}
              />
              {addressProblem ? (
                <span className="blocker apply__problem">{addressProblem}</span>
              ) : (
                <span className="apply__hint">
                  A link starting{" "}
                  <code className="code">https://ipn.eg/</code> — not your phone
                  number.
                </span>
              )}
            </label>

            <label className="field">
              <span className="field__label">Your InstaPay number</span>
              <input
                className="input"
                type="tel"
                required
                value={fields.instapay_phone ?? ""}
                onChange={(event) => set("instapay_phone", event.target.value)}
              />
              <span className="apply__hint">
                Used if the payment address does not open. Both are needed.
              </span>
            </label>
          </>
        )}

        {method === "bank" && (
          <>
            <label className="field">
              <span className="field__label">Bank</span>
              <input
                className="input"
                required
                value={fields.bank_name ?? ""}
                onChange={(event) => set("bank_name", event.target.value)}
              />
            </label>
            <label className="field">
              <span className="field__label">Account holder's name</span>
              <input
                className="input"
                required
                value={fields.bank_account_holder ?? ""}
                onChange={(event) => set("bank_account_holder", event.target.value)}
              />
              <span className="apply__hint">Exactly as the bank has it.</span>
            </label>
            <label className="field">
              <span className="field__label">Account number</span>
              <input
                className="input"
                required
                value={fields.bank_account_number ?? ""}
                onChange={(event) => set("bank_account_number", event.target.value)}
              />
            </label>
          </>
        )}

        {method === "wallet" && (
          <label className="field">
            <span className="field__label">Wallet number</span>
            <input
              className="input"
              type="tel"
              required
              value={fields.wallet_phone ?? ""}
              onChange={(event) => set("wallet_phone", event.target.value)}
            />
          </label>
        )}

        <button
          type="submit"
          className="button button--primary apply__submit"
          disabled={working || addressProblem !== null}
        >
          {working ? "Sending…" : "Send my application"}
        </button>
      </form>
    </main>
  );
}
