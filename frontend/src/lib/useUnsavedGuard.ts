import { useEffect } from "react";

/**
 * Asks before unsaved work is lost.
 *
 * The app runs on a plain `BrowserRouter`, which has no way to hold a
 * navigation (`useBlocker` needs a data router), so this does the two things
 * that can be done from a page:
 *
 * - closing or reloading the tab: the browser's own question (`beforeunload`,
 *   as Targets does);
 * - following a link inside the app (the sidebar, a breadcrumb, any anchor):
 *   one question, answered before the router sees the click.
 *
 * The browser's Back button is not covered; the page's own buttons are the
 * way out and it says what is unsaved.
 */
export function useUnsavedGuard(dirty: boolean, question: string): void {
  useEffect(() => {
    if (!dirty) return;

    const hold = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      event.returnValue = "";
    };

    const onClick = (event: MouseEvent) => {
      if (event.defaultPrevented || event.button !== 0) return;
      if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
      const target = event.target instanceof Element ? event.target : null;
      const anchor = target?.closest("a[href]") as HTMLAnchorElement | null;
      if (!anchor || (anchor.target && anchor.target !== "_self") || anchor.hasAttribute("download")) return;
      const to = new URL(anchor.href, window.location.href);
      // Another site opens in its own way; the same address (a hash, a repeat click) loses nothing.
      if (to.origin !== window.location.origin) return;
      if (to.pathname === window.location.pathname && to.search === window.location.search) return;
      if (!window.confirm(question)) {
        event.preventDefault();
        event.stopPropagation();
      }
    };

    window.addEventListener("beforeunload", hold);
    // Capture, on the document: before React's own listeners and the router's.
    document.addEventListener("click", onClick, true);
    return () => {
      window.removeEventListener("beforeunload", hold);
      document.removeEventListener("click", onClick, true);
    };
  }, [dirty, question]);
}
