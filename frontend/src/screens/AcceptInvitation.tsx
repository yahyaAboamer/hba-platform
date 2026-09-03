import { useEffect, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";

import { PasswordField } from "../components/PasswordField";
import { ApiError, acceptInvitation, previewInvitation } from "../lib/api";
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
 *
 * **The link is checked when the page opens, not when the form is sent.** It
 * used to render the whole form for any token-shaped string and refuse only on
 * submit, so somebody withdrawn hours earlier still chose a name and a
 * password before being told — and withdrawing looked like it had done
 * nothing at all.
 *
 * **And it asks for a password only.** The name it used to ask for became the
 * account's, while the details step that follows set the *profile's* — so a
 * model saw one name in their own portal and the maintainer saw another in
 * admin, with neither able to see the other's. The name is asked once now, on
 * the step that already asks for it.
 */
export function AcceptInvitation({
  onSignedIn,
}: {
  onSignedIn: (session: Session) => void;
}) {
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const token = params.get("token") ?? "";

  const [invitedEmail, setInvitedEmail] = useState<string | null>(null);
  const [linkProblem, setLinkProblem] = useState<string | null>(null);
  const [checking, setChecking] = useState(true);

  const [password, setPassword] = useState("");
  // §5.1, and stated here so the rule arrives before the refusal does.
  const tooShort = password.length > 0 && password.length < MINIMUM_PASSWORD;
  const [passwordProblem, setPasswordProblem] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [working, setWorking] = useState(false);

  useEffect(() => {
    if (!token) {
      setChecking(false);
      return;
    }
    let current = true;
    previewInvitation(token)
      .then((invitation) => {
        if (current) setInvitedEmail(invitation.email);
      })
      .catch((caught) => {
        if (!current) return;
        // The server's sentence, verbatim — "This invitation has expired" and
        // its siblings are written to be read by whoever opened the link.
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
      onSignedIn(await acceptInvitation(token, password));
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

  function shell(children: React.ReactNode) {
    return (
      <main className="sign-in accept-invite">
        <div className="sign-in__form">
          <div className="sign-in__brand">
            <span className="sign-in__mark">HBA</span>
            <h1 className="sign-in__title">Set up your account</h1>
          </div>
          {children}
        </div>
      </main>
    );
  }

  if (!token) {
    return shell(
      <p className="notice notice--refused" role="alert">
        This link is missing its invitation. Ask whoever invited you to send it
        again.
      </p>,
    );
  }

  // Deliberately quiet. This resolves in a moment on any real connection, and
  // a spinner here would flash on every single arrival.
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
          Ask HBA to send you a new link — the one you have cannot be used.
        </p>
      </>,
    );
  }

  return (
    <main className="sign-in accept-invite">
      <form className="sign-in__form" onSubmit={submit}>
        <div className="sign-in__brand">
          <span className="sign-in__mark">HBA</span>
          <h1 className="sign-in__title">Set up your account</h1>
        </div>

        {/*
         * Naming the address does three things at once: it confirms they are
         * in the right place, it tells them what they will sign in with, and
         * it explains why nothing here asks for an email. Without it this is a
         * lone password box arriving out of nowhere.
         */}
        <p className="sign-in__lead">
          You will sign in with <strong>{invitedEmail}</strong>. Choose a
          password — we will ask for your details next.
        </p>

        <PasswordField
          value={password}
          onChange={setPassword}
          personal={{ email: invitedEmail ?? undefined }}
          minimum={MINIMUM_PASSWORD}
          onProblemChange={setPasswordProblem}
        />

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
          disabled={
            working ||
            tooShort ||
            password.length === 0 ||
            passwordProblem !== null
          }
        >
          {working ? "Setting up…" : "Continue"}
        </button>
      </form>
    </main>
  );
}
