import { useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";

import { ApiError, acceptInvitation } from "../lib/api";
import type { Session } from "../lib/api";
import "./SignIn.css";

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
      setError(
        caught instanceof ApiError
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
          />
        </label>

        {error && (
          <p className="notice notice--refused sign-in__error" role="alert">
            {error}
          </p>
        )}

        <button
          type="submit"
          className="button button--primary sign-in__submit"
          disabled={working}
        >
          {working ? "Setting up…" : "Get started"}
        </button>
      </form>
    </main>
  );
}
