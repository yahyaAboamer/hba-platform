import { useState } from "react";

import { api } from "../lib/api";

/**
 * Putting a model on the programme.
 *
 * **Not a role in a dropdown.** It sat in Settings beside admin, content
 * manager and affiliate manager — and it did not even sit there, because the
 * list offered only the three staff roles, so there was no way to invite a
 * model at all. Phase 8 built the whole onboarding flow and nothing could
 * start it.
 *
 * The two acts are different and belong apart. Inviting staff is granting
 * somebody permissions over other people's money; inviting a model is putting
 * her on the programme, and she holds no permission at all — §6.1 gives the
 * `affiliate` role an empty permission set on purpose. Offering them from one
 * list says they are variations of one decision, and they are not.
 *
 * So this lives on Affiliates, where models live.
 *
 * What happens next is hers: she sets a password, fills in her own details and
 * her own payout destination, and applies. §6.5 keeps the application form
 * free of anything deciding what she is paid, so approving her — and setting
 * her rate — stays a separate, deliberate act.
 */
export function InviteModel({ onInvited }: { onInvited: () => void }) {
  const [open, setOpen] = useState(false);
  const [email, setEmail] = useState("");
  const [link, setLink] = useState<string | null>(null);
  const [emailed, setEmailed] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [working, setWorking] = useState(false);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setWorking(true);
    setError(null);
    setLink(null);
    try {
      const result = await api.post<{ token: string; emailed: boolean }>(
        "/api/auth/invitations",
        { email: email.trim(), role: "affiliate" },
      );
      setEmailed(result.emailed);
      setLink(`${window.location.origin}/accept-invitation?token=${result.token}`);
      setEmail("");
      onInvited();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Could not invite her.");
    } finally {
      setWorking(false);
    }
  }

  if (!open) {
    return (
      <button
        type="button"
        className="button button--primary"
        onClick={() => setOpen(true)}
      >
        Invite a model
      </button>
    );
  }

  return (
    <section className="panel invite">
      <div className="panel__head">
        <h2 className="panel__title">Invite a model</h2>
      </div>

      <div className="invite__body">
        {error && (
          <p className="notice notice--refused" role="alert">
            {error}
          </p>
        )}

        {/*
         * Both the confirmation and the link, for the reason the staff invite
         * gives: an emailed link is exactly what somebody wants on screen the
         * moment she says it never arrived, and it is shown once because it is
         * a working credential until it is used.
         */}
        {link && (
          <div className="notice notice--settled invite__link">
            <p>
              {emailed
                ? "Emailed to her. Here is the same link, in case it does not arrive — it only appears here once."
                : "Email is not switched on, so send her this link yourself — it only appears here once."}
            </p>
            <code className="code invite__link-value">{link}</code>
          </div>
        )}

        <p className="invite__lead">
          She sets her own password, fills in her details and where she wants to
          be paid, and applies. You approve her and set what she is paid after
          that — nothing about her pay is decided here.
        </p>

        <form onSubmit={submit} className="invite__form">
          <label className="field invite__field">
            <span className="field__label">Her email</span>
            <input
              className="input"
              type="email"
              required
              value={email}
              onChange={(event) => setEmail(event.target.value)}
            />
            <span className="field__hint">
              This is what she will sign in with, so use the one she reads.
            </span>
          </label>

          <div className="invite__actions">
            <button
              type="button"
              className="button"
              onClick={() => {
                setOpen(false);
                setLink(null);
                setError(null);
              }}
            >
              Done
            </button>
            <button
              type="submit"
              className="button button--primary"
              disabled={working || !email.trim()}
            >
              {working ? "Inviting…" : "Send her the link"}
            </button>
          </div>
        </form>
      </div>
    </section>
  );
}
