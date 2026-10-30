import type { ReactNode } from "react";

import type { IconName } from "../frame/Icon";
import type { Moved } from "../frame/moved";
import type { Session } from "../lib/api";

/** The numbers the sidebar can show beside a section, by where they come from. */
export type CountKey =
  | "chats_unread"
  | "models_awaiting_approval"
  | "payments_awaiting_approval";

export type SectionCount = {
  key: CountKey;
  /** What the number means, said in words for whoever cannot see it. */
  sentence: (count: number) => string;
  /** The quieter look: money waiting to be released, not people to look at. */
  settled?: boolean;
};

export type DepartmentSection = {
  slug: string;
  label: string;
  /** The section's address; the sidebar link goes here. */
  to: string;
  count?: SectionCount;
  /** An Operations source whose failed read puts a red dot on this section. */
  alert?: string;
  /** Addresses off the sidebar that show this section as the current one. */
  also?: readonly string[];
  /** The screen runs edge to edge and scrolls inside itself (Chats). */
  wide?: boolean;
};

/** One department, declared once: the frame, the router and the menu read this. */
export type Department = {
  key: "inbox" | "operations" | "affiliates";
  name: string;
  icon: IconName;
  /** The permission that shows it. Never a role's name (ADR 0067). */
  holds: string;
  base: string;
  sections: readonly DepartmentSection[];
  /** The routes under `base`, relative to it. */
  routes: (session: Session) => ReactNode;
  /** Addresses this department used to have, and where they went. */
  moved: readonly Moved[];
  /** On a phone this address takes the whole display (an open chat). */
  immersive?: (pathname: string) => boolean;
};
