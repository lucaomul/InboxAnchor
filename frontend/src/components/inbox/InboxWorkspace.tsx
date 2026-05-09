import { Link } from "@tanstack/react-router";
import { useState, useMemo, useEffect } from "react";
import { MetricBar } from "@/components/inbox/MetricBar";
import { EmailList } from "@/components/inbox/EmailList";
import { EmailDetail } from "@/components/inbox/EmailDetail";
import { RecommendationLanes } from "@/components/inbox/RecommendationLanes";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import type { EmailCategory, PriorityLevel } from "@/lib/mock-data";
import {
  useEmailDetail,
  useEmails,
  useRecommendations,
  useDigest,
  useActionItems,
  useEmailStream,
  useWebhookHealth,
} from "@/hooks/use-inbox-data";
import { useAuth } from "@/hooks/use-auth";
import { useDebounce } from "@/hooks/use-debounce";
import { useTheme } from "@/hooks/use-theme";
import { useOpsProgress } from "@/hooks/use-ops";
import { useMailboxTimeRange } from "@/hooks/use-mailbox-time-range";
import { StickmanLoader, StickmanEmpty, StickmanStyles } from "@/components/StickmenAnimations";
import { Input } from "@/components/ui/input";
import {
  Activity,
  Anchor,
  AlertTriangle,
  ChevronLeft,
  ChevronRight,
  Home,
  Inbox,
  LogOut,
  Palette,
  Search,
  Settings,
  Shield,
  User,
  Wifi,
  WifiOff,
  X,
} from "lucide-react";
import { getApiUrl } from "@/lib/api-client";
import { MAILBOX_TIME_RANGE_OPTIONS } from "@/lib/time-range";
import type { MailboxTimeRange } from "@/lib/time-range";

type View = "inbox" | "lanes";

const PAGE_SIZE = 25;

export function InboxWorkspace() {
  const { email: userEmail, logout } = useAuth();
  const [selectedEmailId, setSelectedEmailId] = useState<string | null>(null);
  const [view, setView] = useState<View>("inbox");
  const [searchQuery, setSearchQuery] = useState("");
  const debouncedSearch = useDebounce(searchQuery, 300);
  const [filterCategory, setFilterCategory] = useState<EmailCategory | "">("");
  const [filterPriority, setFilterPriority] = useState<PriorityLevel | "">("");
  const [page, setPage] = useState(0);
  const [showThemePicker, setShowThemePicker] = useState(false);
  const { theme, setTheme, themes } = useTheme();
  const { timeRange, setTimeRange } = useMailboxTimeRange();

  const apiConnected = typeof window !== "undefined" && !!getApiUrl();
  const emailQueryParams = useMemo(
    () => ({
      limit: PAGE_SIZE,
      offset: page * PAGE_SIZE,
      q: debouncedSearch || undefined,
      category: filterCategory || undefined,
      priority: filterPriority || undefined,
      time_range: timeRange,
    }),
    [debouncedSearch, filterCategory, filterPriority, page, timeRange],
  );
  const {
    data: emailsData,
    isLoading: emailsLoading,
    isError: emailsError,
    error: emailsQueryError,
  } = useEmails(emailQueryParams);
  const {
    data: recommendations,
    isLoading: recsLoading,
    error: recommendationsError,
  } = useRecommendations(
    view === "lanes" ? null : selectedEmailId,
    timeRange,
    view === "lanes" || !!selectedEmailId,
  );
  const { data: digest, isLoading: digestLoading, error: digestError } = useDigest(timeRange);
  const { data: selectedActions } = useActionItems(selectedEmailId, timeRange);
  const { data: selectedEmailDetail } = useEmailDetail(selectedEmailId, timeRange);
  const { data: webhookHealth } = useWebhookHealth();
  const { status: streamStatus } = useEmailStream();
  const { data: progress } = useOpsProgress(timeRange, emailsLoading || digestLoading || recsLoading);

  const emails = emailsData?.emails || [];
  const recs = recommendations || [];
  const dig = digest || {
    totalUnread: 0,
    categoryCounts: {},
    highPriorityIds: [],
    summary: "Loading...",
  };

  useEffect(() => {
    setPage(0);
    setSelectedEmailId(null);
  }, [debouncedSearch, filterCategory, filterPriority, timeRange]);

  useEffect(() => {
    if (!selectedEmailId && emails.length > 0) {
      setSelectedEmailId(emails[0].id);
    }
  }, [emails, selectedEmailId]);

  useEffect(() => {
    const maxPage = Math.max(0, Math.ceil((emailsData?.total || 0) / PAGE_SIZE) - 1);
    if (page > maxPage) {
      setPage(maxPage);
    }
  }, [emailsData?.total, page]);

  const selectedEmailSummary = emails.find((e) => e.id === selectedEmailId) || null;
  const selectedEmail = selectedEmailSummary
    ? { ...selectedEmailSummary, ...(selectedEmailDetail || {}) }
    : selectedEmailDetail || null;
  const selectedClassification = selectedEmail?.classification || null;
  const selectedRecs = selectedEmailId
    ? recs.filter((r) => r.emailId === selectedEmailId)
    : [];

  const hasFilters =
    !!debouncedSearch
    || !!filterCategory
    || !!filterPriority
    || timeRange !== "all_time";
  const totalFiltered = emailsData?.total || 0;
  const totalPages = Math.max(1, Math.ceil(totalFiltered / PAGE_SIZE));
  const pagedEmails = emails;
  const isLoading = emailsLoading;
  const showWorkspaceLoader =
    emailsLoading || digestLoading || recsLoading || progress?.status === "running";
  const progressStats = progress
    ? progress.mode === "backfill"
      ? [
          { label: "Fetched", value: progress.processed_count },
          { label: "Cached", value: progress.cached_count },
          { label: "Hydrated", value: progress.hydrated_count },
          { label: "Batches", value: progress.batch_count },
        ]
      : progress.mode === "workflow"
        ? [
            { label: "Emails read", value: progress.read_count },
            { label: "Labeled", value: progress.labeled_count },
            { label: "Archived", value: progress.archived_count },
            { label: "Marked read", value: progress.marked_read_count },
          ]
      : [
          { label: "Emails read", value: progress.read_count },
          { label: "Processed", value: progress.processed_count },
          { label: "Actions", value: progress.action_item_count },
          { label: "Suggestions", value: progress.recommendation_count },
        ]
    : [];
  const progressActivity = progress?.latest_subject
    ? `${progress.latest_action ? `${String(progress.latest_action).replaceAll("_", " ")} · ` : ""}${progress.latest_subject}`
    : undefined;
  const workspaceLoaderMessage = progress?.mode === "backfill"
    ? `Building mailbox memory. ${progress.cached_count} emails are cached so far, and ${progress.hydrated_count} already have full bodies ready.`
    : progress?.mode === "workflow"
      ? `InboxAnchor is applying live mailbox actions inside ${MAILBOX_TIME_RANGE_OPTIONS.find((option) => option.value === timeRange)?.label.toLowerCase() || "the selected window"}.`
      : progress?.target_count
        ? `Syncing unread mail. ${progress.read_count} emails read and ${progress.processed_count} processed out of ${progress.target_count} in this live batch.`
        : progress?.status === "running"
          ? "Connecting the live mailbox and preparing the unread working set."
          : "Syncing unread mail. Use W, S, the arrow keys, or space while InboxAnchor caches the batch."
  const workspaceError =
    (emailsQueryError instanceof Error && emailsQueryError.message) ||
    (recommendationsError instanceof Error && recommendationsError.message) ||
    (digestError instanceof Error && digestError.message) ||
    "";

  const webhookStatusColor = webhookHealth?.status === "healthy"
    ? "text-safe"
    : webhookHealth?.status === "degraded"
      ? "text-warning"
      : "text-muted-foreground";

  const streamStatusLabel = streamStatus === "connected"
    ? "SSE Connected"
    : streamStatus === "connecting"
      ? "Connecting..."
      : streamStatus === "error"
        ? "SSE Error"
        : "SSE Off";

  return (
    <div className="flex h-screen flex-col bg-background">
      <StickmanStyles />
      <header className="flex items-center justify-between border-b border-border px-5 py-3 shrink-0">
        <div className="flex items-center gap-2.5">
          <Anchor className="w-5 h-5 text-primary" />
          <div>
            <h1 className="text-base font-bold text-foreground tracking-tight">InboxAnchor</h1>
            <p className="text-[10px] text-muted-foreground">Inbox workspace module</p>
          </div>
          {apiConnected ? (
            <Badge variant="safe" className="text-[10px] gap-1">
              <Wifi className="w-2.5 h-2.5" /> Live
            </Badge>
          ) : (
            <Badge variant="muted" className="text-[10px] gap-1">
              <WifiOff className="w-2.5 h-2.5" /> Demo
            </Badge>
          )}
          {apiConnected && (
            <div
              className="flex items-center gap-1.5 ml-2"
              title={`Webhook: ${webhookHealth?.status || "unknown"} | ${streamStatusLabel}`}
            >
              <Activity className={`w-3.5 h-3.5 ${webhookStatusColor}`} />
              <span
                className={`text-[10px] ${
                  streamStatus === "connected"
                    ? "text-safe"
                    : streamStatus === "error"
                      ? "text-destructive"
                      : "text-muted-foreground"
                }`}
              >
                {streamStatusLabel}
              </span>
            </div>
          )}
        </div>
        <div className="flex items-center gap-3">
          <div className="flex items-center gap-1 rounded-lg bg-secondary p-0.5">
            <Link
              to="/"
              className="flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-medium text-muted-foreground transition-colors hover:text-foreground"
            >
              <Home className="w-3.5 h-3.5" />
              Command Center
            </Link>
            <button
              onClick={() => setView("inbox")}
              className={`flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-medium transition-colors ${
                view === "inbox"
                  ? "bg-card text-foreground shadow-sm"
                  : "text-muted-foreground hover:text-foreground"
              }`}
            >
              <Inbox className="w-3.5 h-3.5" />
              Inbox
            </button>
            <button
              onClick={() => setView("lanes")}
              className={`flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-medium transition-colors ${
                view === "lanes"
                  ? "bg-card text-foreground shadow-sm"
                  : "text-muted-foreground hover:text-foreground"
              }`}
            >
              <Shield className="w-3.5 h-3.5" />
              Safety Lanes
            </button>
          </div>
          <div className="relative">
            <button
              onClick={() => setShowThemePicker(!showThemePicker)}
              className="text-muted-foreground hover:text-foreground transition-colors"
              title="Change theme"
            >
              <Palette className="w-4 h-4" />
            </button>
            {showThemePicker && (
              <div className="absolute right-0 top-8 z-50 rounded-lg border border-border bg-card p-2 shadow-lg min-w-[160px] animate-scale-in">
                {themes.map((t) => (
                  <button
                    key={t.name}
                    onClick={() => {
                      setTheme(t.name);
                      setShowThemePicker(false);
                    }}
                    className={`flex items-center gap-2 w-full rounded-md px-3 py-1.5 text-xs transition-colors hover:bg-secondary ${
                      theme === t.name
                        ? "bg-secondary text-foreground font-medium"
                        : "text-muted-foreground"
                    }`}
                  >
                    <span
                      className="w-3 h-3 rounded-full border border-border shrink-0"
                      style={{ backgroundColor: t.preview }}
                    />
                    {t.label}
                  </button>
                ))}
              </div>
            )}
          </div>
          <Link to="/settings" className="text-muted-foreground hover:text-foreground transition-colors">
            <Settings className="w-4 h-4" />
          </Link>
          {userEmail ? (
            <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
              <User className="w-3.5 h-3.5" />
              <span className="max-w-[120px] truncate">{userEmail}</span>
              <button onClick={logout} className="hover:text-foreground transition-colors" title="Log out">
                <LogOut className="w-3.5 h-3.5" />
              </button>
            </div>
          ) : (
            <div className="flex items-center gap-2">
              <Link
                to="/login"
                className="inline-flex items-center rounded-md px-3 py-1.5 text-xs font-medium text-muted-foreground transition-colors hover:bg-secondary hover:text-foreground"
              >
                Log in
              </Link>
              <Link
                to="/login"
                className="inline-flex items-center rounded-md bg-primary px-3 py-1.5 text-xs font-medium text-primary-foreground transition-colors hover:bg-primary/90"
              >
                Create account
              </Link>
            </div>
          )}
        </div>
      </header>

      <div className="border-b border-border px-5 py-2.5 shrink-0 flex items-center gap-3 flex-wrap">
        <div className="relative flex-1 min-w-[200px] max-w-sm">
          <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-muted-foreground" />
          <Input
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            placeholder="Search emails..."
            className="pl-8 h-8 text-xs"
          />
        </div>
        <select
          value={timeRange}
          onChange={(e) => setTimeRange(e.target.value as MailboxTimeRange)}
          className="h-8 rounded-md border border-input bg-transparent px-2 text-xs text-foreground focus:outline-none focus:ring-1 focus:ring-ring"
        >
          {MAILBOX_TIME_RANGE_OPTIONS.map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
        </select>
        <select
          value={filterCategory}
          onChange={(e) => setFilterCategory(e.target.value as EmailCategory | "")}
          className="h-8 rounded-md border border-input bg-transparent px-2 text-xs text-foreground focus:outline-none focus:ring-1 focus:ring-ring"
        >
          <option value="">All Categories</option>
          <option value="urgent">Urgent</option>
          <option value="work">Work</option>
          <option value="finance">Finance</option>
          <option value="newsletter">Newsletter</option>
          <option value="promo">Promo</option>
          <option value="personal">Personal</option>
          <option value="opportunity">Opportunity</option>
          <option value="low_priority">Low Priority</option>
        </select>
        <select
          value={filterPriority}
          onChange={(e) => setFilterPriority(e.target.value as PriorityLevel | "")}
          className="h-8 rounded-md border border-input bg-transparent px-2 text-xs text-foreground focus:outline-none focus:ring-1 focus:ring-ring"
        >
          <option value="">All Priorities</option>
          <option value="critical">Critical</option>
          <option value="high">High</option>
          <option value="medium">Medium</option>
          <option value="low">Low</option>
        </select>
        {hasFilters && (
          <button
            onClick={() => {
              setSearchQuery("");
              setTimeRange("all_time");
              setFilterCategory("");
              setFilterPriority("");
            }}
            className="flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground transition-colors"
          >
            <X className="w-3 h-3" /> Clear
          </button>
        )}
      </div>

      <div className="border-b border-border px-5 py-3 shrink-0">
        {digestLoading ? (
          <div className="space-y-2">
            <Skeleton className="h-4 w-32" />
            <Skeleton className="h-3 w-full max-w-lg" />
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-4 mt-3">
              {[1, 2, 3, 4].map((i) => <Skeleton key={i} className="h-20 rounded-lg" />)}
            </div>
          </div>
        ) : (
          <>
            <p className="text-sm text-foreground font-medium mb-2">Inbox Briefing</p>
            <p className="text-xs text-muted-foreground leading-relaxed mb-3">{dig.summary}</p>
            <MetricBar digest={dig} />
          </>
        )}
      </div>
      {workspaceError && (
        <div className="border-b border-border bg-amber-500/5 px-5 py-3">
          <div className="flex items-start gap-3 rounded-xl border border-amber-500/30 bg-card px-4 py-3">
            <AlertTriangle className="mt-0.5 h-4 w-4 text-amber-500" />
            <div>
              <p className="text-sm font-medium text-foreground">
                The live mailbox is connected, but this workspace could not load the unread set.
              </p>
              <p className="mt-1 text-xs leading-5 text-muted-foreground">{workspaceError}</p>
            </div>
          </div>
        </div>
      )}

      <div className="flex flex-1 min-h-0">
        {view === "inbox" ? (
          <>
            <div className="w-[360px] shrink-0 border-r border-border overflow-y-auto">
              {showWorkspaceLoader ? (
                <div className="flex h-full items-center justify-center p-5">
                  <StickmanLoader
                    playful
                    stage={progress?.stage ? `Stage: ${progress.stage}` : undefined}
                    stats={progressStats}
                    activity={progressActivity}
                    message={workspaceLoaderMessage}
                  />
                </div>
              ) : emailsError ? (
                <div className="flex items-center justify-center h-full p-5">
                  <StickmanEmpty
                    message={
                      workspaceError ||
                      "Failed to load emails. Check your API connection."
                    }
                  />
                </div>
              ) : totalFiltered === 0 ? (
                <div className="flex items-center justify-center h-full p-5">
                  <StickmanEmpty
                    message={hasFilters ? "No emails match your filters." : "No emails found."}
                  />
                </div>
              ) : (
                <>
                  <EmailList
                    emails={pagedEmails}
                    selectedId={selectedEmailId}
                    onSelect={setSelectedEmailId}
                  />
                  {totalPages > 1 && (
                    <div className="flex items-center justify-between border-t border-border px-3 py-2">
                      <Button
                        size="sm"
                        variant="ghost"
                        disabled={page === 0}
                        onClick={() => {
                          setSelectedEmailId(null);
                          setPage((p) => Math.max(0, p - 1));
                        }}
                      >
                        <ChevronLeft className="w-3.5 h-3.5" />
                      </Button>
                      <span className="text-[10px] text-muted-foreground">
                        {page + 1} / {totalPages} ({totalFiltered} emails)
                      </span>
                      <Button
                        size="sm"
                        variant="ghost"
                        disabled={page >= totalPages - 1}
                        onClick={() => {
                          setSelectedEmailId(null);
                          setPage((p) => Math.min(totalPages - 1, p + 1));
                        }}
                      >
                        <ChevronRight className="w-3.5 h-3.5" />
                      </Button>
                    </div>
                  )}
                </>
              )}
            </div>
            <div className="flex-1 overflow-y-auto">
              {selectedEmail && selectedClassification ? (
                <EmailDetail
                  email={selectedEmail}
                  classification={selectedClassification}
                  recommendations={selectedRecs}
                  actionItems={selectedActions || []}
                  timeRange={timeRange}
                />
              ) : (
                <div className="flex items-center justify-center h-full">
                  <StickmanLoader message="Select an email to view details" />
                </div>
              )}
            </div>
          </>
        ) : (
          <div className="flex-1 overflow-y-auto p-5">
            {recsLoading ? (
              <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
                {[1, 2, 3].map((i) => (
                  <div
                    key={i}
                    className="rounded-lg border border-border bg-card/50 p-4 space-y-3"
                  >
                    <Skeleton className="h-5 w-24" />
                    {[1, 2].map((j) => <Skeleton key={j} className="h-16 rounded-md" />)}
                  </div>
                ))}
              </div>
            ) : recs.length === 0 ? (
              <StickmanEmpty message="No recommendations yet. Emails are being analyzed..." />
            ) : (
              <RecommendationLanes
                recommendations={recs}
                emails={emails}
                onSelectEmail={(id) => {
                  setSelectedEmailId(id);
                  setView("inbox");
                }}
              />
            )}
          </div>
        )}
      </div>
    </div>
  );
}
