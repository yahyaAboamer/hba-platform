import { Fragment, useEffect, useRef, useState } from "react";

import { OpsIcon, clockTime } from "../../components/OpsSource";
import { InboxIcon } from "./InboxIcon";
import { ApiError, api } from "../../lib/api";
import { dayKey, dayMark } from "../../lib/inbox";
import type { ChatMessage, ChatOrder, TriedAgain } from "../../lib/inbox";

/**
 * A chat's messages, oldest first (ADR 0059; the approved mockup
 * `docs/design/whatsapp-inbox-2026-10-11.html`, frames 1 and 2).
 *
 * Her words are hers: shown as text and never as markup, in whichever
 * direction they are written - most are Arabic.
 */

const BUTTON_FOR: Record<string, string> = { confirmed: "Confirm", edit: "Edit", cancelled: "Cancel" };
const WHAT: Record<string, string> = {
  image: "Photo",
  sticker: "Sticker",
  audio: "Voice note",
  video: "Video",
  document: "File",
};
const TICK: Record<string, { icon: "tick" | "ticks"; words: string } | undefined> = {
  sent: { icon: "tick", words: "Sent" },
  delivered: { icon: "ticks", words: "Delivered" },
  read: { icon: "ticks", words: "Read" },
};

/** The handful offered; WhatsApp takes any one emoji. */
const REACTIONS = ["👍", "❤️", "😂", "😮", "😢", "🙏"];

function fileSize(bytes: number | null): string {
  if (!bytes) return "";
  if (bytes < 1024 * 1024) return `${Math.max(1, Math.round(bytes / 1024))} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function clock(seconds: number): string {
  const whole = Math.max(0, Math.floor(seconds));
  return `${Math.floor(whole / 60)}:${String(whole % 60).padStart(2, "0")}`;
}

/** A voice note: play, how far through, how long. */
function Voice({ url }: { url: string }) {
  const audio = useRef<HTMLAudioElement | null>(null);
  const [playing, setPlaying] = useState(false);
  const [at, setAt] = useState(0);
  const [length, setLength] = useState<number | null>(null);
  const [broken, setBroken] = useState(false);

  function toggle() {
    const player = audio.current;
    if (!player) return;
    if (player.paused) {
      player.play().catch(() => setBroken(true));
    } else {
      player.pause();
    }
  }

  if (broken) {
    return (
      <a className="inbox-file" href={url} download>
        <InboxIcon name="mic" />
        <span>
          Voice note
          <small>This browser cannot play it. Download</small>
        </span>
      </a>
    );
  }

  const played = length ? Math.min(100, (at / length) * 100) : 0;
  return (
    <div className="inbox-voice">
      <button
        type="button"
        className="inbox-voice__play"
        aria-label={playing ? "Pause voice note" : "Play voice note"}
        onClick={toggle}
      >
        <InboxIcon name={playing ? "pause" : "play"} />
      </button>
      <span className="inbox-voice__wave" style={{ ["--played" as string]: `${played}%` }} />
      <span className="inbox-voice__len">
        {length === null ? "" : clock(playing || at > 0 ? at : length)}
      </span>
      {/* Fetched only when played: a chat of voice notes is not ten downloads. */}
      <audio
        ref={audio}
        src={url}
        preload="none"
        onPlay={() => setPlaying(true)}
        onPause={() => setPlaying(false)}
        onEnded={() => {
          setPlaying(false);
          setAt(0);
        }}
        onTimeUpdate={(event) => setAt(event.currentTarget.currentTime)}
        onLoadedMetadata={(event) => {
          const seconds = event.currentTarget.duration;
          if (Number.isFinite(seconds)) setLength(seconds);
        }}
        onError={() => setBroken(true)}
      />
    </div>
  );
}

/** A photo at full size, over the chat. Escape or the button closes it. */
function PhotoViewer({ url, words, onClose }: { url: string; words: string; onClose: () => void }) {
  const close = useRef<HTMLButtonElement | null>(null);
  useEffect(() => {
    const before = document.activeElement as HTMLElement | null;
    close.current?.focus();
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("keydown", onKey);
      before?.focus?.();
    };
  }, [onClose]);

  return (
    <div className="inbox-viewer" role="dialog" aria-modal="true" aria-label={words} onClick={onClose}>
      <button
        ref={close}
        type="button"
        className="inbox-iconbtn inbox-viewer__close"
        aria-label="Close photo"
      >
        <InboxIcon name="close" />
      </button>
      <img src={url} alt={words} onClick={(event) => event.stopPropagation()} />
    </div>
  );
}

function Media({ message, customer }: { message: ChatMessage; customer: string }) {
  const [viewing, setViewing] = useState(false);
  // What asking WhatsApp again came to, laid over what the chat last said.
  const [tried, setTried] = useState<TriedAgain | null>(null);
  const [asking, setAsking] = useState(false);
  const media = message.media && tried ? { ...message.media, ...tried } : message.media;
  const what = WHAT[message.kind] ?? "File";
  const isFile = message.kind === "document";

  async function tryAgain() {
    if (!media) return;
    setAsking(true);
    try {
      setTried(await api.post<TriedAgain>(`/api/inbox/media/${media.id}/try-again`, {}));
    } catch (error) {
      setTried({
        state: media.state,
        url: null,
        can_try_again: false,
        problem: error instanceof ApiError ? error.message : `The ${what.toLowerCase()} could not be fetched. Try again later.`,
      });
    } finally {
      setAsking(false);
    }
  }

  if (!media || !media.url || media.state !== "stored") {
    const state = media?.state;
    const again = media?.can_try_again ? (
      <button type="button" className="inbox-again" onClick={() => void tryAgain()} disabled={asking}>
        {asking ? "Fetching…" : "Try again"}
      </button>
    ) : null;
    const problem = tried?.problem ? <small role="alert">{tried.problem}</small> : null;
    if (isFile) {
      return (
        <div className="inbox-file">
          <InboxIcon name="file" />
          <span>
            {media?.filename || "File"}
            <small>
              {state === "pending" ? "Being fetched…" : state === "failed" ? "Could not be copied" : "No longer available"}
            </small>
            {problem}
            {again}
          </span>
        </div>
      );
    }
    return (
      <div className="inbox-gone">
        <InboxIcon name={message.kind === "audio" ? "mic" : "image"} />
        <span>
          {state === "pending"
            ? `${what} is being fetched…`
            : state === "failed"
              ? `${what} could not be copied`
              : `${what} no longer available`}
          {problem}
          {again}
        </span>
      </div>
    );
  }

  if (message.kind === "image" || message.kind === "sticker") {
    const words = `${what} from ${message.direction === "in" ? customer : message.sender ?? "HBA"}`;
    return (
      <>
        <button
          type="button"
          className="inbox-photo"
          aria-label={`Open ${what.toLowerCase()}`}
          onClick={() => setViewing(true)}
        >
          {/* Our own copy, through the server: never straight from WhatsApp. */}
          <img src={`/api/inbox/media/${media.id}`} alt={words} loading="lazy" />
        </button>
        {viewing && <PhotoViewer url={media.url} words={words} onClose={() => setViewing(false)} />}
      </>
    );
  }
  if (message.kind === "audio") return <Voice url={media.url} />;
  if (message.kind === "video") {
    return <video className="inbox-video" src={media.url} controls preload="none" aria-label={what} />;
  }
  return (
    <a className="inbox-file" href={media.url} download={media.filename ?? true}>
      <InboxIcon name="file" />
      <span>
        {media.filename || "File"}
        <small>{fileSize(media.size_bytes) || "Download"}</small>
      </span>
    </a>
  );
}

function whoSent(message: ChatMessage): string {
  if (message.origin === "automatic") {
    return message.kind === "template" ? "Automatic · order confirmation" : "Automatic";
  }
  if (message.origin === "imported") return "HBA";
  return message.sender ?? "HBA";
}

/** `text` with each place it holds `words` marked, ignoring case. */
function Marked({ text, words }: { text: string; words?: string }) {
  const wanted = words?.trim().toLowerCase();
  const lower = text.toLowerCase();
  // A letter whose lower case is longer would put the marks in the wrong place.
  if (!wanted || wanted.length < 2 || lower.length !== text.length) return <>{text}</>;
  const parts = [];
  let from = 0;
  for (let at = lower.indexOf(wanted); at !== -1; at = lower.indexOf(wanted, from)) {
    if (at > from) parts.push(text.slice(from, at));
    parts.push(<mark key={at}>{text.slice(at, at + wanted.length)}</mark>);
    from = at + wanted.length;
  }
  parts.push(text.slice(from));
  return <>{parts}</>;
}

export function ChatMessages({
  messages,
  orders,
  customer,
  now,
  canSend,
  found = null,
  marked,
  onRetry,
  onReply,
  onReact,
}: {
  messages: ChatMessage[];
  orders: ChatOrder[];
  /** What she is called here: her first name, or her number. */
  customer: string;
  now: number;
  /** Whether a reply or a reaction may be sent right now. */
  canSend: boolean;
  /** The message a search inside the chat is on, picked out. */
  found?: number | null;
  /** The words searched for, marked wherever a message holds them. */
  marked?: string;
  onRetry?: (message: ChatMessage) => void;
  onReply?: (message: ChatMessage) => void;
  onReact?: (message: ChatMessage, emoji: string) => void;
}) {
  const [reactingTo, setReactingTo] = useState<number | null>(null);

  // A reaction is not a message of its own: it sits on the one it is to.
  const reactions = new Map<number, { hers?: string; ours?: string }>();
  // Which button she tapped on each order's confirmation, and her last tap.
  const tappedOn = new Map<string, string>();
  const lastTap = new Map<string, number>();
  for (const message of messages) {
    if (message.kind === "reaction" && message.reply_to) {
      const on = reactions.get(message.reply_to.id) ?? {};
      if (message.direction === "in") on.hers = message.body ?? undefined;
      else on.ours = message.body ?? undefined;
      reactions.set(message.reply_to.id, on);
    }
    if (message.kind === "button" && message.tapped && message.order_id) {
      tappedOn.set(message.order_id, message.tapped);
      lastTap.set(message.order_id, message.id);
    }
  }
  const orderById = new Map(orders.map((order) => [order.order_id, order]));

  let day = "";
  let saidImported = false;

  return (
    <>
      {messages.map((message) => {
        if (message.kind === "reaction") return null;
        const marks = [];
        if (message.at && dayKey(message.at) !== day) {
          day = dayKey(message.at);
          marks.push(
            <span key={`day-${message.id}`} className="inbox-day">
              {dayMark(message.at, now)}
            </span>,
          );
        }
        if (message.origin === "imported" && !saidImported) {
          saidImported = true;
          marks.push(
            <div key={`imported-${message.id}`} className="inbox-note">
              Brought over from the old inbox. Who sent each reply was not recorded there.
            </div>,
          );
        }

        // A tap that was believed is an event in the chat, not a message.
        if (message.kind === "button" && message.tapped) {
          const order = message.order_id ? orderById.get(message.order_id) : undefined;
          // "Now" is only true of her last tap, and only while it still stands.
          const tagNow =
            order && order.answer === message.tapped && lastTap.get(order.order_id) === message.id
              ? order.tag
              : null;
          return (
            <Fragment key={message.id}>
              {marks}
              <div
                className={found === message.id ? "inbox-note inbox-msg--found" : "inbox-note"}
                data-message={message.id}
              >
                {customer} tapped {BUTTON_FOR[message.tapped] ?? message.tapped}
                {tagNow ? ` · the order is now tagged ${tagNow}` : order?.order ? ` · ${order.order}` : ""}
              </div>
            </Fragment>
          );
        }

        const out = message.direction === "out";
        const failed = message.status === "failed";
        const tick = out ? TICK[message.status] : undefined;
        const on = reactions.get(message.id);
        // Only a message WhatsApp holds can be answered or reacted to.
        const reachable = message.direction === "in" || Boolean(tick);
        const isMedia = message.kind in WHAT;
        const picked = message.order_id ? tappedOn.get(message.order_id) : undefined;

        return (
          <Fragment key={message.id}>
            {marks}
            <div
              className={[
                "inbox-msg",
                out ? "inbox-msg--out" : "inbox-msg--in",
                failed && "inbox-msg--failed",
                found === message.id && "inbox-msg--found",
              ]
                .filter(Boolean)
                .join(" ")}
              // Not a stop for the Tab key, but a tap on a phone lands here,
              // which is what brings up Reply and React.
              tabIndex={-1}
              data-message={message.id}
            >
              {out ? (
                <span className="inbox-msg__who">{whoSent(message)}</span>
              ) : (
                <span className="visually-hidden">{customer}: </span>
              )}
              {message.reply_to && (
                <div className="inbox-msg__quote" dir="auto">
                  <span className="visually-hidden">In reply to: </span>
                  {message.reply_to.body || WHAT[message.reply_to.kind] || "A message"}
                </div>
              )}
              {isMedia && <Media message={message} customer={customer} />}
              {message.kind === "unsupported" ? (
                <p className="inbox-msg__cannot">A message this inbox cannot show</p>
              ) : (
                message.body && (
                  <p dir="auto">
                    <Marked text={message.body} words={marked} />
                  </p>
                )
              )}
              {message.buttons && message.buttons.length > 0 && (
                <div className="inbox-msg__btns">
                  {message.buttons.map((label) => {
                    const hers = picked !== undefined && BUTTON_FOR[picked] === label;
                    return (
                      <span key={label} className={hers ? "inbox-msg__picked" : undefined}>
                        {label}
                        {hers && <span className="visually-hidden"> (tapped)</span>}
                      </span>
                    );
                  })}
                </div>
              )}
              <div className="inbox-msg__meta">
                {message.at ? clockTime(message.at) : ""}
                {out && message.status === "queued" && (
                  <span className="inbox-msg__tick" role="img" aria-label="Sending">
                    <OpsIcon name="clock" />
                  </span>
                )}
                {tick && (
                  <span
                    className={
                      message.status === "read" ? "inbox-msg__tick inbox-msg__tick--read" : "inbox-msg__tick"
                    }
                    role="img"
                    aria-label={tick.words}
                  >
                    <InboxIcon name={tick.icon} />
                  </span>
                )}
              </div>
              {(on?.hers || on?.ours) && (
                <div className="inbox-msg__reactions">
                  {on.hers && (
                    <span title={`${customer} reacted`}>
                      {on.hers}
                      <span className="visually-hidden"> from {customer}</span>
                    </span>
                  )}
                  {on.ours && (
                    <span title="The team reacted">
                      {on.ours}
                      <span className="visually-hidden"> from the team</span>
                    </span>
                  )}
                </div>
              )}
              {canSend && reachable && (onReply || onReact) && (
                <div className="inbox-msg__tools">
                  {onReply && (
                    <button
                      type="button"
                      className="inbox-toolbtn"
                      aria-label="Reply to this message"
                      onClick={() => onReply(message)}
                    >
                      <InboxIcon name="reply" />
                    </button>
                  )}
                  {onReact && (
                    <button
                      type="button"
                      className="inbox-toolbtn"
                      aria-label="React to this message"
                      aria-expanded={reactingTo === message.id}
                      onClick={() => setReactingTo(reactingTo === message.id ? null : message.id)}
                    >
                      <InboxIcon name="smile" />
                    </button>
                  )}
                  {onReact && reactingTo === message.id && (
                    <div className="inbox-reactions" role="group" aria-label="React with">
                      {REACTIONS.map((emoji) => (
                        <button
                          key={emoji}
                          type="button"
                          aria-pressed={on?.ours === emoji}
                          onClick={() => {
                            setReactingTo(null);
                            // The one already given, pressed again, is taken back.
                            onReact(message, on?.ours === emoji ? "" : emoji);
                          }}
                        >
                          {emoji}
                        </button>
                      ))}
                    </div>
                  )}
                </div>
              )}
            </div>
            {failed && (
              <div className="inbox-failed">
                <OpsIcon name="alert" />
                Not sent: {message.error || "WhatsApp did not take it."}
                {onRetry && message.kind === "text" && message.body && (
                  <button type="button" className="ops-linkbtn" onClick={() => onRetry(message)}>
                    Try again
                  </button>
                )}
              </div>
            )}
          </Fragment>
        );
      })}
    </>
  );
}
