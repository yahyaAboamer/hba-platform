import { useState } from "react";

import { api } from "../lib/api";
import { instapayProblem } from "./Apply";
import "./Apply.css";

type Masked = Record<string, string | null> | null;

type Method = "instapay" | "bank" | "wallet";

const METHOD_LABEL: Record<Method, string> = {
  instapay: "InstaPay",
  bank: "Bank transfer",
  wallet: "Mobile wallet",
};

const FIELD_LABEL: Record<string, string> = {
  instapay_address_url: "InstaPay payment address",
  instapay_phone: "InstaPay number",
  bank_name: "Bank",
  bank_account_holder: "Account holder",
  bank_account_number: "Account number",
  wallet_phone: "Wallet number",
};

/**
 * §6.4. Where her money goes — the highest-risk thing she can do.
 *
 * Two steps, deliberately. The password is asked for at the point of
 * committing rather than up front, so she confirms the change and authorises
 * it in one deliberate act instead of typing a password before she knows what
 * she is authorising.
 */
export function MyPayout({
  current,
  required,
  onChanged,
  onCancel,
}: {
  current: Masked;
  required: Record<string, string[]>;
  onChanged: () => void;
  onCancel: () => void;
}) {
  const [method, setMethod] = useState<Method>(
    (current?.method as Method) ?? "instapay",
  );
  const [fields, setFields] = useState<Record<string, string>>({});
  const [password, setPassword] = useState("");
  const [confirming, setConfirming] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [working, setWorking] = useState(false);

  const needed = required[method] ?? [];
  const addressProblem =
    method === "instapay"
      ? instapayProblem(fields.instapay_address_url ?? "")
      : null;
  const incomplete = needed.some((field) => !(fields[field] ?? "").trim());

  async function commit(event: React.FormEvent) {
    event.preventDefault();
    setWorking(true);
    setError(null);
    try {
      await api.put("/api/me/payout-destination", {
        password,
        method,
        ...fields,
      });
      onChanged();
    } catch (caught) {
      setError(
        caught instanceof Error ? caught.message : "Could not change that.",
      );
      // Never left filled after a failure - the next attempt is a fresh,
      // deliberate act rather than one click on a stale form.
      setPassword("");
    } finally {
      setWorking(false);
    }
  }

  return (
    <section className="panel apply__panel">
      <h2 className="panel__title">Change where you are paid</h2>

      {error && (
        <p className="notice notice--refused apply__error" role="alert">
          {error}
        </p>
      )}

      <p className="apply__lead">
        This changes where your money is sent. HBA is told whenever it moves.
      </p>

      {!confirming ? (
        <>
          <fieldset className="apply__choice">
            <legend className="field__label">How should we pay you?</legend>
            {(Object.keys(METHOD_LABEL) as Method[]).map((option) => (
              <label
                key={option}
                className={
                  method === option
                    ? "apply__option apply__option--on"
                    : "apply__option"
                }
              >
                <input
                  type="radio"
                  name="new-method"
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

          {needed.map((field) => (
            <label className="field" key={field}>
              <span className="field__label">{FIELD_LABEL[field] ?? field}</span>
              <input
                className="input"
                value={fields[field] ?? ""}
                onChange={(event) =>
                  setFields((was) => ({ ...was, [field]: event.target.value }))
                }
                aria-invalid={
                  field === "instapay_address_url" && addressProblem !== null
                }
              />
              {field === "instapay_address_url" && addressProblem && (
                <span className="blocker apply__problem">{addressProblem}</span>
              )}
            </label>
          ))}

          <div className="apply__actions">
            <button type="button" className="button" onClick={onCancel}>
              Cancel
            </button>
            <button
              type="button"
              className="button button--primary"
              disabled={incomplete || addressProblem !== null}
              onClick={() => setConfirming(true)}
            >
              Continue
            </button>
          </div>
        </>
      ) : (
        <form onSubmit={commit}>
          {/*
           * §6.4.2. Both sides shown masked. She supplied both, so masking
           * costs her nothing and means the screen she is looking at is not
           * one worth photographing.
           */}
          <dl className="apply__compare">
            <div>
              <dt>Now</dt>
              <dd>{describe(current)}</dd>
            </div>
            <div>
              <dt>After this change</dt>
              <dd>
                {METHOD_LABEL[method]} ·{" "}
                <span className="code">
                  …{(fields[needed[needed.length - 1]] ?? "").slice(-4)}
                </span>
              </dd>
            </div>
          </dl>

          {/*
           * §6.4.1. The password, not the session - a session is what an
           * attacker already has. Asked here rather than up front so she
           * confirms and authorises in one act, knowing what she is
           * authorising.
           */}
          <label className="field">
            <span className="field__label">Enter your password to confirm</span>
            <input
              className="input"
              type="password"
              autoComplete="current-password"
              required
              value={password}
              onChange={(event) => setPassword(event.target.value)}
            />
          </label>

          <div className="apply__actions">
            <button
              type="button"
              className="button"
              onClick={() => {
                setConfirming(false);
                setPassword("");
              }}
              disabled={working}
            >
              Back
            </button>
            <button
              type="submit"
              className="button button--primary"
              disabled={working || !password}
            >
              {working ? "Changing…" : "Change where I am paid"}
            </button>
          </div>
        </form>
      )}
    </section>
  );
}

function describe(destination: Masked): string {
  if (!destination) return "Nothing on file";
  const method = (destination.method as Method) ?? "instapay";
  const shown =
    destination.instapay_address_url ??
    destination.bank_account_number ??
    destination.wallet_phone ??
    "";
  return `${METHOD_LABEL[method] ?? method} · ${shown}`;
}
