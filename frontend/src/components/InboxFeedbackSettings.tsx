import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

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
 * Why a number would be refused as a test's, or null when it is fine. The same
 * reading as the server's (`sending.egyptian_mobile`: any usual way of writing
 * an Egyptian mobile), checked here first; the server decides.
 */
export function testPhoneProblem(value: string): string | null {
  let digits = value.replace(/\D/g, "");
  if (digits.startsWith("0020")) digits = digits.slice(2);
  else if (digits.startsWith("0")) digits = `20${digits.slice(1)}`;
  else if (digits.length === 10 && digits.startsWith("1")) digits = `20${digits}`;
  // The 0 of 010... kept after the country code (+20 0100...).
  if (digits.startsWith("200") && /^20(10|11|12|15)\d{8}$/.test(`20${digits.slice(3)}`)) {
    digits = `20${digits.slice(3)}`;
  }
  return /^20(10|11|12|15)\d{8}$/.test(digits)
    ? null
    : "That is not an Egyptian mobile number. Write it like 01xxxxxxxxx.";
}

/**
 * The feature's settings, read once. Shared by the short card in Settings and
 * the setup page in the Inbox, which holds the forms (`FeedbackConnection`).
 */
export function useFeedbackSettings(enabled = true) {
  const [settings, setSettings] = useState<FeedbackSettings | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);

  useEffect(() => {
    if (!enabled) return;
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
  }, [enabled]);

  return { settings, setSettings, loadError };
}

/** *On · asking since 5 Nov*, or *Off · nothing is being sent*. */
export function statusLine(settings: FeedbackSettings): string {
  return settings.enabled
    ? `On${settings.started_at ? ` · asking since ${dayMonth(settings.started_at)}` : ""}`
    : "Off · nothing is being sent";
}

/** The reason reward codes cannot be made, or null when they can (or it is not known). */
export function codesProblem(settings: FeedbackSettings): string | null {
  if (!settings.codes_ready || settings.codes_ready.ready) return null;
  return `Reward codes cannot be made yet. ${settings.codes_ready.reason ?? ""}`.trim();
}

/**
 * Inbox → Feedback in Settings → Integrations, beside the WhatsApp connection
 * (ADR 0083). Integrations is for connections, so this is short: whether the
 * questions are on, a reward-code problem (that is a connection fault, a
 * Shopify permission), and the way to the setup page in the Inbox, where the
 * wording, the review link, the reply time and the test live.
 */
function Card() {
  const { settings, loadError } = useFeedbackSettings();

  if (loadError) {
    return (
      <section className="pay-detail__card sync__card" aria-labelledby="inbox-feedback-settings-title">
        <h3 className="pay-detail__card-title" id="inbox-feedback-settings-title">
          Feedback questions
        </h3>
        <p className="sync__error">{loadError}</p>
      </section>
    );
  }
  if (!settings) return null;

  const problem = codesProblem(settings);
  return (
    <section className="pay-detail__card sync__card" aria-labelledby="inbox-feedback-settings-title">
      <h3 className="pay-detail__card-title" id="inbox-feedback-settings-title">
        Feedback questions
      </h3>
      <p className="shop-conn__meta">{statusLine(settings)}</p>
      {problem && <p className="shop-conn__meta integrations__problem">{problem}</p>}
      <Link className="button button--quiet shop-conn__submit integrations__open" to="/inbox/feedback/setup">
        Open feedback setup
      </Link>
    </section>
  );
}

/** The owner's card. Anybody else gets nothing, and the server would refuse a save anyway. */
export function InboxFeedbackSettings({ session }: { session: Session }) {
  return isOwner(session) ? <Card /> : null;
}
