import { useState } from "react";
import { Link } from "react-router-dom";

import { AuthShell } from "../components/AuthShell";
import { PasswordField } from "../components/PasswordField";
import { ApiError, resendSignInCode, signIn, signInWithCode } from "../lib/api";
import type { CodeAnswer, Session, TwoStepMethod } from "../lib/api";

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
  const [pending, setPending] = useState<CodeAnswer | null>(null);

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
        setPending(result);
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
        pending={pending.pending}
        method={pending.method}
        sentTo={pending.sentTo}
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
 * The second step, and where its code comes from: an email to the masked
 * address, or the authenticator app (which also takes a recovery code).
 *
 * Shared by signing in and by a password reset, which for somebody with an
 * authenticator on also ends here - otherwise whoever can read the mailbox
 * would walk past the second step.
 */
export function CodeStep({
  pending,
  method = "authenticator",
  sentTo = null,
  onSignedIn,
  onStartOver,
}: {
  pending: string;
  method?: TwoStepMethod;
  /** The masked address an email code went to. */
  sentTo?: string | null;
  onSignedIn: (session: Session, notice?: string) => void;
  /** The pending sign-in lapsed or was used; `message` says so. */
  onStartOver: (message: string | null) => void;
}) {
  const emailed = method === "email";
  const [code, setCode] = useState("");
  const [recovery, setRecovery] = useState(false);
  const [remember, setRemember] = useState(true);
  const [address, setAddress] = useState(sentTo);
  const [sentAgain, setSentAgain] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [working, setWorking] = useState(false);
  const [resending, setResending] = useState(false);

  function failed(caught: unknown) {
    if (caught instanceof ApiError && caught.status === 410) {
      // The pending sign-in lapsed or was used: nothing to retry, start over.
      onStartOver(caught.message);
      return;
    }
    setError(
      caught instanceof ApiError
        ? caught.message
        : "Could not reach the platform. Check the connection and try again.",
    );
  }

  async function submitCode(event: React.FormEvent) {
    event.preventDefault();
    setWorking(true);
    setError(null);
    try {
      const { session, recoveryCodesLeft } = await signInWithCode(pending, code.trim(), remember);
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
      failed(caught);
    } finally {
      setWorking(false);
    }
  }

  async function sendAgain() {
    setResending(true);
    setError(null);
    setSentAgain(false);
    try {
      const sent = await resendSignInCode(pending);
      setAddress(sent.sent_to);
      setSentAgain(true);
      setCode("");
    } catch (caught) {
      failed(caught);
    } finally {
      setResending(false);
    }
  }

  return (
    <AuthShell eyebrow="Two-step sign-in" title="Enter your code" onSubmit={submitCode}>
      <p className="auth__lead">
        {emailed
          ? `We sent a 6-digit code to ${address ?? "your email"}. It works for 10 minutes.`
          : "Open your authenticator app (for example Google Authenticator) and type the 6-digit code it shows for HBA."}
      </p>
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

      <label className="twostep__remember">
        <input type="checkbox" aria-describedby="remember-hint" checked={remember} onChange={(event) => setRemember(event.target.checked)} />
        <span>Remember this browser for 30 days</span>
      </label>
      <p className="twostep__hint" id="remember-hint">Leave this off on a shared computer.</p>

      {sentAgain && <p className="auth__lead" role="status">A new code is on its way to {address}.</p>}
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
      {emailed ? (
        <button type="button" className="auth__link" onClick={sendAgain} disabled={resending}>
          {resending ? "Sending…" : "Send a new code"}
        </button>
      ) : (
        <button
          type="button"
          className="auth__link"
          onClick={() => { setRecovery(!recovery); setCode(""); setError(null); }}
        >
          {recovery ? "Use the code from my app instead" : "Use a recovery code instead"}
        </button>
      )}
      <button type="button" className="auth__link" onClick={() => onStartOver(null)}>
        Back to email and password
      </button>
    </AuthShell>
  );
}
