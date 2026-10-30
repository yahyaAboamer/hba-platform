import { useEffect, useMemo, useState } from "react";

import { departmentsFor } from "../departments";
import type { CountKey } from "../departments/types";
import type { TodayBody, TodayRead } from "../departments/today/types";
import { api } from "../lib/api";
import type { Session } from "../lib/api";

/** How often what is waiting is read again. */
const EVERY_MS = 30_000;

type Counts = Partial<Record<CountKey, number>>;

/**
 * What the sidebar has to say, and where it comes from: one read of
 * `GET /api/today`, which the Today page shares rather than asking again.
 *
 * A failed or refused read leaves its number *absent*, never 0: no badge
 * reads as nothing to say, while a 0 asserts there is nothing waiting - a
 * claim this would be making up. The server only reads the departments this
 * person holds, so nobody knocks on a door that refuses them.
 */
export type Waiting = {
  counts: Counts;
  /** Operations sources whose latest read failed, with when each was last read cleanly. */
  failures: Record<string, string | null>;
  /** The whole body, for the Today page. */
  today: TodayRead;
  /** Chats reads the list far more often than the frame does, and tells it. */
  setUnread: (unread: number) => void;
};

const NO_COUNTS: Counts = {};
const NO_FAILURES: Record<string, string | null> = {};

export function useWaiting(session: Session): Waiting {
  const [today, setToday] = useState<TodayRead>({ body: null, readAt: null, failed: false });
  // Chats' own, newer number; the next read of the whole body replaces it.
  const [pushed, setPushed] = useState<number | null>(null);
  const holdsAny = departmentsFor(session).length > 0;

  useEffect(() => {
    if (!holdsAny) return undefined;
    let current = true;
    const read = () =>
      api
        .get<TodayBody>("/api/today")
        .then((body) => {
          if (!current) return;
          setToday({ body, readAt: Date.now(), failed: false });
          setPushed(null);
        })
        .catch(() => {
          if (!current) return;
          setToday({ body: null, readAt: null, failed: true });
          setPushed(null);
        });
    void read();
    const timer = window.setInterval(() => void read(), EVERY_MS);
    return () => {
      current = false;
      window.clearInterval(timer);
    };
  }, [holdsAny]);

  const setUnread = useMemo(() => (unread: number) => setPushed(unread), []);

  const counts = useMemo<Counts>(() => {
    const read = today.body?.counts ?? NO_COUNTS;
    return pushed === null ? read : { ...read, chats_unread: pushed };
  }, [today.body, pushed]);

  return {
    counts,
    failures: today.body?.failures ?? NO_FAILURES,
    today,
    setUnread,
  };
}
