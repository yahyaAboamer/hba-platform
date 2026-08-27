import { useEffect, useState } from "react";

import { api } from "../lib/api";
import "./Apply.css";

type Mine = {
  applied: boolean;
  status: string | null;
  required_fields: Record<string, string[]>;
};

type Method = "instapay" | "bank" | "wallet";

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
        <h1 className="apply__title">Join the programme</h1>
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
            <label className="field">
              <span className="field__label">Your InstaPay payment address</span>
              <input
                className="input"
                required
                value={fields.instapay_address_url ?? ""}
                onChange={(event) => set("instapay_address_url", event.target.value)}
                placeholder="https://ipn.eg/S/your-name/instapay/…"
              />
              {/*
               * §13.1 wants an illustrated guide here showing where this lives
               * in the InstaPay app. The screenshots are an asset the business
               * has to provide; until they exist this is written guidance in
               * the same place the images will go, rather than a field with no
               * explanation at all.
               */}
              <span className="apply__hint">
                Open InstaPay, go to your profile, and copy your{" "}
                <strong>payment address</strong>. It is a link starting{" "}
                <code className="code">https://ipn.eg/</code> — not your phone
                number.
              </span>
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
          disabled={working}
        >
          {working ? "Sending…" : "Send my application"}
        </button>
      </form>
    </main>
  );
}
