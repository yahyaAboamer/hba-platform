import { ActivityPanel } from "../../screens/settings/ActivityPanel";
import "../../screens/Settings.css";

/**
 * `/affiliates/activity`: the activity log narrowed to Affiliates' entries.
 * The server narrows it too: whoever is not the owner reads only the
 * departments they hold.
 */
export function ActivityLog() {
  return <>
    <div className="page__head"><div className="page__title"><h1>Activity log</h1></div></div>
    <div className="settings__sections"><ActivityPanel department="affiliates" /></div>
  </>;
}
