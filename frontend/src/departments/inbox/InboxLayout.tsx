import { useCallback, useEffect, useMemo, useState } from "react";
import { Outlet, useMatch, useOutletContext } from "react-router-dom";

import { api } from "../../lib/api";
import type { Session } from "../../lib/api";
import { SideShell } from "../../components/SideShell";

/** How often the sidebar's unread count is read while Chats is not open. */
const COUNT_EVERY_MS = 30_000;

type Counts = { counts: { unread: number } };

/** What the Inbox's screens are handed by the shell around them. */
export type InboxOutlet = {
  /** Chats reads the list far more often than the shell does, and tells it. */
  setUnread: (unread: number) => void;
};

/** Outside the shell - a screen drawn on its own - there is nobody to tell. */
const ALONE: InboxOutlet = { setUnread: () => undefined };

export function useInbox(): InboxOutlet {
  return useOutletContext<InboxOutlet | undefined>() ?? ALONE;
}

/**
 * The shell customer service signs in to, and the operations manager and the
 * admin switch to (ADR 0059; the approved mockup
 * `docs/design/whatsapp-inbox-2026-10-11.html`).
 *
 * Two sections, Chats and Confirmations. The number beside Chats is how many
 * conversations have something unread; absent when there is none, and absent
 * when it could not be read - a 0 would be a claim.
 */
export function InboxLayout({ session }: { session: Session }) {
  const [unread, setUnread] = useState<number | null>(null);
  const onChats = useMatch("/inbox/chats/*") !== null;
  const inAChat = useMatch("/inbox/chats/:conversationId") !== null;

  const readCount = useCallback(() => {
    api
      .get<Counts>("/api/inbox/conversations?limit=1")
      .then((body) => setUnread(body.counts.unread))
      .catch(() => undefined);
  }, []);

  useEffect(() => {
    // Chats reads the list itself every few seconds and passes the count up.
    if (onChats) return;
    readCount();
    const timer = window.setInterval(readCount, COUNT_EVERY_MS);
    return () => window.clearInterval(timer);
  }, [onChats, readCount]);

  // The setter never changes, so neither does what the screens are handed.
  const context = useMemo<InboxOutlet>(() => ({ setUnread }), []);

  return (
    <SideShell
      session={session}
      dashboard="inbox"
      name="Inbox"
      home="/inbox"
      flush={onChats}
      immersive={inAChat}
      sections={[
        { to: "/inbox/chats", label: "Chats", count: unread ?? undefined },
        { to: "/inbox/confirmations", label: "Confirmations" },
      ]}
    >
      <Outlet context={context} />
    </SideShell>
  );
}
