import { useEffect, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";

import { PasswordField } from "../components/PasswordField";
import {
  ApiError,
  completePasswordReset,
  previewPasswordReset,
  requestPasswordReset,
} from "../lib/api";
import type { Session } from "../lib/api";
import "./SignIn.css";

/** §5.1. Enforced by the server; said here so nobody meets it as a rejection. */
const MINIMUM_PASSWORD = 12;

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
  onSignedIn: (session: Session) => void;
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

function shell(children: React.ReactNode) {
  return (
    <main className="sign-in">
      <div className="sign-in__form">
        <div className="sign-in__brand">
          <span className="sign-in__mark">HBA</span>
          <h1 className="sign-in__title">Reset your password</h1>
        </div>
        {children}
      </div>
    </main>
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
    return shell(
      <>
        {/*
         * **Says "if", not "we have".** Confirming that mail is on its way
         * would tell anybody who typed an address whether that person is on
         * the programme - and the people here are named individuals whose
         * association with HBA is theirs to disclose, not this screen's.
         */}
        <p className="sign-in__lead">
          If there is an account for that address, a link is on its way. It
          works once and expires in two hours.
        </p>
        <p className="sign-in__lead">
          Nothing has changed yet — your current password still works until you
          open the link and choose a new one.
        </p>
      </>,
    );
  }

  return (
    <main className="sign-in">
      <form className="sign-in__form" onSubmit={submit}>
        <div className="sign-in__brand">
          <span className="sign-in__mark">HBA</span>
          <h1 className="sign-in__title">Reset your password</h1>
        </div>
        <p className="sign-in__lead">
          Type the address you sign in with and we will send you a link.
        </p>

        <label className="field">
          <span className="field__label">Email address</span>
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
          className="button button--primary sign-in__submit"
          disabled={working || !email.trim()}
        >
          {working ? "Sending…" : "Send me a link"}
        </button>
      </form>
    </main>
  );
}

function UseTheLink({
  token,
  onSignedIn,
  navigate,
}: {
  token: string;
  onSignedIn: (session: Session) => void;
  navigate: ReturnType<typeof useNavigate>;
}) {
  const [account, setAccount] = useState<string | null>(null);
  const [linkProblem, setLinkProblem] = useState<string | null>(null);
  const [checking, setChecking] = useState(true);

  const [password, setPassword] = useState("");
  const [passwordProblem, setPasswordProblem] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [working, setWorking] = useState(false);

  const tooShort = password.length > 0 && password.length < MINIMUM_PASSWORD;

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
      onSignedIn(await completePasswordReset(token, password));
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

  if (checking) {
    return shell(<p className="sign-in__lead">Checking your link…</p>);
  }

  if (linkProblem) {
    return shell(
      <>
        <p className="notice notice--refused" role="alert">
          {linkProblem}
        </p>
        <p className="sign-in__lead">
          Ask for a new one from the sign-in screen — this link cannot be used.
        </p>
      </>,
    );
  }

  return (
    <main className="sign-in">
      <form className="sign-in__form" onSubmit={submit}>
        <div className="sign-in__brand">
          <span className="sign-in__mark">HBA</span>
          <h1 className="sign-in__title">Choose a new password</h1>
        </div>

        <p className="sign-in__lead">
          For <strong>{account}</strong>. Anywhere you are already signed in
          will be signed out.
        </p>

        <PasswordField
          value={password}
          onChange={setPassword}
          personal={{ email: account ?? undefined }}
          minimum={MINIMUM_PASSWORD}
          label="New password"
          onProblemChange={setPasswordProblem}
        />

        {error && (
          <p className="notice notice--refused sign-in__error" role="alert">
            {error}
          </p>
        )}

        <button
          type="submit"
          className="button button--primary sign-in__submit"
          disabled={
            working ||
            tooShort ||
            password.length === 0 ||
            passwordProblem !== null
          }
        >
          {working ? "Saving…" : "Save and sign in"}
        </button>
      </form>
    </main>
  );
}
