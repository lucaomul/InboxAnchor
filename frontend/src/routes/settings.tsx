import { createFileRoute, Link } from "@tanstack/react-router";
import { useState, useEffect } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { toast } from "sonner";
import {
  fetchProviderConnection,
  getApiUrl,
  getGmailAuthUrl,
  setApiUrl,
  setAuthSession,
  saveProviderConnection,
  exchangeGmailCode,
  fetchWebhookHealth,
} from "@/lib/api-client";
import { Anchor, ArrowLeft, CheckCircle, ExternalLink, LogOut, Mail, Server, Activity, AlertCircle, RefreshCw } from "lucide-react";

export const Route = createFileRoute("/settings")({
  head: () => ({
    meta: [
      { title: "Settings — InboxAnchor" },
      { name: "description", content: "Configure your InboxAnchor API connection and Gmail account." },
    ],
  }),
  component: SettingsPage,
});

function SettingsPage() {
  const [apiUrl, setApiUrlState] = useState("");
  const [saved, setSaved] = useState(false);
  const [gmailConnected, setGmailConnected] = useState(false);
  const [gmailAccountHint, setGmailAccountHint] = useState("");
  const [gmailLoading, setGmailLoading] = useState(false);
  const [gmailError, setGmailError] = useState("");
  const [apiError, setApiError] = useState("");
  const [webhookStatus, setWebhookStatus] = useState<string | null>(null);
  const [webhookLoading, setWebhookLoading] = useState(false);
  const [webhookDetails, setWebhookDetails] = useState<{ uptime: number; clients: number; lastEvent: string | null } | null>(null);

  useEffect(() => {
    const currentApiUrl = getApiUrl();
    setApiUrlState(currentApiUrl);
    if (currentApiUrl) {
      void loadGmailConnection();
    }
  }, []);

  // Handle OAuth callback code from URL
  useEffect(() => {
    if (typeof window === "undefined") return;
    const params = new URLSearchParams(window.location.search);
    const code = params.get("code");
    if (code) {
      setGmailLoading(true);
      exchangeGmailCode(code)
        .then((res) => {
          setAuthSession(res.access_token, res.email);
          setGmailConnected(true);
          setGmailAccountHint(res.email);
          // Clean up URL
          window.history.replaceState({}, "", "/settings");
        })
        .catch((err) => setGmailError(err.message))
        .finally(async () => {
          await loadGmailConnection();
          setGmailLoading(false);
        });
    }
  }, []);

  const loadGmailConnection = async () => {
    try {
      const connection = await fetchProviderConnection("gmail");
      setGmailConnected(connection.status === "connected");
      setGmailAccountHint(connection.account_hint || "");
    } catch {
      setGmailConnected(false);
      setGmailAccountHint("");
    }
  };

  const handleSaveApi = () => {
    setApiError("");
    try {
      setApiUrl(apiUrl);
      setSaved(true);
      toast.success("API URL saved");
      void loadGmailConnection();
      setTimeout(() => setSaved(false), 2000);
    } catch (err) {
      setApiError(err instanceof Error ? err.message : "Invalid URL format. Must be a valid http:// or https:// URL.");
      toast.error("Invalid URL format");
    }
  };

  const checkWebhookHealth = async (retryCount = 0) => {
    setWebhookLoading(true);
    try {
      const health = await fetchWebhookHealth();
      setWebhookStatus(health.status);
      setWebhookDetails({
        uptime: health.uptime_seconds,
        clients: health.connected_clients,
        lastEvent: health.last_event_at,
      });
      toast.success(`Webhook is ${health.status}`);
    } catch {
      if (retryCount < 2) {
        toast(`Retrying health check... (${retryCount + 1}/3)`);
        setTimeout(() => checkWebhookHealth(retryCount + 1), 2000);
        return;
      }
      setWebhookStatus("unreachable");
      setWebhookDetails(null);
      toast.error("Webhook unreachable after 3 attempts");
    } finally {
      setWebhookLoading(false);
    }
  };

  const handleConnectGmail = async () => {
    setGmailLoading(true);
    setGmailError("");
    try {
      const authUrl = await getGmailAuthUrl();
      window.location.href = authUrl;
    } catch (err: unknown) {
      setGmailError(err instanceof Error ? err.message : "Failed to get auth URL");
      setGmailLoading(false);
    }
  };

  const handleDisconnect = async () => {
    setGmailLoading(true);
    setGmailError("");
    try {
      await saveProviderConnection("gmail", {
        provider: "gmail",
        status: "configured",
        account_hint: "",
        sync_enabled: false,
        dry_run_only: true,
        last_tested_at: null,
        notes: "Disconnected from the InboxAnchor frontend settings workspace.",
      });
      setGmailConnected(false);
      setGmailAccountHint("");
      toast.success("Gmail provider disconnected");
    } catch (err) {
      setGmailError(err instanceof Error ? err.message : "Unable to disconnect Gmail");
    } finally {
      setGmailLoading(false);
    }
  };

  return (
    <div className="flex h-screen flex-col bg-background">
      {/* Top bar */}
      <header className="flex items-center gap-3 border-b border-border px-5 py-3 shrink-0">
        <Link to="/" className="text-muted-foreground hover:text-foreground transition-colors">
          <ArrowLeft className="w-4 h-4" />
        </Link>
        <Anchor className="w-5 h-5 text-primary" />
        <h1 className="text-base font-bold text-foreground tracking-tight">Settings</h1>
      </header>

      <div className="flex-1 overflow-y-auto">
        <div className="max-w-xl mx-auto px-5 py-8 space-y-8">
          {/* API Connection */}
          <section className="rounded-lg border border-border bg-card p-5 space-y-4">
            <div className="flex items-center gap-2">
              <Server className="w-5 h-5 text-primary" />
              <h2 className="text-sm font-semibold text-foreground">API Connection</h2>
            </div>
            <p className="text-xs text-muted-foreground">
              Enter the base URL of your deployed InboxAnchor backend (e.g. https://inboxanchor.example.com/api).
            </p>
            <div className="flex gap-2">
              <Input
                value={apiUrl}
                onChange={(e) => setApiUrlState(e.target.value)}
                placeholder="https://your-api.example.com"
                className="flex-1"
              />
              <Button onClick={handleSaveApi} size="sm">
                {saved ? (
                  <span className="flex items-center gap-1">
                    <CheckCircle className="w-3.5 h-3.5" /> Saved
                  </span>
                ) : (
                  "Save"
                )}
              </Button>
            </div>
            {apiError && (
              <p className="text-xs text-destructive flex items-center gap-1">
                <AlertCircle className="w-3 h-3 shrink-0" /> {apiError}
              </p>
            )}
          </section>

          {/* Webhook Health */}
          <section className="rounded-lg border border-border bg-card p-5 space-y-4">
            <div className="flex items-center gap-2">
              <Activity className="w-5 h-5 text-primary" />
              <h2 className="text-sm font-semibold text-foreground">Webhook Health</h2>
              {webhookStatus && (
                <Badge
                  variant={webhookStatus === "healthy" ? "safe" : webhookStatus === "degraded" ? "warning" : "critical"}
                  className="text-[10px]"
                >
                  {webhookStatus}
                </Badge>
              )}
            </div>
            <p className="text-xs text-muted-foreground">
              Check the health of the webhook/SSE stream endpoint on your InboxAnchor server.
            </p>
            <Button onClick={() => checkWebhookHealth()} disabled={webhookLoading || !apiUrl} size="sm" variant="outline">
              {webhookLoading ? <RefreshCw className="w-3.5 h-3.5 animate-spin mr-1" /> : <RefreshCw className="w-3.5 h-3.5 mr-1" />}
              Check Health
            </Button>
            {webhookDetails && (
              <div className="grid grid-cols-3 gap-3 text-center">
                <div className="rounded-md bg-secondary p-2">
                  <p className="text-lg font-bold text-foreground">{webhookDetails.clients}</p>
                  <p className="text-[10px] text-muted-foreground">Clients</p>
                </div>
                <div className="rounded-md bg-secondary p-2">
                  <p className="text-lg font-bold text-foreground">{Math.floor(webhookDetails.uptime / 60)}m</p>
                  <p className="text-[10px] text-muted-foreground">Uptime</p>
                </div>
                <div className="rounded-md bg-secondary p-2">
                  <p className="text-xs font-medium text-foreground truncate">
                    {webhookDetails.lastEvent ? new Date(webhookDetails.lastEvent).toLocaleTimeString() : "—"}
                  </p>
                  <p className="text-[10px] text-muted-foreground">Last Event</p>
                </div>
              </div>
            )}
          </section>

          {/* Gmail OAuth */}
          <section className="rounded-lg border border-border bg-card p-5 space-y-4">
            <div className="flex items-center gap-2">
              <Mail className="w-5 h-5 text-primary" />
              <h2 className="text-sm font-semibold text-foreground">Gmail Account</h2>
            </div>
            <p className="text-xs text-muted-foreground">
              Connect your Gmail account to allow InboxAnchor to read, label, and triage the live inbox through Google OAuth.
            </p>

            {gmailError && (
              <div className="rounded-md bg-destructive/10 border border-destructive/30 p-3">
                <p className="text-xs text-destructive">{gmailError}</p>
              </div>
            )}

            {gmailConnected ? (
              <div className="flex items-center justify-between rounded-md bg-safe/10 border border-safe/30 p-3">
                <div className="flex items-center gap-2">
                  <CheckCircle className="w-4 h-4 text-safe" />
                  <div>
                    <span className="text-sm text-foreground">Gmail connected</span>
                    {gmailAccountHint && (
                      <p className="text-[11px] text-muted-foreground">{gmailAccountHint}</p>
                    )}
                  </div>
                  <Badge variant="safe" className="text-[10px]">Active</Badge>
                </div>
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={handleDisconnect}
                  className="text-muted-foreground"
                  disabled={gmailLoading}
                >
                  <LogOut className="w-3.5 h-3.5 mr-1" />
                  Disconnect
                </Button>
              </div>
            ) : (
              <Button
                onClick={handleConnectGmail}
                disabled={gmailLoading || !apiUrl}
                className="w-full"
              >
                {gmailLoading ? (
                  "Redirecting to Google..."
                ) : (
                  <span className="flex items-center gap-2">
                    <ExternalLink className="w-4 h-4" />
                    Connect Gmail Account
                  </span>
                )}
              </Button>
            )}
            {!apiUrl && !gmailConnected && (
              <p className="text-xs text-warning">Set the API URL above first to enable Gmail connection.</p>
            )}
          </section>
        </div>
      </div>
    </div>
  );
}
