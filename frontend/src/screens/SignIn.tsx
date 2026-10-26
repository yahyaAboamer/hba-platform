import { useState } from "react";
import { Link } from "react-router-dom";

import { AuthShell } from "../components/AuthShell";
import { PasswordField } from "../components/PasswordField";
import { ApiError, signIn, signInWithCode } from "../lib/api";
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
export function SignIn({
  onSignedIn,
}: {
  /** `notice` is something to tell the person once they are in. */
  onSignedIn: (session: Session, notice?: string) => void;
}) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [working, setWorking] = useState(false);
  // Set once the password was right and a code is the next thing asked.
  const [pending, setPending] = useState<string | null>(null);

  function backToPassword(message: string | null = null) {
    setPending(null);
    setError(message);
  }

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setWorking(true);
    setError(null);
    try {
      const result = await signIn(email, password);
      if (result.kind === "code") {
        setPending(result.pending);
        setPassword("");
      } else {
        onSignedIn(result.session);
      }
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

  if (pending !== null) {
    return (
      <CodeStep
        pending={pending}
        onSignedIn={onSignedIn}
        onStartOver={backToPassword}
      />
    );
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

/**
 * The second step: the code from the authenticator app, or a recovery code.
 *
 * Shared by signing in and by a password reset, which for somebody with
 * two-step on also ends here - otherwise whoever can read the mailbox would
 * walk past the second step.
 */
export function CodeStep({
  pending,
  onSignedIn,
  onStartOver,
}: {
  pending: string;
  onSignedIn: (session: Session, notice?: string) => void;
  /** The pending sign-in lapsed or was used; `message` says so. */
  onStartOver: (message: string | null) => void;
}) {
  const [code, setCode] = useState("");
  const [recovery, setRecovery] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [working, setWorking] = useState(false);

  async function submitCode(event: React.FormEvent) {
    event.preventDefault();
    setWorking(true);
    setError(null);
    try {
      const { session, recoveryCodesLeft } = await signInWithCode(pending, code.trim());
      onSignedIn(
        session,
        recoveryCodesLeft === null
          ? undefined
          : `You signed in with a recovery code. ${
              recoveryCodesLeft === 0
                ? "You have none left"
                : `You have ${recoveryCodesLeft} left`
            } - make new ones in Settings, under My preferences.`,
      );
    } catch (caught) {
      if (caught instanceof ApiError && caught.status === 410) {
        // The pending sign-in lapsed or was used: nothing to retry, start over.
        onStartOver(caught.message);
      } else {
        setError(
          caught instanceof ApiError
            ? caught.message
            : "Could not reach the platform. Check the connection and try again.",
        );
      }
    } finally {
      setWorking(false);
    }
  }

  return (
    <AuthShell eyebrow="Two-step sign-in" title="Enter your code" onSubmit={submitCode}>
      <label className="field">
        <span className="field__label">{recovery ? "Recovery code" : "6-digit code"}</span>
        <input
          key={recovery ? "recovery" : "code"}
          className="input"
          inputMode={recovery ? "text" : "numeric"}
          autoComplete={recovery ? "off" : "one-time-code"}
          autoCapitalize="none"
          spellCheck={false}
          autoFocus
          required
          value={code}
          onChange={(event) => setCode(event.target.value)}
        />
      </label>

      {error && (
        <p className="notice notice--refused auth__error" role="alert">
          {error}
        </p>
      )}

      <button
        type="submit"
        className="button button--primary auth__submit"
        disabled={working || code.trim() === ""}
      >
        {working ? "Checking…" : "Sign in"}
      </button>
      <button
        type="button"
        className="auth__link"
        onClick={() => { setRecovery(!recovery); setCode(""); setError(null); }}
      >
        {recovery ? "Use the code from my app instead" : "Use a recovery code instead"}
      </button>
      <button type="button" className="auth__link" onClick={() => onStartOver(null)}>
        Back to email and password
      </button>
    </AuthShell>
  );
}
