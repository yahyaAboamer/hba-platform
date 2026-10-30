import { useOutletContext } from "react-router-dom";

/** What the Inbox's screens are handed by the frame around them. */
export type InboxOutlet = {
  /** Chats reads the list far more often than the frame does, and tells it. */
  setUnread: (unread: number) => void;
};

/** Outside the frame - a screen drawn on its own - there is nobody to tell. */
const ALONE: InboxOutlet = { setUnread: () => undefined };

export function useInbox(): InboxOutlet {
  return useOutletContext<InboxOutlet | undefined>() ?? ALONE;
}
