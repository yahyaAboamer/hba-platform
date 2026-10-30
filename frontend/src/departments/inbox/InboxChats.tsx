import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";

import { ChatPane } from "../components/ChatPane";
import { InboxIcon } from "../components/InboxIcon";
import type { InboxIconName } from "../components/InboxIcon";
import { useInbox } from "../components/InboxLayout";
import { OpsIcon, age, clockTime, useNow } from "../components/OpsSource";
import { api } from "../lib/api";
import { chatName, listTime } from "../lib/inbox";
import type { Conversation, InboxHealth } from "../lib/inbox";
import "./OperationsDashboard.css";
import "./Inbox.css";

/**
 * Inbox → Chats (ADR 0059; the approved mockup
 * `docs/design/whatsapp-inbox-2026-10-11.html`, frames 1, 2 and 7).
 *
 * Three columns on a laptop: every conversation, the open chat, the
 * customer's order. On a phone one at a time: the list, then the chat with
 * its own way back.
 *
 * The list is read a page at a time and again every few seconds, so a new
 * message shows without a reload and the thousandth chat costs what the
 * first does.
 */

/** New messages show within this long. Not read while the tab is hidden. */
const LIST_EVERY_MS = 5_000;
const HEALTH_EVERY_MS = 60_000;
const SEARCH_AFTER_MS = 300;

const VIEWS = [
  { key: "all", label: "All", count: null },
  { key: "unread", label: "Unread", count: "unread" },
  { key: "edit", label: "Wants a change", count: "edit" },
  { key: "cancelled", label: "Cancelled", count: null },
] as const;
type ViewKey = (typeof VIEWS)[number]["key"];

type Counts = { all: number; unread: number; edit: number };
type Page = { conversations: Conversation[]; next: string | null; counts: Counts };

const EMPTY: Record<ViewKey, string> = {
  all: "No chats yet. One appears here when a customer writes, or a confirmation is sent.",
  unread: "Nothing unread.",
  edit: "Nobody is waiting on a change.",
  cancelled: "Nobody has asked to cancel.",
};

function movedAt(chat: Conversation): number {
  return chat.last_message_at ? new Date(chat.last_message_at).getTime() : 0;
}

/**
 * The chats already loaded that still belong below a fresh first page.
 *
 * One that would now sort inside the first page and is not in it has left
 * this view - read, answered, no longer matching - and is dropped.
 */
function olderThan(page: Page, loaded: Conversation[]): Conversation[] {
  const last = page.conversations[page.conversations.length - 1];
  if (page.next === null || !last) return [];
  const inPage = new Set(page.conversations.map((chat) => chat.id));
  return loaded.filter(
    (chat) =>
      !inPage.has(chat.id) &&
      (movedAt(chat) < movedAt(last) || (movedAt(chat) === movedAt(last) && chat.id < last.id)),
  );
}

function useChatList(view: ViewKey, q: string) {
  const { setUnread } = useInbox();
  const [chats, setChats] = useState<Conversation[] | null>(null);
  const [counts, setCounts] = useState<Counts | null>(null);
  const [failed, setFailed] = useState(false);
  const [more, setMore] = useState<string | null>(null);
  const [readingMore, setReadingMore] = useState(false);
  // What is on screen, for merging a fresh page into it; and which view and
  // search it belongs to, so an answer to an older question is ignored.
  const held = useRef<Conversation[]>([]);
  const asked = useRef(0);

  const address = useCallback(
    (before?: string) => {
      const params = new URLSearchParams();
      if (view !== "all") params.set("view", view);
      if (q) params.set("q", q);
      if (before) params.set("before", before);
      const query = params.toString();
      return `/api/inbox/conversations${query ? `?${query}` : ""}`;
    },
    [view, q],
  );

  const readFirst = useCallback(() => {
    const question = asked.current;
    api
      .get<Page>(address())
      .then((page) => {
        if (question !== asked.current) return;
        const older = olderThan(page, held.current);
        held.current = [...page.conversations, ...older];
        setChats(held.current);
        // Only while nothing older is held is the first page's marker ours.
        if (older.length === 0) setMore(page.next);
        setCounts(page.counts);
        setUnread(page.counts.unread);
        setFailed(false);
      })
      .catch(() => {
        if (question === asked.current) setFailed(true);
      });
  }, [address, setUnread]);

  useEffect(() => {
    asked.current += 1;
    held.current = [];
    setChats(null);
    setMore(null);
    readFirst();
    const timer = window.setInterval(() => {
      if (!document.hidden) readFirst();
    }, LIST_EVERY_MS);
    return () => window.clearInterval(timer);
  }, [readFirst]);

  const readMore = useCallback(() => {
    if (!more || readingMore) return;
    const question = asked.current;
    setReadingMore(true);
    api
      .get<Page>(address(more))
      .then((page) => {
        if (question !== asked.current) return;
        const have = new Set(held.current.map((chat) => chat.id));
        held.current = [...held.current, ...page.conversations.filter((chat) => !have.has(chat.id))];
        setChats(held.current);
        setMore(page.next);
      })
      .catch(() => undefined)
      .finally(() => setReadingMore(false));
  }, [more, readingMore, address]);

  return { chats, counts, failed, more, readingMore, readMore, reload: readFirst };
}

function useHealth(): InboxHealth | null {
  const [health, setHealth] = useState<InboxHealth | null>(null);
  useEffect(() => {
    const read = () =>
      api
        .get<InboxHealth>("/api/inbox/health")
        .then(setHealth)
        .catch(() => undefined);
    read();
    const timer = window.setInterval(read, HEALTH_EVERY_MS);
    return () => window.clearInterval(timer);
  }, []);
  return health;
}

/** Whether the list is being kept up to date, and WhatsApp heard from. */
function Pulse({ health, failed, now }: { health: InboxHealth | null; failed: boolean; now: number }) {
  if (failed) {
    return (
      <p className="ops-fresh ops-fresh--failed" role="status">
        <OpsIcon name="alert" />
        Not updating
      </p>
    );
  }
  if (health && !health.connected) {
    return (
      <p className="ops-fresh" role="status" title="An admin connects WhatsApp in Settings.">
        <OpsIcon name="plug" />
        Not connected
      </p>
    );
  }
  if (health?.quiet_since) {
    return (
      <p className="ops-fresh ops-fresh--failed" role="status" title="New messages may not be arriving.">
        <OpsIcon name="alert" />
        WhatsApp quiet for {age(health.quiet_since, now)}
      </p>
    );
  }
  return (
    <p
      className="ops-fresh"
      role="status"
      title={
        health?.last_heard_at
          ? `WhatsApp was last heard from at ${clockTime(health.last_heard_at)}.`
          : undefined
      }
    >
      <OpsIcon name="clock" />
      Live
    </p>
  );
}

/** The list's second line: what was last said, and by whom. */
function lastLine(chat: Conversation): { icon: InboxIconName | null; words: string; ours: boolean } {
  const words = chat.last_preview ?? "";
  if (chat.last_direction === "out") return { icon: "tick", words: words || "Sent a file", ours: true };
  if (words === "Photo") return { icon: "image", words, ours: false };
  if (words === "Voice note") return { icon: "mic", words, ours: false };
  if (words === "Video" || words === "File") return { icon: "file", words, ours: false };
  return { icon: null, words, ours: false };
}

function ChatRow({ chat, open, now }: { chat: Conversation; open: boolean; now: number }) {
  const name = chatName(chat);
  const last = lastLine(chat);
  const unread = chat.unread_count > 0;
  return (
    <li>
      <Link
        to={`/inbox/chats/${chat.id}`}
        className={unread ? "inbox-chat inbox-chat--unread" : "inbox-chat"}
        aria-current={open ? "true" : undefined}
      >
        <span className="inbox-avatar" aria-hidden="true">
          {chat.name?.trim() ? name.charAt(0).toUpperCase() : "+"}
        </span>
        <span className="inbox-chat__name">{name}</span>
        <span className="inbox-chat__time">
          {chat.last_message_at ? listTime(chat.last_message_at, now) : ""}
        </span>
        <span className="inbox-chat__last">
          {last.icon && <InboxIcon name={last.icon} />}
          {last.ours && <span className="visually-hidden">Sent: </span>}
          <span className="inbox-chat__words">{last.words}</span>
        </span>
        {unread ? (
          <span className="inbox-chat__badge">
            {chat.unread_count}
            <span className="visually-hidden"> unread</span>
          </span>
        ) : chat.answer === "cancelled" ? (
          <span className="inbox-chat__flag">Cancel</span>
        ) : chat.answer === "edit" ? (
          <span className="inbox-chat__flag">Edit</span>
        ) : (
          <span />
        )}
      </Link>
    </li>
  );
}

export function InboxChats() {
  const { conversationId } = useParams();
  const openId = conversationId && /^\d+$/.test(conversationId) ? Number(conversationId) : null;

  const [view, setView] = useState<ViewKey>("all");
  const [typed, setTyped] = useState("");
  const [q, setQ] = useState("");
  const now = useNow();
  const health = useHealth();

  // Searched a moment after the typing stops, not on every letter.
  useEffect(() => {
    const timer = window.setTimeout(() => setQ(typed.trim()), SEARCH_AFTER_MS);
    return () => window.clearTimeout(timer);
  }, [typed]);

  const { chats, counts, failed, more, readingMore, readMore, reload } = useChatList(view, q);

  // Older chats load as the end of the list comes into view. The button is
  // there for a keyboard, and where the browser cannot watch for it.
  const end = useRef<HTMLLIElement | null>(null);
  useEffect(() => {
    const node = end.current;
    if (!node || !more || typeof IntersectionObserver !== "function") return;
    const watcher = new IntersectionObserver((seen) => {
      if (seen.some((entry) => entry.isIntersecting)) readMore();
    });
    watcher.observe(node);
    return () => watcher.disconnect();
  }, [more, readMore, chats]);

  return (
    <div className={openId === null ? "inbox" : "inbox inbox--open"}>
      <section className="inbox-col inbox-col--list" aria-label="Conversations">
        <div className="inbox-col__head">
          <div>
            <h1>Chats</h1>
            {counts && (
              <small>
                {counts.all.toLocaleString("en-US")}{" "}
                {counts.all === 1 ? "conversation" : "conversations"}
              </small>
            )}
          </div>
          <Pulse health={health} failed={failed} now={now} />
        </div>

        <label className="inbox-search">
          <span className="visually-hidden">Search chats</span>
          <InboxIcon name="search" />
          <input
            type="search"
            placeholder="Name, phone or order number"
            value={typed}
            maxLength={120}
            onChange={(event) => setTyped(event.target.value)}
          />
        </label>

        <div className="inbox-filters" role="group" aria-label="Show">
          {VIEWS.map((option) => {
            const count = option.count && counts ? counts[option.count] : 0;
            return (
              <button
                key={option.key}
                type="button"
                className="ops-chip"
                aria-pressed={view === option.key}
                onClick={() => setView(option.key)}
              >
                {option.label}
                {count > 0 ? ` · ${count}` : ""}
              </button>
            );
          })}
        </div>

        {failed && chats === null && (
          <p className="notice notice--refused inbox-notice" role="alert">
            Couldn't load the chats.{" "}
            <button type="button" className="ops-linkbtn" onClick={reload}>
              Try again
            </button>
          </p>
        )}

        {chats === null && !failed && <p className="loading inbox-notice">Loading…</p>}

        {chats !== null && chats.length === 0 && (
          <div className="inbox-empty">
            <InboxIcon name="search" />
            {q ? (
              <span>
                No chat matches “{q}”.
                <br />
                Check the number, or search by phone.
              </span>
            ) : (
              <span>{EMPTY[view]}</span>
            )}
          </div>
        )}

        {chats !== null && chats.length > 0 && (
          <ul className="inbox-chats">
            {chats.map((chat) => (
              <ChatRow key={chat.id} chat={chat} open={chat.id === openId} now={now} />
            ))}
            {more && (
              <li className="inbox-chats__more" ref={end}>
                <button type="button" className="ops-linkbtn" disabled={readingMore} onClick={readMore}>
                  {readingMore ? "Loading older chats…" : "Show older chats"}
                </button>
              </li>
            )}
          </ul>
        )}
      </section>

      {openId === null ? (
        <section className="inbox-col inbox-col--none" aria-label="Chat">
          <div className="inbox-empty">
            <InboxIcon name="template" />
            <span>Choose a chat to read it.</span>
          </div>
        </section>
      ) : (
        // Keyed by the chat, so nothing of the last one is carried into this.
        <ChatPane key={openId} conversationId={openId} onChanged={reload} />
      )}
    </div>
  );
}
