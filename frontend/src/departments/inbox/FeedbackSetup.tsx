import { Link } from "react-router-dom";

import { FeedbackConnection } from "./FeedbackConnection";
import { FeedbackMessages, useWording } from "./FeedbackMessages";
import { InboxIcon } from "./InboxIcon";
import "./FeedbackSetup.css";

/**
 * Inbox → Feedback → Setup (ADR 0083): where the feedback questions are set
 * up. Settings → Integrations is for connections; the wording, the review
 * link, the reply time and the test are not a connection, so they live beside
 * the sheet they feed.
 *
 * Everyone who can open the Feedback sheet can read this page. Changing
 * anything, and sending a test, is an admin's: the server refuses it to
 * anybody else, and the page does not offer it.
 */
export function FeedbackSetup() {
  const wording = useWording();
  const canEdit = wording.body?.can_edit === true;

  return (
    <>
      <header className="page__head">
        <div className="page__title">
          <h1>Feedback setup</h1>
          <span className="page__subtitle">
            How the delivery questions are asked: the words, the review link and the reply time
          </span>
        </div>
        <Link className="inbox-btn inbox-btn--quiet" to="/inbox/feedback">
          <InboxIcon name="left" />
          Back to the answers
        </Link>
      </header>

      {wording.body && !canEdit && (
        <p className="notice fbs-readonly" role="status">
          Only an admin can change these settings or send a test. You can see everything as it is now.
        </p>
      )}

      <FeedbackConnection canEdit={canEdit} />

      {wording.error ? (
        <div className="notice notice--refused fbs-loaderror" role="alert">
          <p>{wording.error}</p>
          <button type="button" className="inbox-btn inbox-btn--quiet" onClick={wording.retry}>
            Try again
          </button>
        </div>
      ) : wording.body ? (
        <FeedbackMessages body={wording.body} onSaved={wording.setBody} />
      ) : (
        <p className="empty" role="status">
          Loading the messages…
        </p>
      )}
    </>
  );
}
