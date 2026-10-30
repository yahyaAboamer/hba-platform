import { useEffect, useRef, useState } from "react";

import type { ChatMessage } from "../../lib/inbox";
import { NO_MICROPHONE, canRecord, startRecording } from "../../lib/voiceNote";
import type { Recording } from "../../lib/voiceNote";
import { ChatTemplates } from "./ChatTemplates";
import type { Template } from "./ChatTemplates";
import { InboxIcon } from "./InboxIcon";
import { useIsNarrow } from "../../components/OpsSource";

/** WhatsApp's own limit on a text message. */
const MAX_TEXT = 4096;

/** What WhatsApp takes from us (`app/services/inbox/media.py`, SENDABLE). */
const ACCEPT = [
  "image/jpeg", "image/png", "video/mp4", "video/3gpp",
  "audio/ogg", "audio/mpeg", "audio/mp4", "audio/aac", "audio/amr",
  "application/pdf", ".doc", ".docx", ".xls", ".xlsx", ".txt",
].join(",");
/** The largest file the server keeps. It judges each kind's own limit. */
const MAX_FILE_BYTES = 25 * 1024 * 1024;

function fileSize(bytes: number): string {
  if (bytes < 1024 * 1024) return `${Math.max(1, Math.round(bytes / 1024))} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function clock(seconds: number): string {
  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")}`;
}

/**
 * Where staff type (ADR 0059; the approved mockup's frames 1 and 2): text,
 * a file, a voice note, and the approved messages.
 *
 * WhatsApp allows a free reply only for 24 hours after the customer's last
 * message. Once that has passed the box is replaced by the reason, in the
 * mockup's words, and the approved messages - the only thing that can still
 * be sent.
 */
export function ChatComposer({
  windowOpen,
  replyTo,
  onCancelReply,
  onSend,
  onSendFile,
  onSendTemplate,
}: {
  windowOpen: boolean;
  /** The message being answered, shown above the box until sent or dropped. */
  replyTo: ChatMessage | null;
  onCancelReply: () => void;
  /** Each sends, and answers with why it could not, or null when it went. */
  onSend: (body: string) => Promise<string | null>;
  onSendFile: (
    file: Blob,
    options: { filename: string; caption: string; voice: boolean },
  ) => Promise<string | null>;
  onSendTemplate: (template: Template) => Promise<string | null>;
}) {
  const [text, setText] = useState("");
  const [sending, setSending] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const [attached, setAttached] = useState<File | null>(null);
  const [picking, setPicking] = useState(false);
  // When the recording began; null when none is being made.
  const [recordingSince, setRecordingSince] = useState<number | null>(null);
  const [recordedFor, setRecordedFor] = useState(0);
  const recording = useRef<Recording | null>(null);
  const box = useRef<HTMLTextAreaElement | null>(null);
  const chooser = useRef<HTMLInputElement | null>(null);
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

  useEffect(() => {
    if (recordingSince === null) return;
    const timer = window.setInterval(
      () => setRecordedFor(Math.floor((Date.now() - recordingSince) / 1000)),
      500,
    );
    return () => window.clearInterval(timer);
  }, [recordingSince]);

  // Leaving the chat lets go of the microphone.
  useEffect(() => () => recording.current?.cancel(), []);

  async function send() {
    if (sending) return;
    const body = text.trim();
    if (!attached && !body) return;
    setSending(true);
    setProblem(null);
    const refused = attached
      ? await onSendFile(attached, { filename: attached.name, caption: body, voice: false })
      : await onSend(body);
    setSending(false);
    if (refused) {
      setProblem(refused);
    } else {
      setText("");
      setAttached(null);
    }
    box.current?.focus();
  }

  function choose(file: File | undefined) {
    if (!file) return;
    setProblem(null);
    if (file.size > MAX_FILE_BYTES) {
      setProblem("That file is larger than WhatsApp allows (25 MB).");
      return;
    }
    setAttached(file);
    box.current?.focus();
  }

  async function record() {
    setProblem(null);
    try {
      recording.current = await startRecording();
      setRecordedFor(0);
      setRecordingSince(Date.now());
    } catch (error) {
      setProblem(error instanceof Error ? error.message : NO_MICROPHONE);
    }
  }

  function discard() {
    recording.current?.cancel();
    recording.current = null;
    setRecordingSince(null);
  }

  async function sendRecording() {
    const made = recording.current;
    if (!made) return;
    recording.current = null;
    setRecordingSince(null);
    setSending(true);
    try {
      const note = await made.stop();
      const refused = await onSendFile(note.file, {
        filename: note.filename,
        caption: "",
        voice: note.voice,
      });
      if (refused) setProblem(refused);
    } catch (error) {
      setProblem(error instanceof Error ? error.message : "The voice note could not be sent.");
    } finally {
      setSending(false);
    }
  }

  if (!windowOpen) {
    return (
      <div className="inbox-closed">
        <p>
          <strong>You can't type a message here.</strong> WhatsApp only allows free replies for 24
          hours after the customer's last message. Send one of the approved messages; when she
          answers, the chat opens again.
        </p>
        <ChatTemplates onSend={onSendTemplate} />
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
      {picking && (
        <div className="inbox-picker" id="inbox-approved">
          <ChatTemplates
            onSend={async (template) => {
              const refused = await onSendTemplate(template);
              if (!refused) setPicking(false);
              return refused;
            }}
          />
        </div>
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
      {attached && (
        <div className="inbox-replying">
          <div className="inbox-file">
            <InboxIcon name={attached.type.startsWith("image/") ? "image" : "file"} />
            <span>
              {attached.name}
              <small>{fileSize(attached.size)}</small>
            </span>
          </div>
          <button
            type="button"
            className="inbox-iconbtn"
            aria-label={`Remove ${attached.name}`}
            onClick={() => setAttached(null)}
          >
            <InboxIcon name="close" />
          </button>
        </div>
      )}

      {recordingSince !== null ? (
        <div className="inbox-composer inbox-composer--recording">
          <button
            type="button"
            className="inbox-iconbtn"
            aria-label="Discard the recording"
            onClick={discard}
          >
            <InboxIcon name="close" />
          </button>
          <p className="inbox-recording" role="status">
            <span className="inbox-recording__dot" aria-hidden="true" />
            Recording {clock(recordedFor)}
          </p>
          <button
            type="button"
            className="inbox-send"
            aria-label="Send the voice note"
            onClick={() => void sendRecording()}
          >
            <InboxIcon name="send" />
          </button>
        </div>
      ) : (
        <div className="inbox-composer">
          <input
            ref={chooser}
            type="file"
            className="visually-hidden"
            tabIndex={-1}
            aria-hidden="true"
            accept={ACCEPT}
            data-testid="inbox-file"
            onChange={(event) => {
              choose(event.target.files?.[0]);
              // The same file can be chosen again after it is removed.
              event.target.value = "";
            }}
          />
          <button
            type="button"
            className="inbox-iconbtn"
            aria-label="Attach a photo, video or file"
            disabled={sending}
            onClick={() => chooser.current?.click()}
          >
            <InboxIcon name="clip" />
          </button>
          <button
            type="button"
            className="inbox-iconbtn"
            aria-label="Send an approved message"
            aria-expanded={picking}
            aria-controls={picking ? "inbox-approved" : undefined}
            onClick={() => setPicking(!picking)}
          >
            <InboxIcon name="template" />
          </button>
          <label className="visually-hidden" htmlFor="inbox-reply">
            Message
          </label>
          <textarea
            id="inbox-reply"
            ref={box}
            rows={1}
            dir="auto"
            placeholder={attached ? "Add a caption" : "Type a message"}
            maxLength={attached ? 1024 : MAX_TEXT}
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
          {canRecord() && !attached && (
            <button
              type="button"
              className="inbox-iconbtn"
              aria-label="Record a voice note"
              disabled={sending}
              onClick={() => void record()}
            >
              <InboxIcon name="mic" />
            </button>
          )}
          <button
            type="button"
            className="inbox-send"
            aria-label="Send"
            disabled={sending || (!attached && !text.trim())}
            onClick={() => void send()}
          >
            <InboxIcon name="send" />
          </button>
        </div>
      )}
    </div>
  );
}
