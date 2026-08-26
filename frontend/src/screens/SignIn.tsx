import { useState } from "react";

import { ApiError, signIn } from "../lib/api";
import type { Session } from "../lib/api";
import "./SignIn.css";

/**
 * The way in.
 *
 * Deliberately plain. This is the first thing anybody sees, and the thing it
 * needs to say is that the tool is careful with money — which is said by being
 * unhurried and specific, not by being decorated.
 */
export function SignIn({ onSignedIn }: { onSignedIn: (session: Session) => void }) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [working, setWorking] = useState(false);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setWorking(true);
    setError(null);
    try {
      onSignedIn(await signIn(email, password));
    } catch (caught) {
      // The platform deliberately does not say which half was wrong - that
      // would confirm an email exists. So neither does this.
      setError(
        caught instanceof ApiError && caught.status === 401
          ? "That email and password do not match an account."
          : caught instanceof ApiError
            ? caught.message
            : "Could not reach the platform. Check the connection and try again.",
      );
    } finally {
      setWorking(false);
    }
  }

  return (
    <main className="sign-in">
      <form className="sign-in__form" onSubmit={submit}>
        <div className="sign-in__brand">
          <span className="sign-in__mark">HBA</span>
          <h1 className="sign-in__title">Affiliate payroll</h1>
        </div>

        <label className="field">
          <span className="field__label">Email</span>
          <input
            className="input"
            type="email"
            autoComplete="username"
            required
            value={email}
            onChange={(event) => setEmail(event.target.value)}
          />
        </label>

        <label className="field">
          <span className="field__label">Password</span>
          <input
            className="input"
            type="password"
            autoComplete="current-password"
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
          {working ? "Signing in…" : "Sign in"}
        </button>
      </form>
    </main>
  );
}
