/**
 * The frame's icons: the approved mockup's own symbols
 * (`docs/design/hba-os-shell-2026-10-25.html`), drawn inline as strokes.
 * Always beside words or under an `aria-label` - never the only thing said.
 */
export type IconName =
  | "inbox"
  | "truck"
  | "models"
  | "settings"
  | "chev"
  | "down"
  | "menu"
  | "close"
  | "alert";

export function Icon({ name, className }: { name: IconName; className?: string }) {
  return (
    <svg
      className={className ? `frame__ic ${className}` : "frame__ic"}
      viewBox="0 0 24 24"
      aria-hidden="true"
      focusable="false"
    >
      {name === "inbox" && (
        <path d="M5 4.5h14a1.5 1.5 0 0 1 1.5 1.5v9.5A1.5 1.5 0 0 1 19 17h-7.5L7 20.5V17H5a1.5 1.5 0 0 1-1.5-1.5V6A1.5 1.5 0 0 1 5 4.5z" />
      )}
      {name === "truck" && (
        <>
          <path d="M2.5 6.5h11v9.5h-11zM13.5 9.5h4l3.5 3.5v3h-7.5" />
          <circle cx="6.5" cy="17.5" r="1.9" />
          <circle cx="17" cy="17.5" r="1.9" />
        </>
      )}
      {name === "models" && (
        <>
          <circle cx="9" cy="8" r="3.3" />
          <path d="M3 19.5a6 6 0 0 1 12 0" />
          <path d="M15.5 4.9a3.2 3.2 0 0 1 0 6.2M17.5 13.7a6 6 0 0 1 3.5 5.8" />
        </>
      )}
      {name === "settings" && (
        <>
          <path d="M4 7h9M18 7h2M4 17h2M11 17h9" />
          <circle cx="15.5" cy="7" r="2.3" />
          <circle cx="8.5" cy="17" r="2.3" />
        </>
      )}
      {name === "chev" && <path d="M9 6l6 6-6 6" />}
      {name === "down" && <path d="M6 9l6 6 6-6" />}
      {name === "menu" && <path d="M4 7h16M4 12h16M4 17h16" />}
      {name === "close" && <path d="M6 6l12 12M18 6L6 18" />}
      {name === "alert" && (
        <>
          <circle cx="12" cy="12" r="8.5" />
          <path d="M12 7.5v5.5" />
          <circle cx="12" cy="16.4" r="1.1" fill="currentColor" stroke="none" />
        </>
      )}
    </svg>
  );
}
