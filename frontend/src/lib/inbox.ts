/**
 * Small things both Inbox screens say the same way (ADR 0059).
 */

import { clockTime, dayAndTime, dayMonth } from "../components/OpsSource";

/**
 * "+20 100 555 0188" from the stored "201005550188".
 *
 * Only an Egyptian mobile is grouped; anything else is shown as its digits
 * with a plus, rather than grouped by a rule that may not be its own.
 */
export function formatPhone(phone: string | null): string {
  const digits = (phone ?? "").replace(/\D/g, "");
  if (!digits) return "";
  const egyptian = /^20(1\d{2})(\d{3})(\d{4})$/.exec(digits);
  if (egyptian) return `+20 ${egyptian[1]} ${egyptian[2]} ${egyptian[3]}`;
  return `+${digits}`;
}

/** Whether two moments fall on the same day in Cairo. */
function sameDay(iso: string, now: number): boolean {
  return dayMonth(iso) === dayMonth(new Date(now).toISOString())
    && Math.abs(now - new Date(iso).getTime()) < 36 * 3_600_000;
}

/** "Today, 12:40" or "10 Oct, 19:55", Cairo time. */
export function dayTimeLabel(iso: string, now: number): string {
  return sameDay(iso, now) ? `Today, ${clockTime(iso)}` : dayAndTime(iso);
}

/**
 * When a chat last moved, as the list shows it: "14:21" today, "Yesterday",
 * then "8 Oct".
 */
export function listTime(iso: string, now: number): string {
  if (sameDay(iso, now)) return clockTime(iso);
  if (sameDay(iso, now - 24 * 3_600_000)) return "Yesterday";
  return dayMonth(iso);
}

const LONG_DAY = new Intl.DateTimeFormat("en-US", {
  timeZone: "Africa/Cairo",
  day: "numeric",
  month: "long",
  year: "numeric",
});

function longParts(moment: Date): Record<string, string> {
  return Object.fromEntries(LONG_DAY.formatToParts(moment).map((part) => [part.type, part.value]));
}

/** A chat's day mark: "Today", "Yesterday", "8 October", "8 October 2025". */
export function dayMark(iso: string, now: number): string {
  if (sameDay(iso, now)) return "Today";
  if (sameDay(iso, now - 24 * 3_600_000)) return "Yesterday";
  const parts = longParts(new Date(iso));
  return parts.year === longParts(new Date(now)).year
    ? `${parts.day} ${parts.month}`
    : `${parts.day} ${parts.month} ${parts.year}`;
}

/** The day a moment falls on in Cairo, for telling one day's messages from the next. */
export function dayKey(iso: string): string {
  const parts = longParts(new Date(iso));
  return `${parts.year}-${parts.month}-${parts.day}`;
}

/** What an order's answer is called on screen. */
export const ANSWER_WORDS: Record<string, string> = {
  confirmed: "Confirmed",
  edit: "Wants a change",
  cancelled: "Asked to cancel",
};

// ── What the server sends (app/services/inbox/chats.py) ─────────────────────

/** A conversation as the list and a chat's heading show it. */
export type Conversation = {
  id: number;
  /** Digits only, country code first: "201005550188". */
  phone: string;
  name: string | null;
  last_message_at: string | null;
  last_preview: string | null;
  last_direction: "in" | "out" | null;
  unread_count: number;
  /** Whether a free reply may be typed right now, and until when. */
  window_open: boolean;
  window_closes_at: string | null;
  /** Her most recent order's answer. */
  answer: string | null;
};

/** One order's confirmation, beside the chat. */
export type ChatOrder = {
  order_id: string;
  order: string | null;
  admin_url: string | null;
  state: string;
  answer: string | null;
  answered_at: string | null;
  placed_at: string | null;
  sent_at: string | null;
  total: string | null;
  /** The one tag the order carries in Shopify for this. */
  tag: string | null;
  why: string | null;
  can_send_again: boolean;
  /** The platform's tags as Shopify really has them, once read (ADR 0063). */
  shopify_tags?: string | null;
  tags_read_at?: string | null;
  /** Where the answer was given: "whatsapp", "inbox" or "shopify". */
  answered_in?: string | null;
  /** "payment" for an unpaid international order's payment link (ADR 0062). */
  kind?: "confirmation" | "payment";
  country?: string | null;
  paid_at?: string | null;
  reminded_at?: string | null;
  /** Unpaid three days after the link went out. */
  needs_a_person?: boolean;
  invoice_at?: string | null;
  invoice_error?: string | null;
};

export type ConversationDetail = Conversation & { orders: ChatOrder[] };

export type ChatMedia = {
  id: number;
  state: "pending" | "stored" | "gone" | "failed";
  mime_type: string | null;
  filename: string | null;
  size_bytes: number | null;
  /** Only once our own copy is kept. */
  url: string | null;
  /** Not kept, and WhatsApp still holds it: staff may ask for it again. */
  can_try_again?: boolean;
};

/** What asking WhatsApp again for a file came to. */
export type TriedAgain = Pick<ChatMedia, "state" | "url" | "can_try_again"> & { problem: string | null };

export type ChatMessage = {
  id: number;
  direction: "in" | "out";
  kind:
    | "text" | "image" | "audio" | "video" | "document" | "sticker"
    | "template" | "button" | "reaction" | "unsupported";
  body: string | null;
  status: "received" | "queued" | "sent" | "delivered" | "read" | "failed";
  error: string | null;
  origin: "customer" | "staff" | "automatic" | "imported";
  sender: string | null;
  reply_to: { id: number; direction: "in" | "out"; kind: string; body: string | null } | null;
  template: string | null;
  buttons: string[] | null;
  /** Her answer, when this is a tap that was believed. */
  tapped: string | null;
  voice: boolean;
  order_id: string | null;
  at: string | null;
  media: ChatMedia | null;
};

/** Whether WhatsApp is connected, sending and being heard from. */
export type InboxHealth = {
  connected: boolean;
  sending: boolean;
  last_heard_at: string | null;
  quiet_since: string | null;
};

/** Who a conversation is with: her name, or her number when she has none. */
export function chatName(chat: { name: string | null; phone: string }): string {
  return chat.name?.trim() || formatPhone(chat.phone);
}

/** Where an order's confirmation stands, in a few words and a tone. */
export function orderStatus(order: {
  state: string;
  answer: string | null;
  kind?: string;
  paid_at?: string | null;
  needs_a_person?: boolean;
}): {
  words: string;
  tone: "settled" | "owed" | "refused" | "plain";
} {
  if (order.kind === "payment") {
    if (order.paid_at) return { words: "Paid", tone: "settled" };
    if (order.needs_a_person) return { words: "Unpaid for 3 days", tone: "owed" };
    if (order.state === "sent") return { words: "Payment link sent", tone: "plain" };
  }
  if (order.answer === "confirmed") return { words: ANSWER_WORDS.confirmed, tone: "settled" };
  if (order.answer === "edit") return { words: ANSWER_WORDS.edit, tone: "owed" };
  if (order.answer === "cancelled") return { words: ANSWER_WORDS.cancelled, tone: "refused" };
  if (order.state === "sent") return { words: "Waiting for an answer", tone: "plain" };
  if (order.state === "no_whatsapp") return { words: "No WhatsApp", tone: "owed" };
  if (order.state === "pending" || order.state === "sending") return { words: "Being sent", tone: "plain" };
  return { words: "Not sent", tone: "owed" };
}

/** "EGP 1,450" from the stored "1450.00". A payment request's amount
 * already says its currency ("EGP 5,850.00") and is shown as it is. */
export function totalLabel(total: string | null): string {
  if (!total) return "—";
  if (/^[A-Z]{3} /.test(total)) return total;
  const amount = Number(total.replace(/[^\d.]/g, ""));
  if (!Number.isFinite(amount) || !/\d/.test(total)) return total;
  return `EGP ${amount.toLocaleString("en-US", { maximumFractionDigits: 2 })}`;
}
