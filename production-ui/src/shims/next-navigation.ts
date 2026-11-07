/** `next/navigation`'s `usePathname`, as Production's screens read it. */
import { appPath } from "@/lib/base-path";

export function usePathname(): string {
  return appPath(window.location.pathname);
}
