import { useEffect, useState } from "react";

import { ApiError, api } from "../lib/api";
import type { Session } from "../lib/api";
import { isOwner } from "../frame/where";
import type { FeedbackSettings } from "../lib/inbox";
import { dayMonth } from "./OpsSource";

/** The API's own limits (`feedback.save_settings`), checked here first so a slip is caught before it is sent. */
const REVIEW_URL_MAX = 500;
const HOURS_MIN = 1;
const HOURS_MAX = 72;

/** Why a review link would be refused, or null when it is fine (empty clears it). */
export function reviewLinkProblem(value: string): string | null {
  const link = value.trim();
  if (link === "") return null;
  if (link.length > REVIEW_URL_MAX) return `The review link can be at most ${REVIEW_URL_MAX} characters.`;
  if (!/^https:\/\/[^\s/]+/i.test(link) || /\s/.test(link)) {
    return "The review link must start with https:// and be a single link.";
  }
  return null;
}

/** Why a promised reply time would be refused, or null when it is fine. */
export function replyHoursProblem(value: string): string | null {
  const hours = value.trim();
  if (!/^\d+$/.test(hours) || Number(hours) < HOURS_MIN || Number(hours) > HOURS_MAX) {
    return `Enter a whole number of hours from ${HOURS_MIN} to ${HOURS_MAX}.`;
  }
  return null;
}

/**
 * Inbox → Feedback's settings, in Settings → Integrations beside the
 * WhatsApp connection (ADR 0083). Read-only: whether the questions are on
 * (a switch on the server, not here), since when, and whether reward codes
 * can be made. Editable: the review link and the reply time promised to an
 * unhappy customer.
 */
function Card() {
  const [settings, setSettings] = useState<FeedbackSettings | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [open, setOpen] = useState(false);
  const [link, setLink] = useState("");
  const [hours, setHours] = useState("");
  const [working, setWorking] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState<string | null>(null);

  useEffect(() => {
    let current = true;
    api
      .get<FeedbackSettings>("/api/inbox/feedback/settings")
      .then((found) => {
        if (current) setSettings(found);
      })
      .catch((caught) => {
        if (current) {
          setLoadError(
            caught instanceof ApiError ? caught.message : "The feedback settings could not be read.",
          );
        }
      });
    return () => {
      current = false;
    };
  }, []);

  if (loadError) {
    return (
      <section className="pay-detail__card sync__card" aria-labelledby="inbox-feedback-settings-title">
        <h2 className="pay-detail__card-title" id="inbox-feedback-settings-title">
          Feedback questions
        </h2>
        <p className="sync__error">{loadError}</p>
      </section>
    );
  }
  if (!settings) return null;

  const linkProblem = reviewLinkProblem(link);
  const hoursProblem = replyHoursProblem(hours);
  const changed = link.trim() !== (settings.review_url ?? "") || hours.trim() !== String(settings.reply_hours);

  function edit() {
    if (!settings) return;
    setLink(settings.review_url ?? "");
    setHours(String(settings.reply_hours));
    setError(null);
    setSaved(null);
    setOpen(true);
  }

  async function save(event: React.FormEvent) {
    event.preventDefault();
    if (!settings || linkProblem || hoursProblem || !changed) return;
    setWorking(true);
    setError(null);
    try {
      // Only what was changed: a field left out keeps its saved value.
      const body: { review_url?: string; reply_hours?: number } = {};
      if (link.trim() !== (settings.review_url ?? "")) body.review_url = link.trim();
      if (hours.trim() !== String(settings.reply_hours)) body.reply_hours = Number(hours.trim());
      const answer = await api.put<FeedbackSettings>("/api/inbox/feedback/settings", body);
      // The answer to a save leaves out the Shopify check; keep the last one.
      setSettings({ ...answer, codes_ready: settings.codes_ready });
      setOpen(false);
      setSaved("Saved.");
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : "The settings were not changed.");
    } finally {
      setWorking(false);
    }
  }

  return (
    <section className="pay-detail__card sync__card" aria-labelledby="inbox-feedback-settings-title">
      <h2 className="pay-detail__card-title" id="inbox-feedback-settings-title">
        Feedback questions
      </h2>
      <p className="shop-conn__meta">
        {settings.enabled
          ? `On${settings.started_at ? ` · asking since ${dayMonth(settings.started_at)}` : ""}`
          : "Off · nothing is being sent"}
      </p>
      {settings.codes_ready && (
        <p className="shop-conn__meta">
          {settings.codes_ready.ready
            ? "Reward codes can be made."
            : `Reward codes cannot be made yet. ${settings.codes_ready.reason ?? ""}`.trim()}
        </p>
      )}
      <p className="shop-conn__meta">
        Review link: {settings.review_url ? settings.review_url : "not set"} · Unhappy customers are
        promised a reply within {settings.reply_hours} {settings.reply_hours === 1 ? "hour" : "hours"}
      </p>
      <p className="sync__hint">Turning the questions on or off is done on the server, not here.</p>
      {saved && (
        <p className="sync__notice" role="status">
          {saved}
        </p>
      )}
      {open ? (
        <form className="shop-conn" onSubmit={save} noValidate>
          <label className="shop-conn__field" htmlFor="inbox-feedback-link">
            <span className="shop-conn__label">Review link</span>
            <input
              id="inbox-feedback-link"
              className="shop-conn__input"
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
            <p className="sync__error" id="inbox-feedback-link-problem">
              {linkProblem}
            </p>
          ) : (
            <p className="sync__hint" id="inbox-feedback-link-hint">
              Sent to customers who loved it or found it okay. Leave empty to send none.
            </p>
          )}
          <label className="shop-conn__field" htmlFor="inbox-feedback-hours">
            <span className="shop-conn__label">Reply time promised to unhappy customers (hours)</span>
            <input
              id="inbox-feedback-hours"
              className="shop-conn__input"
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
            <p className="sync__error" id="inbox-feedback-hours-problem">
              {hoursProblem}
            </p>
          )}
          {error && (
            <p className="sync__error" role="alert">
              {error}
            </p>
          )}
          <button
            type="submit"
            className="button shop-conn__submit"
            disabled={working || linkProblem !== null || hoursProblem !== null || !changed}
          >
            {working ? "Saving…" : "Save"}
          </button>{" "}
          <button
            type="button"
            className="button button--quiet shop-conn__submit"
            onClick={() => {
              setError(null);
              setOpen(false);
            }}
          >
            Cancel
          </button>
        </form>
      ) : (
        <button type="button" className="button button--quiet shop-conn__submit" onClick={edit}>
          Change
        </button>
      )}
    </section>
  );
}

/** The owner's card. Anybody else gets nothing, and the server would refuse a save anyway. */
export function InboxFeedbackSettings({ session }: { session: Session }) {
  return isOwner(session) ? <Card /> : null;
}
