import { useEffect, useState } from "react";

import { ApiError, api } from "../lib/api";
import { OpsIcon } from "./OpsSource";

/**
 * The approved messages (ADR 0059; the approved mockup's frame 2, "The
 * customer has been silent for more than 24 hours").
 *
 * Once her 24 hours have passed, WhatsApp takes only a message Meta has
 * approved. The list is read from Meta each time, so it is whatever is
 * approved now. One that needs nothing filled in can be sent as it stands;
 * one that is filled in from an order - the confirmation - is listed with
 * why it is not sent from here.
 *
 * Sending is a second step: it reaches a customer and is paid for.
 */

export type Template = {
  name: string;
  language: string;
  category: string | null;
  body: string | null;
  sendable: boolean;
  why_not: string | null;
};

/** "we_tried_to_reach_you" as a person would say it. */
function title(name: string): string {
  const words = name.replace(/[_-]+/g, " ").trim();
  return words.charAt(0).toUpperCase() + words.slice(1);
}

export function ChatTemplates({
  onSend,
}: {
  /** Sends, and answers with why it could not, or null when it went. */
  onSend: (template: Template) => Promise<string | null>;
}) {
  const [templates, setTemplates] = useState<Template[] | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const [chosen, setChosen] = useState<Template | null>(null);
  const [sending, setSending] = useState(false);

  useEffect(() => {
    let wanted = true;
    api
      .get<{ templates: Template[] }>("/api/inbox/templates")
      .then((body) => {
        if (wanted) setTemplates(body.templates);
      })
      .catch((error) => {
        if (wanted) {
          setProblem(
            error instanceof ApiError ? error.message : "The approved messages could not be read.",
          );
        }
      });
    return () => {
      wanted = false;
    };
  }, []);

  async function send() {
    if (!chosen || sending) return;
    setSending(true);
    setProblem(null);
    const refused = await onSend(chosen);
    setSending(false);
    if (refused) setProblem(refused);
    else setChosen(null);
  }

  if (chosen) {
    return (
      <div className="inbox-templates" role="group" aria-label={`Send ${title(chosen.name)}`}>
        <p className="inbox-template__body" dir="auto">
          {chosen.body ?? title(chosen.name)}
        </p>
        {problem && (
          <p className="notice notice--refused" role="alert">
            {problem}
          </p>
        )}
        <div className="inbox-template__actions">
          <button type="button" className="inbox-btn inbox-btn--small" disabled={sending} onClick={() => void send()}>
            {sending ? "Sending…" : "Send this message"}
          </button>
          <button
            type="button"
            className="inbox-btn inbox-btn--quiet inbox-btn--small"
            disabled={sending}
            onClick={() => {
              setChosen(null);
              setProblem(null);
            }}
          >
            Back
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="inbox-templates">
      {problem && (
        <p className="notice notice--refused" role="alert">
          {problem}
        </p>
      )}
      {templates === null && !problem && <p className="loading">Reading the approved messages…</p>}
      {templates !== null && templates.length === 0 && (
        <p className="inbox-templates__none">No message has been approved yet.</p>
      )}
      {templates?.map((template) => (
        <button
          key={`${template.name}:${template.language}`}
          type="button"
          className="inbox-template"
          disabled={!template.sendable}
          onClick={() => setChosen(template)}
        >
          <span>
            {title(template.name)}
            <small dir="auto">{template.sendable ? template.body : template.why_not}</small>
          </span>
          {template.sendable && <OpsIcon name="right" />}
        </button>
      ))}
    </div>
  );
}
