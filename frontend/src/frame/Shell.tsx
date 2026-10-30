import type { ReactNode } from "react";

import "../components/Layout.css";
import "./frame.css";
import { PhoneBar, PhoneMenu } from "./Phone";
import { Sidebar } from "./Sidebar";

/**
 * The one frame every department sits in (Phase 2, Batch 2.1; ADR 0068),
 * made of parts: the sidebar, the phone's top bar and menu, and the page -
 * `Shell.Main` (padded, scrolling: what every screen sits in) or
 * `Shell.Wide` (edge to edge, scrolling inside itself: Chats).
 */
function ShellRoot({ immersive = false, children }: { immersive?: boolean; children: ReactNode }) {
  return <div className={immersive ? "frame frame--immersive" : "frame"}>{children}</div>;
}

function Main({ children }: { children: ReactNode }) {
  return <main className="frame__main">{children}</main>;
}

function Wide({ children }: { children: ReactNode }) {
  return <main className="frame__main frame__main--wide">{children}</main>;
}

export const Shell = Object.assign(ShellRoot, { Sidebar, PhoneBar, PhoneMenu, Main, Wide });
