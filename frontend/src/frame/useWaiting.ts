import { useEffect, useMemo, useRef, useState } from "react";

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
 * Until something has been read, every number is *absent*, never 0: no badge
 * reads as nothing to say, while a 0 asserts there is nothing waiting - a
 * claim this would be making up. A later failed read keeps the last reading.
 * The server only reads the departments this person holds, so nobody knocks
 * on a door that refuses them.
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
  // Chats' own, newer number; a read asked for after it replaces it.
  const [pushed, setPushed] = useState<number | null>(null);
  const pushedAt = useRef(0);
  const holdsAny = departmentsFor(session).length > 0;

  useEffect(() => {
    if (!holdsAny) return undefined;
    let current = true;
    const read = () => {
      const asked = Date.now();
      return api
        .get<TodayBody>("/api/today")
        .then((body) => {
          if (!current) return;
          setToday({ body, readAt: Date.now(), failed: false });
          // An answer to a question asked before Chats' number is older than it.
          if (asked >= pushedAt.current) setPushed(null);
        })
        .catch(() => {
          if (!current) return;
          // One failed read (a restart, a phone between networks) keeps what
          // was last read, with its time, rather than blanking the page and
          // every badge: an old reading says when it is from; a blank says
          // nothing is known. Nothing read yet stays nothing.
          setToday((now) => ({ ...now, failed: true }));
        });
    };
    // A tab nobody is looking at does not ask; it asks again on being looked at.
    const tick = () => {
      if (!document.hidden) void read();
    };
    const seen = () => {
      if (!document.hidden) void read();
    };
    void read();
    const timer = window.setInterval(tick, EVERY_MS);
    document.addEventListener("visibilitychange", seen);
    return () => {
      current = false;
      window.clearInterval(timer);
      document.removeEventListener("visibilitychange", seen);
    };
  }, [holdsAny]);

  const setUnread = useMemo(
    () => (unread: number) => {
      pushedAt.current = Date.now();
      setPushed(unread);
    },
    [],
  );

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
