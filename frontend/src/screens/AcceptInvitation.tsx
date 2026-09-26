import { useEffect, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";

import { AccountChip, AuthShell } from "../components/AuthShell";
import { MINIMUM_PASSWORD, PasswordField } from "../components/PasswordField";
import { ApiError, acceptInvitation, previewInvitation } from "../lib/api";
import type { Session } from "../lib/api";

/**
 * Turning an invitation into an account - step one of two for a model.
 *
 * No email field: the token already names who this is, so asking for one
 * again would only open a way for it to disagree. The address is shown as a
 * chip instead, which confirms she is in the right place and tells her what
 * she will sign in with, without a sentence explaining either.
 *
 * **Nothing announces the next step.** It said *"we will ask for your details
 * next"*; the two-segment bar at the top says the same thing without being
 * read, which is what the owner asked for.
 *
 * **The link is checked when the page opens, not when the form is sent.** It
 * used to render the whole form for any token-shaped string and refuse only on
 * submit, so somebody withdrawn hours earlier still chose a password before
 * being told - and withdrawing looked like it had done nothing at all.
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
  const tooShort = password.length < MINIMUM_PASSWORD;
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
          ? `A password needs at least ${MINIMUM_PASSWORD} characters.`
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
      <AuthShell title="Set up your account">
        <p className="notice notice--refused" role="alert">
          This link is missing its invitation. Ask whoever invited you to send it
          again.
        </p>
      </AuthShell>
    );
  }

  // Deliberately quiet. This resolves in a moment on any real connection, and
  // a spinner here would flash on every single arrival.
  if (checking) {
    return (
      <AuthShell eyebrow="Welcome to HBA" title="Create your password">
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
        <p className="auth__lead">Ask HBA to send you a new one.</p>
      </AuthShell>
    );
  }

  return (
    <AuthShell
      eyebrow="Welcome to HBA"
      title="Create your password"
      step={{ current: 1, of: 2 }}
      onSubmit={submit}
    >
      {invitedEmail && <AccountChip email={invitedEmail} />}

      <PasswordField
        value={password}
        onChange={setPassword}
        personal={{ email: invitedEmail ?? undefined }}
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
        {working ? "Setting up…" : "Continue"}
      </button>
    </AuthShell>
  );
}
