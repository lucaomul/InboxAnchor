import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import {
  fetchOpsOverview,
  fetchOpsProgress,
  getApiUrl,
  runMailboxBackfill,
  runAutoLabel,
  runFullAnchorWorkflow,
  runOpsScan,
  runSafeCleanupWorkflow,
} from "@/lib/api-client";

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

export function useOpsOverview() {
  return useQuery({
    queryKey: ["opsOverview"],
    queryFn: async () => {
      if (!isApiConfigured()) {
        return null;
      }
      return fetchOpsOverview();
    },
    enabled: isApiConfigured(),
    staleTime: 15_000,
    refetchInterval: 30_000,
  });
}

export function useOpsProgress(enabled: boolean = true) {
  return useQuery({
    queryKey: ["opsProgress"],
    queryFn: async () => {
      if (!isApiConfigured()) {
        return null;
      }
      return fetchOpsProgress();
    },
    enabled: isApiConfigured() && enabled,
    refetchInterval: (query) =>
      query.state.data && query.state.data.status === "running" ? 1_000 : 3_000,
    staleTime: 500,
  });
}

export function useRunOpsScan() {
  const invalidate = useInvalidateWorkspace();
  return useMutation({
    mutationFn: runOpsScan,
    onSuccess: (result) => {
      invalidate();
      toast.success("Unread scan refreshed", {
        description: `${result.unreadCount} unread emails mapped for the current provider.`,
      });
    },
    onError: (err) => toast.error(`Failed to refresh scan: ${err.message}`),
  });
}

export function useRunAutoLabel() {
  const invalidate = useInvalidateWorkspace();
  return useMutation({
    mutationFn: runAutoLabel,
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
    mutationFn: runMailboxBackfill,
    onSuccess: (result) => {
      invalidate();
      toast.success("Mailbox memory sync complete", {
        description: `${result.cachedCount || 0} emails are now cached locally, with ${result.hydratedCount || 0} full bodies ready instantly.`,
      });
    },
    onError: (err) => toast.error(`Failed to build mailbox memory: ${err.message}`),
  });
}

export function useRunSafeCleanupWorkflow() {
  const invalidate = useInvalidateWorkspace();
  return useMutation({
    mutationFn: runSafeCleanupWorkflow,
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
    mutationFn: runFullAnchorWorkflow,
    onSuccess: (result) => {
      invalidate();
      toast.success("Mailbox upgrade sweep complete", {
        description: `${result.labelsApplied || 0} labels applied and ${result.cleanupApplied || 0} safe cleanups executed.`,
      });
    },
    onError: (err) => toast.error(`Failed to run mailbox upgrade: ${err.message}`),
  });
}
