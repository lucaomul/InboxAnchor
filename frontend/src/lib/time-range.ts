export type MailboxTimeRange =
  | "all_time"
  | "today"
  | "last_7_days"
  | "this_month"
  | "last_month"
  | "last_3_months"
  | "last_6_months"
  | "last_1_year"
  | "last_3_years"
  | "last_5_years"
  | "last_10_years"
  | "older_than_10_years";

export interface MailboxTimeRangeOption {
  value: MailboxTimeRange;
  label: string;
}

export const DEFAULT_MAILBOX_TIME_RANGE: MailboxTimeRange = "all_time";
const MAILBOX_TIME_RANGE_KEY = "inboxanchor_mailbox_time_range";

export const MAILBOX_TIME_RANGE_OPTIONS: MailboxTimeRangeOption[] = [
  { value: "all_time", label: "All time" },
  { value: "today", label: "Today" },
  { value: "last_7_days", label: "Last 7 days" },
  { value: "this_month", label: "This month" },
  { value: "last_month", label: "Last month" },
  { value: "last_3_months", label: "Last 3 months" },
  { value: "last_6_months", label: "Last 6 months" },
  { value: "last_1_year", label: "Last year" },
  { value: "last_3_years", label: "Last 3 years" },
  { value: "last_5_years", label: "Last 5 years" },
  { value: "last_10_years", label: "Last 10 years" },
  { value: "older_than_10_years", label: "10+ years ago" },
];

export function isMailboxTimeRange(value: string): value is MailboxTimeRange {
  return MAILBOX_TIME_RANGE_OPTIONS.some((option) => option.value === value);
}

export function getStoredMailboxTimeRange(): MailboxTimeRange {
  if (typeof window === "undefined") return DEFAULT_MAILBOX_TIME_RANGE;
  const stored = window.localStorage.getItem(MAILBOX_TIME_RANGE_KEY) || "";
  return isMailboxTimeRange(stored) ? stored : DEFAULT_MAILBOX_TIME_RANGE;
}

export function setStoredMailboxTimeRange(value: MailboxTimeRange) {
  if (typeof window === "undefined") return;
  window.localStorage.setItem(MAILBOX_TIME_RANGE_KEY, value);
}

export function mailboxTimeRangeLabel(value: MailboxTimeRange): string {
  return (
    MAILBOX_TIME_RANGE_OPTIONS.find((option) => option.value === value)?.label
    || "All time"
  );
}
