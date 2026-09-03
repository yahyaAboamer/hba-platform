import { useEffect, useState } from "react";

import { checkPassword } from "../lib/api";
import "./PasswordField.css";

const LABELS = ["Too weak", "Weak", "Getting there", "Good", "Strong"];

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

/**
 * Choosing a password, with the platform saying what it thinks as you type.
 *
 * Three things, and each earns its place:
 *
 * **Show/hide.** The single biggest reducer of typos on a phone, and the
 * reason people paste a password they then cannot reproduce.
 *
 * **A meter.** Deliberately advice, never a gate - what is actually enforced
 * is length and `password_problem`. A meter that blocked would be a
 * composition rule wearing a friendlier face, and composition rules are what
 * produce `Password1!`. Its job is to make somebody *lengthen* one, which is
 * the thing that genuinely resists guessing.
 *
 * **The reason, before the button.** A password that will be refused says so
 * while it is being typed, rather than after a round trip and a form reset.
 *
 * The strength comes from the server (see `checkPassword`): working it out
 * here would be a second implementation of the rules, and the day it drifted
 * the screen would say "strong" over something the server refuses.
 */
export function PasswordField({
  value,
  onChange,
  personal,
  minimum,
  label = "Choose a password",
  onProblemChange,
}: {
  value: string;
  onChange: (value: string) => void;
  personal?: { email?: string; name?: string };
  minimum: number;
  label?: string;
  /** So the form can refuse to submit something the server would reject. */
  onProblemChange?: (problem: string | null) => void;
}) {
  const [reveal, setReveal] = useState(false);
  const [strength, setStrength] = useState(0);
  const [problem, setProblem] = useState<string | null>(null);

  const tooShort = value.length > 0 && value.length < minimum;

  useEffect(() => {
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
  }, [value, personal?.email, personal?.name]);

  return (
    <label className="field">
      <span className="field__label">{label}</span>
      <span className="password__row">
        <input
          className="input password__input"
          type={reveal ? "text" : "password"}
          autoComplete="new-password"
          required
          value={value}
          onChange={(event) => onChange(event.target.value)}
          aria-invalid={tooShort || problem !== null}
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

      {/*
       * Four segments rather than a percentage bar: a bar invites the question
       * "how do I get to 100%", which is the composition-rule mindset again.
       * Four steps read as "longer is better" and stop there.
       */}
      {value.length > 0 && (
        <span className="password__meter" aria-hidden="true">
          {[0, 1, 2, 3].map((step) => (
            <span
              key={step}
              className={
                step < strength
                  ? `password__segment password__segment--on password__segment--${strength}`
                  : "password__segment"
              }
            />
          ))}
        </span>
      )}

      {value.length > 0 && (
        <span className="field__hint" role="status">
          {tooShort
            ? `${minimum - value.length} character${
                minimum - value.length === 1 ? "" : "s"
              } to go.`
            : problem
              ? ""
              : `${LABELS[strength]}. Longer is what makes a password hard to guess — a few unrelated words beats a short jumble.`}
        </span>
      )}

      {problem && !tooShort && (
        <span className="blocker password__problem">{problem}</span>
      )}
    </label>
  );
}
