import { useEffect, useState } from "react";

import instapayGuide from "../assets/instapay-link.png";
import { api } from "../lib/api";
import {
  accountHolderProblem,
  cardProblem,
  EGYPTIAN_BANKS,
  mobileProblem,
  OTHER_BANK,
  WALLET_PROVIDERS,
} from "../lib/payouts";
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
 * not wait on a round trip to be told they pasted their phone number.
 *
 * The host is checked and the path is not, for the reason the server gives:
 * no real address has ever been seen here, and refusing a genuine one because
 * its path looks unfamiliar would stop them joining at all.
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
 * §13 step 2. What a model fills in for themselves.
 *
 * Phone-first (§12.5): the admin screens are used to reconcile twenty rows at
 * month end on a laptop; this one is filled in once, standing up, on a phone.
 *
 * **Nothing here decides what they are paid.** No rate, no salary, no targets —
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

  // The field accepted sixteen digits as a name, which is what somebody does
  // when two number fields sit next to each other. The transfer then goes out
  // addressed to a number and the bank returns it.
  const holderProblem =
    method === "bank"
      ? accountHolderProblem(fields.bank_account_holder ?? "")
      : null;

  // Everything below assumes an Egyptian bank, an Egyptian mobile and Egyptian
  // pounds. Somebody abroad has none of those, and inventing details that fit
  // the form would produce money addressed nowhere - so the question is asked
  // before the fields, and answered honestly if the answer is "not yet".
  const [inEgypt, setInEgypt] = useState(true);

  const numberProblem =
    method === "instapay"
      ? mobileProblem(fields.instapay_phone ?? "", "The InstaPay number")
      : method === "wallet"
        ? mobileProblem(fields.wallet_phone ?? "", "The wallet number")
        : method === "bank"
          ? cardProblem(fields.bank_account_number ?? "")
          : null;

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
          <span className="field__label">Your name</span>
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

        {/*
         * **Asked before how, because it decides whether how is answerable.**
         * Every option below is Egyptian - an Egyptian mobile, an Egyptian
         * bank card, Egyptian pounds. Somebody abroad filling those in
         * produces details nobody can pay, and the first anybody learns of it
         * is a failed transfer.
         *
         * Plain words rather than "domestic" and "international": the person
         * reading this is telling us where they are, not classifying
         * themselves.
         */}
        <fieldset className="apply__choice">
          <legend className="field__label">Where is your bank or wallet?</legend>
          <label className={inEgypt ? "pay__option pay__option--on" : "pay__option"}>
            <input
              type="radio"
              name="based"
              checked={inEgypt}
              onChange={() => setInEgypt(true)}
            />
            <span className="pay__option-body">
              <strong>In Egypt</strong>
            </span>
          </label>
          <label className={!inEgypt ? "pay__option pay__option--on" : "pay__option"}>
            <input
              type="radio"
              name="based"
              checked={!inEgypt}
              onChange={() => setInEgypt(false)}
            />
            <span className="pay__option-body">
              <strong>Outside Egypt</strong>
            </span>
          </label>
        </fieldset>

        {!inEgypt && (
          <p className="notice apply__abroad">
            We pay in Egyptian pounds through InstaPay, a local bank or a mobile
            wallet, and none of those will reach you outside Egypt. Email us at{" "}
            <a href="mailto:yahyaaboaamer@gmail.com">yahyaaboaamer@gmail.com</a>{" "}
            and we will arrange it with you directly — please do not fill in
            somebody else's account here.
          </p>
        )}

        {inEgypt && (
        <>
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
            <BankField
              value={fields.bank_name ?? ""}
              onChange={(next) => set("bank_name", next)}
            />
            <label className="field">
              <span className="field__label">Account holder&rsquo;s name</span>
              <input
                className="input"
                required
                value={fields.bank_account_holder ?? ""}
                onChange={(event) => set("bank_account_holder", event.target.value)}
                aria-invalid={holderProblem !== null}
              />
              <span className="apply__hint">Exactly as the bank has it.</span>
              {holderProblem && (
                <span className="blocker apply__problem">{holderProblem}</span>
              )}
            </label>
            <label className="field">
              <span className="field__label">Card number</span>
              <input
                className="input"
                required
                inputMode="numeric"
                value={fields.bank_account_number ?? ""}
                onChange={(event) => set("bank_account_number", event.target.value)}
              />
              {/*
               * The card, not the account number. Egyptian account numbers
               * vary in length by bank, so no single rule could check one
               * without refusing somebody's real account - and the card is
               * sixteen digits everywhere.
               */}
              <span className="apply__hint">
                The 16 digits on the front of your bank card.
              </span>
            </label>
          </>
        )}

        {method === "wallet" && (
          <>
            <label className="field">
              <span className="field__label">Which wallet</span>
              <select
                className="input"
                required
                value={fields.wallet_provider ?? ""}
                onChange={(event) => set("wallet_provider", event.target.value)}
              >
                <option value="" disabled>
                  Choose one
                </option>
                {WALLET_PROVIDERS.map((provider) => (
                  <option key={provider} value={provider}>
                    {provider}
                  </option>
                ))}
              </select>
              {/*
               * All four take the same eleven digits, so the number alone
               * does not say where a transfer should go — whoever sends it
               * has been guessing from the prefix, and prefixes have been
               * portable in Egypt for years.
               */}
              <span className="apply__hint">
                Every wallet uses the same number format, so this is what says
                where the money should go.
              </span>
            </label>
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
          </>
        )}

        {/*
         * One place for whichever number is in play, said while the field is
         * still under their finger. The form used to take a five-digit
         * "phone" and a nine-digit "card" without a word - money addressed to
         * nowhere, and nobody finds out until a transfer fails.
         */}
        {numberProblem && (
          <span className="blocker apply__problem">{numberProblem}</span>
        )}
        </>
        )}

        <button
          type="submit"
          className="button button--primary apply__submit"
          disabled={
            working ||
            !inEgypt ||
            addressProblem !== null ||
            numberProblem !== null ||
            holderProblem !== null
          }
        >
          {working ? "Sending…" : "Send my application"}
        </button>
      </form>
    </main>
  );
}


/**
 * Which bank, from a list, with a way out.
 *
 * The field was free text and collected "cib", "بنك مصر" and "Bank" - none of
 * them wrong exactly, and none of them the same as each other when somebody
 * is sending twenty transfers at month end.
 *
 * **"Another bank" reveals a text field rather than blocking.** This list
 * will be out of date the first time two banks merge, and a model who cannot
 * name their own bank cannot be paid. Constraining the common case is worth
 * doing; refusing the uncommon one is not.
 */
function BankField({
  value,
  onChange,
}: {
  value: string;
  onChange: (value: string) => void;
}) {
  const listed = (EGYPTIAN_BANKS as readonly string[]).includes(value);
  // Anything already typed that is not on the list keeps the form in its
  // "other" state, so an existing destination does not silently lose its bank
  // the first time somebody opens this screen.
  const [other, setOther] = useState(value !== "" && !listed);

  return (
    <>
      <label className="field">
        <span className="field__label">Bank</span>
        <select
          className="input"
          required
          value={other ? OTHER_BANK : value}
          onChange={(event) => {
            const chosen = event.target.value;
            if (chosen === OTHER_BANK) {
              setOther(true);
              onChange("");
            } else {
              setOther(false);
              onChange(chosen);
            }
          }}
        >
          <option value="" disabled>
            Choose your bank
          </option>
          {EGYPTIAN_BANKS.map((bank) => (
            <option key={bank} value={bank}>
              {bank}
            </option>
          ))}
          <option value={OTHER_BANK}>{OTHER_BANK}…</option>
        </select>
      </label>

      {other && (
        <label className="field">
          <span className="field__label">Which bank</span>
          <input
            className="input"
            required
            value={value}
            onChange={(event) => onChange(event.target.value)}
          />
        </label>
      )}
    </>
  );
}
