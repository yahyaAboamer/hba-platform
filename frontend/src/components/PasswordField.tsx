import { useEffect, useState } from "react";

import { checkPassword } from "../lib/api";
import "./PasswordField.css";

/**
 * The shortest password the server accepts - `MINIMUM_PASSWORD_LENGTH` in
 * `app/core/passwords.py`, which the server enforces regardless.
 *
 * **One copy on this side.** Three screens each declared their own `12` after
 * the server had moved to 8, so the button stayed disabled over passwords the
 * server would have taken and the meter was already calling "good". The owner
 * met it on a phone: *"1 character to go"* under a password two bars strong.
 */
export const MINIMUM_PASSWORD = 8;

/** One word, never a sentence - the owner, 26 September. */
const WORDS = ["", "Weak", "Fair", "Good", "Strong"];

/**
 * The eye everybody already knows, crossed out when the password is hidden.
 *
 * A "Show" button read as a control that might *do* something rather than
 * reveal something - and every other password field on the internet uses this
 * icon, so a word here is a small thing to have to learn.
 */
function Eye({ open }: { open: boolean }) {
  return (
    <svg
      width="20"
      height="20"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.6"
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
      width="14"
      height="14"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2.4"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d="M5 12.5 10 17.5 19 7" />
    </svg>
  );
}

/**
 * A password box, with the platform saying what it thinks as you type.
 *
 * **Show/hide**, inside the box. The single biggest reducer of typos on a
 * phone, and the reason people paste a password they then cannot reproduce.
 *
 * **A meter, and one rule.** The only thing enforced by length is the
 * minimum, so that is the one requirement shown - *"8+ characters"*, ticked
 * once met - and the meter beside it is advice, never a gate, summed up in a
 * single word. The owner asked for exactly that: a person choosing a password
 * has seen a hundred of these and does not need the theory of guessing
 * explained under a green bar.
 *
 * **The reason, before the button.** A password the server would refuse (a
 * common one, her own name) says why while it is being typed.
 *
 * The strength comes from the server (see `checkPassword`): working it out
 * here would be a second implementation of the rules, and the day it drifted
 * the screen would say "strong" over something the server refuses.
 *
 * `advise={false}` is the same box for signing in: the eye, and nothing that
 * judges a password somebody already has.
 */
export function PasswordField({
  value,
  onChange,
  personal,
  minimum = MINIMUM_PASSWORD,
  label = "Password",
  labelAside,
  advise = true,
  onProblemChange,
}: {
  value: string;
  onChange: (value: string) => void;
  personal?: { email?: string; name?: string };
  minimum?: number;
  label?: string;
  /** Beside the label, at the far end - *Forgot?* on the sign-in screen. */
  labelAside?: React.ReactNode;
  advise?: boolean;
  /** So the form can refuse to submit something the server would reject. */
  onProblemChange?: (problem: string | null) => void;
}) {
  const [reveal, setReveal] = useState(false);
  const [strength, setStrength] = useState(0);
  const [problem, setProblem] = useState<string | null>(null);

  const longEnough = value.length >= minimum;

  useEffect(() => {
    if (!advise) return;
    if (!value) {
      setStrength(0);
      setProblem(null);
      onProblemChange?.(null);
      return;
    }

    // Debounced, because this asks the server on every keystroke otherwise.
    // 300ms is below the threshold where somebody notices a delay and well
    // above the rate anybody types.
    let current = true;
    const timer = setTimeout(() => {
      checkPassword(value, personal)
        .then((answer) => {
          if (!current) return;
          setStrength(answer.strength);
          setProblem(answer.problem);
          onProblemChange?.(answer.problem);
        })
        .catch(() => {
          // The meter is advice. If the platform cannot be reached, say
          // nothing rather than claiming a password is weak - the submit
          // itself is the check that matters, and it will report properly.
          if (!current) return;
          setStrength(0);
          setProblem(null);
          onProblemChange?.(null);
        });
    }, 300);

    return () => {
      current = false;
      clearTimeout(timer);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [advise, value, personal?.email, personal?.name]);

  const id = advise ? "password-new" : "password-current";
  const word = advise && longEnough && !problem ? WORDS[strength] : "";

  return (
    <div className="field">
      <span className="field__label-row">
        <label className="field__label" htmlFor={id}>
          {label}
        </label>
        {labelAside}
      </span>
      <span className="password__box">
        <input
          id={id}
          className="input password__input"
          type={reveal ? "text" : "password"}
          autoComplete={advise ? "new-password" : "current-password"}
          required
          value={value}
          onChange={(event) => onChange(event.target.value)}
          aria-invalid={advise && problem !== null}
        />
        <button
          type="button"
          className="password__reveal"
          onClick={() => setReveal((was) => !was)}
          aria-label={reveal ? "Hide the password" : "Show the password"}
          aria-pressed={reveal}
        >
          <Eye open={reveal} />
        </button>
      </span>

      {advise && (
        <>
          {/*
           * Four segments rather than a percentage bar: a bar invites the
           * question "how do I get to 100%", which is the composition-rule
           * mindset again. Four steps read as "longer is better" and stop.
           */}
          <span className="password__meter" aria-hidden="true">
            {[0, 1, 2, 3].map((step) => (
              <span
                key={step}
                className={
                  value.length > 0 && step < strength
                    ? `password__segment password__segment--${strength}`
                    : "password__segment"
                }
              />
            ))}
          </span>

          <span className="password__status" role="status">
            <span
              className={
                longEnough ? "password__rule password__rule--met" : "password__rule"
              }
            >
              {longEnough && <Tick />}
              {minimum}+ characters
            </span>
            {word && (
              <span className={`password__word password__word--${strength}`}>
                {word}
              </span>
            )}
          </span>

          {problem && <span className="blocker password__problem">{problem}</span>}
        </>
      )}
    </div>
  );
}
