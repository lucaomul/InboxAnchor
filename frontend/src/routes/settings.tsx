import { createFileRoute, Link } from "@tanstack/react-router";
import { useState, useEffect } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { toast } from "sonner";
import {
  activateGmailWorkspace,
  fetchProviderConnection,
  fetchEmailAliases,
  fetchWorkspaceSettings,
  generateEmailAlias,
  getApiUrl,
  getAuthEmail,
  getGmailAuthUrl,
  revokeEmailAlias,
  setApiUrl,
  saveWorkspaceSettings,
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
  const [aliasLabel, setAliasLabel] = useState("");
  const [aliasPurpose, setAliasPurpose] = useState("");
  const [aliasMode, setAliasMode] = useState<"plus" | "managed">("plus");
  const [aliasDomain, setAliasDomain] = useState("");
  const [managedAliasEnabled, setManagedAliasEnabled] = useState(false);
  const [managedAliasReady, setManagedAliasReady] = useState(false);
  const [managedAliasResolverConfigured, setManagedAliasResolverConfigured] = useState(false);
  const [managedAliasResolverBaseUrl, setManagedAliasResolverBaseUrl] = useState("");
  const [managedAliasPublicBackendReady, setManagedAliasPublicBackendReady] = useState(false);
  const [managedAliasInboundReady, setManagedAliasInboundReady] = useState(false);
  const [managedAliasBlockers, setManagedAliasBlockers] = useState<string[]>([]);
  const [plusFallbackEnabled, setPlusFallbackEnabled] = useState(false);
  const [aliasItems, setAliasItems] = useState<Array<{
    id: number;
    alias_address: string;
    label: string;
    purpose: string;
    note: string;
    status: "active" | "revoked";
    created_at: string;
  }>>([]);
  const [aliasLoading, setAliasLoading] = useState(false);
  const [aliasError, setAliasError] = useState("");
  const frontendLoginRedirect =
    typeof window === "undefined" ? "http://127.0.0.1:4173/login" : `${window.location.origin}/login`;
  const authEmail = getAuthEmail();
  const canGenerateFallbackAlias =
    plusFallbackEnabled && gmailConnected && (!managedAliasEnabled || !managedAliasReady);

  useEffect(() => {
    const currentApiUrl = getApiUrl();
    setApiUrlState(currentApiUrl);
    if (currentApiUrl) {
      void loadGmailConnection();
      void loadAliases();
    }
  }, []);

  // Handle OAuth callback code from URL
  useEffect(() => {
    if (typeof window === "undefined") return;
    const params = new URLSearchParams(window.location.search);
    const code = params.get("code");
    const state = params.get("state");
    if (code) {
      setGmailLoading(true);
      exchangeGmailCode(code, state, `${window.location.origin}/login`)
        .then(async (res) => {
          setAuthSession(res.access_token, res.email);
          await activateGmailWorkspace(res.email);
          setGmailConnected(true);
          setGmailAccountHint(res.email);
          // Clean up URL
          window.history.replaceState({}, "", "/settings");
        })
        .catch((err) => setGmailError(err.message))
        .finally(async () => {
          await loadGmailConnection();
          await loadAliases();
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

  const loadAliases = async () => {
    if (!getApiUrl() || !getAuthEmail()) {
      setAliasItems([]);
      return;
    }
    try {
      const response = await fetchEmailAliases();
      setAliasItems(response.items);
      setAliasMode(response.mode === "managed" ? "managed" : "plus");
      setAliasDomain(response.domain || "");
      setManagedAliasEnabled(Boolean(response.managed_enabled));
      setManagedAliasReady(Boolean(response.managed_ready));
      setManagedAliasResolverConfigured(Boolean(response.managed_resolver_configured));
      setManagedAliasResolverBaseUrl(response.managed_resolver_base_url || "");
      setManagedAliasPublicBackendReady(Boolean(response.managed_public_backend_ready));
      setManagedAliasInboundReady(Boolean(response.managed_inbound_ready));
      setManagedAliasBlockers(response.managed_blockers || []);
      setPlusFallbackEnabled(Boolean(response.plus_fallback_enabled));
      setAliasError("");
    } catch (err) {
      setAliasError(err instanceof Error ? err.message : "Unable to load aliases");
    }
  };

  const handleSaveApi = () => {
    setApiError("");
    try {
      setApiUrl(apiUrl);
      setSaved(true);
      toast.success("API URL saved");
      void loadGmailConnection();
      void loadAliases();
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
      const workspace = await fetchWorkspaceSettings();
      await saveProviderConnection("gmail", {
        provider: "gmail",
        status: "configured",
        account_hint: "",
        sync_enabled: false,
        dry_run_only: true,
        last_tested_at: null,
        notes: "Disconnected from the InboxAnchor frontend settings workspace.",
      });
      if (workspace.preferred_provider === "gmail") {
        await saveWorkspaceSettings({
          ...workspace,
          preferred_provider: "fake",
        });
      }
      setGmailConnected(false);
      setGmailAccountHint("");
      setAliasItems([]);
      toast.success("Gmail provider disconnected");
    } catch (err) {
      setGmailError(err instanceof Error ? err.message : "Unable to disconnect Gmail");
    } finally {
      setGmailLoading(false);
    }
  };

  const handleGenerateAlias = async () => {
    setAliasLoading(true);
    setAliasError("");
    try {
      const created = await generateEmailAlias({
        label: aliasLabel,
        purpose: aliasPurpose,
      });
      setAliasItems((previous) => [created, ...previous]);
      setAliasMode(created.alias_type === "managed" ? "managed" : "plus");
      if (created.alias_type === "managed") {
        const generatedDomain = created.alias_address.split("@")[1] || "";
        setAliasDomain(generatedDomain);
        setManagedAliasEnabled(true);
      }
      setAliasLabel("");
      setAliasPurpose("");
      toast.success("Privacy alias created");
    } catch (err) {
      const message = err instanceof Error ? err.message : "Unable to create alias";
      setAliasError(message);
      toast.error(message);
    } finally {
      setAliasLoading(false);
    }
  };

  const handleRevokeAlias = async (aliasId: number) => {
    setAliasLoading(true);
    setAliasError("");
    try {
      const revoked = await revokeEmailAlias(aliasId);
      setAliasItems((previous) =>
        previous.map((item) => (item.id === revoked.id ? revoked : item)),
      );
      toast.success("Alias revoked");
    } catch (err) {
      const message = err instanceof Error ? err.message : "Unable to revoke alias";
      setAliasError(message);
      toast.error(message);
    } finally {
      setAliasLoading(false);
    }
  };

  const handleCopyAlias = async (aliasAddress: string) => {
    try {
      await navigator.clipboard.writeText(aliasAddress);
      toast.success("Alias copied");
    } catch {
      toast.error("Could not copy the alias address");
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
                placeholder="http://127.0.0.1:8000"
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
            <p className="text-[11px] leading-5 text-muted-foreground">
              For local development, prefer <span className="font-medium text-foreground">http://127.0.0.1:8000</span>.
              Some browsers resolve <span className="font-medium text-foreground">localhost</span> differently and can miss a
              backend that is only bound to IPv4.
            </p>
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
            <div className="rounded-md border border-border bg-secondary/30 p-3">
              <p className="text-xs leading-5 text-muted-foreground">
                Before you connect Gmail:
              </p>
              <p className="mt-2 text-xs leading-5 text-muted-foreground">
                1. Set <span className="font-medium text-foreground">GMAIL_CREDENTIALS_PATH</span> on the backend.
              </p>
              <p className="text-xs leading-5 text-muted-foreground">
                2. Add <span className="font-medium text-foreground">{frontendLoginRedirect}</span> as an authorized redirect URI in Google Cloud if you are using this React frontend.
              </p>
            </div>

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

          <section className="rounded-lg border border-border bg-card p-5 space-y-4">
            <div className="flex items-center gap-2">
              <Mail className="w-5 h-5 text-primary" />
              <h2 className="text-sm font-semibold text-foreground">Privacy Aliases</h2>
            </div>
            <p className="text-xs text-muted-foreground">
              Generate privacy aliases for signups, newsletters, and vendors without giving your
              core inbox address to every service you touch. When live Gmail routing is available,
              InboxAnchor can also auto-label alias mail and keep it out of the primary inbox.
            </p>
            <div className="rounded-md border border-border bg-secondary/30 p-3 text-xs leading-5 text-muted-foreground">
              {managedAliasEnabled && managedAliasReady ? (
                <>
                  InboxAnchor is using its managed alias domain
                  {" "}
                  <span className="font-medium text-foreground">{aliasDomain}</span>
                  {" "}
                  for cleaner addresses like
                  {" "}
                  <span className="font-medium text-foreground">
                    travel1234567@{aliasDomain}
                  </span>.
                </>
              ) : managedAliasEnabled ? (
                <>
                  InboxAnchor sees the managed alias domain
                  {" "}
                  <span className="font-medium text-foreground">{aliasDomain}</span>
                  {" "}
                  but the inbound path is not fully live yet, so product-owned aliases like
                  {" "}
                  <span className="font-medium text-foreground">
                    travel1234567@{aliasDomain}
                  </span>
                  {" "}
                  will not forward until the remaining setup is finished.
                </>
              ) : (
                <>
                  InboxAnchor alias domain is not configured yet.
                  {plusFallbackEnabled ? (
                    <>
                      {" "}
                      This workspace still allows Gmail plus-addressing as an explicit fallback,
                      but those aliases expose part of the underlying mailbox address because Gmail
                      requires the original local-part before the
                      {" "}
                      <span className="font-medium text-foreground">+</span>
                      {" "}
                      tag.
                    </>
                  ) : (
                    <>
                      {" "}
                      Gmail plus-addressing fallback is disabled so InboxAnchor does not expose
                      your real mailbox address.
                    </>
                  )}
                </>
              )}
            </div>
            {managedAliasEnabled && !managedAliasReady ? (
              <div className="rounded-md border border-warning/30 bg-warning/5 p-3 text-[11px] leading-5 text-warning space-y-2">
                <p>
                  Managed aliases are not live yet.
                  {" "}
                  {!managedAliasResolverConfigured ? "The backend resolver secret is missing. " : ""}
                  {!managedAliasPublicBackendReady ? "The Cloudflare worker has no public backend URL it can reach. " : ""}
                  {!managedAliasInboundReady ? "Cloudflare inbound routing still needs to be marked ready. " : ""}
                </p>
                {managedAliasResolverBaseUrl ? (
                  <p>
                    Current resolver base URL:
                    {" "}
                    <span className="font-medium text-foreground">{managedAliasResolverBaseUrl}</span>
                  </p>
                ) : null}
                {managedAliasBlockers.map((item) => (
                  <p key={item}>
                    {item}
                  </p>
                ))}
                {plusFallbackEnabled ? (
                  <p>
                    InboxAnchor can still generate a working Gmail fallback alias while the managed
                    path is offline.
                  </p>
                ) : null}
              </div>
            ) : null}
            {!managedAliasEnabled ? (
              <div className="rounded-md border border-warning/30 bg-warning/5 p-3 text-[11px] leading-5 text-warning">
                To get product-owned aliases like
                {" "}
                <span className="font-medium">travel1234567@inboxanchor.com</span>
                {" "}
                instead of exposing the Gmail local-part, configure
                {" "}
                <span className="font-medium">INBOXANCHOR_ALIAS_MANAGED_ENABLED=true</span>
                {" "}
                and
                {" "}
                <span className="font-medium">INBOXANCHOR_ALIAS_DOMAIN=your-domain.com</span>
                {" "}
                on the backend after inbound forwarding is ready.
              </div>
            ) : null}
            {!authEmail ? (
              <p className="text-xs text-warning">Log in to manage privacy aliases.</p>
            ) : !gmailConnected && !managedAliasEnabled && plusFallbackEnabled ? (
              <p className="text-xs text-warning">Connect Gmail first to generate privacy aliases.</p>
            ) : (
              <>
                <div className="grid gap-3 sm:grid-cols-2">
                  <Input
                    value={aliasLabel}
                    onChange={(e) => setAliasLabel(e.target.value)}
                    placeholder="Alias label (example: travel)"
                  />
                  <Input
                    value={aliasPurpose}
                    onChange={(e) => setAliasPurpose(e.target.value)}
                    placeholder="Purpose (example: airline promos)"
                  />
                </div>
                <Button
                  onClick={handleGenerateAlias}
                  disabled={
                    aliasLoading ||
                    (managedAliasEnabled && !managedAliasReady && !canGenerateFallbackAlias) ||
                    (!managedAliasEnabled && !plusFallbackEnabled)
                  }
                >
                  {aliasLoading
                    ? "Generating..."
                    : managedAliasEnabled && managedAliasReady
                      ? "Generate InboxAnchor alias"
                      : managedAliasEnabled && canGenerateFallbackAlias
                        ? "Generate Gmail fallback alias"
                      : managedAliasEnabled
                        ? "Managed alias setup incomplete"
                      : plusFallbackEnabled
                        ? "Generate Gmail fallback alias"
                        : "Managed alias domain required"}
                </Button>
                {aliasError ? (
                  <p className="text-xs text-destructive">{aliasError}</p>
                ) : null}
                <div className="space-y-3">
                  {aliasItems.length === 0 ? (
                    <p className="text-xs text-muted-foreground">
                      No aliases created yet. Generate one for newsletters, marketplaces, or any
                      source that does not need your main address.
                    </p>
                  ) : (
                    aliasItems.map((alias) => (
                      <div
                        key={alias.id}
                        className="rounded-lg border border-border bg-secondary/20 p-3"
                      >
                        <div className="flex flex-wrap items-center justify-between gap-3">
                          <div>
                            <p className="text-sm font-medium text-foreground">{alias.alias_address}</p>
                            <p className="text-[11px] text-muted-foreground">
                              {alias.label || "Unlabeled"}{alias.purpose ? ` · ${alias.purpose}` : ""}
                            </p>
                          </div>
                          <Badge
                            variant={alias.status === "active" ? "safe" : "muted"}
                            className="text-[10px]"
                          >
                            {alias.status}
                          </Badge>
                        </div>
                        <p className="mt-2 text-[11px] leading-5 text-muted-foreground">{alias.note}</p>
                        <div className="mt-3 flex flex-wrap gap-2">
                          <Button
                            size="sm"
                            variant="outline"
                            onClick={() => handleCopyAlias(alias.alias_address)}
                          >
                            Copy alias
                          </Button>
                          {alias.status === "active" ? (
                            <Button
                              size="sm"
                              variant="ghost"
                              onClick={() => handleRevokeAlias(alias.id)}
                              disabled={aliasLoading}
                            >
                              Revoke
                            </Button>
                          ) : null}
                        </div>
                      </div>
                    ))
                  )}
                </div>
              </>
            )}
          </section>
        </div>
      </div>
    </div>
  );
}
