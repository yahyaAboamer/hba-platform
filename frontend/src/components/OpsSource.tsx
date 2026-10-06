import { useCallback, useEffect, useRef, useState, useSyncExternalStore } from "react";

/**
 * What every Operations tab says about its source (ADR 0057 §6; the approved
 * mockup's frame 4, "When a number is old, failed or not there yet").
 *
 * A number is never shown as current when it isn't, and a failure is never
 * shown as 0. Colour always comes with a word and an icon.
 */

export type FreshnessState = "fresh" | "stale" | "failed" | "not_connected" | "never";

/** The server's `freshness` block, as `/api/order-ops/*` returns it. */
export type Freshness = {
  source: string;
  label: string;
  state: FreshnessState;
  updated_at: string | null;
  checked_at: string | null;
  error: string | null;
  row_count: number | null;
};

/** The mockup's icons, drawn inline. */
export function OpsIcon({ name }: { name: "clock" | "alert" | "plug" | "ext" | "down" | "up" }) {
  const common = {
    fill: "none",
    stroke: "currentColor",
    strokeWidth: 2,
    strokeLinecap: "round" as const,
    strokeLinejoin: "round" as const,
  };
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">
      {name === "clock" && (
        <>
          <circle cx="12" cy="12" r="9" {...common} />
          <path d="M12 7v5l3 2" {...common} />
        </>
      )}
      {name === "alert" && (
        <>
          <circle cx="12" cy="12" r="9" {...common} />
          <path d="M12 7.5v5.5" {...common} />
          <circle cx="12" cy="16.5" r="1.2" fill="currentColor" />
        </>
      )}
      {name === "plug" && <path d="M9 3v5M15 3v5M7 8h10v3a5 5 0 0 1-10 0V8zM12 16v5" {...common} />}
      {name === "ext" && (
        <path
          d="M14 4h6v6M20 4l-9 9M18 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h5"
          {...common}
        />
      )}
      {name === "down" && <path d="M6 9l6 6 6-6" {...common} />}
      {name === "up" && <path d="M6 15l6-6 6 6" {...common} />}
    </svg>
  );
}

const CLOCK = new Intl.DateTimeFormat("en-GB", {
  timeZone: "Africa/Cairo",
  hour: "2-digit",
  minute: "2-digit",
  hourCycle: "h23",
});

const DAY_AND_TIME = new Intl.DateTimeFormat("en-GB", {
  timeZone: "Africa/Cairo",
  day: "numeric",
  month: "short",
  hour: "2-digit",
  minute: "2-digit",
  hourCycle: "h23",
});

/** "14:21", Cairo time. */
export function clockTime(iso: string): string {
  return CLOCK.format(new Date(iso));
}

/** "3 Oct, 10:42", Cairo time. */
export function dayAndTime(iso: string): string {
  const parts = Object.fromEntries(
    DAY_AND_TIME.formatToParts(new Date(iso)).map((part) => [part.type, part.value]),
  );
  return `${parts.day} ${parts.month}, ${parts.hour}:${parts.minute}`;
}

/** Read a tab again this often, so a new read shows without a reload. */
const REFRESH_MS = 60_000;

/**
 * A tab's body, read on arrival and every minute after. `failed` is the
 * platform itself not answering, which is not the source failing: that is in
 * the body's `freshness`.
 *
 * Takes the request itself rather than its path, so each screen's own call
 * to its route stays where the reachability test reads it.
 */
export function useOpsTab<T>(fetchTab: () => Promise<T>, onLoad?: (body: T) => void) {
  const [tab, setTab] = useState<T | null>(null);
  const [failed, setFailed] = useState(false);
  const fetcher = useRef(fetchTab);
  fetcher.current = fetchTab;
  const loaded = useRef(onLoad);
  loaded.current = onLoad;

  const reload = useCallback(() => {
    fetcher
      .current()
      .then((body) => {
        setTab(body);
        setFailed(false);
        loaded.current?.(body);
      })
      .catch(() => setFailed(true));
  }, []);

  useEffect(() => {
    reload();
    const timer = window.setInterval(reload, REFRESH_MS);
    return () => window.clearInterval(timer);
  }, [reload]);

  return { tab, failed, reload };
}

/** "Today", "1 day", "3 days": calendar days in Cairo, as the server counts. */
export function waitingLabel(days: number): string {
  if (days === 0) return "Today";
  return days === 1 ? "1 day" : `${days} days`;
}

/**
 * The current time, re-rendering every 30 seconds so "N minutes ago" stays
 * true. Read at each render rather than kept: a time kept from the last tick
 * runs behind a read that arrived since, and would call it older than it is.
 */
export function useNow(): number {
  const [, setTick] = useState(0);
  useEffect(() => {
    const timer = window.setInterval(() => setTick((tick) => tick + 1), 30_000);
    return () => window.clearInterval(timer);
  }, []);
  return Date.now();
}

const NARROW = "(max-width: 800px)";

/** Whether the shell has folded to its phone layout (Layout.css, <=800px). */
export function useIsNarrow(): boolean {
  // Wide where the browser cannot say (jsdom, very old browsers).
  const supported = typeof window.matchMedia === "function";
  return useSyncExternalStore(
    (notify) => {
      if (!supported) return () => undefined;
      const query = window.matchMedia(NARROW);
      query.addEventListener("change", notify);
      return () => query.removeEventListener("change", notify);
    },
    () => supported && window.matchMedia(NARROW).matches,
    () => false,
  );
}

/** The server's promise: no number older than this is current (FRESH_FOR). */
const FRESH_FOR_MS = 10 * 60_000;

/**
 * The state as of now, not as of the last answer from the server. A page
 * left open while the platform cannot be reached keeps its last answer;
 * "fresh" must still turn old here once the numbers pass 10 minutes.
 */
export function stateNow(freshness: Freshness, now: number): FreshnessState {
  const { state, updated_at: updatedAt } = freshness;
  if (state === "fresh" && updatedAt && now - new Date(updatedAt).getTime() > FRESH_FOR_MS) {
    return "stale";
  }
  return state;
}

function age(iso: string, now: number): string {
  const minutes = Math.max(0, Math.floor((now - new Date(iso).getTime()) / 60_000));
  if (minutes < 60) return minutes === 1 ? "1 minute" : `${minutes} minutes`;
  const hours = Math.floor(minutes / 60);
  return hours === 1 ? "1 hour" : `${hours} hours`;
}

/** The line at the right of the tab's heading. */
export function FreshLine({ freshness, now }: { freshness: Freshness; now: number }) {
  const { label, updated_at: updatedAt } = freshness;
  const state = stateNow(freshness, now);

  if (state === "failed") {
    return (
      <p className="ops-fresh ops-fresh--failed">
        <OpsIcon name="alert" />
        Can't reach {label}
      </p>
    );
  }
  if (state === "not_connected") {
    return (
      <p className="ops-fresh">
        <OpsIcon name="plug" />
        Not connected
      </p>
    );
  }
  if (state === "never" || !updatedAt) {
    return (
      <p className="ops-fresh" role="status">
        <OpsIcon name="clock" />
        Reading {label}…
      </p>
    );
  }
  if (state === "stale") {
    return (
      <p className="ops-fresh ops-fresh--stale" role="status">
        <OpsIcon name="clock" />
        Not updated for {age(updatedAt, now)}
      </p>
    );
  }
  const minutes = Math.floor((now - new Date(updatedAt).getTime()) / 60_000);
  return (
    <p
      className="ops-fresh"
      role="status"
      title={`Read from ${label} at ${clockTime(updatedAt)}. Read again every 5 minutes.`}
    >
      <OpsIcon name="clock" />
      {minutes < 1 ? "Updated just now" : `Updated ${age(updatedAt, now)} ago`}
    </p>
  );
}

/** The notice under the heading when the numbers are old, failed or absent. */
export function SourceBanner({ freshness, now }: { freshness: Freshness; now: number }) {
  const { label, updated_at: updatedAt, error } = freshness;
  const state = stateNow(freshness, now);

  if (state === "stale" && updatedAt) {
    return (
      <div className="ops-banner" role="status">
        <OpsIcon name="clock" />
        <div>
          These are {label}'s numbers from {clockTime(updatedAt)}.
          <small>{label} has been slow to answer. The platform keeps trying every 5 minutes.</small>
        </div>
      </div>
    );
  }
  if (state === "failed") {
    return (
      <div className="ops-banner ops-banner--failed" role="alert">
        <OpsIcon name="alert" />
        <div>
          {error ?? `Couldn't read ${label}.`}
          <small>
            {updatedAt
              ? `The numbers below are from ${clockTime(updatedAt)}. `
              : "There are no numbers to show yet. "}
            The platform keeps trying every 5 minutes.
          </small>
        </div>
      </div>
    );
  }
  if (state === "not_connected") {
    return (
      <div className="ops-banner ops-banner--off" role="status">
        <OpsIcon name="plug" />
        <div>
          {label} isn't connected yet.
          <small>
            {freshness.source === "shopify"
              ? "An admin connects Shopify in Settings → Shopify."
              : `An admin adds the ${label} key.`}{" "}
            Until then this tab has no numbers.
          </small>
        </div>
      </div>
    );
  }
  return null;
}
