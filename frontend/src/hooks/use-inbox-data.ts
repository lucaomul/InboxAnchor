import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState, useCallback } from "react";
import { toast } from "sonner";
import {
  fetchEmailById,
  fetchEmails,
  fetchClassifications,
  fetchRecommendations,
  fetchDigest,
  fetchActionItems,
  createEmailStream,
  getApiUrl,
  applyRecommendation,
  approveRecommendation,
  blockRecommendation,
  applyAllSafe,
  fetchWebhookHealth,
  type FetchEmailsParams,
  type StreamStatus,
} from "@/lib/api-client";
import type { MailboxTimeRange } from "@/lib/time-range";
import {
  MOCK_EMAILS,
  MOCK_CLASSIFICATIONS,
  MOCK_RECOMMENDATIONS,
  MOCK_DIGEST,
  MOCK_ACTION_ITEMS,
} from "@/lib/mock-data";

function isApiConfigured() {
  return !!getApiUrl();
}

export function useEmails(params?: FetchEmailsParams) {
  return useQuery({
    queryKey: ["emails", params],
    queryFn: async () => {
      if (!isApiConfigured()) {
        return {
          emails: MOCK_EMAILS.map((email) => ({
            ...email,
            classification: MOCK_CLASSIFICATIONS[email.id],
          })),
          total: MOCK_EMAILS.length,
        };
      }
      return fetchEmails(params);
    },
    staleTime: 30_000,
    placeholderData: (previousData) => previousData,
  });
}

export function useEmailDetail(emailId: string | null, timeRange: MailboxTimeRange) {
  return useQuery({
    queryKey: ["emailDetail", emailId, timeRange],
    queryFn: async () => {
      if (!emailId || !isApiConfigured()) {
        return null;
      }
      return fetchEmailById(emailId, timeRange);
    },
    enabled: !!emailId && isApiConfigured(),
    staleTime: 30_000,
  });
}

export function useClassifications(timeRange: MailboxTimeRange) {
  return useQuery({
    queryKey: ["classifications", timeRange],
    queryFn: async () => {
      if (!isApiConfigured()) return MOCK_CLASSIFICATIONS;
      return fetchClassifications(timeRange);
    },
    staleTime: 30_000,
  });
}

export function useRecommendations(
  emailId: string | null | undefined,
  timeRange: MailboxTimeRange,
  enabled: boolean = true,
) {
  return useQuery({
    queryKey: ["recommendations", emailId || "all", timeRange],
    queryFn: async () => {
      if (!isApiConfigured()) return MOCK_RECOMMENDATIONS;
      return fetchRecommendations(emailId, timeRange);
    },
    enabled,
    staleTime: 30_000,
  });
}

export function useDigest(timeRange: MailboxTimeRange) {
  return useQuery({
    queryKey: ["digest", timeRange],
    queryFn: async () => {
      if (!isApiConfigured()) return MOCK_DIGEST;
      return fetchDigest(timeRange);
    },
    staleTime: 30_000,
  });
}

export function useActionItems(emailId: string | null, timeRange: MailboxTimeRange) {
  return useQuery({
    queryKey: ["actions", emailId, timeRange],
    queryFn: async () => {
      if (!emailId) return [];
      if (!isApiConfigured()) return MOCK_ACTION_ITEMS[emailId] || [];
      return fetchActionItems(emailId, timeRange);
    },
    enabled: !!emailId,
    staleTime: 60_000,
  });
}

export function useEmailStream() {
  const qc = useQueryClient();
  const esRef = useRef<EventSource | null>(null);
  const [status, setStatus] = useState<StreamStatus>("disconnected");

  useEffect(() => {
    if (!isApiConfigured()) {
      setStatus("disconnected");
      return;
    }

    const es = createEmailStream(
      () => {
        qc.invalidateQueries({ queryKey: ["emails"] });
        qc.invalidateQueries({ queryKey: ["classifications"] });
        qc.invalidateQueries({ queryKey: ["recommendations"] });
        qc.invalidateQueries({ queryKey: ["digest"] });
      },
      setStatus,
    );
    esRef.current = es;

    return () => {
      es?.close();
      esRef.current = null;
      setStatus("disconnected");
    };
  }, [qc]);

  return { ref: esRef, status };
}

// --- Mutations ---

function useInvalidateAll() {
  const qc = useQueryClient();
  return useCallback(() => {
    qc.invalidateQueries({ queryKey: ["emails"] });
    qc.invalidateQueries({ queryKey: ["recommendations"] });
    qc.invalidateQueries({ queryKey: ["digest"] });
  }, [qc]);
}

export function useApplyRecommendation() {
  const invalidate = useInvalidateAll();
  return useMutation({
    mutationFn: ({
      emailId,
      action,
      timeRange,
    }: {
      emailId: string;
      action: string;
      timeRange: MailboxTimeRange;
    }) => applyRecommendation(emailId, action, timeRange),
    onSuccess: () => {
      invalidate();
      toast.success("Action applied successfully");
    },
    onError: (err) => toast.error(`Failed to apply: ${err.message}`),
  });
}

export function useApproveRecommendation() {
  const invalidate = useInvalidateAll();
  return useMutation({
    mutationFn: ({
      emailId,
      action,
      timeRange,
    }: {
      emailId: string;
      action: string;
      timeRange: MailboxTimeRange;
    }) => approveRecommendation(emailId, action, timeRange),
    onSuccess: () => {
      invalidate();
      toast.success("Recommendation approved");
    },
    onError: (err) => toast.error(`Failed to approve: ${err.message}`),
  });
}

export function useBlockRecommendation() {
  const invalidate = useInvalidateAll();
  return useMutation({
    mutationFn: ({
      emailId,
      action,
      timeRange,
    }: {
      emailId: string;
      action: string;
      timeRange: MailboxTimeRange;
    }) => blockRecommendation(emailId, action, timeRange),
    onSuccess: () => {
      invalidate();
      toast("Recommendation blocked", { description: "This action will not be applied automatically." });
    },
    onError: (err) => toast.error(`Failed to block: ${err.message}`),
  });
}

export function useApplyAllSafe() {
  const invalidate = useInvalidateAll();
  return useMutation({
    mutationFn: (timeRange: MailboxTimeRange) => applyAllSafe(timeRange),
    onSuccess: () => {
      invalidate();
      toast.success("All safe actions applied!");
    },
    onError: (err) => toast.error(`Failed to apply all: ${err.message}`),
  });
}

export function useWebhookHealth() {
  return useQuery({
    queryKey: ["webhookHealth"],
    queryFn: async () => {
      if (!isApiConfigured()) return null;
      return fetchWebhookHealth();
    },
    staleTime: 15_000,
    refetchInterval: 30_000,
  });
}
