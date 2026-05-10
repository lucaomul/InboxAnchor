import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import {
  fetchOpsOverview,
  fetchOpsProgress,
  getApiUrl,
  runMailboxBackfill,
  runAutoLabel,
  runLabelCleanup,
  runFullAnchorWorkflow,
  runOpsScan,
  runSafeCleanupWorkflow,
} from "@/lib/api-client";
import type { MailboxTimeRange } from "@/lib/time-range";

function useInvalidateWorkspace() {
  const qc = useQueryClient();
  return () => {
    qc.invalidateQueries({ queryKey: ["opsOverview"] });
    qc.invalidateQueries({ queryKey: ["opsProgress"] });
    qc.invalidateQueries({ queryKey: ["emails"] });
    qc.invalidateQueries({ queryKey: ["classifications"] });
    qc.invalidateQueries({ queryKey: ["recommendations"] });
    qc.invalidateQueries({ queryKey: ["digest"] });
  };
}

function isApiConfigured() {
  return typeof window !== "undefined" && !!getApiUrl();
}

export function useOpsOverview(timeRange: MailboxTimeRange) {
  return useQuery({
    queryKey: ["opsOverview", timeRange],
    queryFn: async () => {
      if (!isApiConfigured()) {
        return null;
      }
      return fetchOpsOverview(timeRange);
    },
    enabled: isApiConfigured(),
    staleTime: 15_000,
    refetchInterval: 30_000,
  });
}

export function useOpsProgress(timeRange: MailboxTimeRange, enabled: boolean = true) {
  return useQuery({
    queryKey: ["opsProgress", timeRange],
    queryFn: async () => {
      if (!isApiConfigured()) {
        return null;
      }
      return fetchOpsProgress(timeRange);
    },
    enabled: isApiConfigured() && enabled,
    refetchInterval: (query) =>
      !query.state.data || query.state.data.status === "running" ? 800 : 3_000,
    staleTime: 500,
  });
}

export function useRunOpsScan() {
  const invalidate = useInvalidateWorkspace();
  return useMutation({
    mutationFn: (timeRange: MailboxTimeRange) => runOpsScan(timeRange),
    onSuccess: (result) => {
      invalidate();
      toast.success("Unread scan started", {
        description: `${result.unreadCount} unread emails are queued for mailbox refresh on the current provider.`,
      });
    },
    onError: (err) => toast.error(`Failed to refresh scan: ${err.message}`),
  });
}

export function useRunAutoLabel() {
  const invalidate = useInvalidateWorkspace();
  return useMutation({
    mutationFn: (timeRange: MailboxTimeRange) => runAutoLabel(timeRange),
    onSuccess: (result) => {
      invalidate();
      toast.success("Auto-label sweep complete", {
        description: `${result.count || 0} unread emails received organization labels.`,
      });
    },
    onError: (err) => toast.error(`Failed to apply labels: ${err.message}`),
  });
}

export function useRunMailboxBackfill() {
  const invalidate = useInvalidateWorkspace();
  return useMutation({
    mutationFn: (timeRange: MailboxTimeRange) => runMailboxBackfill(timeRange),
    onSuccess: (result) => {
      invalidate();
      toast.success("Mailbox memory sync started", {
        description: `${result.cachedCount || 0} emails are already cached locally, and InboxAnchor will keep indexing the mailbox in the background.`,
      });
    },
    onError: (err) => toast.error(`Failed to build mailbox memory: ${err.message}`),
  });
}

export function useRunLabelCleanup() {
  const invalidate = useInvalidateWorkspace();
  return useMutation({
    mutationFn: (timeRange: MailboxTimeRange) => runLabelCleanup(timeRange),
    onSuccess: (result) => {
      invalidate();
      const deletedLabelCount =
        typeof result.deletedLabelCount === "number" ? result.deletedLabelCount : 0;
      toast.success("InboxAnchor labels removed", {
        description:
          deletedLabelCount > 0
            ? `${result.count || 0} emails were cleaned, and ${deletedLabelCount} InboxAnchor label definitions were deleted from the mailbox too.`
            : `${result.count || 0} emails had InboxAnchor-generated labels removed without touching the messages.`,
      });
    },
    onError: (err) => toast.error(`Failed to clean labels: ${err.message}`),
  });
}

export function useRunSafeCleanupWorkflow() {
  const invalidate = useInvalidateWorkspace();
  return useMutation({
    mutationFn: (timeRange: MailboxTimeRange) => runSafeCleanupWorkflow(timeRange),
    onSuccess: (result) => {
      invalidate();
      toast.success("Safe cleanup applied", {
        description: `${result.count || 0} low-risk actions executed on the live inbox.`,
      });
    },
    onError: (err) => toast.error(`Failed to run safe cleanup: ${err.message}`),
  });
}

export function useRunFullAnchorWorkflow() {
  const invalidate = useInvalidateWorkspace();
  return useMutation({
    mutationFn: (timeRange: MailboxTimeRange) => runFullAnchorWorkflow(timeRange),
    onSuccess: (result) => {
      invalidate();
      toast.success("Mailbox upgrade sweep complete", {
        description: `${result.labelsApplied || 0} labels applied and ${result.cleanupApplied || 0} safe cleanups executed.`,
      });
    },
    onError: (err) => toast.error(`Failed to run mailbox upgrade: ${err.message}`),
  });
}
