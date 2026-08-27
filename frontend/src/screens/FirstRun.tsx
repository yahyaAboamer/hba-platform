import { useState } from "react";

import { ApiError, api, rememberToken } from "../lib/api";
import type { Actor, Session } from "../lib/api";
import { currentUser } from "../lib/api";
import "./SignIn.css";

/** §5.1. Long enough to be worth having; the server enforces it too. */
const MINIMUM_PASSWORD = 12;

/**
 * The very first account on a fresh deployment.
 *
 * Until this existed, standing up the platform meant calling
 * `POST /api/auth/bootstrap` by hand — and the API docs are switched off in
 * production, so the one step every deployment begins with had no interface at
 * all. That is a poor first impression and a genuine obstacle: it needs
 * doing again every time staging is reset, which is a thing staging exists for.
 *
 * **Nobody ever sets somebody else's password.** The first administrator
 * chooses their own here, it is hashed before it is stored, and there is no
 * default and no reset that produces a known value. This screen is the only
 * place that account can be created, and it stops existing the moment it is.
 */
export function FirstRun({ onSignedIn }: { onSignedIn: (session: Session) => void }) {
  const [email, setEmail] = useState("");
  const [name, setName] = useState("");
  const [password, setPassword] = useState("");
  const [again, setAgain] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [working, setWorking] = useState(false);

  // Checked here so it is said before the button is pressed, and on the server
  // regardless — this hides a mistake, it does not enforce a rule.
  const problem =
    password.length > 0 && password.length < MINIMUM_PASSWORD
      ? `A password needs at least ${MINIMUM_PASSWORD} characters.`
      : again.length > 0 && password !== again
        ? "Those two passwords are not the same."
        : null;

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (problem) return;
    setWorking(true);
    setError(null);
    try {
      const result = await api.post<{ csrf: string; actor: Actor }>(
        "/api/auth/bootstrap",
        { email: email.trim(), display_name: name.trim(), password },
      );
      rememberToken(result.csrf);
      // Ask once more for the permission list, exactly as signing in does, so
      // there is one source of truth for what this account may do.
      const session = await currentUser();
      if (session === null) {
        throw new ApiError(401, "The account was made, but the session did not stick.");
      }
      onSignedIn(session);
    } catch (caught) {
      setError(
        caught instanceof ApiError && caught.status === 409
          ? "This platform already has an account. Sign in instead."
          : caught instanceof Error
            ? caught.message
            : "Could not set up the platform.",
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
          <h1 className="sign-in__title">Set up the platform</h1>
        </div>

        <p className="sign-in__lead">
          Nobody has an account here yet. This makes the first one, and it is an
          administrator. Do it now — until you do, anyone who finds this page
          could do it instead.
        </p>

        <label className="field">
          <span className="field__label">Your email</span>
          <input
            className="input"
            type="email"
            autoComplete="username"
            required
            value={email}
            onChange={(event) => setEmail(event.target.value)}
          />
          <span className="field__hint">This is what you will sign in with.</span>
        </label>

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
          <span className="field__label">Choose a password</span>
          <input
            className="input"
            type="password"
            autoComplete="new-password"
            required
            value={password}
            onChange={(event) => setPassword(event.target.value)}
          />
          <span className="field__hint">
            At least {MINIMUM_PASSWORD} characters. Nobody else ever sees it, and
            there is no way to recover it — keep it somewhere.
          </span>
        </label>

        <label className="field">
          <span className="field__label">And again</span>
          <input
            className="input"
            type="password"
            autoComplete="new-password"
            required
            value={again}
            onChange={(event) => setAgain(event.target.value)}
          />
        </label>

        {problem && <p className="blocker sign-in__error">{problem}</p>}

        {error && (
          <p className="notice notice--refused sign-in__error" role="alert">
            {error}
          </p>
        )}

        <button
          type="submit"
          className="button button--primary sign-in__submit"
          disabled={working || problem !== null || password.length === 0}
        >
          {working ? "Setting up…" : "Create my account"}
        </button>
      </form>
    </main>
  );
}
