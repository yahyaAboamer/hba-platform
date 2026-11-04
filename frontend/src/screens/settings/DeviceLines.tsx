import type { DeviceSession, TrustedBrowser } from "../../lib/api";

/** *Active now*, or when they were last seen. */
function seenWords(iso: string): string {
  if (Date.now() - new Date(iso).getTime() < 5 * 60_000) return "Active now";
  return `Last seen ${lastSeen(iso).replace(/^Today, /, "today at ")}`;
}

/** One device: what it is, the address it came from, and when it was last used. */
export function DeviceLine({ device, action }: { device: DeviceSession; action?: React.ReactNode }) {
  return (
    <li className="twostep__row">
      <span>
        {device.device}{device.current && <span className="settings__you">This device</span>}
        <small>{[device.ip_address, seenWords(device.last_seen_at)].filter(Boolean).join(" · ")}</small>
      </span>
      {action}
    </li>
  );
}

const dayWords = (iso: string) =>
  new Intl.DateTimeFormat("en-GB", { timeZone: "Africa/Cairo", day: "numeric", month: "long" }).format(new Date(iso));

/** One remembered browser: what it is, and until when it skips the code. */
export function BrowserLine({ browser, action }: { browser: TrustedBrowser; action?: React.ReactNode }) {
  return (
    <li className="twostep__row">
      <span>
        {browser.device}{browser.current && <span className="settings__you">This browser</span>}
        <small>{[browser.ip_address, `Remembered until ${dayWords(browser.expires_at)}`].filter(Boolean).join(" · ")}</small>
      </span>
      {action}
    </li>
  );
}


/** *Today, 14:31*, *Yesterday*, *3 August*, or *Never*. In Cairo. */
export function lastSeen(iso: string | null): string {
  if (!iso) return "Never";
  const day = (value: Date) =>
    new Intl.DateTimeFormat("en-CA", { timeZone: "Africa/Cairo" }).format(value);
  const then = new Date(iso);
  const now = new Date();
  if (day(then) === day(now)) {
    return `Today, ${new Intl.DateTimeFormat("en-GB", { timeZone: "Africa/Cairo", hour: "2-digit", minute: "2-digit", hourCycle: "h23" }).format(then)}`;
  }
  if (day(then) === day(new Date(now.getTime() - 86_400_000))) return "Yesterday";
  return new Intl.DateTimeFormat("en-GB", {
    timeZone: "Africa/Cairo", day: "numeric", month: "long",
    ...(then.getFullYear() !== now.getFullYear() ? { year: "numeric" as const } : {}),
  }).format(then);
}
