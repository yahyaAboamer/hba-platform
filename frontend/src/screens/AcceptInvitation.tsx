import { useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";

import { ApiError, acceptInvitation } from "../lib/api";
import type { Session } from "../lib/api";
import "./SignIn.css";

/** §5.1. Enforced by the server; said here so nobody meets it as a rejection. */
const MINIMUM_PASSWORD = 12;

/**
 * Turning an invitation into an account.
 *
 * Reuses `SignIn.css` rather than its own stylesheet — this is the same
 * moment as signing in, one step earlier, and it should look like it. No
 * email field: the token already names who this is, so asking for one again
 * would only open a way for it to disagree.
 */
export function AcceptInvitation({
  onSignedIn,
}: {
  onSignedIn: (session: Session) => void;
}) {
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const token = params.get("token") ?? "";

  const [displayName, setDisplayName] = useState("");
  const [password, setPassword] = useState("");
  // §5.1, and stated here so the rule arrives before the refusal does.
  const tooShort = password.length > 0 && password.length < MINIMUM_PASSWORD;
  const [error, setError] = useState<string | null>(null);
  const [working, setWorking] = useState(false);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setWorking(true);
    setError(null);
    try {
      onSignedIn(await acceptInvitation(token, displayName, password));
      // Accepting sets a live session, but this route renders unconditionally
      // regardless of one (an already-signed-in admin opening their own
      // invite link is a real case, not a misuse - see App.tsx). Nothing
      // takes the new account into the app without this: `onSignedIn` only
      // updates state one level up, and staying on this form with a filled-in
      // password left visible reads as "nothing happened" to the person who
      // just finished signing up.
      navigate("/", { replace: true });
    } catch (caught) {
      // A 422 is the server's shape check, and its body is a validation
      // structure rather than a sentence. Shown raw it read "422" to somebody
      // whose only mistake was a short password.
      setError(
        caught instanceof ApiError && caught.status === 422
          ? `Check the form — a password needs at least ${MINIMUM_PASSWORD} characters.`
          : caught instanceof ApiError
            ? caught.message
            : "Could not reach the platform. Check the connection and try again.",
      );
    } finally {
      setWorking(false);
    }
  }

  if (!token) {
    return (
      <main className="sign-in">
        <div className="sign-in__form">
          <div className="sign-in__brand">
            <span className="sign-in__mark">HBA</span>
            <h1 className="sign-in__title">Affiliate payroll</h1>
          </div>
          <p className="notice notice--refused" role="alert">
            This link is missing its invitation. Ask whoever invited you to
            send it again.
          </p>
        </div>
      </main>
    );
  }

  return (
    <main className="sign-in">
      <form className="sign-in__form" onSubmit={submit}>
        <div className="sign-in__brand">
          <span className="sign-in__mark">HBA</span>
          <h1 className="sign-in__title">Set up your account</h1>
        </div>

        {/*
         * It reads as the whole sign-up and is the first of two steps. Somebody
         * arriving here from an email has no idea more is coming, and said so:
         * *as a model I would think this is just a page where I create my user.*
         */}
        <p className="sign-in__lead">
          First a password, so only you can get in. Next you will fill in your
          details, your discount code, and where you want to be paid.
        </p>

        <label className="field">
          <span className="field__label">Your name</span>
          <input
            className="input"
            required
            value={displayName}
            onChange={(event) => setDisplayName(event.target.value)}
          />
        </label>

        <label className="field">
          <span className="field__label">Choose a password</span>
          <input
            className="input"
            type="password"
            autoComplete="new-password"
            required
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            aria-invalid={tooShort}
          />
          <span className="field__hint">
            At least {MINIMUM_PASSWORD} characters.
          </span>
        </label>

        {tooShort && (
          <p className="blocker sign-in__error">
            That is {MINIMUM_PASSWORD - password.length} character
            {MINIMUM_PASSWORD - password.length === 1 ? "" : "s"} short.
          </p>
        )}

        {error && (
          <p className="notice notice--refused sign-in__error" role="alert">
            {error}
          </p>
        )}

        <button
          type="submit"
          className="button button--primary sign-in__submit"
          disabled={working || tooShort || password.length === 0}
        >
          {working ? "Setting up…" : "Continue"}
        </button>
      </form>
    </main>
  );
}
