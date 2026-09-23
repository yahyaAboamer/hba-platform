import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { api } from "../lib/api";
import { formatSentAt } from "./Affiliates";
import "./InvitePage.css";

/** An invitation nobody has opened yet. Not a model, and still ours. */
type Invited = {
  id: number;
  email: string;
  expired: boolean;
  /** Cancelled on purpose, as opposed to simply lapsed. */
  withdrawn: boolean;
  created_at: string;
};

/** Only the fields this screen reads. The roster's payload is much wider. */
type Applicant = {
  id: number;
  name: string;
  status: string;
  created_at: string | null;
};

/**
 * Putting a model on the programme — `vInvite` in the approved admin, lines
 * 1232–1277.
 *
 * **Not a role in a dropdown.** Inviting staff is granting somebody
 * permissions over other people's money; inviting a model is putting them on
 * the programme, and they hold no permission at all (§6.1 gives the
 * `affiliate` role an empty permission set on purpose). Offering both from one
 * list says they are variations of one decision, and they are not.
 *
 * **A page, not the modal it used to be.** The export gives the act a screen
 * because two things belong beside it: the applications somebody is waiting to
 * review, and the invitations already out. In a modal those were invisible,
 * and the most common reason to invite somebody twice is not knowing the first
 * link is still live.
 *
 * What happens next is theirs: they set a password, fill in their own details
 * and their own payout destination, and apply. §6.5 keeps the application form
 * free of anything deciding what they are paid, so approving them — and
 * setting their rate — stays a separate, deliberate act.
 */
export function InvitePage() {
  const [email, setEmail] = useState("");
  const [link, setLink] = useState<string | null>(null);
  const [emailed, setEmailed] = useState(false);
  const [sentTo, setSentTo] = useState("");
  const [copied, setCopied] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const [working, setWorking] = useState(false);
  const [applicants, setApplicants] = useState<Applicant[] | null>(null);
  const [invited, setInvited] = useState<Invited[]>([]);

  const reload = useCallback(() => {
    api
      .get<{ affiliates: Applicant[]; invited: Invited[] }>("/api/affiliates")
      .then((body) => {
        setApplicants(body.affiliates.filter((row) => row.status === "pending"));
        setInvited(body.invited ?? []);
      })
      .catch((caught) => setProblem(caught.message));
  }, []);

  useEffect(reload, [reload]);

  async function send(event: React.FormEvent) {
    event.preventDefault();
    setWorking(true);
    setProblem(null);
    setLink(null);
    setCopied(false);
    try {
      const result = await api.post<{ link: string; emailed: boolean }>(
        "/api/auth/invitations",
        { email: email.trim(), role: "affiliate" },
      );
      setEmailed(result.emailed);
      setSentTo(email.trim());
      // **The server's link, not one assembled here.** This screen used to
      // build its own from the browser's address bar while the email built a
      // different one from PUBLIC_BASE_URL - so on 2026-09-02 the maintainer
      // read a working link off the panel while the model received a dead one,
      // and only the model could tell. An empty string means the platform does
      // not know its own address, which is said below rather than hidden.
      setLink(result.link);
      setEmail("");
      reload();
    } catch (caught) {
      setProblem(
        caught instanceof Error ? caught.message : "Could not send the invitation.",
      );
    } finally {
      setWorking(false);
    }
  }

  async function copy() {
    if (!link) return;
    try {
      await navigator.clipboard.writeText(link);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1400);
    } catch {
      // Denied, or an insecure context. The link is on screen and selectable,
      // so the button quietly does nothing rather than raising an error about
      // a convenience.
    }
  }

  /**
   * Resend or withdraw one invitation.
   *
   * **Both paths written out.** `…/${id}/${what}` reads to the reachability
   * guard as `/api/staff/invitations/{}/{}`, which nothing serves — it fails
   * the build, and rightly: a path assembled from a variable is a path no
   * test can check against the routes that exist.
   */
  function act(id: number, what: "resend" | "revoke") {
    const call =
      what === "resend"
        ? api.post(`/api/staff/invitations/${id}/resend`)
        : api.post(`/api/staff/invitations/${id}/revoke`);
    call.then(reload).catch((caught) => setProblem(caught.message));
  }

  return (
    <div className="invite-page">
      <Link className="invite-page__back" to="/affiliates">
        ← Models
      </Link>

      <section className="invite-page__card">
        {/* The export's own title and subtitle: *Invitations*, because the
         *  screen is both halves - sending one and managing the ones still
         *  outstanding - and a page headed *Invite a model* above a list of
         *  three unanswered links is describing one of the two. */}
        <h1 className="invite-page__title">Invitations</h1>
        <p className="invite-page__subtitle">
          Invite a model and manage outstanding links
        </p>

        <form className="invite-page__form" onSubmit={send}>
          <input
            className="input"
            type="email"
            required
            value={email}
            placeholder="name@example.com"
            aria-label="Email address"
            onChange={(event) => setEmail(event.target.value)}
          />
          <button
            type="submit"
            className="button button--primary"
            disabled={working || !email.trim()}
          >
            {working ? "Sending…" : "Send invitation"}
          </button>
        </form>

        {/* This is what they sign in with, so it has to be the address they
            actually read. */}
        <p className="invite-page__hint">
          The link opens a form: a password, their own details, and where they
          want to be paid. You approve the application and set the pay after
          that — nothing about pay is decided here.
        </p>

        {problem && (
          <p className="invite-page__problem" role="alert">
            {problem}
          </p>
        )}

        {/*
         * Both the confirmation and the link: an emailed link is exactly what
         * somebody wants on screen the moment it is said never to have
         * arrived, and it is shown once because it is a working credential
         * until it is used.
         */}
        {link && (
          <div className="invite-page__link">
            <span className="code invite-page__link-value">{link}</span>
            <button type="button" className="button button--row" onClick={copy}>
              {copied ? "Copied" : "Copy"}
            </button>
          </div>
        )}
        {link && (
          <p className="invite-page__hint">
            {emailed
              ? `Emailed to ${sentTo}. The same link is above, in case it does not arrive — it only appears here once.`
              : "Email is not switched on, so send this link yourself — it only appears here once."}
          </p>
        )}

        {/*
         * The one state that must never be silent: the platform does not know
         * its own public address, so the email it just queued carries no link
         * at all. Saying nothing here leaves somebody waiting for a mail that
         * can never work.
         */}
        {link === "" && sentTo && (
          <p className="invite-page__problem" role="alert">
            The invitation was recorded, but the platform does not know its own
            web address, so no link could be built — the email will not contain
            one. Set <span className="code">PUBLIC_BASE_URL</span> on the
            service, then use Resend on {sentTo}.
          </p>
        )}
      </section>

      {/*
       * Waiting on somebody here, so it sits above the invitations that are
       * waiting on somebody else.
       */}
      {applicants !== null && applicants.length > 0 && (
        <section className="invite-page__list">
          <h2 className="invite-page__list-title">Applications awaiting review</h2>
          {applicants.map((row) => (
            <Link className="invite-page__row" key={row.id} to={`/affiliates/${row.id}`}>
              <span>
                {row.name}
                <span className="invite-page__sub">
                  {row.created_at ? `Applied ${formatSentAt(row.created_at)}` : "Applied"}
                </span>
              </span>
              <span className="invite-page__go">Review →</span>
            </Link>
          ))}
        </section>
      )}

      <section className="invite-page__list">
        <h2 className="invite-page__list-title">Outstanding invitations</h2>
        {invited.length === 0 ? (
          <p className="invite-page__empty">No invitation is outstanding.</p>
        ) : (
          // Live first, then lapsed and withdrawn: the ones somebody is still
          // waiting on belong on top.
          [...invited.filter((row) => !row.expired), ...invited.filter((row) => row.expired)].map(
            (row) => (
              <div className="invite-page__row" key={row.id}>
                <span>
                  {row.email}
                  <span className="invite-page__sub">Sent {formatSentAt(row.created_at)}</span>
                </span>
                <span
                  className={
                    row.expired || row.withdrawn
                      ? "invite-page__state invite-page__state--gone"
                      : "invite-page__state"
                  }
                >
                  {row.withdrawn ? "Withdrawn" : row.expired ? "Expired" : "Invited"}
                </span>
                {/* Resend always; withdraw only where it can still do
                    anything. */}
                <button type="button" className="button button--row" onClick={() => act(row.id, "resend")}>
                  Resend
                </button>
                {!row.expired && !row.withdrawn && (
                  <button
                    type="button"
                    className="button button--row invite-page__withdraw"
                    onClick={() => act(row.id, "revoke")}
                  >
                    Withdraw
                  </button>
                )}
              </div>
            ),
          )
        )}
      </section>
    </div>
  );
}
