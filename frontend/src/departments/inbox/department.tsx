import { Navigate, Route } from "react-router-dom";

import type { Department } from "../types";
import { InboxChats } from "./InboxChats";
import { InboxConfirmations } from "./InboxConfirmations";

/**
 * The Inbox (ADR 0059; the approved mockup
 * `docs/design/whatsapp-inbox-2026-10-11.html`, in the frame of
 * `docs/design/hba-os-shell-2026-10-25.html`).
 *
 * `/inbox` opens on Chats, and a chat's own address is `/inbox/chats/<id>`.
 * The number beside Chats is how many conversations have something unread.
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
  ],
  routes: () => (
    <>
      <Route index element={<Navigate to="chats" replace />} />
      <Route path="chats" element={<InboxChats />} />
      <Route path="chats/:conversationId" element={<InboxChats />} />
      <Route path="confirmations" element={<InboxConfirmations />} />
      <Route path="*" element={<Navigate to="/inbox/chats" replace />} />
    </>
  ),
  moved: [],
  immersive: (pathname) => /^\/inbox\/chats\/[^/]+/.test(pathname),
};
