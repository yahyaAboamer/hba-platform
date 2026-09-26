import { useState } from "react";
import { Link } from "react-router-dom";

import { AuthShell } from "../components/AuthShell";
import { PasswordField } from "../components/PasswordField";
import { ApiError, signIn } from "../lib/api";
import type { Session } from "../lib/api";

/**
 * The way in - for staff and models alike, in the portal's look (ADR 0047).
 *
 * Nothing here explains signing in; everybody has done it a thousand times.
 * **"Forgot?" sits beside the password label**, where the owner's approved
 * mockup and most sign-in screens put it. It used to sit under the button as
 * the answer to "that did not work" - but a person who already knows she has
 * forgotten should not have to fail once to find it.
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
    <AuthShell eyebrow="Welcome back" title="Sign in" onSubmit={submit}>
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

      <PasswordField
        value={password}
        onChange={setPassword}
        advise={false}
        labelAside={
          <Link className="auth__link" to="/reset-password">
            Forgot?
          </Link>
        }
      />

      {error && (
        <p className="notice notice--refused auth__error" role="alert">
          {error}
        </p>
      )}

      <button
        type="submit"
        className="button button--primary auth__submit"
        disabled={working}
      >
        {working ? "Signing in…" : "Sign in"}
      </button>
    </AuthShell>
  );
}
