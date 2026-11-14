import { Navigate, Route } from "react-router-dom";

import type { Department } from "../types";
import { InboxChats } from "./InboxChats";
import { InboxConfirmations } from "./InboxConfirmations";
import { FeedbackSetup } from "./FeedbackSetup";
import { InboxFeedback } from "./InboxFeedback";

/**
 * The Inbox (ADR 0059; the approved mockup
 * `docs/design/whatsapp-inbox-2026-10-11.html`, in the frame of
 * `docs/design/hba-os-shell-2026-10-25.html`).
 *
 * `/inbox` opens on Chats, and a chat's own address is `/inbox/chats/<id>`.
 * The number beside Chats is how many conversations have something unread.
 *
 * Feedback (ADR 0083) is the sheet of every answer to "how did your order
 * go?". The number beside it is how many unhappy customers still need a
 * person to follow up: not added to Chats' number, which says *waiting for a
 * reply*, so each sentence stays true. A folded Inbox adds the two.
 * Its setup (the words, the review link, the reply time, a test) is
 * `/inbox/feedback/setup`: under Feedback in the sidebar, not a section of its
 * own, because it is rarely opened and a link on the sheet reads better.
 */
export const inbox: Department = {
  key: "inbox",
  name: "Inbox",
  icon: "inbox",
  holds: "inbox.use",
  base: "/inbox",
  sections: [
    {
      slug: "chats",
      label: "Chats",
      to: "/inbox/chats",
      wide: true,
      count: {
        key: "chats_unread",
        sentence: (count) => `${count} ${count === 1 ? "chat" : "chats"} waiting for a reply`,
      },
    },
    { slug: "confirmations", label: "Confirmations", to: "/inbox/confirmations" },
    {
      slug: "feedback",
      label: "Feedback",
      to: "/inbox/feedback",
      count: {
        key: "chats_follow_up",
        sentence: (count) =>
          `${count} ${count === 1 ? "customer needs" : "customers need"} a follow-up`,
      },
    },
  ],
  routes: () => (
    <>
      <Route index element={<Navigate to="chats" replace />} />
      <Route path="chats" element={<InboxChats />} />
      <Route path="chats/:conversationId" element={<InboxChats />} />
      <Route path="confirmations" element={<InboxConfirmations />} />
      <Route path="feedback" element={<InboxFeedback />} />
      {/* Off the sidebar: a link on the sheet's head and on Settings → Integrations reach it. */}
      <Route path="feedback/setup" element={<FeedbackSetup />} />
      <Route path="*" element={<Navigate to="/inbox/chats" replace />} />
    </>
  ),
  moved: [],
  immersive: (pathname) => /^\/inbox\/chats\/[^/]+/.test(pathname),
};
