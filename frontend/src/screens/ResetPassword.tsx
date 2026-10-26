import { useEffect, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";

import { AccountChip, AuthShell } from "../components/AuthShell";
import { MINIMUM_PASSWORD, PasswordField } from "../components/PasswordField";
import {
  ApiError,
  completePasswordReset,
  previewPasswordReset,
  requestPasswordReset,
} from "../lib/api";
import type { Session } from "../lib/api";
import { CodeStep } from "./SignIn";

/**
 * Getting back in when the password is gone.
 *
 * Two screens in one, chosen by whether the URL carries a token: **ask for a
 * link**, or **use one**.
 *
 * Before this existed there was no way back at all. No reset route, and
 * re-inviting was refused too, because an address that already holds an
 * account is turned away. A model who forgot their password could only be
 * helped by editing the database - survivable with one administrator, not
 * with twenty people.
 */
export function ResetPassword({
  onSignedIn,
}: {
  onSignedIn: (session: Session, notice?: string) => void;
}) {
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const token = params.get("token") ?? "";

  return token ? (
    <UseTheLink token={token} onSignedIn={onSignedIn} navigate={navigate} />
  ) : (
    <AskForALink />
  );
}

function AskForALink() {
  const [email, setEmail] = useState("");
  const [sent, setSent] = useState(false);
  const [working, setWorking] = useState(false);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setWorking(true);
    try {
      await requestPasswordReset(email.trim());
    } catch {
      // Deliberately swallowed. The server answers the same way whatever
      // happened, and a failure shown here would be the one signal that
      // distinguishes an address with an account from one without.
    } finally {
      setWorking(false);
      setSent(true);
    }
  }

  if (sent) {
    return (
      <AuthShell eyebrow="Reset password" title="Check your email">
        {/*
         * **Says "if", not "we have".** Confirming that mail is on its way
         * would tell anybody who typed an address whether that person is on
         * the programme - and the people here are named individuals whose
         * association with HBA is theirs to disclose, not this screen's.
         */}
        <p className="auth__lead">
          If there is an account for that address, a link is on its way. It
          works once and expires in two hours. Your current password still
          works until then.
        </p>
        <Link className="auth__link" to="/">
          Back to sign in
        </Link>
      </AuthShell>
    );
  }

  return (
    <AuthShell eyebrow="Reset password" title="Forgot your password?" onSubmit={submit}>
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

      <button
        type="submit"
        className="button button--primary auth__submit"
        disabled={working || !email.trim()}
      >
        {working ? "Sending…" : "Send me a link"}
      </button>
    </AuthShell>
  );
}

function UseTheLink({
  token,
  onSignedIn,
  navigate,
}: {
  token: string;
  onSignedIn: (session: Session, notice?: string) => void;
  navigate: ReturnType<typeof useNavigate>;
}) {
  const [account, setAccount] = useState<string | null>(null);
  const [linkProblem, setLinkProblem] = useState<string | null>(null);
  const [checking, setChecking] = useState(true);

  const [password, setPassword] = useState("");
  const [passwordProblem, setPasswordProblem] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [working, setWorking] = useState(false);
  // The password is changed, and two-step sign-in still asks for its code.
  const [pending, setPending] = useState<string | null>(null);

  const tooShort = password.length < MINIMUM_PASSWORD;

  useEffect(() => {
    let current = true;
    previewPasswordReset(token)
      .then((found) => {
        if (current) setAccount(found.email);
      })
      .catch((caught) => {
        if (!current) return;
        setLinkProblem(
          caught instanceof ApiError
            ? caught.message
            : "Could not reach the platform. Check the connection and try again.",
        );
      })
      .finally(() => {
        if (current) setChecking(false);
      });
    return () => {
      current = false;
    };
  }, [token]);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setWorking(true);
    setError(null);
    try {
      const result = await completePasswordReset(token, password);
      if (result.kind === "code") {
        setPending(result.pending);
        setPassword("");
        return;
      }
      onSignedIn(result.session);
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

  if (pending !== null) {
    return (
      <CodeStep
        pending={pending}
        onSignedIn={(session, notice) => {
          onSignedIn(session, notice);
          navigate("/", { replace: true });
        }}
        // The link is spent and the password already changed: the way on is
        // the ordinary sign-in, with the new password.
        onStartOver={() => navigate("/sign-in", { replace: true })}
      />
    );
  }

  if (checking) {
    return (
      <AuthShell eyebrow="Reset password" title="Choose a new password">
        <p className="auth__lead">Checking your link…</p>
      </AuthShell>
    );
  }

  if (linkProblem) {
    return (
      <AuthShell title="This link cannot be used">
        <p className="notice notice--refused" role="alert">
          {linkProblem}
        </p>
        <Link className="auth__link" to="/reset-password">
          Ask for a new link
        </Link>
      </AuthShell>
    );
  }

  return (
    <AuthShell eyebrow="Reset password" title="Choose a new password" onSubmit={submit}>
      {account && <AccountChip email={account} />}

      <PasswordField
        value={password}
        onChange={setPassword}
        personal={{ email: account ?? undefined }}
        label="New password"
        onProblemChange={setPasswordProblem}
      />

      {error && (
        <p className="notice notice--refused auth__error" role="alert">
          {error}
        </p>
      )}

      <button
        type="submit"
        className="button button--primary auth__submit"
        disabled={working || tooShort || passwordProblem !== null}
      >
        {working ? "Saving…" : "Save and sign in"}
      </button>
    </AuthShell>
  );
}
