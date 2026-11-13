/**
 * The Inbox mockup's icons that Operations does not already draw
 * (`docs/design/whatsapp-inbox-2026-10-11.html`; `OpsIcon` has the rest).
 * Always beside words or under an `aria-label`: never the only thing said.
 */
export type InboxIconName =
  | "search"
  | "clip"
  | "mic"
  | "send"
  | "tick"
  | "ticks"
  | "image"
  | "file"
  | "play"
  | "pause"
  | "template"
  | "left"
  | "reply"
  | "smile"
  | "close"
  | "stop"
  | "up"
  | "down"
  | "lock"
  | "list"
  | "settings";

export function InboxIcon({ name }: { name: InboxIconName }) {
  const line = {
    fill: "none",
    stroke: "currentColor",
    strokeWidth: 2,
    strokeLinecap: "round" as const,
    strokeLinejoin: "round" as const,
  };
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">
      {name === "search" && (
        <>
          <circle cx="11" cy="11" r="7" {...line} />
          <path d="M20 20l-4-4" {...line} />
        </>
      )}
      {name === "clip" && (
        <path
          d="M20 11.5l-8.2 8.2a5 5 0 0 1-7-7L13 4.5a3.3 3.3 0 0 1 4.7 4.7l-8.2 8.1a1.7 1.7 0 0 1-2.3-2.3L14.5 7.6"
          {...line}
        />
      )}
      {name === "mic" && (
        <>
          <rect x="9" y="3" width="6" height="11" rx="3" {...line} />
          <path d="M5.5 11a6.5 6.5 0 0 0 13 0M12 17.5V21" {...line} />
        </>
      )}
      {name === "send" && <path d="M4 12l16-8-6 16-3-7-7-1z" {...line} />}
      {name === "tick" && <path d="M5 12.5l4.5 4.5L19 7.5" {...line} />}
      {name === "ticks" && <path d="M2 12.5l4.5 4.5L15 8M9.5 15.5L11 17l9.5-9" {...line} />}
      {name === "image" && (
        <>
          <rect x="3" y="4" width="18" height="16" rx="2" {...line} />
          <circle cx="9" cy="10" r="1.6" fill="currentColor" />
          <path d="M4 18l5-5 4 4 3-3 4 4" {...line} />
        </>
      )}
      {name === "file" && (
        <path d="M7 3h7l5 5v12a1 1 0 0 1-1 1H7a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1zM14 3v5h5" {...line} />
      )}
      {name === "play" && <path d="M8 5l11 7-11 7z" fill="currentColor" />}
      {name === "pause" && <path d="M7 5h4v14H7zM13 5h4v14h-4z" fill="currentColor" />}
      {name === "stop" && <rect x="6" y="6" width="12" height="12" rx="2" fill="currentColor" />}
      {name === "template" && (
        <>
          <rect x="4" y="4" width="16" height="16" rx="2" {...line} />
          <path d="M8 9h8M8 13h8M8 17h4" {...line} />
        </>
      )}
      {name === "lock" && (
        <>
          <rect x="5" y="11" width="14" height="9" rx="2" {...line} />
          <path d="M8 11V8a4 4 0 0 1 8 0v3" {...line} />
        </>
      )}
      {name === "list" && <path d="M8 6h12M8 12h12M8 18h12M4 6h.01M4 12h.01M4 18h.01" {...line} />}
      {name === "settings" && (
        <>
          <circle cx="12" cy="12" r="3" {...line} />
          <path d="M12 3v3M12 18v3M3 12h3M18 12h3M5.6 5.6l2.1 2.1M16.3 16.3l2.1 2.1M18.4 5.6l-2.1 2.1M7.7 16.3l-2.1 2.1" {...line} />
        </>
      )}
      {name === "left" && <path d="M15 6l-6 6 6 6" {...line} />}
      {name === "reply" && <path d="M10 8L5 12l5 4M5 12h9a5 5 0 0 1 5 5v1" {...line} />}
      {name === "smile" && (
        <>
          <circle cx="12" cy="12" r="9" {...line} />
          <path d="M8.5 14.5a4.5 4.5 0 0 0 7 0" {...line} />
          <circle cx="9" cy="10" r="1.1" fill="currentColor" />
          <circle cx="15" cy="10" r="1.1" fill="currentColor" />
        </>
      )}
      {name === "close" && <path d="M6 6l12 12M18 6L6 18" {...line} />}
      {name === "up" && <path d="M6 15l6-6 6 6" {...line} />}
      {name === "down" && <path d="M6 9l6 6 6-6" {...line} />}
    </svg>
  );
}
