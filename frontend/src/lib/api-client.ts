// InboxAnchor API Client
// Connects to the deployed InboxAnchor Python backend

import type {
  EmailMessage,
  EmailClassification,
  EmailRecommendation,
  EmailActionItem,
  InboxDigest,
} from "./mock-data";
import type { MailboxTimeRange, MailboxTimeRangeOption } from "./time-range";
import { z } from "zod";

const API_URL_KEY = "inboxanchor_api_url";
const GMAIL_TOKEN_KEY = "inboxanchor_gmail_token";
const AUTH_TOKEN_KEY = "inboxanchor_auth_token";
const AUTH_EMAIL_KEY = "inboxanchor_auth_email";

// --- Validation schemas ---

const apiUrlSchema = z.string().url().max(500).regex(/^https?:\/\//, "Must start with http:// or https://");

export function getApiUrl(): string {
  if (typeof window === "undefined") return "";
  return localStorage.getItem(API_URL_KEY) || "";
}

export function setApiUrl(url: string) {
  const cleaned = url.replace(/\/+$/, "");
  apiUrlSchema.parse(cleaned);
  localStorage.setItem(API_URL_KEY, cleaned);
}

export function getGmailToken(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem(GMAIL_TOKEN_KEY);
}

export function setGmailToken(token: string) {
  localStorage.setItem(GMAIL_TOKEN_KEY, token);
}

export function clearGmailToken() {
  localStorage.removeItem(GMAIL_TOKEN_KEY);
}

// --- Auth token ---

export function getAuthToken(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem(AUTH_TOKEN_KEY);
}

export function getAuthEmail(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem(AUTH_EMAIL_KEY);
}

export function setAuthSession(token: string, email: string) {
  localStorage.setItem(AUTH_TOKEN_KEY, token);
  localStorage.setItem(AUTH_EMAIL_KEY, email);
}

export function clearAuthSession() {
  localStorage.removeItem(AUTH_TOKEN_KEY);
  localStorage.removeItem(AUTH_EMAIL_KEY);
  localStorage.removeItem(GMAIL_TOKEN_KEY);
}

export function isAuthenticated(): boolean {
  return !!getAuthToken();
}

function localApiHint(base: string): string {
  if (!base.includes("localhost")) {
    return "";
  }
  return " If your backend is running locally, try http://127.0.0.1:8000 instead of localhost.";
}

function explainApiFailure(base: string, path: string, rawMessage: string): string {
  const message = rawMessage.trim();

  if (path.startsWith("/auth/gmail")) {
    if (message.includes("GMAIL_CREDENTIALS_PATH is not configured")) {
      return "Gmail OAuth is not configured on the backend yet. Set GMAIL_CREDENTIALS_PATH to your Google OAuth client JSON file and restart the API.";
    }
    if (message.includes("Gmail OAuth credentials file was not found")) {
      return "The backend is missing the Gmail OAuth credentials file. Check GMAIL_CREDENTIALS_PATH and restart the API.";
    }
    if (message.includes("redirect_uri_mismatch")) {
      return "Google rejected the OAuth redirect URI. Add your frontend login URL, such as http://127.0.0.1:4173/login, to the authorized redirect URIs in Google Cloud.";
    }
  }

  if (!message) {
    return `Could not reach the API at ${base}.${localApiHint(base)}`;
  }

  return message;
}

async function apiFetch<T>(path: string, options?: RequestInit): Promise<T> {
  const base = getApiUrl();
  if (!base) throw new Error("API URL not configured. Go to Settings to set it.");
  const token = getGmailToken();
  const authToken = getAuthToken();
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(authToken ? { Authorization: `Bearer ${authToken}` } : token ? { Authorization: `Bearer ${token}` } : {}),
    ...(options?.headers as Record<string, string> || {}),
  };
  let res: Response;
  try {
    res = await fetch(`${base}${path}`, { ...options, headers });
  } catch {
    throw new Error(
      `Could not reach the API at ${base}. Make sure the backend is running and reachable from the browser.${localApiHint(base)}`,
    );
  }
  if (!res.ok) {
    const body = await res.text().catch(() => "");
    let parsedMessage = body || res.statusText;
    try {
      const payload = JSON.parse(body);
      if (typeof payload?.message === "string" && payload.message.trim()) {
        parsedMessage = payload.message;
      } else if (typeof payload?.detail === "string" && payload.detail.trim()) {
        parsedMessage = payload.detail;
      }
    } catch {
      // Keep the original response body when it is not JSON.
    }
    throw new Error(`API ${res.status}: ${explainApiFailure(base, path, parsedMessage)}`);
  }
  return res.json();
}

// --- Auth ---

export interface GmailAuthUrlResponse {
  auth_url: string;
}

export async function getGmailAuthUrl(): Promise<string> {
  const { auth_url } = await apiFetch<GmailAuthUrlResponse>("/auth/gmail/url");
  return auth_url;
}

export interface GmailCallbackResponse {
  access_token: string;
  email: string;
}

export async function exchangeGmailCode(
  code: string,
  state?: string | null,
  redirectUri?: string,
): Promise<GmailCallbackResponse> {
  return apiFetch<GmailCallbackResponse>("/auth/gmail/callback", {
    method: "POST",
    body: JSON.stringify({
      code,
      state: state || undefined,
      redirect_uri: redirectUri || undefined,
    }),
  });
}

export interface AuthUser {
  id: string;
  email: string;
  full_name: string;
  created_at?: string;
}

export interface AuthSessionResponse {
  error: boolean;
  token: string;
  expires_at: string;
  user: AuthUser;
}

export interface AuthStateResponse {
  authenticated: boolean;
  expires_at?: string;
  user?: AuthUser;
}

export async function loginWithPassword(email: string, password: string): Promise<AuthSessionResponse> {
  return apiFetch<AuthSessionResponse>("/auth/login", {
    method: "POST",
    body: JSON.stringify({ email, password }),
  });
}

export async function signupWithPassword(
  fullName: string,
  email: string,
  password: string,
): Promise<AuthSessionResponse> {
  return apiFetch<AuthSessionResponse>("/auth/signup", {
    method: "POST",
    body: JSON.stringify({
      full_name: fullName,
      email,
      password,
    }),
  });
}

export async function fetchCurrentSession(): Promise<AuthStateResponse> {
  return apiFetch<AuthStateResponse>("/auth/me", {
    method: "GET",
  });
}

export async function logoutSession(): Promise<{ ok: boolean }> {
  return apiFetch<{ ok: boolean }>("/auth/logout", {
    method: "POST",
  });
}

export interface ProviderConnectionState {
  provider: string;
  status: string;
  account_hint: string;
  sync_enabled: boolean;
  dry_run_only: boolean;
  last_tested_at: string | null;
  notes: string;
}

export async function fetchProviderConnection(provider: string): Promise<ProviderConnectionState> {
  return apiFetch<ProviderConnectionState>(`/providers/${provider}/connection`);
}

export async function saveProviderConnection(
  provider: string,
  payload: ProviderConnectionState,
): Promise<ProviderConnectionState> {
  return apiFetch<ProviderConnectionState>(`/providers/${provider}/connection`, {
    method: "PUT",
    body: JSON.stringify(payload),
  });
}

export interface WorkspacePolicy {
  allow_newsletter_mark_read: boolean;
  newsletter_confidence_threshold: number;
  allow_promo_archive: boolean;
  promo_archive_age_days: number;
  allow_low_priority_cleanup: boolean;
  low_priority_age_days: number;
  allow_spam_trash_recommendations: boolean;
  auto_label_recommendations: boolean;
  require_review_for_attachments: boolean;
  require_review_for_finance: boolean;
  require_review_for_personal: boolean;
}

export interface WorkspaceSettings {
  preferred_provider: string;
  dry_run_default: boolean;
  default_scan_limit: number;
  default_batch_size: number;
  default_confidence_threshold: number;
  default_email_preview_limit: number;
  default_recommendation_preview_limit: number;
  follow_up_radar_enabled: boolean;
  follow_up_after_hours: number;
  follow_up_priority_floor: string;
  onboarding_completed: boolean;
  operator_mode: string;
  policy: WorkspacePolicy;
  updated_at?: string;
}

export async function fetchWorkspaceSettings(): Promise<WorkspaceSettings> {
  return apiFetch<WorkspaceSettings>("/settings/workspace");
}

export async function saveWorkspaceSettings(
  payload: WorkspaceSettings,
): Promise<WorkspaceSettings> {
  return apiFetch<WorkspaceSettings>("/settings/workspace", {
    method: "PUT",
    body: JSON.stringify(payload),
  });
}

export async function activateGmailWorkspace(email: string): Promise<void> {
  const current = await fetchWorkspaceSettings();
  await saveProviderConnection("gmail", {
    provider: "gmail",
    status: "connected",
    account_hint: email,
    sync_enabled: true,
    dry_run_only: false,
    last_tested_at: new Date().toISOString(),
    notes: "Connected through the InboxAnchor Gmail frontend flow.",
  });
  await saveWorkspaceSettings({
    ...current,
    preferred_provider: "gmail",
    default_scan_limit: Math.max(current.default_scan_limit, 10000),
    default_batch_size: Math.max(current.default_batch_size, 1000),
    default_email_preview_limit: Math.max(current.default_email_preview_limit, 250),
    default_recommendation_preview_limit: Math.max(
      current.default_recommendation_preview_limit,
      400,
    ),
  });
}

// --- Emails ---

export interface FetchEmailsParams {
  limit?: number;
  offset?: number;
  q?: string;
  category?: string;
  priority?: string;
  unread_only?: boolean;
  time_range?: MailboxTimeRange;
}

export interface FetchEmailsResponse {
  emails: EmailMessage[];
  total: number;
}

export async function fetchEmails(params?: FetchEmailsParams): Promise<FetchEmailsResponse> {
  const qs = new URLSearchParams();
  if (params?.limit) qs.set("limit", String(params.limit));
  if (params?.offset) qs.set("offset", String(params.offset));
  if (params?.q) qs.set("q", params.q);
  if (params?.category) qs.set("category", params.category);
  if (params?.priority) qs.set("priority", params.priority);
  if (params?.unread_only) qs.set("unread_only", "true");
  if (params?.time_range) qs.set("time_range", params.time_range);
  const query = qs.toString();
  return apiFetch<FetchEmailsResponse>(`/emails${query ? `?${query}` : ""}`);
}

export async function fetchEmailById(
  emailId: string,
  timeRange?: MailboxTimeRange,
): Promise<EmailMessage> {
  const qs = new URLSearchParams();
  if (timeRange) qs.set("time_range", timeRange);
  const query = qs.toString();
  return apiFetch<EmailMessage>(`/emails/${emailId}${query ? `?${query}` : ""}`);
}

export interface ReplySendResponse {
  ok: boolean;
  emailId: string;
  provider: string;
  toAddress: string;
  details: string;
}

export async function sendReply(
  emailId: string,
  body: string,
  timeRange?: MailboxTimeRange,
): Promise<ReplySendResponse> {
  const qs = new URLSearchParams();
  if (timeRange) qs.set("time_range", timeRange);
  const query = qs.toString();
  return apiFetch<ReplySendResponse>(`/emails/${emailId}/reply${query ? `?${query}` : ""}`, {
    method: "POST",
    body: JSON.stringify({ body }),
  });
}

// --- Classifications ---

export async function fetchClassifications(
  timeRange?: MailboxTimeRange,
): Promise<Record<string, EmailClassification>> {
  const qs = new URLSearchParams();
  if (timeRange) qs.set("time_range", timeRange);
  const query = qs.toString();
  return apiFetch<Record<string, EmailClassification>>(`/classifications${query ? `?${query}` : ""}`);
}

// --- Recommendations ---

export async function fetchRecommendations(
  emailId?: string | null,
  timeRange?: MailboxTimeRange,
): Promise<EmailRecommendation[]> {
  const qs = new URLSearchParams();
  if (emailId) qs.set("email_id", emailId);
  if (timeRange) qs.set("time_range", timeRange);
  const query = qs.toString();
  return apiFetch<EmailRecommendation[]>(`/recommendations${query ? `?${query}` : ""}`);
}

// --- Action Items ---

export async function fetchActionItems(
  emailId: string,
  timeRange?: MailboxTimeRange,
): Promise<EmailActionItem[]> {
  const qs = new URLSearchParams();
  if (timeRange) qs.set("time_range", timeRange);
  const query = qs.toString();
  return apiFetch<EmailActionItem[]>(`/emails/${emailId}/actions${query ? `?${query}` : ""}`);
}

// --- Digest ---

export async function fetchDigest(timeRange?: MailboxTimeRange): Promise<InboxDigest> {
  const qs = new URLSearchParams();
  if (timeRange) qs.set("time_range", timeRange);
  const query = qs.toString();
  return apiFetch<InboxDigest>(`/digest${query ? `?${query}` : ""}`);
}

// --- Triage actions ---

export async function applyRecommendation(
  emailId: string,
  action: string,
  timeRange?: MailboxTimeRange,
): Promise<void> {
  const qs = new URLSearchParams();
  if (timeRange) qs.set("time_range", timeRange);
  const query = qs.toString();
  await apiFetch(`/recommendations/${emailId}/apply${query ? `?${query}` : ""}`, {
    method: "POST",
    body: JSON.stringify({ action }),
  });
}

export async function applyAllSafe(timeRange?: MailboxTimeRange): Promise<void> {
  const qs = new URLSearchParams();
  if (timeRange) qs.set("time_range", timeRange);
  const query = qs.toString();
  await apiFetch(`/recommendations/apply-all-safe${query ? `?${query}` : ""}`, { method: "POST" });
}

// --- Approve / Block ---

export async function approveRecommendation(
  emailId: string,
  action: string,
  timeRange?: MailboxTimeRange,
): Promise<void> {
  const qs = new URLSearchParams();
  if (timeRange) qs.set("time_range", timeRange);
  const query = qs.toString();
  await apiFetch(`/recommendations/${emailId}/approve${query ? `?${query}` : ""}`, {
    method: "POST",
    body: JSON.stringify({ action }),
  });
}

export async function blockRecommendation(
  emailId: string,
  action: string,
  timeRange?: MailboxTimeRange,
): Promise<void> {
  const qs = new URLSearchParams();
  if (timeRange) qs.set("time_range", timeRange);
  const query = qs.toString();
  await apiFetch(`/recommendations/${emailId}/block${query ? `?${query}` : ""}`, {
    method: "POST",
    body: JSON.stringify({ action }),
  });
}

// --- Webhook health ---

export interface WebhookHealthResponse {
  status: "healthy" | "degraded" | "down";
  last_event_at: string | null;
  uptime_seconds: number;
  connected_clients: number;
}

export async function fetchWebhookHealth(): Promise<WebhookHealthResponse> {
  return apiFetch<WebhookHealthResponse>("/health/webhook");
}

// --- Ops / command center ---

export interface OpsWorkflowCard {
  slug: string;
  label: string;
  description: string;
  impact: string;
}

export interface OpsOverview {
  provider: string;
  timeRange: MailboxTimeRange;
  timeRangeLabel: string;
  timeRangeOptions: MailboxTimeRangeOption[];
  runId: string;
  unreadCount: number;
  highPriorityCount: number;
  safeCleanupCount: number;
  needsApprovalCount: number;
  blockedCount: number;
  autoLabelCandidates: number;
  attachmentsCount: number;
  cachedEmailsCount: number;
  cachedUnreadCount: number;
  hydratedEmailsCount: number;
  oldestCachedAt: string | null;
  newestCachedAt: string | null;
  mailboxMemory?: {
    targetCount: number;
    processedTotal: number;
    resumeOffset: number;
    remainingCount: number;
    completed: boolean;
    fullMailboxMode?: boolean;
    includeBody: boolean;
    unreadOnly: boolean;
    lastBackfillAt: string | null;
  };
  categoryCounts: Record<string, number>;
  summary: string;
  liveConnected: boolean;
  providerStatus: string;
  accountHint: string;
  workflows: OpsWorkflowCard[];
}

export interface WorkflowMutationResult {
  count?: number;
  labelsApplied?: number;
  cleanupApplied?: number;
  cachedCount?: number;
  hydratedCount?: number;
  processedTotal?: number;
  resumeOffset?: number;
  remainingCount?: number;
  completed?: boolean;
  deletedLabelCount?: number;
  deletedLabels?: string[];
  overview: OpsOverview;
}

export interface OpsProgress {
  provider: string;
  time_range: MailboxTimeRange;
  time_range_label: string;
  mode: "scan" | "backfill" | "workflow";
  status: "idle" | "running" | "complete" | "error" | "paused";
  stage: string;
  target_count: number;
  processed_count: number;
  read_count: number;
  action_item_count: number;
  recommendation_count: number;
  batch_count: number;
  cached_count: number;
  hydrated_count: number;
  labeled_count: number;
  labels_removed_count: number;
  archived_count: number;
  marked_read_count: number;
  trashed_count: number;
  reply_sent_count: number;
  oldest_cached_at?: string | null;
  newest_cached_at?: string | null;
  latest_subject?: string | null;
  latest_action?: string | null;
  run_id?: string | null;
  error?: string | null;
  updated_at: string;
}

export async function fetchOpsOverview(timeRange?: MailboxTimeRange): Promise<OpsOverview> {
  const qs = new URLSearchParams();
  if (timeRange) qs.set("time_range", timeRange);
  const query = qs.toString();
  return apiFetch<OpsOverview>(`/ops/overview${query ? `?${query}` : ""}`);
}

export async function fetchOpsProgress(timeRange?: MailboxTimeRange): Promise<OpsProgress> {
  const qs = new URLSearchParams();
  if (timeRange) qs.set("time_range", timeRange);
  const query = qs.toString();
  return apiFetch<OpsProgress>(`/ops/progress${query ? `?${query}` : ""}`);
}

export async function runOpsScan(timeRange?: MailboxTimeRange): Promise<OpsOverview> {
  return apiFetch<OpsOverview>("/ops/scan", {
    method: "POST",
    body: JSON.stringify({ force_refresh: true, time_range: timeRange }),
  });
}

export async function runMailboxBackfill(timeRange?: MailboxTimeRange): Promise<WorkflowMutationResult> {
  return apiFetch<WorkflowMutationResult>("/ops/backfill", {
    method: "POST",
    body: JSON.stringify({
      force_refresh: false,
      limit: null,
      batch_size: 250,
      include_body: false,
      unread_only: false,
      time_range: timeRange,
    }),
  });
}

export async function runMailboxClassification(
  timeRange?: MailboxTimeRange,
): Promise<WorkflowMutationResult> {
  return apiFetch<WorkflowMutationResult>("/ops/classify-cache", {
    method: "POST",
    body: JSON.stringify({ force_refresh: true, time_range: timeRange }),
  });
}

export async function runAutoLabel(timeRange?: MailboxTimeRange): Promise<WorkflowMutationResult> {
  return apiFetch<WorkflowMutationResult>("/ops/auto-label", {
    method: "POST",
    body: JSON.stringify({ force_refresh: true, time_range: timeRange }),
  });
}

export async function runLabelCleanup(timeRange?: MailboxTimeRange): Promise<WorkflowMutationResult> {
  return apiFetch<WorkflowMutationResult>("/ops/clean-labels", {
    method: "POST",
    body: JSON.stringify({ force_refresh: false, time_range: timeRange }),
  });
}

export async function runSafeCleanupWorkflow(
  timeRange?: MailboxTimeRange,
): Promise<WorkflowMutationResult> {
  return apiFetch<WorkflowMutationResult>("/ops/safe-cleanup", {
    method: "POST",
    body: JSON.stringify({ force_refresh: true, time_range: timeRange }),
  });
}

export async function runIndustrialReadWorkflow(
  timeRange?: MailboxTimeRange,
): Promise<WorkflowMutationResult> {
  return apiFetch<WorkflowMutationResult>("/ops/industrial-read", {
    method: "POST",
    body: JSON.stringify({ force_refresh: false, time_range: timeRange }),
  });
}

export async function runFullAnchorWorkflow(
  timeRange?: MailboxTimeRange,
): Promise<WorkflowMutationResult> {
  return apiFetch<WorkflowMutationResult>("/ops/full-anchor", {
    method: "POST",
    body: JSON.stringify({ force_refresh: true, time_range: timeRange }),
  });
}

export interface EmailAlias {
  id: number;
  owner_email: string;
  provider: string;
  alias_address: string;
  target_email: string;
  alias_type: string;
  label: string;
  purpose: string;
  note: string;
  status: "active" | "revoked";
  created_at: string;
  revoked_at?: string | null;
}

export interface EmailAliasListResponse {
  items: EmailAlias[];
  count: number;
  mode?: "plus" | "managed";
  domain?: string | null;
  managed_enabled?: boolean;
  managed_ready?: boolean;
  managed_resolver_configured?: boolean;
  managed_resolver_base_url?: string | null;
  managed_public_backend_ready?: boolean;
  managed_inbound_ready?: boolean;
  managed_blockers?: string[];
  plus_fallback_enabled?: boolean;
}

export async function fetchEmailAliases(status?: "active" | "revoked"): Promise<EmailAliasListResponse> {
  const qs = new URLSearchParams();
  if (status) qs.set("status", status);
  const query = qs.toString();
  return apiFetch<EmailAliasListResponse>(`/aliases${query ? `?${query}` : ""}`);
}

export async function generateEmailAlias(payload: {
  label?: string;
  purpose?: string;
}): Promise<EmailAlias> {
  return apiFetch<EmailAlias>("/aliases/generate", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function revokeEmailAlias(aliasId: number): Promise<EmailAlias> {
  return apiFetch<EmailAlias>(`/aliases/${aliasId}/revoke`, {
    method: "POST",
  });
}

// --- SSE stream ---

export type StreamStatus = "connecting" | "connected" | "disconnected" | "error";

export function createEmailStream(
  onMessage: (data: unknown) => void,
  onStatusChange?: (status: StreamStatus) => void,
): EventSource | null {
  const base = getApiUrl();
  if (!base) return null;
  const token = getGmailToken();
  const authToken = getAuthToken();
  const url = new URL(`${base}/stream/emails`);
  if (authToken) url.searchParams.set("token", authToken);
  else if (token) url.searchParams.set("token", token);
  onStatusChange?.("connecting");
  const es = new EventSource(url.toString());
  es.onopen = () => onStatusChange?.("connected");
  es.onmessage = (ev) => {
    try {
      onMessage(JSON.parse(ev.data));
    } catch {
      // ignore parse errors
    }
  };
  es.onerror = () => {
    if (es.readyState === EventSource.CLOSED) {
      onStatusChange?.("disconnected");
    } else {
      onStatusChange?.("error");
    }
  };
  return es;
}
