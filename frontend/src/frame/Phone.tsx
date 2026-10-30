import { useEffect, useRef } from "react";
import type { KeyboardEvent, ReactNode, RefObject } from "react";

import { Icon } from "./Icon";
import { Brand } from "./Sidebar";

/**
 * The phone's top bar (below 800px; the mockup's frame 7): the menu, the
 * current section's name, and 44px of nothing on the right where search
 * comes in Phase 3.
 */
export function PhoneBar({
  title,
  onOpen,
  menuButton,
}: {
  title: string;
  onOpen: () => void;
  menuButton: RefObject<HTMLButtonElement | null>;
}) {
  return (
    <header className="frame__pbar">
      <button
        type="button"
        ref={menuButton}
        className="frame__iconbtn"
        aria-label="Open the menu"
        aria-haspopup="dialog"
        onClick={onOpen}
      >
        <Icon name="menu" />
      </button>
      <div className="frame__pbar-title">{title}</div>
      <span className="frame__pbar-gap" aria-hidden="true" />
    </header>
  );
}

const FOCUSABLE = "a[href], button:not([disabled])";

/**
 * The phone's menu: the whole display, with the brand and a close button on
 * top and the same departments below. Escape and the close button close it;
 * focus goes in on opening and back to the menu button on closing; the page
 * behind does not scroll.
 */
export function PhoneMenu({
  role,
  onClose,
  menuButton,
  children,
}: {
  role: string;
  onClose: () => void;
  menuButton: RefObject<HTMLButtonElement | null>;
  children: ReactNode;
}) {
  const sheet = useRef<HTMLDivElement>(null);
  const close = useRef<HTMLButtonElement>(null);
  // The latest `onClose`, read when the window widens, so a new function on
  // every render does not move the focus back and forth.
  const closing = useRef(onClose);
  closing.current = onClose;

  useEffect(() => {
    const opener = menuButton.current;
    close.current?.focus();
    const overflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    // Widened past a phone (a turned tablet, a resized window), the sidebar
    // is back and the menu has nothing left to do: it closes rather than
    // holding the page still from behind its own `display: none`.
    const wide = window.matchMedia?.("(min-width: 801px)");
    const onWide = (event: MediaQueryListEvent) => {
      if (event.matches) closing.current();
    };
    wide?.addEventListener("change", onWide);
    return () => {
      wide?.removeEventListener("change", onWide);
      document.body.style.overflow = overflow;
      opener?.focus();
    };
  }, [menuButton]);

  function onKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    if (event.key === "Escape") {
      onClose();
      return;
    }
    if (event.key !== "Tab") return;
    // Focus stays inside: the page behind is not there while this is open.
    const inside = Array.from(sheet.current?.querySelectorAll<HTMLElement>(FOCUSABLE) ?? []);
    if (inside.length === 0) return;
    const first = inside[0];
    const last = inside[inside.length - 1];
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  }

  return (
    <div
      ref={sheet}
      className="frame__sheet"
      role="dialog"
      aria-modal="true"
      aria-label="Menu"
      onKeyDown={onKeyDown}
    >
      <div className="frame__sheet-top">
        <Brand role={role} />
        <button
          type="button"
          ref={close}
          className="frame__iconbtn"
          aria-label="Close the menu"
          onClick={onClose}
        >
          <Icon name="close" />
        </button>
      </div>
      {children}
    </div>
  );
}
