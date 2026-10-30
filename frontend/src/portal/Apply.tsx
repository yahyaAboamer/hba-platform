import { useEffect, useState } from "react";

import instapayGuide from "../assets/instapay-link.png";
import { AuthShell } from "../components/AuthShell";
import { api } from "../lib/api";
import {
  accountHolderProblem,
  cardProblem,
  EGYPTIAN_BANKS,
  mobileProblem,
  OTHER_BANK,
  WALLET_PROVIDERS,
} from "../lib/payouts";
import "./Onboarding.css";

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
  bank: "Bank",
  wallet: "Wallet",
};

/** Stroke icons in the portal's weight - never emoji. */
function MethodIcon({ method }: { method: Method }) {
  return (
    <svg
      width="22"
      height="22"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.7"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      {method === "instapay" && <path d="M13 2.5 4.5 13.5H12l-1 8 8.5-11H12l1-8Z" />}
      {method === "bank" && (
        <>
          <path d="M3 9.5 12 4l9 5.5" />
          <path d="M5 10v8M9.7 10v8M14.3 10v8M19 10v8" />
          <path d="M3 20.5h18" />
        </>
      )}
      {method === "wallet" && (
        <>
          <rect x="5.5" y="2.5" width="13" height="19" rx="2.5" />
          <path d="M10.5 18.5h3" />
        </>
      )}
    </svg>
  );
}

/**
 * The circled *i*: what a field is for, on request.
 *
 * The owner's words: the two lines under the discount code "need to either be
 * removed or put inside a small i circled information button". They matter -
 * a code typed wrong is sales that never reach her - so they are kept, and
 * kept out of the way of somebody who already knows.
 */
function InfoTip({ label, children }: { label: string; children: React.ReactNode }) {
  const [open, setOpen] = useState(false);
  return (
    <span className="onboard__tip">
      <button
        type="button"
        className="onboard__tip-button"
        aria-label={label}
        aria-expanded={open}
        onClick={() => setOpen((was) => !was)}
        onKeyDown={(event) => {
          if (event.key === "Escape") setOpen(false);
        }}
        onBlur={() => setOpen(false)}
      >
        <svg
          width="16"
          height="16"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.8"
          strokeLinecap="round"
          aria-hidden="true"
        >
          <circle cx="12" cy="12" r="9.5" />
          <path d="M12 11v5.5" />
          <path d="M12 7.6v.1" />
        </svg>
      </button>
      {open && (
        <span className="onboard__bubble" role="note">
          {children}
        </span>
      )}
    </span>
  );
}

/**
 * §13 step 2. What a model fills in for themselves - step two of two.
 *
 * Phone-first (§12.5), and **said in as few words as the fields allow** (the
 * owner, 26 September): no introduction, no *"your"* on every label, no line
 * under a box that its placeholder already says. What still needs saying -
 * what a discount code is for, where InstaPay keeps its link - is one tap
 * away rather than always on screen.
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
  /**
   * Optional, and kept as text rather than as numbers on purpose: an empty
   * string is a person who did not answer, and `0` would be a measurement.
   */
  const [height, setHeight] = useState("");
  const [weight, setWeight] = useState("");
  const [method, setMethod] = useState<Method>("instapay");
  const [fields, setFields] = useState<Record<string, string>>({});
  const [guideOpen, setGuideOpen] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [working, setWorking] = useState(false);

  // Every method below is Egyptian - an Egyptian mobile, an Egyptian bank
  // card, Egyptian pounds. Somebody abroad has none of those, and inventing
  // details that fit the form would produce money addressed nowhere. So she
  // says so, and applies without them: HBA arranges her payment directly
  // (ADR 0046). She used to be stopped here with the button switched off.
  const [abroad, setAbroad] = useState(false);

  const addressProblem =
    !abroad && method === "instapay"
      ? instapayProblem(fields.instapay_address_url ?? "")
      : null;

  // The field accepted sixteen digits as a name, which is what somebody does
  // when two number fields sit next to each other. The transfer then goes out
  // addressed to a number and the bank returns it.
  const holderProblem =
    !abroad && method === "bank"
      ? accountHolderProblem(fields.bank_account_holder ?? "")
      : null;

  const numberProblem = abroad
    ? null
    : method === "instapay"
      ? mobileProblem(fields.instapay_phone ?? "", "The InstaPay number")
      : method === "wallet"
        ? mobileProblem(fields.wallet_phone ?? "", "The wallet number")
        : cardProblem(fields.bank_account_number ?? "");

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
        // Omitted entirely when blank, so the server sees "not supplied"
        // rather than a null it has to interpret. A05: never a reason to
        // refuse an application.
        ...(height.trim() ? { height_cm: Number(height) } : {}),
        ...(weight.trim() ? { weight_kg: Number(weight) } : {}),
        // Abroad sends no method and no fields at all - not even ones typed
        // before she switched - so nothing half-Egyptian is ever stored.
        ...(abroad ? { abroad: true } : { payout_method: method, ...fields }),
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
      <AuthShell eyebrow="Almost there" title="Your details" step={{ current: 2, of: 2 }}>
        {error ? (
          <p className="notice notice--refused" role="alert">
            {error}
          </p>
        ) : (
          <p className="auth__lead">Loading…</p>
        )}
      </AuthShell>
    );
  }

  return (
    <AuthShell
      eyebrow="Almost there"
      title="Your details"
      step={{ current: 2, of: 2 }}
      onSubmit={submit}
    >
      <label className="field">
        <span className="field__label">Full name</span>
        <input
          className="input"
          required
          autoComplete="name"
          placeholder="First and family name"
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
          autoComplete="tel"
          placeholder="01X XXXX XXXX"
          value={phone}
          onChange={(event) => setPhone(event.target.value)}
        />
      </label>

      <div className="field">
        <span className="onboard__label-row">
          <label className="field__label" htmlFor="apply-code">
            Discount code
          </label>
          <InfoTip label="About the discount code">
            The code customers type at checkout. Enter it exactly as it is in
            the shop — that is how your sales reach you.
          </InfoTip>
        </span>
        <input
          id="apply-code"
          className="input onboard__code"
          required
          autoCapitalize="characters"
          placeholder="e.g. NOUR10"
          value={code}
          onChange={(event) => setCode(event.target.value)}
        />
      </div>

      {/*
       * A05: marketing would like these for sizing. Nothing refuses an
       * application without them, here or on the server. "(optional)" sits on
       * the label, in brackets, because a person filling this in standing up
       * reads labels and skips hints.
       */}
      <fieldset className="field onboard__fieldset">
        <legend className="field__label">
          Height &amp; weight <span className="onboard__optional">(optional)</span>
        </legend>
        <div className="onboard__pair">
          <span className="onboard__unit">
            <input
              className="input"
              type="number"
              inputMode="numeric"
              min={100}
              max={250}
              aria-label="Height in centimetres"
              placeholder="Height"
              value={height}
              onChange={(event) => setHeight(event.target.value)}
            />
            <span aria-hidden="true">cm</span>
          </span>
          <span className="onboard__unit">
            <input
              className="input"
              type="number"
              inputMode="numeric"
              min={30}
              max={250}
              aria-label="Weight in kilograms"
              placeholder="Weight"
              value={weight}
              onChange={(event) => setWeight(event.target.value)}
            />
            <span aria-hidden="true">kg</span>
          </span>
        </div>
      </fieldset>

      <hr className="onboard__rule" />

      <fieldset className="onboard__fieldset onboard__group">
        <legend className="onboard__eyebrow">Getting paid</legend>
        <div className="onboard__segments">
          <label className="onboard__segment">
            <input
              type="radio"
              name="where"
              checked={!abroad}
              onChange={() => setAbroad(false)}
            />
            <span>In Egypt</span>
          </label>
          <label className="onboard__segment">
            <input
              type="radio"
              name="where"
              checked={abroad}
              onChange={() => setAbroad(true)}
            />
            <span>Outside Egypt</span>
          </label>
        </div>
      </fieldset>

      {abroad ? (
        <div className="onboard__abroad">
          <span className="onboard__abroad-icon" aria-hidden="true">
            <svg
              width="20"
              height="20"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.7"
              strokeLinecap="round"
              strokeLinejoin="round"
            >
              <circle cx="12" cy="12" r="9.5" />
              <path d="M2.5 12h19" />
              <path d="M12 2.5c2.6 2.7 3.9 5.9 3.9 9.5s-1.3 6.8-3.9 9.5c-2.6-2.7-3.9-5.9-3.9-9.5S9.4 5.2 12 2.5Z" />
            </svg>
          </span>
          <span className="onboard__abroad-text">
            <strong>We will arrange it with you</strong>
            <span>Send your application — HBA will contact you to set up payment abroad.</span>
          </span>
        </div>
      ) : (
        <>
          <fieldset className="onboard__fieldset">
            <legend className="onboard__sr">How should we pay you?</legend>
            <div className="onboard__methods">
              {(Object.keys(METHOD_LABEL) as Method[]).map((option) => (
                <label key={option} className="onboard__method">
                  <input
                    type="radio"
                    name="method"
                    checked={method === option}
                    onChange={() => {
                      setMethod(option);
                      setFields({});
                      setGuideOpen(false);
                    }}
                  />
                  <span className="onboard__method-face">
                    <MethodIcon method={option} />
                    {METHOD_LABEL[option]}
                  </span>
                </label>
              ))}
            </div>
          </fieldset>

          {method === "instapay" && (
            <>
              <div className="field">
                <span className="onboard__label-row onboard__label-row--split">
                  <label className="field__label" htmlFor="apply-ipn">
                    InstaPay link
                  </label>
                  {/*
                   * §13.1's illustrated guide, folded (the owner, 26
                   * September): most people know where their own link is.
                   * Three steps, and *Copy* named explicitly - tapping Link
                   * opens a share sheet, and "tap Link" alone sends it to
                   * WhatsApp as easily as it copies it.
                   */}
                  <button
                    type="button"
                    className="auth__link"
                    aria-expanded={guideOpen}
                    onClick={() => setGuideOpen((was) => !was)}
                  >
                    {guideOpen ? "Hide" : "Where do I find it?"}
                  </button>
                </span>
                {guideOpen && (
                  <figure className="onboard__guide">
                    <img
                      src={instapayGuide}
                      alt="The InstaPay home screen, with the Link button under your account circled"
                    />
                    <ol>
                      <li>Open InstaPay</li>
                      <li>
                        Tap <strong>Link</strong>
                      </li>
                      <li>
                        Choose <strong>Copy</strong>
                      </li>
                    </ol>
                  </figure>
                )}
                <input
                  id="apply-ipn"
                  className="input"
                  required
                  inputMode="url"
                  placeholder="https://ipn.eg/…"
                  value={fields.instapay_address_url ?? ""}
                  onChange={(event) => set("instapay_address_url", event.target.value)}
                  aria-invalid={addressProblem !== null}
                />
                {addressProblem && <span className="blocker">{addressProblem}</span>}
              </div>

              <label className="field">
                <span className="field__label">InstaPay number</span>
                <input
                  className="input"
                  type="tel"
                  required
                  placeholder="01X XXXX XXXX"
                  value={fields.instapay_phone ?? ""}
                  onChange={(event) => set("instapay_phone", event.target.value)}
                />
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
                <span className="field__label">Account holder</span>
                <input
                  className="input"
                  required
                  placeholder="Name exactly as the bank has it"
                  value={fields.bank_account_holder ?? ""}
                  onChange={(event) => set("bank_account_holder", event.target.value)}
                  aria-invalid={holderProblem !== null}
                />
                {holderProblem && <span className="blocker">{holderProblem}</span>}
              </label>
              {/*
               * The card, not the account number. Egyptian account numbers
               * vary in length by bank, so no single rule could check one
               * without refusing somebody's real account - and the card is
               * sixteen digits everywhere.
               */}
              <label className="field">
                <span className="field__label">Card number</span>
                <input
                  className="input"
                  required
                  inputMode="numeric"
                  placeholder="16 digits on your card"
                  value={fields.bank_account_number ?? ""}
                  onChange={(event) => set("bank_account_number", event.target.value)}
                />
              </label>
            </>
          )}

          {method === "wallet" && (
            <>
              {/*
               * All four take the same eleven digits, so the number alone
               * does not say where a transfer should go - which is why the
               * provider is asked at all.
               */}
              <label className="field">
                <span className="field__label">Wallet</span>
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
              </label>
              <label className="field">
                <span className="field__label">Wallet number</span>
                <input
                  className="input"
                  type="tel"
                  required
                  placeholder="01X XXXX XXXX"
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
          {numberProblem && <span className="blocker">{numberProblem}</span>}
        </>
      )}

      {error && (
        <p className="notice notice--refused auth__error" role="alert">
          {error}
        </p>
      )}

      <button
        type="submit"
        className="button button--primary auth__submit"
        disabled={
          working ||
          addressProblem !== null ||
          numberProblem !== null ||
          holderProblem !== null
        }
      >
        {working ? "Sending…" : "Send application"}
      </button>
    </AuthShell>
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
