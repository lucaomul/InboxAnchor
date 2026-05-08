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

export function useEmailDetail(emailId: string | null) {
  return useQuery({
    queryKey: ["emailDetail", emailId],
    queryFn: async () => {
      if (!emailId || !isApiConfigured()) {
        return null;
      }
      return fetchEmailById(emailId);
    },
    enabled: !!emailId && isApiConfigured(),
    staleTime: 30_000,
  });
}

export function useClassifications() {
  return useQuery({
    queryKey: ["classifications"],
    queryFn: async () => {
      if (!isApiConfigured()) return MOCK_CLASSIFICATIONS;
      return fetchClassifications();
    },
    staleTime: 30_000,
  });
}

export function useRecommendations(emailId?: string | null, enabled: boolean = true) {
  return useQuery({
    queryKey: ["recommendations", emailId || "all"],
    queryFn: async () => {
      if (!isApiConfigured()) return MOCK_RECOMMENDATIONS;
      return fetchRecommendations(emailId);
    },
    enabled,
    staleTime: 30_000,
  });
}

export function useDigest() {
  return useQuery({
    queryKey: ["digest"],
    queryFn: async () => {
      if (!isApiConfigured()) return MOCK_DIGEST;
      return fetchDigest();
    },
    staleTime: 30_000,
  });
}

export function useActionItems(emailId: string | null) {
  return useQuery({
    queryKey: ["actions", emailId],
    queryFn: async () => {
      if (!emailId) return [];
      if (!isApiConfigured()) return MOCK_ACTION_ITEMS[emailId] || [];
      return fetchActionItems(emailId);
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
    mutationFn: ({ emailId, action }: { emailId: string; action: string }) =>
      applyRecommendation(emailId, action),
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
    mutationFn: ({ emailId, action }: { emailId: string; action: string }) =>
      approveRecommendation(emailId, action),
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
    mutationFn: ({ emailId, action }: { emailId: string; action: string }) =>
      blockRecommendation(emailId, action),
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
    mutationFn: applyAllSafe,
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
