import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import {
  fetchOpsOverview,
  runAutoLabel,
  runFullAnchorWorkflow,
  runOpsScan,
  runSafeCleanupWorkflow,
} from "@/lib/api-client";

function useInvalidateWorkspace() {
  const qc = useQueryClient();
  return () => {
    qc.invalidateQueries({ queryKey: ["opsOverview"] });
    qc.invalidateQueries({ queryKey: ["emails"] });
    qc.invalidateQueries({ queryKey: ["classifications"] });
    qc.invalidateQueries({ queryKey: ["recommendations"] });
    qc.invalidateQueries({ queryKey: ["digest"] });
  };
}

export function useOpsOverview() {
  return useQuery({
    queryKey: ["opsOverview"],
    queryFn: fetchOpsOverview,
    staleTime: 15_000,
    refetchInterval: 30_000,
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
