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
  /**
   * Where her delivery feedback stands, as the list marks it (ADR 0083):
   * `reopened` and `follow_up` need a person; `neutral` is an "It was okay".
   * A marker only - the chat's own `feedback` is an object (`ChatFeedback`).
   */
  feedback?: FeedbackMarker | null;
};

export type FeedbackMarker = "reopened" | "follow_up" | "neutral";

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

/**
 * Her answer to "how did your order go?", beside her chat (ADR 0083). The
 * newest one only; null when she was never asked.
 */
export type ChatFeedback = {
  id: number;
  order_name: string | null;
  asked_at: string | null;
  /** `sent`, or why it was not: `no_whatsapp`, `failed`, `would_send`, `pending`, `sending`. */
  state: string;
  rating: FeedbackRating | null;
  rated_at: string | null;
  reason: string | null;
  reason_title: string | null;
  comment: string | null;
  reorder: FeedbackReorder | null;
  step: FeedbackStep;
  needs_follow_up: boolean;
  resolved_at: string | null;
  resolved_by_name: string | null;
  /** Her answer to "was it solved?": null until she gives one. */
  solved: boolean | null;
  reopened_count: number;
  last_error: string | null;
  code: string | null;
  code_used: boolean;
};

export type ConversationDetail = Conversation & {
  orders: ChatOrder[];
  feedback?: ChatFeedback | null;
};

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
  /** A message the inbox cannot draw (kind `unsupported`): what it was, in words. */
  note?: string | null;
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


// ── Feedback after delivery (ADR 0083; app/modules/inbox/services/feedback.py) ─

export type FeedbackRating = "loved" | "okay" | "unhappy";
export type FeedbackReorder = "very_likely" | "maybe" | "unlikely";
export type FeedbackStep = "rating" | "reason" | "comment" | "support" | "solved" | "reorder" | "done";
export type FeedbackFollowUp = "needs_follow_up" | "resolved" | "reopened";

/** What her answer is called on screen. */
export const RATING_WORDS: Record<FeedbackRating, string> = {
  loved: "Loved it",
  okay: "It was okay",
  unhappy: "Not happy",
};

/** How likely she says she is to order again. */
export const REORDER_WORDS: Record<FeedbackReorder, string> = {
  very_likely: "Very likely",
  maybe: "Maybe",
  unlikely: "Unlikely",
};

/**
 * Why a question did not reach her, in a few words; null when it did.
 * A row whose question is still being sent says so rather than nothing.
 */
export function feedbackStateNote(state: string): string | null {
  switch (state) {
    case "sent":
      return null;
    case "no_whatsapp":
      return "Not on WhatsApp";
    case "failed":
      return "Could not be sent";
    case "would_send":
      return "Would send: sending is off";
    case "pending":
      return "Waiting to be sent";
    case "sending":
      return "Being sent";
    default:
      return null;
  }
}

/** One asked order, as a row of the Feedback sheet. */
export type FeedbackRow = {
  id: number;
  order_id: string;
  order_name: string | null;
  delivered_at: string | null;
  sent_at: string | null;
  asked_at: string | null;
  customer_name: string | null;
  phone: string | null;
  products: string[];
  courier: string | null;
  state: string;
  state_label: string;
  skip_reason: string | null;
  last_error: string | null;
  step: FeedbackStep;
  rating: FeedbackRating | null;
  rated_at: string | null;
  reason: string | null;
  comment: string | null;
  comment_at: string | null;
  reorder: FeedbackReorder | null;
  needs_follow_up: boolean;
  resolved_at: string | null;
  resolved_by: number | null;
  resolved_by_name: string | null;
  solved: boolean | null;
  solved_at: string | null;
  reopened_count: number;
  code: string | null;
  code_sent_at: string | null;
  code_expires_at: string | null;
  code_used_at: string | null;
  code_order_name: string | null;
};

/** The numbers for the sheet's current filters. */
export type FeedbackSummary = {
  /** Questions actually sent. */
  asked: number;
  /** Failed, sent to a number not on WhatsApp, or held because sending is off. */
  not_reached: number;
  answered: number;
  loved: number;
  okay: number;
  unhappy: number;
  needs_follow_up: number;
  solved: number;
  codes_sent: number;
  codes_used: number;
};

type Choice = { id: string; title: string };

/** The sheet's filter menus. `reasons` depends on the answer chosen. */
export type FeedbackOptions = {
  couriers: string[];
  ratings: Choice[];
  reasons: Partial<Record<FeedbackRating, Choice[]>>;
  states: Choice[];
};

export type FeedbackPage = {
  rows: FeedbackRow[];
  next_offset: number | null;
  summary: FeedbackSummary;
  options: FeedbackOptions;
  /** Whether the questions are being sent at all (the feature's switch on the server). */
  enabled: boolean;
};

/** The feature's switch and settings (`GET /api/inbox/feedback/settings`). */
export type FeedbackSettings = {
  enabled: boolean;
  started_at: string | null;
  review_url: string | null;
  reply_hours: number;
  /** Only the read; a save does not answer it. */
  codes_ready?: { ready: boolean; reason: string | null };
};
