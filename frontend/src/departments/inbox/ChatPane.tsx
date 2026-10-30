import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import type { KeyboardEvent } from "react";
import { Link } from "react-router-dom";

import { ApiError, api } from "../lib/api";
import { chatName, formatPhone, orderStatus } from "../lib/inbox";
import type { ChatMessage, ConversationDetail } from "../lib/inbox";
import { ChatComposer } from "./ChatComposer";
import { ChatMessages } from "./ChatMessages";
import { ChatOrderPanel } from "./ChatOrderPanel";
import type { Template } from "./ChatTemplates";
import { InboxIcon } from "./InboxIcon";
import { clockTime, dayMonth, useIsNarrow, useNow } from "./OpsSource";

/** New messages and ticks show within this long. Not read while hidden. */
const CHAT_EVERY_MS = 4_000;
/** Closer to the newest message than this, the chat follows new ones down. */
const NEAR_END_PX = 120;

type MessagePage = { messages: ChatMessage[]; earlier: string | null };
type SearchFound = { matches: { id: number }[]; more: boolean };

/** A search inside the chat is asked this long after the last key. */
const SEARCH_AFTER_MS = 300;
/** Pages read above what is loaded, at most, to reach a match. */
const MOST_PAGES_TO_A_MATCH = 50;

function inOrder(a: ChatMessage, b: ChatMessage): number {
  const byTime = new Date(a.at ?? 0).getTime() - new Date(b.at ?? 0).getTime();
  return byTime || a.id - b.id;
}

/** `fresh` laid over `loaded`: a message already held is replaced, a new one added. */
function merged(loaded: ChatMessage[], fresh: ChatMessage[]): ChatMessage[] {
  const byId = new Map(loaded.map((message) => [message.id, message]));
  for (const message of fresh) byId.set(message.id, message);
  return [...byId.values()].sort(inOrder);
}

function newestFromHer(messages: ChatMessage[]): number {
  return messages.reduce(
    (newest, message) => (message.direction === "in" ? Math.max(newest, message.id) : newest),
    0,
  );
}

/** "can reply freely until 14:21 tomorrow", or why not. */
function windowWords(closesAt: string | null, open: boolean, now: number): string {
  if (!closesAt) return "has not written yet";
  if (!open) return `free replies closed ${dayMonth(closesAt)}, ${clockTime(closesAt)}`;
  const today = dayMonth(closesAt) === dayMonth(new Date(now).toISOString());
  return `can reply freely until ${clockTime(closesAt)} ${today ? "today" : "tomorrow"}`;
}

/**
 * The open chat and the order beside it (ADR 0059; the approved mockup's
 * frames 1, 2 and 7).
 *
 * The chat is read at its newest page and again every few seconds, so a new
 * message and a tick turning blue show without a reload. Earlier pages are
 * read as the top is reached.
 */
export function ChatPane({
  conversationId,
  onChanged,
}: {
  conversationId: number;
  /** Something the list shows has changed: read, answered, replied to. */
  onChanged: () => void;
}) {
  const [detail, setDetail] = useState<ConversationDetail | null>(null);
  const [messages, setMessages] = useState<ChatMessage[] | null>(null);
  const [earlier, setEarlier] = useState<string | null>(null);
  const [readingEarlier, setReadingEarlier] = useState(false);
  const [missing, setMissing] = useState(false);
  const [failed, setFailed] = useState(false);
  const [orderOpen, setOrderOpen] = useState(false);
  const [replyTo, setReplyTo] = useState<ChatMessage | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const [announced, setAnnounced] = useState("");
  // Searching inside the chat: what is typed, what the server found for it
  // (newest first), and which of those is on screen.
  const [searchOpen, setSearchOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [found, setFound] = useState<SearchFound | null>(null);
  const [foundFor, setFoundFor] = useState("");
  const [onMatch, setOnMatch] = useState(0);
  const [searchProblem, setSearchProblem] = useState<string | null>(null);
  const now = useNow();
  const narrow = useIsNarrow();

  const held = useRef<ChatMessage[]>([]);
  const heardFromHer = useRef<number | null>(null);
  const thread = useRef<HTMLDivElement | null>(null);
  // Whether to follow the newest message down, and how tall the chat was
  // before earlier messages were put above what is on screen.
  const follow = useRef(true);
  const heightBefore = useRef<number | null>(null);
  // The page marker above what is loaded, read inside a loop that outlives
  // one render.
  const earlierRef = useRef<string | null>(null);
  earlierRef.current = earlier;
  const scrollTo = useRef<number | null>(null);
  const searchBox = useRef<HTMLInputElement | null>(null);
  const searchButton = useRef<HTMLButtonElement | null>(null);
  const changed = useRef(onChanged);
  changed.current = onChanged;

  const readDetail = useCallback(
    () =>
      api
        .get<ConversationDetail>(`/api/inbox/conversations/${conversationId}`)
        .then(setDetail)
        .catch((error) => {
          if (error instanceof ApiError && error.status === 404) setMissing(true);
        }),
    [conversationId],
  );

  /** She has been read: the count clears here, and her ticks turn blue. */
  const markRead = useCallback(
    () =>
      api
        .post<ConversationDetail>(`/api/inbox/conversations/${conversationId}/read`)
        .then((read) => {
          setDetail(read);
          changed.current();
        })
        .catch(() => undefined),
    [conversationId],
  );

  const readNewest = useCallback(
    () =>
      api
        .get<MessagePage>(`/api/inbox/conversations/${conversationId}/messages`)
        .then((page) => {
          const first = heardFromHer.current === null;
          if (first) setEarlier(page.earlier);
          held.current = merged(held.current, page.messages);
          setMessages(held.current);
          setFailed(false);

          const fromHer = newestFromHer(held.current);
          if (first) {
            heardFromHer.current = fromHer;
          } else if (fromHer > (heardFromHer.current ?? 0)) {
            heardFromHer.current = fromHer;
            setAnnounced("A new message arrived.");
            // Read as it arrives, while somebody is looking at it.
            if (!document.hidden) void markRead();
            else void readDetail();
          }
        })
        .catch((error) => {
          if (error instanceof ApiError && error.status === 404) setMissing(true);
          else setFailed(true);
        }),
    [conversationId, markRead, readDetail],
  );

  useEffect(() => {
    api
      .get<ConversationDetail>(`/api/inbox/conversations/${conversationId}`)
      .then((found) => {
        setDetail(found);
        if (found.unread_count > 0) void markRead();
      })
      .catch((error) => {
        if (error instanceof ApiError && error.status === 404) setMissing(true);
        else setFailed(true);
      });
    void readNewest();
    const timer = window.setInterval(() => {
      if (!document.hidden) void readNewest();
    }, CHAT_EVERY_MS);
    return () => window.clearInterval(timer);
  }, [conversationId, markRead, readNewest]);

  // A chat opens at its newest message and stays there as more arrive,
  // unless somebody has scrolled up to read. Earlier messages go in above
  // without moving what is on screen.
  useLayoutEffect(() => {
    const box = thread.current;
    if (!box) return;
    if (heightBefore.current !== null) {
      box.scrollTop += box.scrollHeight - heightBefore.current;
      heightBefore.current = null;
    } else if (follow.current) {
      box.scrollTop = box.scrollHeight;
    }
    // Also when the chat's heading arrives: the messages are drawn only once
    // both are in, whichever came first.
  }, [messages, detail]);

  // The box under the chat grows - a second line typed, a refusal shown - and
  // the chat above it shrinks. The newest message stays in view when it does.
  useEffect(() => {
    const box = thread.current;
    if (!box || typeof ResizeObserver !== "function") return;
    const watcher = new ResizeObserver(() => {
      if (follow.current) box.scrollTop = box.scrollHeight;
    });
    watcher.observe(box);
    return () => watcher.disconnect();
  }, []);

  const readEarlier = useCallback(() => {
    if (!earlier || readingEarlier) return;
    setReadingEarlier(true);
    api
      .get<MessagePage>(`/api/inbox/conversations/${conversationId}/messages?before=${encodeURIComponent(earlier)}`)
      .then((page) => {
        heightBefore.current = thread.current?.scrollHeight ?? null;
        held.current = merged(held.current, page.messages);
        setMessages(held.current);
        setEarlier(page.earlier);
      })
      .catch(() => undefined)
      .finally(() => setReadingEarlier(false));
  }, [conversationId, earlier, readingEarlier]);

  // Asked of the server, not of what is on screen: a match pages above what
  // is loaded is still found, and then loaded to be shown.
  useEffect(() => {
    if (!searchOpen) return;
    const words = query.trim();
    if (words.length < 2) {
      setFound(null);
      setFoundFor("");
      setSearchProblem(null);
      return;
    }
    let current = true;
    const timer = window.setTimeout(() => {
      api
        .get<SearchFound>(
          `/api/inbox/conversations/${conversationId}/search?q=${encodeURIComponent(words)}`,
        )
        .then((result) => {
          if (!current) return;
          setFound(result);
          setFoundFor(words);
          setSearchProblem(null);
          setOnMatch(0);
          if (result.matches.length > 0) void showMatch(result.matches[0].id);
        })
        .catch((error) => {
          if (current) {
            setSearchProblem(error instanceof ApiError ? error.message : "Couldn't search this chat.");
          }
        });
    }, SEARCH_AFTER_MS);
    return () => {
      current = false;
      window.clearTimeout(timer);
    };
    // showMatch reads only refs and stable setters.
  }, [conversationId, query, searchOpen]);

  /** Read earlier pages until the message is loaded, then bring it into view. */
  async function showMatch(id: number) {
    follow.current = false;
    let pages = 0;
    while (!held.current.some((message) => message.id === id) && earlierRef.current) {
      if (pages++ >= MOST_PAGES_TO_A_MATCH) break;
      try {
        const page = await api.get<MessagePage>(
          `/api/inbox/conversations/${conversationId}/messages?limit=100&before=${encodeURIComponent(earlierRef.current)}`,
        );
        held.current = merged(held.current, page.messages);
        earlierRef.current = page.earlier;
        setEarlier(page.earlier);
      } catch {
        break;
      }
    }
    scrollTo.current = id;
    setMessages([...held.current]);
  }

  // A match that has just been loaded or stepped to is brought to the middle.
  useEffect(() => {
    const id = scrollTo.current;
    const box = thread.current;
    if (id === null || !box) return;
    const bubble = box.querySelector<HTMLElement>(`[data-message="${id}"]`);
    if (!bubble) return;
    scrollTo.current = null;
    follow.current = false;
    bubble.scrollIntoView?.({ block: "center" });
  }, [messages]);

  function step(by: number) {
    if (!found || found.matches.length === 0) return;
    const next = (onMatch + by + found.matches.length) % found.matches.length;
    setOnMatch(next);
    void showMatch(found.matches[next].id);
  }

  function openSearch() {
    setSearchOpen(true);
    window.setTimeout(() => searchBox.current?.focus(), 0);
  }

  function closeSearch() {
    setSearchOpen(false);
    setQuery("");
    setFound(null);
    setFoundFor("");
    setSearchProblem(null);
    searchButton.current?.focus();
  }

  function onSearchKey(event: KeyboardEvent<HTMLInputElement>) {
    if (event.key === "Escape") {
      event.preventDefault();
      closeSearch();
    } else if (event.key === "Enter") {
      event.preventDefault();
      // Enter goes back in time, as the list of matches does; Shift goes forward.
      step(event.shiftKey ? -1 : 1);
    }
  }

  function onScroll() {
    const box = thread.current;
    if (!box) return;
    follow.current = box.scrollHeight - box.scrollTop - box.clientHeight < NEAR_END_PX;
    if (box.scrollTop < 40) readEarlier();
  }

  function took(message: ChatMessage) {
    held.current = merged(held.current, [message]);
    follow.current = true;
    setMessages(held.current);
    changed.current();
  }

  async function send(body: string, answering: ChatMessage | null): Promise<string | null> {
    try {
      const sent = await api.post<ChatMessage>(`/api/inbox/conversations/${conversationId}/messages`, {
        body,
        reply_to: answering?.id ?? null,
      });
      took(sent);
      setReplyTo(null);
      return null;
    } catch (error) {
      return error instanceof ApiError ? error.message : "That could not be sent. Try again.";
    }
  }

  /** A photo, a video, a document, or a voice note just recorded. */
  async function sendFile(
    file: Blob,
    options: { filename: string; caption: string; voice: boolean },
  ): Promise<string | null> {
    try {
      const sent = await api.upload<ChatMessage>(`/api/inbox/conversations/${conversationId}/media`, file, {
        field: "upload",
        filename: options.filename,
        fields: { caption: options.caption, voice: options.voice ? "true" : "false" },
      });
      took(sent);
      return null;
    } catch (error) {
      return error instanceof ApiError ? error.message : "That file could not be sent. Try again.";
    }
  }

  /** One of the approved messages: the way to reach her after her 24 hours. */
  async function sendTemplate(template: Template): Promise<string | null> {
    try {
      const sent = await api.post<ChatMessage>(`/api/inbox/conversations/${conversationId}/template`, {
        name: template.name,
        language: template.language,
      });
      took(sent);
      return null;
    } catch (error) {
      return error instanceof ApiError ? error.message : "That message could not be sent. Try again.";
    }
  }

  async function react(message: ChatMessage, emoji: string) {
    setProblem(null);
    try {
      const sent = await api.post<ChatMessage>(`/api/inbox/conversations/${conversationId}/reactions`, {
        message_id: message.id,
        emoji,
      });
      took(sent);
    } catch (error) {
      setProblem(error instanceof ApiError ? error.message : "The reaction could not be sent.");
    }
  }

  /** "2 of 5", "No message holds that", or nothing while there is nothing to say. */
  function searchWords(): string {
    if (searchProblem) return searchProblem;
    if (!found || query.trim() !== foundFor) return "";
    if (found.matches.length === 0) return "No message holds that";
    return `${onMatch + 1} of ${found.matches.length}${found.more ? "+" : ""}`;
  }

  if (missing) {
    return (
      <section className="inbox-col inbox-col--none" aria-label="Chat">
        <div className="inbox-empty">
          <InboxIcon name="search" />
          <span>
            There is no chat at this address. <Link to="/inbox/chats">Back to chats</Link>
          </span>
        </div>
      </section>
    );
  }

  const name = detail ? chatName(detail) : "";
  // Her first name where she has one: "Nour tapped Edit".
  const customer = detail?.name?.trim().split(/\s+/)[0] || name || "The customer";
  const windowOpen = Boolean(
    detail?.window_closes_at && new Date(detail.window_closes_at).getTime() > now,
  );
  const order = detail?.orders[0];
  const under = !detail
    ? ""
    : narrow && order
      ? `${order.order ?? order.order_id} · ${orderStatus(order).words}`
      : `${detail.name?.trim() ? `${formatPhone(detail.phone)} · ` : ""}${windowWords(detail.window_closes_at, windowOpen, now)}`;

  return (
    <>
      <section className="inbox-col inbox-col--chat" aria-label={name ? `Chat with ${name}` : "Chat"}>
        <div className="inbox-col__head">
          <div className="inbox-chathead">
            <Link className="inbox-back" to="/inbox/chats" aria-label="Back to chats">
              <InboxIcon name="left" />
            </Link>
            <div>
              <h2 dir="auto">{name || "…"}</h2>
              {detail && <small>{under}</small>}
            </div>
          </div>
          <div className="inbox-chathead__tools">
            <button
              type="button"
              ref={searchButton}
              className="inbox-iconbtn"
              aria-label="Search in this chat"
              aria-expanded={searchOpen}
              aria-controls="inbox-chatsearch"
              onClick={() => (searchOpen ? closeSearch() : openSearch())}
            >
              <InboxIcon name="search" />
            </button>
            <button
              type="button"
              className="inbox-btn inbox-btn--quiet inbox-btn--small inbox-orderbtn"
              aria-expanded={orderOpen}
              aria-controls="inbox-order-panel"
              onClick={() => setOrderOpen(!orderOpen)}
            >
              Order
            </button>
          </div>
        </div>

        {searchOpen && (
          <div className="inbox-chatsearch" id="inbox-chatsearch" role="search">
            <label className="inbox-search">
              <span className="visually-hidden">Search in this chat</span>
              <InboxIcon name="search" />
              <input
                ref={searchBox}
                type="search"
                dir="auto"
                maxLength={120}
                placeholder="Search in this chat"
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                onKeyDown={onSearchKey}
              />
            </label>
            <span className="inbox-chatsearch__count" role="status">
              {searchWords()}
            </span>
            <button
              type="button"
              className="inbox-iconbtn"
              aria-label="Earlier match"
              disabled={!found || found.matches.length < 2}
              onClick={() => step(1)}
            >
              <InboxIcon name="up" />
            </button>
            <button
              type="button"
              className="inbox-iconbtn"
              aria-label="Later match"
              disabled={!found || found.matches.length < 2}
              onClick={() => step(-1)}
            >
              <InboxIcon name="down" />
            </button>
            <button type="button" className="inbox-iconbtn" aria-label="Close the search" onClick={closeSearch}>
              <InboxIcon name="close" />
            </button>
          </div>
        )}

        <div
          className="inbox-thread"
          ref={thread}
          onScroll={onScroll}
          tabIndex={0}
          role="group"
          aria-label="Messages"
        >
          {earlier && (
            <button
              type="button"
              className="ops-linkbtn inbox-thread__earlier"
              disabled={readingEarlier}
              onClick={readEarlier}
            >
              {readingEarlier ? "Loading earlier messages…" : "Show earlier messages"}
            </button>
          )}
          {messages === null && !failed && <p className="loading">Loading…</p>}
          {failed && messages === null && (
            <p className="notice notice--refused" role="alert">
              Couldn't load this chat.{" "}
              <button type="button" className="ops-linkbtn" onClick={() => void readNewest()}>
                Try again
              </button>
            </p>
          )}
          {messages !== null && messages.length === 0 && (
            <div className="inbox-note">No messages yet.</div>
          )}
          {messages !== null && detail && (
            <ChatMessages
              messages={messages}
              orders={detail.orders}
              customer={customer}
              now={now}
              canSend={windowOpen}
              found={searchOpen && found?.matches[onMatch] ? found.matches[onMatch].id : null}
              marked={searchOpen ? foundFor : undefined}
              onRetry={(message) => void send(message.body ?? "", null).then(setProblem)}
              onReply={setReplyTo}
              onReact={(message, emoji) => void react(message, emoji)}
            />
          )}
        </div>
        <p className="visually-hidden" role="status">
          {announced}
        </p>

        {problem && (
          <p className="notice notice--refused inbox-composer__problem" role="alert">
            {problem}
          </p>
        )}
        {detail && (
          <ChatComposer
            windowOpen={windowOpen}
            replyTo={replyTo}
            onCancelReply={() => setReplyTo(null)}
            onSend={(body) => send(body, replyTo)}
            onSendFile={sendFile}
            onSendTemplate={sendTemplate}
          />
        )}
      </section>

      <aside
        id="inbox-order-panel"
        className={
          orderOpen ? "inbox-col inbox-col--order inbox-col--order-open" : "inbox-col inbox-col--order"
        }
        aria-label="Order"
      >
        {narrow && (
          <div className="inbox-col__head">
            <h2>Order</h2>
            <button
              type="button"
              className="inbox-iconbtn"
              aria-label="Close the order"
              onClick={() => setOrderOpen(false)}
            >
              <InboxIcon name="close" />
            </button>
          </div>
        )}
        {detail && (
          <ChatOrderPanel
            orders={detail.orders}
            now={now}
            onAnswered={() => {
              void readDetail();
              changed.current();
            }}
          />
        )}
      </aside>
    </>
  );
}
