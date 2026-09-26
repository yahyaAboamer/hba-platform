import { useState } from "react";

import { api } from "../lib/api";
import { destinationHolder } from "../lib/payouts";
import type { Me } from "./MyDetails";
import { MyPayout } from "./MyPayout";
import "./Onboarding.css";

type Destination = Record<string, string | null>;

/** The field that tells her which account it is, in the order they matter. */
const IDENTIFYING = [
  "bank_account_number",
  "wallet_phone",
  "instapay_phone",
  "instapay_address_url",
] as const;

function identifying(destination: Destination): string[] {
  return IDENTIFYING.map((field) => destination[field])
    .filter((value): value is string => Boolean(value))
    .map((value) => value.replace(/^https?:\/\//, ""));
}

function EyeIcon({ open }: { open: boolean }) {
  return (
    <svg
      width="17"
      height="17"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.7"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d="M1.5 12S5 5.5 12 5.5 22.5 12 22.5 12 19 18.5 12 18.5 1.5 12 1.5 12Z" />
      <circle cx="12" cy="12" r="3.2" />
      {!open && <path d="M3 21 21 3" />}
    </svg>
  );
}

function Tick() {
  return (
    <svg
      width="13"
      height="13"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="3"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d="M5 12.5 10 17.5 19 7" />
    </svg>
  );
}

type StepState = "done" | "now" | "next";

function Step({
  state,
  label,
  note,
}: {
  state: StepState;
  label: string;
  note?: string;
}) {
  return (
    <li className={`pending__step pending__step--${state}`}>
      <span className="pending__marker" aria-hidden="true">
        <span className="pending__node">
          {state === "done" && <Tick />}
          {state === "now" && <span className="pending__dot" />}
        </span>
        <span className="pending__line" />
      </span>
      <span className="pending__words">
        {state === "now" ? <strong>{label}</strong> : label}
        {note && <span className="pending__now">{note}</span>}
        <span className="onboard__sr">
          {state === "done" ? " — done" : state === "now" ? "" : " — not yet"}
        </span>
      </span>
    </li>
  );
}

/**
 * What a model sees between sending her application and being approved.
 *
 * **One thing, said big**: HBA is checking her code, and there is nothing for
 * her to do. It used to be two panels of the same weight, a paragraph each,
 * with the only action an underlined link wedged against a bordered button
 * (the owner, 26 September: "no bold things or big things for the most needed
 * information"). Now the state is a badge and a heading, the path from here to
 * earning is four steps she can see herself on, and her details are rows she
 * can read at a glance.
 *
 * **Her own screen, not the You tab's.** `MyDetails` is the approved export's
 * You panel and stays exactly that; this screen borrows only its payout form
 * (`MyPayout`) for *Change*.
 *
 * **The account stays shortened until she asks** - an eye beside it, rather
 * than a sentence explaining why it is shortened. Reading it back is audited
 * on the server (`/api/me/payout-destination`), as it always was.
 */
export function ApplicationPending({
  me,
  onChanged,
}: {
  me: Me;
  onChanged: () => void | Promise<void>;
}) {
  const [changing, setChanging] = useState(false);
  const [changed, setChanged] = useState(false);
  const [full, setFull] = useState<Destination | null>(null);
  const [reading, setReading] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);

  const code = me.codes[0]?.code ?? null;
  const destination = me.payout_destination;

  if (changing) {
    return (
      <MyPayout
        current={destination}
        required={me.required_fields}
        onChanged={async () => {
          // Wait for the record to come back before closing the form, so the
          // row behind it is already showing the new destination.
          await onChanged();
          setFull(null);
          setChanging(false);
          setChanged(true);
        }}
        onCancel={() => setChanging(false)}
      />
    );
  }

  async function toggleFull() {
    if (full) {
      setFull(null);
      return;
    }
    setReading(true);
    setProblem(null);
    try {
      setFull(await api.get<Destination>("/api/me/payout-destination"));
    } catch (caught) {
      setProblem(
        caught instanceof Error ? caught.message : "Could not read them back. Try again.",
      );
    } finally {
      setReading(false);
    }
  }

  return (
    <div className="pending">
      <section className="pending__card pending__hero" aria-labelledby="pending-title">
        <span className="pending__badge">
          <span className="pending__dot" aria-hidden="true" />
          In review
        </span>
        <h1 className="pending__title" id="pending-title">
          We&rsquo;re checking your code
        </h1>
        <p className="pending__lead">
          You&rsquo;ll get an email once{" "}
          {code ? <strong>{code}</strong> : "your code"} is approved. Nothing else
          to do.
        </p>

        <ol className="pending__steps">
          <Step state="done" label="Account created" />
          <Step state="done" label="Details sent" />
          <Step state="now" label="Code approval" note="In progress" />
          <Step state="next" label="Start earning" />
        </ol>
      </section>

      {changed && (
        <p className="notice notice--settled" role="status">
          Changed. This is where your money will be sent from now on.
        </p>
      )}

      <section className="pending__card" aria-labelledby="pending-details">
        <h2 className="pending__heading" id="pending-details">
          Your details
        </h2>

        <div className="pending__row">
          <span className="pending__field">
            <span className="pending__label">Discount code</span>
            <span className="pending__value pending__value--code">{code ?? "—"}</span>
          </span>
          {me.codes[0] && !me.codes[0].verified && (
            <span className="pending__pill">Checking</span>
          )}
        </div>

        <div className="pending__row">
          <span className="pending__field">
            <span className="pending__label">Paid to</span>
            {destination ? (
              <>
                <span className="pending__value">{destinationHolder(destination)}</span>
                <span className="pending__sub">
                  <span>{identifying(full ?? destination).join(" · ")}</span>
                  <button
                    type="button"
                    className="pending__eye"
                    onClick={toggleFull}
                    disabled={reading}
                    aria-pressed={full !== null}
                    aria-label={full ? "Shorten the number again" : "Show the full number"}
                  >
                    <EyeIcon open={full !== null} />
                  </button>
                </span>
              </>
            ) : me.payout_abroad ? (
              <>
                <span className="pending__value">Outside Egypt</span>
                <span className="pending__sub">HBA will arrange it with you</span>
              </>
            ) : (
              <span className="pending__value pending__value--plain">
                Nothing on file yet
              </span>
            )}
          </span>
          <button
            type="button"
            className="pending__change"
            onClick={() => setChanging(true)}
          >
            {destination ? "Change" : "Add"}
          </button>
        </div>
        {problem && (
          <p className="notice notice--refused" role="alert">
            {problem}
          </p>
        )}

        {/*
         * "Sign-in email", not "Email" (D07): she has one address and it is
         * her login. Shown, not editable - moving a login is a real change.
         */}
        <div className="pending__row">
          <span className="pending__field">
            <span className="pending__label">Sign-in email</span>
            <span className="pending__value pending__value--plain">{me.email}</span>
          </span>
        </div>
      </section>
    </div>
  );
}
