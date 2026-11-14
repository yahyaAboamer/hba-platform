import { useState } from "react";
import { Link } from "react-router-dom";

import {
  codesProblem,
  replyHoursProblem,
  reviewLinkProblem,
  statusLine,
  testPhoneProblem,
  useFeedbackSettings,
} from "../../components/InboxFeedbackSettings";
import { ApiError, api } from "../../lib/api";
import { formatPhone } from "../../lib/inbox";
import type { FeedbackSettings, FeedbackTestSent } from "../../lib/inbox";
import "./FeedbackSetup.css";

const REVIEW_URL_MAX = 500;

/**
 * The top of Inbox → Feedback setup: where the feature stands, the two
 * settings that are not wording (the review link and the reply time promised
 * to an unhappy customer), and a test send. What the questions *say* is
 * `FeedbackMessages`, below this.
 *
 * Reading is for everyone who can open the Inbox's Feedback; changing a
 * setting and sending a test are an admin's (`canEdit`), and the server
 * refuses them to anybody else anyway.
 */
export function FeedbackConnection({ canEdit }: { canEdit: boolean }) {
  const { settings, setSettings, loadError } = useFeedbackSettings();

  if (loadError) {
    return (
      <p className="notice notice--refused" role="alert">
        {loadError}
      </p>
    );
  }
  if (!settings) return <p className="empty">Loading…</p>;

  return (
    <div className="fbs-cards">
      <StatusCard settings={settings} />
      <LinkCard settings={settings} onSaved={setSettings} canEdit={canEdit} />
      {canEdit && <TestCard />}
    </div>
  );
}

function StatusCard({ settings }: { settings: FeedbackSettings }) {
  const problem = codesProblem(settings);
  return (
    <section className="panel fbs-card" aria-labelledby="fbs-status-title">
      <div className="panel__head">
        <h2 className="panel__title" id="fbs-status-title">
          Status
        </h2>
      </div>
      <div className="fbs-card__body">
        <p className="fbs-card__lead">{statusLine(settings)}</p>
        {settings.codes_ready && (
          <p className={problem ? "fbs-card__line fbs-card__line--owed" : "fbs-card__line"}>
            {problem ?? "Reward codes can be made."}
          </p>
        )}
        <p className="fbs-card__hint">Turning the questions on or off is done on the server, not here.</p>
      </div>
    </section>
  );
}

function LinkCard({
  settings,
  onSaved,
  canEdit,
}: {
  settings: FeedbackSettings;
  onSaved: (next: FeedbackSettings) => void;
  canEdit: boolean;
}) {
  const [open, setOpen] = useState(false);
  const [link, setLink] = useState("");
  const [hours, setHours] = useState("");
  const [working, setWorking] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState<string | null>(null);

  const linkProblem = reviewLinkProblem(link);
  const hoursProblem = replyHoursProblem(hours);
  const changed = link.trim() !== (settings.review_url ?? "") || hours.trim() !== String(settings.reply_hours);

  function edit() {
    setLink(settings.review_url ?? "");
    setHours(String(settings.reply_hours));
    setError(null);
    setSaved(null);
    setOpen(true);
  }

  async function save(event: React.FormEvent) {
    event.preventDefault();
    if (linkProblem || hoursProblem || !changed) return;
    setWorking(true);
    setError(null);
    try {
      // Only what was changed: a field left out keeps its saved value.
      const body: { review_url?: string; reply_hours?: number } = {};
      if (link.trim() !== (settings.review_url ?? "")) body.review_url = link.trim();
      if (hours.trim() !== String(settings.reply_hours)) body.reply_hours = Number(hours.trim());
      const answer = await api.put<FeedbackSettings>("/api/inbox/feedback/settings", body);
      // The answer to a save leaves out the Shopify check; keep the last one.
      onSaved({ ...answer, codes_ready: settings.codes_ready });
      setOpen(false);
      setSaved("Saved.");
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : "The settings were not changed.");
    } finally {
      setWorking(false);
    }
  }

  return (
    <section className="panel fbs-card" aria-labelledby="fbs-link-title">
      <div className="panel__head">
        <h2 className="panel__title" id="fbs-link-title">
          Review link and reply time
        </h2>
        {canEdit && !open && (
          <button type="button" className="inbox-btn inbox-btn--quiet inbox-btn--small" onClick={edit}>
            Change
            <span className="visually-hidden"> the review link and reply time</span>
          </button>
        )}
      </div>
      <div className="fbs-card__body">
        <dl className="fbs-facts">
          <div>
            <dt>Review link</dt>
            <dd>{settings.review_url ? settings.review_url : "not set"}</dd>
          </div>
          <div>
            <dt>Unhappy customers are promised a reply within</dt>
            <dd>
              {settings.reply_hours} {settings.reply_hours === 1 ? "hour" : "hours"}
            </dd>
          </div>
        </dl>
        {saved && (
          <p className="fbs-notice" role="status">
            {saved}
          </p>
        )}
        {open && (
          <form className="fbs-form" onSubmit={save} noValidate>
            <label className="field" htmlFor="inbox-feedback-link">
              <span className="field__label">Review link</span>
              <input
                id="inbox-feedback-link"
                className="input"
                type="url"
                inputMode="url"
                autoComplete="off"
                spellCheck={false}
                maxLength={REVIEW_URL_MAX + 50}
                value={link}
                placeholder="https://…"
                aria-invalid={linkProblem !== null}
                aria-describedby={linkProblem ? "inbox-feedback-link-problem" : "inbox-feedback-link-hint"}
                onChange={(event) => setLink(event.target.value)}
              />
            </label>
            {linkProblem ? (
              <p className="fbs-error" id="inbox-feedback-link-problem">
                {linkProblem}
              </p>
            ) : (
              <p className="fbs-card__hint" id="inbox-feedback-link-hint">
                Sent to customers who loved it or found it okay. Leave empty to send none.
              </p>
            )}
            <label className="field" htmlFor="inbox-feedback-hours">
              <span className="field__label">Reply time promised to unhappy customers (hours)</span>
              <input
                id="inbox-feedback-hours"
                className="input fbs-input--short"
                type="text"
                inputMode="numeric"
                autoComplete="off"
                value={hours}
                aria-invalid={hoursProblem !== null}
                aria-describedby={hoursProblem ? "inbox-feedback-hours-problem" : undefined}
                onChange={(event) => setHours(event.target.value)}
              />
            </label>
            {hoursProblem && (
              <p className="fbs-error" id="inbox-feedback-hours-problem">
                {hoursProblem}
              </p>
            )}
            {error && (
              <p className="fbs-error" role="alert">
                {error}
              </p>
            )}
            <div className="fbs-form__actions">
              <button
                type="submit"
                className="inbox-btn"
                disabled={working || linkProblem !== null || hoursProblem !== null || !changed}
              >
                {working ? "Saving…" : "Save"}
              </button>
              <button
                type="button"
                className="inbox-btn inbox-btn--quiet"
                onClick={() => {
                  setError(null);
                  setOpen(false);
                }}
              >
                Cancel
              </button>
            </div>
          </form>
        )}
      </div>
    </section>
  );
}

/**
 * The real first question sent to one number now, even while the questions are
 * off, so the owner can answer it on his own phone and try each path.
 */
function TestCard() {
  const [phone, setPhone] = useState("");
  const [testing, setTesting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [sent, setSent] = useState<FeedbackTestSent | null>(null);

  const problem = phone.trim() === "" ? null : testPhoneProblem(phone);

  async function send(event: React.FormEvent) {
    event.preventDefault();
    if (testing) return;
    const refused = testPhoneProblem(phone);
    if (refused) {
      setSent(null);
      setError(refused);
      return;
    }
    setTesting(true);
    setError(null);
    setSent(null);
    try {
      setSent(await api.post<FeedbackTestSent>("/api/inbox/feedback/test", { phone: phone.trim() }));
    } catch (caught) {
      // The server's own words: it knows why (not connected, sending off, not a number it may message).
      setError(caught instanceof ApiError ? caught.message : "The test could not be sent.");
    } finally {
      setTesting(false);
    }
  }

  return (
    <section className="panel fbs-card" aria-labelledby="fbs-test-title">
      <div className="panel__head">
        <h2 className="panel__title" id="fbs-test-title">
          Send a test
        </h2>
      </div>
      <div className="fbs-card__body">
        <form className="fbs-form" onSubmit={send} noValidate>
          <label className="field" htmlFor="inbox-feedback-test-phone">
            <span className="field__label">Number to send the test to</span>
            <input
              id="inbox-feedback-test-phone"
              className="input"
              type="tel"
              inputMode="tel"
              autoComplete="off"
              maxLength={40}
              value={phone}
              placeholder="01xxxxxxxxx"
              aria-invalid={problem !== null}
              aria-describedby={problem ? "inbox-feedback-test-problem" : "inbox-feedback-test-hint"}
              onChange={(event) => {
                setPhone(event.target.value);
                setError(null);
              }}
            />
          </label>
          {problem ? (
            <p className="fbs-error" id="inbox-feedback-test-problem">
              {problem}
            </p>
          ) : (
            <p className="fbs-card__hint" id="inbox-feedback-test-hint">
              Sends the real first question to this number now, even while questions are switched off. Answer
              it on that phone to try each path. Tests are not counted in the sheet.
            </p>
          )}
          {error && !problem && (
            <p className="fbs-error" role="alert">
              {error}
            </p>
          )}
          {sent && (
            <p className="fbs-notice" role="status">
              Sent to {formatPhone(sent.phone)}. <Link to={`/inbox/chats/${sent.conversation_id}`}>Open the chat</Link>
            </p>
          )}
          <div className="fbs-form__actions">
            <button
              type="submit"
              className="inbox-btn inbox-btn--quiet"
              disabled={testing || phone.trim() === "" || problem !== null}
            >
              {testing ? "Sending…" : "Send a test to this number"}
            </button>
          </div>
        </form>
      </div>
    </section>
  );
}
