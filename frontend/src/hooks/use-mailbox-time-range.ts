import { useEffect, useState } from "react";
import {
  DEFAULT_MAILBOX_TIME_RANGE,
  getStoredMailboxTimeRange,
  setStoredMailboxTimeRange,
  type MailboxTimeRange,
} from "@/lib/time-range";

export function useMailboxTimeRange() {
  const [timeRange, setTimeRangeState] = useState<MailboxTimeRange>(() => getStoredMailboxTimeRange());

  useEffect(() => {
    setTimeRangeState(getStoredMailboxTimeRange());
  }, []);

  const setTimeRange = (value: MailboxTimeRange) => {
    setTimeRangeState(value);
    setStoredMailboxTimeRange(value);
  };

  return { timeRange, setTimeRange };
}
