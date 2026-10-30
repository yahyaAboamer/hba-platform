import type { CountKey } from "../types";

/** The three departments Today draws from. */
export type TodayDepartment = "inbox" | "operations" | "affiliates";

/**
 * One thing waiting for this person, as `GET /api/today` words it. The
 * server writes the sentence and the time rules; the page only lays them out.
 */
export type TodayItem = {
  key: string;
  department: TodayDepartment;
  /** Something has stopped working: drawn red, first, with the primary button. */
  broken: boolean;
  /** It has waited longer than it should: the time is drawn orange. */
  late: boolean;
  what: string;
  detail: string;
  since: string | null;
  due: string | null;
  /** How the time column is written: from `since`, as "since ...", to `due`, or blank. */
  when: "elapsed" | "since" | "deadline" | null;
  go: { label: string; to: string };
};

export type TodayOrderRowKey =
  | "waiting"
  | "confirmed"
  | "with_bosta"
  | "delivered"
  | "cancelled"
  | "not_asked";

/** One stage of the last seven days' orders; the rows add up to `placed`. */
export type TodayOrderRow = {
  key: TodayOrderRowKey;
  label: string;
  department: string;
  count: number;
};

export type TodayOrders = {
  from: string;
  to: string;
  placed: number;
  bosta_as_of: string | null;
  rows: TodayOrderRow[];
};

/** `GET /api/today`: also the sidebar's numbers, so there is one read for both. */
export type TodayBody = {
  now: string;
  departments: TodayDepartment[];
  items: TodayItem[];
  /** Only the numbers that could be read: absent is not 0. */
  counts: Partial<Record<CountKey, number>>;
  /** Operations sources whose latest read failed, with their last clean read. */
  failures: Record<string, string | null>;
  orders: TodayOrders | null;
  /** Departments the server could not read just now. */
  unread?: TodayDepartment[];
};

/** What the frame knows of that read, shared by the sidebar and the page. */
export type TodayRead = {
  body: TodayBody | null;
  /** When this browser got it, for "Updated 2 minutes ago". */
  readAt: number | null;
  /** The last try failed; there is no body to show until one succeeds. */
  failed: boolean;
};
