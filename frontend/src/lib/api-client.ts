// InboxAnchor API Client
// Connects to the deployed InboxAnchor Python backend

import type {
  EmailMessage,
  EmailClassification,
  EmailRecommendation,
  EmailActionItem,
  InboxDigest,
} from "./mock-data";
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
  const res = await fetch(`${base}${path}`, { ...options, headers });
  if (!res.ok) {
    const body = await res.text().catch(() => "");
    throw new Error(`API ${res.status}: ${body || res.statusText}`);
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

export async function exchangeGmailCode(code: string): Promise<GmailCallbackResponse> {
  return apiFetch<GmailCallbackResponse>("/auth/gmail/callback", {
    method: "POST",
    body: JSON.stringify({ code }),
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

// --- Emails ---

export interface FetchEmailsParams {
  limit?: number;
  offset?: number;
  q?: string;
  category?: string;
  priority?: string;
  unread_only?: boolean;
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
  const query = qs.toString();
  return apiFetch<FetchEmailsResponse>(`/emails${query ? `?${query}` : ""}`);
}

// --- Classifications ---

export async function fetchClassifications(): Promise<Record<string, EmailClassification>> {
  return apiFetch<Record<string, EmailClassification>>("/classifications");
}

// --- Recommendations ---

export async function fetchRecommendations(): Promise<EmailRecommendation[]> {
  return apiFetch<EmailRecommendation[]>("/recommendations");
}

// --- Action Items ---

export async function fetchActionItems(emailId: string): Promise<EmailActionItem[]> {
  return apiFetch<EmailActionItem[]>(`/emails/${emailId}/actions`);
}

// --- Digest ---

export async function fetchDigest(): Promise<InboxDigest> {
  return apiFetch<InboxDigest>("/digest");
}

// --- Triage actions ---

export async function applyRecommendation(emailId: string, action: string): Promise<void> {
  await apiFetch(`/recommendations/${emailId}/apply`, {
    method: "POST",
    body: JSON.stringify({ action }),
  });
}

export async function applyAllSafe(): Promise<void> {
  await apiFetch("/recommendations/apply-all-safe", { method: "POST" });
}

// --- Approve / Block ---

export async function approveRecommendation(emailId: string, action: string): Promise<void> {
  await apiFetch(`/recommendations/${emailId}/approve`, {
    method: "POST",
    body: JSON.stringify({ action }),
  });
}

export async function blockRecommendation(emailId: string, action: string): Promise<void> {
  await apiFetch(`/recommendations/${emailId}/block`, {
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
  runId: string;
  unreadCount: number;
  highPriorityCount: number;
  safeCleanupCount: number;
  needsApprovalCount: number;
  blockedCount: number;
  autoLabelCandidates: number;
  attachmentsCount: number;
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
  overview: OpsOverview;
}

export async function fetchOpsOverview(): Promise<OpsOverview> {
  return apiFetch<OpsOverview>("/ops/overview");
}

export async function runOpsScan(): Promise<OpsOverview> {
  return apiFetch<OpsOverview>("/ops/scan", {
    method: "POST",
    body: JSON.stringify({ force_refresh: true }),
  });
}

export async function runAutoLabel(): Promise<WorkflowMutationResult> {
  return apiFetch<WorkflowMutationResult>("/ops/auto-label", {
    method: "POST",
    body: JSON.stringify({ force_refresh: true }),
  });
}

export async function runSafeCleanupWorkflow(): Promise<WorkflowMutationResult> {
  return apiFetch<WorkflowMutationResult>("/ops/safe-cleanup", {
    method: "POST",
    body: JSON.stringify({ force_refresh: true }),
  });
}

export async function runFullAnchorWorkflow(): Promise<WorkflowMutationResult> {
  return apiFetch<WorkflowMutationResult>("/ops/full-anchor", {
    method: "POST",
    body: JSON.stringify({ force_refresh: true }),
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
