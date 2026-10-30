import { useEffect, useMemo, useState } from "react";

import type { CountKey } from "../departments/types";
import { api, can } from "../lib/api";
import type { Session } from "../lib/api";
import type { Freshness } from "../components/OpsSource";

/** How often the sidebar's numbers are read again. */
const EVERY_MS = 60_000;
/** How often the unread chats are read while Chats (which reads its own) is not open. */
const INBOX_EVERY_MS = 30_000;

type Counts = Partial<Record<CountKey, number>>;

/**
 * What the sidebar has to say, and where each thing comes from.
 *
 * A failed or refused read leaves its number *absent*, never 0: no badge
 * reads as nothing to say, while a 0 asserts there is nothing waiting - a
 * claim this would be making up. Each read is only made for whoever holds
 * the permission behind it, so nobody knocks on a door that refuses them.
 */
export type Waiting = {
  counts: Counts;
  /** Operations sources whose latest read failed, with when each was last read cleanly. */
  failures: Record<string, string | null>;
  /** Chats reads the list far more often than the frame does, and tells it. */
  setUnread: (unread: number) => void;
};

function poll(read: () => Promise<void>, every: number, on: boolean): () => void {
  if (!on) return () => undefined;
  void read();
  const timer = window.setInterval(() => void read(), every);
  return () => window.clearInterval(timer);
}

export function useWaiting(session: Session, chatsOpen: boolean): Waiting {
  const [counts, setCounts] = useState<Counts>({});
  const [failures, setFailures] = useState<Record<string, string | null>>({});
  const affiliates = can(session, "affiliates.view");
  const operations = can(session, "order_ops.view");
  const inbox = can(session, "inbox.use");

  const setUnread = useMemo(
    () => (unread: number) => setCounts((now) => ({ ...now, chats_unread: unread })),
    [],
  );

  useEffect(
    () =>
      poll(
        () =>
          api
            .get<CountsBody>("/api/operations/counts")
            .then((body) => {
              const models = body.models_awaiting_approval;
              const payments = body.payments_awaiting_approval;
              setCounts((now) => ({
                ...now,
                models_awaiting_approval: typeof models === "number" ? models : undefined,
                payments_awaiting_approval: typeof payments === "number" ? payments : undefined,
              }));
            })
            .catch(() =>
              setCounts((now) => ({
                ...now,
                models_awaiting_approval: undefined,
                payments_awaiting_approval: undefined,
              })),
            ),
        EVERY_MS,
        affiliates,
      ),
    [affiliates],
  );

  useEffect(
    () =>
      poll(
        () =>
          api
            .get<{ sources: FreshnessRow[] }>("/api/operations/freshness")
            .then((body) =>
              setFailures(
                Object.fromEntries(
                  body.sources
                    .filter((row) => row.state === "failed")
                    .map((row) => [row.source, row.updated_at ?? null]),
                ),
              ),
            )
            .catch(() => setFailures({})),
        EVERY_MS,
        operations,
      ),
    [operations],
  );

  useEffect(
    () =>
      // Chats reads the list itself every few seconds and passes the count up.
      poll(
        () =>
          api
            .get<{ counts: { unread: number } }>("/api/inbox/conversations?limit=1")
            .then((body) => setUnread(body.counts.unread))
            .catch(() => setCounts((now) => ({ ...now, chats_unread: undefined }))),
        INBOX_EVERY_MS,
        inbox && !chatsOpen,
      ),
    [inbox, chatsOpen, setUnread],
  );

  return { counts, failures, setUnread };
}

/** `GET /api/operations/counts`, read for the two numbers the sidebar shows. */
type CountsBody = Record<string, unknown>;

/** One row of `GET /api/operations/freshness`. */
type FreshnessRow = {
  source: string;
  label: string;
  state: Freshness["state"];
  updated_at: string | null;
  failed_at: string | null;
};
