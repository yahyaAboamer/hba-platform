import { useOutletContext } from "react-router-dom";

import type { TodayRead } from "./types";

/** What the frame hands the Today page: the one read it shares with the sidebar. */
export type TodayOutlet = { today: TodayRead };

/** Outside the frame there is nothing read yet. */
const NOTHING: TodayRead = { body: null, readAt: null, failed: false };

export function useToday(): TodayRead {
  return useOutletContext<TodayOutlet | undefined>()?.today ?? NOTHING;
}
