import { useMemo, useRef, useState } from "react";
import { Outlet, useLocation } from "react-router-dom";

import { useMaintainerTheme } from "../components/useMaintainerTheme";
import type { InboxOutlet } from "../departments/inbox/useInbox";
import type { TodayOutlet } from "../departments/today/useToday";
import type { Department } from "../departments/types";
import type { Session } from "../lib/api";
import { Shell } from "./Shell";
import { SideBody } from "./Sidebar";
import { useWaiting } from "./useWaiting";
import { whereAmI } from "./where";

/**
 * The staff route tree's one layout: the sidebar for the departments this
 * person holds, and the page beside it.
 *
 * `departments` is already only the ones they hold. The outlet's context
 * carries what the screens inside need from the frame: the Inbox's
 * `setUnread`, and the one read of `/api/today` the Today page shares with
 * the sidebar.
 */
export function Frame({ session, departments }: { session: Session; departments: readonly Department[] }) {
  const { pathname } = useLocation();
  const where = whereAmI(pathname, departments);
  const waiting = useWaiting(session);
  // Opened *at* an address: moving to another one closes it, with no effect
  // to run late and close a menu somebody has only just opened.
  const [openedAt, setOpenedAt] = useState<string | null>(null);
  const menuOpen = openedAt === pathname;
  const menuButton = useRef<HTMLButtonElement>(null);

  // This device's copy of the theme paints the first frame; the account's
  // choice holds once it answers.
  useMaintainerTheme();

  const outlet = useMemo<InboxOutlet & TodayOutlet>(
    () => ({ setUnread: waiting.setUnread, today: waiting.today }),
    [waiting.setUnread, waiting.today],
  );

  const role = where.settings
    ? "Settings"
    : where.today
      ? "Today"
      : ((where.department ?? departments[0])?.name ?? "");
  const title = where.settings
    ? "Settings"
    : where.today
      ? "Today"
      : (where.section?.label ?? where.department?.name ?? "HBA");
  const page = <Outlet context={outlet} />;

  return (
    <Shell immersive={where.department?.immersive?.(pathname) === true}>
      <Shell.Sidebar
        session={session}
        departments={departments}
        where={where}
        pathname={pathname}
        waiting={waiting}
        role={role}
      />
      <Shell.PhoneBar title={title} onOpen={() => setOpenedAt(pathname)} menuButton={menuButton} />
      {where.section?.wide ? <Shell.Wide>{page}</Shell.Wide> : <Shell.Main>{page}</Shell.Main>}
      {menuOpen && (
        <Shell.PhoneMenu role={role} onClose={() => setOpenedAt(null)} menuButton={menuButton}>
          <SideBody
            session={session}
            departments={departments}
            where={where}
            pathname={pathname}
            waiting={waiting}
            onNavigate={() => setOpenedAt(null)}
          />
        </Shell.PhoneMenu>
      )}
    </Shell>
  );
}
