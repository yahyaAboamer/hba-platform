import { useEffect, useRef, useState } from "react";

import type { ChatMessage } from "../lib/inbox";
import { InboxIcon } from "./InboxIcon";
import { useIsNarrow } from "./OpsSource";

/** WhatsApp's own limit on a text message. */
const MAX_TEXT = 4096;

/**
 * Where staff type (ADR 0059; the approved mockup's frames 1 and 2).
 *
 * WhatsApp allows a free reply only for 24 hours after the customer's last
 * message. Once that has passed the box is replaced by the reason, in the
 * mockup's words.
 */
export function ChatComposer({
  windowOpen,
  replyTo,
  onCancelReply,
  onSend,
}: {
  windowOpen: boolean;
  /** The message being answered, shown above the box until sent or dropped. */
  replyTo: ChatMessage | null;
  onCancelReply: () => void;
  /** Sends, and answers with why it could not, or null when it went. */
  onSend: (body: string) => Promise<string | null>;
}) {
  const [text, setText] = useState("");
  const [sending, setSending] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const box = useRef<HTMLTextAreaElement | null>(null);
  const narrow = useIsNarrow();

  // The box grows with what is typed, up to a few lines.
  useEffect(() => {
    const area = box.current;
    if (!area) return;
    area.style.height = "auto";
    // scrollHeight leaves the border out; without it the box is two pixels
    // short and shows a scrollbar for one line of text.
    const border = area.offsetHeight - area.clientHeight;
    area.style.height = `${Math.min(area.scrollHeight + border, 120)}px`;
  }, [text]);

  // Choosing a message to answer puts the cursor where the answer goes.
  useEffect(() => {
    if (replyTo) box.current?.focus();
  }, [replyTo]);

  async function send() {
    const body = text.trim();
    if (!body || sending) return;
    setSending(true);
    setProblem(null);
    const refused = await onSend(body);
    setSending(false);
    if (refused) {
      setProblem(refused);
    } else {
      setText("");
    }
    box.current?.focus();
  }

  if (!windowOpen) {
    return (
      <div className="inbox-closed">
        <p>
          <strong>You can't type a message here.</strong> WhatsApp only allows free replies for 24
          hours after the customer's last message. Send one of the approved messages; when she
          answers, the chat opens again.
        </p>
      </div>
    );
  }

  return (
    <div className="inbox-composer-wrap">
      {problem && (
        <p className="notice notice--refused inbox-composer__problem" role="alert">
          {problem}
        </p>
      )}
      {replyTo && (
        <div className="inbox-replying">
          <div className="inbox-msg__quote" dir="auto">
            <span className="visually-hidden">Replying to: </span>
            {replyTo.body || "A file"}
          </div>
          <button
            type="button"
            className="inbox-iconbtn"
            aria-label="Don't reply to this message"
            onClick={onCancelReply}
          >
            <InboxIcon name="close" />
          </button>
        </div>
      )}
      <div className="inbox-composer">
        <label className="visually-hidden" htmlFor="inbox-reply">
          Message
        </label>
        <textarea
          id="inbox-reply"
          ref={box}
          rows={1}
          dir="auto"
          placeholder="Type a message"
          maxLength={MAX_TEXT}
          value={text}
          onChange={(event) => setText(event.target.value)}
          onKeyDown={(event) => {
            // Enter sends on a keyboard; on a phone it is a new line, and
            // never while an Arabic or other composed letter is being typed.
            if (event.key === "Enter" && !event.shiftKey && !narrow && !event.nativeEvent.isComposing) {
              event.preventDefault();
              void send();
            }
          }}
        />
        <button
          type="button"
          className="inbox-send"
          aria-label="Send"
          disabled={sending || !text.trim()}
          onClick={() => void send()}
        >
          <InboxIcon name="send" />
        </button>
      </div>
    </div>
  );
}
