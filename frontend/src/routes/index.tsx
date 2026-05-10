import type { ReactNode } from "react";
import { createFileRoute, Link } from "@tanstack/react-router";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { StickmanLoader } from "@/components/StickmenAnimations";
import { useAuth } from "@/hooks/use-auth";
import {
  useOpsOverview,
  useOpsProgress,
  useRunAutoLabel,
  useRunMailboxClassification,
  useRunLabelCleanup,
  useRunMailboxBackfill,
  useRunFullAnchorWorkflow,
  useRunIndustrialReadWorkflow,
  useRunOpsScan,
  useRunSafeCleanupWorkflow,
} from "@/hooks/use-ops";
import { useTheme } from "@/hooks/use-theme";
import { useMailboxTimeRange } from "@/hooks/use-mailbox-time-range";
import {
  Activity,
  Anchor,
  AlertTriangle,
  ArrowRight,
  Eraser,
  Inbox,
  Layers3,
  LogOut,
  MailOpen,
  Palette,
  Settings,
  ShieldCheck,
  Sparkles,
  Tags,
  User,
  Wand2,
  Wifi,
  WifiOff,
} from "lucide-react";
import { MAILBOX_TIME_RANGE_OPTIONS } from "@/lib/time-range";
import type { MailboxTimeRange } from "@/lib/time-range";

export const Route = createFileRoute("/")({
  head: () => ({
    meta: [
      { title: "InboxAnchor — Mailbox Command Center" },
      {
        name: "description",
        content:
          "Safety-first inbox operations for labeling, cleanup, unread control, and human-approved mailbox automation.",
      },
    ],
  }),
  component: CommandCenter,
});

const CATEGORY_LABELS: Record<string, string> = {
  urgent: "Urgent",
  work: "Work",
  finance: "Finance",
  newsletter: "Newsletter",
  promo: "Promo",
  personal: "Personal",
  opportunity: "Opportunity",
  low_priority: "Low Priority",
  spam_like: "Spam-Like",
};

function CommandCenter() {
  const { email: userEmail, logout } = useAuth();
  const { theme, setTheme, themes } = useTheme();
  const { timeRange, setTimeRange } = useMailboxTimeRange();
  const { data: overview, isLoading, isError, error } = useOpsOverview(timeRange);
  const scanMutation = useRunOpsScan();
  const backfillMutation = useRunMailboxBackfill();
  const classifyMutation = useRunMailboxClassification();
  const autoLabelMutation = useRunAutoLabel();
  const cleanLabelsMutation = useRunLabelCleanup();
  const cleanupMutation = useRunSafeCleanupWorkflow();
  const industrialReadMutation = useRunIndustrialReadWorkflow();
  const fullAnchorMutation = useRunFullAnchorWorkflow();
  const overviewError = error instanceof Error ? error.message : "InboxAnchor could not load the live mailbox overview yet.";

  const busy =
    scanMutation.isPending ||
    backfillMutation.isPending ||
    classifyMutation.isPending ||
    autoLabelMutation.isPending ||
    cleanLabelsMutation.isPending ||
    cleanupMutation.isPending ||
    industrialReadMutation.isPending ||
    fullAnchorMutation.isPending;
  const shouldPollProgress =
    isLoading ||
    busy ||
    overview?.providerStatus === "checking" ||
    Boolean(overview?.mailboxMemory && !overview.mailboxMemory.completed);
  const { data: progress } = useOpsProgress(timeRange, shouldPollProgress);
  const showLoader =
    isLoading ||
    busy ||
    progress?.status === "running" ||
    overview?.providerStatus === "checking";
  const showPausedMailboxMemory =
    !showLoader &&
    overview?.liveConnected &&
    progress?.mode === "backfill" &&
    progress?.status === "paused";
  const progressStats = progress
    ? progress.mode === "backfill"
      ? [
          { label: "Fetched", value: progress.processed_count },
          { label: "Cached", value: progress.cached_count },
          { label: "Hydrated", value: progress.hydrated_count },
          { label: "Batches", value: progress.batch_count },
        ]
      : progress?.latest_action === "classify"
        ? [
            { label: "Emails read", value: progress.read_count },
            { label: "Prepared", value: progress.processed_count },
            { label: "Actions", value: progress.action_item_count },
            { label: "Suggestions", value: progress.recommendation_count },
          ]
      : progress.latest_action === "remove_labels"
        ? [
            { label: "Emails read", value: progress.read_count },
            { label: "Labels removed", value: progress.labels_removed_count },
            { label: "Processed", value: progress.processed_count },
            { label: "Remaining", value: Math.max(progress.target_count - progress.processed_count, 0) },
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
  const progressMessage = progress?.mode === "backfill"
    ? `Building mailbox memory. ${progress.cached_count} emails are cached so far, and ${progress.hydrated_count} already have full bodies ready.`
    : progress?.latest_action === "classify"
      ? `Preparing sender-aware classifications and safety recommendations from the cached unread working set before any live mailbox changes happen.`
    : progress?.mode === "workflow"
      ? `Applying live mailbox changes in ${overview?.timeRangeLabel?.toLowerCase() || "the selected window"}. Labels, archive actions, and read-state updates will keep moving while you wait.`
      : progress?.target_count
        ? `Mapping the unread working set. ${progress.processed_count} of ${progress.target_count} emails have been processed so far.`
        : overview?.providerStatus === "checking"
          ? "Connecting the live mailbox and preparing the unread scan."
          : "Mapping your mailbox. Use W, S, the arrow keys, or space while the unread cache settles.";

  const metricCards = overview
    ? [
        { label: "Unread mapped", value: overview.unreadCount, note: "live unread inventory" },
        { label: "High priority", value: overview.highPriorityCount, note: "threads needing attention" },
        { label: "Safe cleanups", value: overview.safeCleanupCount, note: "low-risk actions ready" },
        { label: "Mailbox memory", value: overview.cachedEmailsCount, note: "cached historical emails" },
      ]
    : [];

  return (
    <div className="min-h-screen bg-background">
      <header className="border-b border-border">
        <div className="mx-auto flex max-w-7xl items-center justify-between px-5 py-4">
          <div className="flex items-center gap-3">
            <Anchor className="h-6 w-6 text-primary" />
            <div>
              <h1 className="text-base font-bold tracking-tight text-foreground">InboxAnchor</h1>
              <p className="text-[11px] text-muted-foreground">
                Mailbox command center for cleanup, labeling, and unread control
              </p>
            </div>
            {overview?.liveConnected ? (
              <Badge variant="safe" className="gap-1 text-[10px]">
                <Wifi className="h-2.5 w-2.5" /> Live mailbox
              </Badge>
            ) : (
              <Badge variant="muted" className="gap-1 text-[10px]">
                <WifiOff className="h-2.5 w-2.5" /> Preview mode
              </Badge>
            )}
          </div>
          <div className="flex items-center gap-3">
            <Link
              to="/inbox"
              className="inline-flex items-center gap-1.5 rounded-md border border-border bg-card px-3 py-2 text-xs font-medium text-foreground transition-colors hover:bg-secondary"
            >
              <Inbox className="h-3.5 w-3.5" />
              Inbox workspace
            </Link>
            <Link to="/settings" className="text-muted-foreground transition-colors hover:text-foreground">
              <Settings className="h-4 w-4" />
            </Link>
            <div className="relative group">
              <button className="text-muted-foreground transition-colors hover:text-foreground" title="Theme">
                <Palette className="h-4 w-4" />
              </button>
              <div className="invisible absolute right-0 top-7 z-20 min-w-[160px] rounded-lg border border-border bg-card p-2 opacity-0 shadow-lg transition-all group-hover:visible group-hover:opacity-100">
                {themes.map((candidate) => (
                  <button
                    key={candidate.name}
                    onClick={() => setTheme(candidate.name)}
                    className={`flex w-full items-center gap-2 rounded-md px-3 py-1.5 text-xs transition-colors hover:bg-secondary ${
                      theme === candidate.name
                        ? "bg-secondary font-medium text-foreground"
                        : "text-muted-foreground"
                    }`}
                  >
                    <span
                      className="h-3 w-3 rounded-full border border-border"
                      style={{ backgroundColor: candidate.preview }}
                    />
                    {candidate.label}
                  </button>
                ))}
              </div>
            </div>
            {userEmail ? (
              <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
                <User className="h-3.5 w-3.5" />
                <span className="max-w-[140px] truncate">{userEmail}</span>
                <button onClick={logout} className="transition-colors hover:text-foreground" title="Log out">
                  <LogOut className="h-3.5 w-3.5" />
                </button>
              </div>
            ) : (
              <div className="flex items-center gap-2">
                <Link
                  to="/login"
                  className="inline-flex items-center rounded-md px-3 py-2 text-xs font-medium text-muted-foreground transition-colors hover:bg-secondary hover:text-foreground"
                >
                  Log in
                </Link>
                <Link
                  to="/login"
                  className="inline-flex items-center rounded-md bg-primary px-3 py-2 text-xs font-medium text-primary-foreground transition-colors hover:bg-primary/90"
                >
                  Create account
                </Link>
              </div>
            )}
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-7xl px-5 py-6">
        <section className="grid gap-5 lg:grid-cols-[1.3fr_0.9fr]">
          <div className="rounded-2xl border border-border bg-card p-6">
            <div className="flex items-start justify-between gap-4">
              <div className="space-y-3">
                <Badge variant="outline" className="gap-1 text-[10px] uppercase tracking-[0.18em]">
                  <Sparkles className="h-3 w-3" />
                  Mailbox upgrade system
                </Badge>
                <div>
                  <h2 className="text-3xl font-semibold tracking-tight text-foreground">
                    Make the real inbox cleaner without losing trust.
                  </h2>
                  <p className="mt-3 max-w-2xl text-sm leading-6 text-muted-foreground">
                    InboxAnchor is not another inbox client trying to replace Gmail. It is an
                    operations layer that reads unread mail, maps what matters, applies useful
                    labels, and executes only safe cleanup actions on top of Gmail, Yahoo, and
                    IMAP-family inboxes.
                  </p>
                </div>
                <div className="flex flex-wrap gap-2">
                  <div className="inline-flex items-center gap-2 rounded-md border border-border bg-background px-3 py-2 text-xs text-muted-foreground">
                    <span className="font-medium text-foreground">Target window</span>
                    <select
                      value={timeRange}
                      onChange={(e) => setTimeRange(e.target.value as MailboxTimeRange)}
                      className="bg-transparent text-xs text-foreground focus:outline-none"
                    >
                      {MAILBOX_TIME_RANGE_OPTIONS.map((option) => (
                        <option key={option.value} value={option.value}>
                          {option.label}
                        </option>
                      ))}
                    </select>
                  </div>
                  <Link
                    to="/inbox"
                    className="inline-flex items-center gap-1.5 rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground transition-colors hover:bg-primary/90"
                  >
                    Open inbox workspace
                    <ArrowRight className="h-4 w-4" />
                  </Link>
                  <Button
                    variant="outline"
                    onClick={() => scanMutation.mutate(timeRange)}
                    disabled={busy}
                  >
                    <Activity className="mr-2 h-4 w-4" />
                    Refresh unread scan
                  </Button>
                </div>
                {showLoader && (
                  <div className="rounded-2xl border border-border bg-background/70 p-4">
                    <StickmanLoader
                      playful
                      stage={progress?.stage ? `Stage: ${progress.stage}` : undefined}
                      stats={progressStats}
                      activity={progressActivity}
                      message={progressMessage}
                    />
                  </div>
                )}
                {showPausedMailboxMemory && (
                  <div className="rounded-2xl border border-border bg-background/70 p-4">
                    <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
                      <div className="space-y-2">
                        <p className="text-sm font-medium text-foreground">
                          Live mailbox connected. Historical mailbox memory is paused, not broken.
                        </p>
                        <p className="text-sm leading-6 text-muted-foreground">
                          InboxAnchor can already see the real unread set, and it has cached{" "}
                          <span className="font-medium text-foreground">{progress.cached_count}</span>{" "}
                          emails so far with{" "}
                          <span className="font-medium text-foreground">{progress.hydrated_count}</span>{" "}
                          full bodies ready instantly. Resume the backfill any time to keep working
                          deeper into the archive.
                        </p>
                      </div>
                      <div className="flex flex-wrap gap-2">
                        <Badge variant="outline">
                          {progress.target_count > 0
                            ? `${progress.processed_count} / ${progress.target_count} cached`
                            : `${progress.processed_count} cached`}
                        </Badge>
                        <Button
                          variant="outline"
                          onClick={() => backfillMutation.mutate(timeRange)}
                          disabled={busy}
                        >
                          Continue mailbox memory
                        </Button>
                      </div>
                    </div>
                  </div>
                )}
              </div>
            </div>

            <div className="mt-6 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
              {isLoading
                ? [1, 2, 3, 4].map((i) => <Skeleton key={i} className="h-24 rounded-xl" />)
                : metricCards.map((metric) => (
                    <div key={metric.label} className="rounded-xl border border-border bg-background p-4">
                      <p className="text-2xl font-bold text-foreground">{metric.value}</p>
                      <p className="text-sm font-medium text-foreground">{metric.label}</p>
                      <p className="text-xs text-muted-foreground">{metric.note}</p>
                    </div>
                  ))}
            </div>
            {isError && (
              <div className="mt-5 rounded-2xl border border-amber-500/30 bg-amber-500/5 p-4">
                <div className="flex items-start gap-3">
                  <AlertTriangle className="mt-0.5 h-4 w-4 text-amber-500" />
                  <div className="space-y-2">
                    <p className="text-sm font-medium text-foreground">
                      Gmail connected, but the live unread scan did not finish.
                    </p>
                    <p className="text-sm leading-6 text-muted-foreground">{overviewError}</p>
                    <p className="text-xs leading-5 text-muted-foreground">
                      This usually means the backend could not reach the live provider yet. Keep
                      the API URL pointed at the running backend, then retry a fresh unread scan.
                    </p>
                    <div className="pt-1">
                      <Button onClick={() => scanMutation.mutate(timeRange)} disabled={busy}>
                        {scanMutation.isPending ? "Retrying..." : "Retry unread scan"}
                      </Button>
                    </div>
                  </div>
                </div>
              </div>
            )}
          </div>

          <div className="rounded-2xl border border-border bg-card p-6">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-xs uppercase tracking-[0.18em] text-muted-foreground">
                  Provider status
                </p>
                <h3 className="mt-1 text-lg font-semibold text-foreground">
                  {overview?.provider ? overview.provider.toUpperCase() : "Connecting"}
                </h3>
              </div>
              <Badge
                variant={
                  overview?.providerStatus === "connected"
                    ? "safe"
                    : overview?.providerStatus === "configured"
                      ? "warning"
                      : "muted"
                }
                className="text-[10px]"
              >
                {overview?.providerStatus || "checking"}
              </Badge>
            </div>
            <div className="mt-4 space-y-3 text-sm text-muted-foreground">
              <p>
                Account: <span className="text-foreground">{overview?.accountHint || "Not connected yet"}</span>
              </p>
              <p>
                This product is meant to improve the mailbox itself, not only show a prettier
                inbox view. Labels, mark-read actions, and archive decisions can apply directly
                to the connected provider when safe.
              </p>
              <div className="rounded-xl border border-border bg-background p-4">
                <p className="text-sm font-medium text-foreground">Why this differentiates us</p>
                <ul className="mt-2 space-y-2 text-xs leading-5 text-muted-foreground">
                  <li>Labels are generated from classification, urgency, attachments, and action pressure.</li>
                  <li>Cleanup is executed only for low-risk items, not via reckless auto-delete behavior.</li>
                  <li>Unread scans and label sweeps work as an operational layer for Gmail and IMAP-family inboxes.</li>
                  <li>Mailbox memory caches older history locally so the product gets smarter without re-reading everything live.</li>
                </ul>
              </div>
              <div className="grid grid-cols-2 gap-3 rounded-xl border border-border bg-background p-4 text-xs text-muted-foreground">
                <div>
                  <p className="font-medium text-foreground">{overview?.cachedEmailsCount || 0}</p>
                  <p>historical emails cached</p>
                </div>
                <div>
                  <p className="font-medium text-foreground">{overview?.hydratedEmailsCount || 0}</p>
                  <p>full bodies ready instantly</p>
                </div>
              </div>
            </div>
          </div>
        </section>

        <section className="mt-6 grid gap-5 xl:grid-cols-[1.3fr_0.9fr]">
          <div className="rounded-2xl border border-border bg-card p-6">
            <div className="flex items-center gap-2">
              <Wand2 className="h-4 w-4 text-primary" />
              <h3 className="text-lg font-semibold text-foreground">Mailbox workflows</h3>
            </div>
            <p className="mt-2 text-sm text-muted-foreground">
              These workflows act on the real inbox state. They are meant to make Gmail, Yahoo,
              and IMAP-family inboxes visibly better even outside the app interface.
            </p>

            <div className="mt-5 grid gap-4 md:grid-cols-2">
              <WorkflowCard
                title="Build mailbox memory"
                icon={<Activity className="h-4 w-4" />}
                description="Backfill historical mailbox metadata into the local cache so years of email can be searched and hydrated without forcing a giant live triage run."
                impact={overview?.workflows.find((item) => item.slug === "backfill")?.impact}
                cta="Cache history"
                loading={backfillMutation.isPending}
                onClick={() => backfillMutation.mutate(timeRange)}
              />
              <WorkflowCard
                title="Prepare unread decisions"
                icon={<Sparkles className="h-4 w-4" />}
                description="Rebuild sender-aware classifications and safety recommendations from the cached unread working set before you label or clean anything."
                impact={overview?.workflows.find((item) => item.slug === "classify-cache")?.impact}
                cta="Prepare cache"
                loading={classifyMutation.isPending}
                onClick={() => classifyMutation.mutate(timeRange)}
              />
              <WorkflowCard
                title="Auto-label unread mail"
                icon={<Tags className="h-4 w-4" />}
                description="Apply one clean InboxAnchor label per unread email so the mailbox becomes easier to scan inside Gmail or Yahoo itself."
                impact={overview?.workflows.find((item) => item.slug === "auto-label")?.impact}
                cta="Run labels"
                loading={autoLabelMutation.isPending}
                onClick={() => autoLabelMutation.mutate(timeRange)}
              />
              <WorkflowCard
                title="Reset InboxAnchor labels"
                icon={<Eraser className="h-4 w-4" />}
                description="Remove only InboxAnchor-generated labels from the selected mailbox window without deleting or archiving any email."
                impact={overview?.workflows.find((item) => item.slug === "clean-labels")?.impact}
                cta="Clean labels"
                loading={cleanLabelsMutation.isPending}
                onClick={() => cleanLabelsMutation.mutate(timeRange)}
              />
              <WorkflowCard
                title="Industrial mark as read"
                icon={<MailOpen className="h-4 w-4" />}
                description="Mark the full cached unread working set as read in batched provider calls, no matter what category the emails fall into."
                impact={overview?.workflows.find((item) => item.slug === "industrial-read")?.impact}
                cta="Mark all read"
                loading={industrialReadMutation.isPending}
                onClick={() => industrialReadMutation.mutate(timeRange)}
              />
              <WorkflowCard
                title="Safe cleanup"
                icon={<ShieldCheck className="h-4 w-4" />}
                description="Mark newsletters or low-value items as read and archive safe promotions without touching risky mail."
                impact={overview?.workflows.find((item) => item.slug === "safe-cleanup")?.impact}
                cta="Run cleanup"
                loading={cleanupMutation.isPending}
                onClick={() => cleanupMutation.mutate(timeRange)}
              />
              <WorkflowCard
                title="Mailbox upgrade sweep"
                icon={<Layers3 className="h-4 w-4" />}
                description="Prepare unread decisions, label the set, then execute the safe cleanup batch so the provider inbox looks cleaner immediately."
                impact={overview?.workflows.find((item) => item.slug === "full-anchor")?.impact}
                cta="Upgrade mailbox"
                loading={fullAnchorMutation.isPending}
                onClick={() => fullAnchorMutation.mutate(timeRange)}
                featured
              />
              <WorkflowCard
                title="Inbox workspace"
                icon={<Inbox className="h-4 w-4" />}
                description="Drop into the inbox module for detail review, safety lanes, and one-email decision work."
                impact="Use this after the command center has organized the unread set."
                cta="Open inbox"
                onClick={undefined}
                href="/inbox"
              />
            </div>
          </div>

          <div className="rounded-2xl border border-border bg-card p-6">
            <div className="flex items-center gap-2">
              <Activity className="h-4 w-4 text-primary" />
              <h3 className="text-lg font-semibold text-foreground">Mailbox map</h3>
            </div>
            <p className="mt-2 text-sm text-muted-foreground">
              A quick snapshot of what is sitting unread right now.
            </p>
            <div className="mt-5 space-y-3">
              {isLoading
                ? (
                    <div className="rounded-2xl border border-dashed border-border bg-background/70 p-4">
                      <StickmanLoader
                        playful
                        stage={progress?.stage ? `Stage: ${progress.stage}` : undefined}
                        stats={progressStats}
                        message={
                          progress?.mode === "backfill"
                            ? "Jump over old email piles while InboxAnchor builds mailbox memory."
                            : "Jump over email piles while InboxAnchor prepares the mailbox map."
                        }
                      />
                    </div>
                  )
                : Object.entries(overview?.categoryCounts || {}).map(([key, value]) => (
                    <div
                      key={key}
                      className="flex items-center justify-between rounded-xl border border-border bg-background px-4 py-3"
                    >
                      <div>
                        <p className="text-sm font-medium text-foreground">
                          {CATEGORY_LABELS[key] || key}
                        </p>
                        <p className="text-xs text-muted-foreground">
                          {key === "newsletter" || key === "promo"
                            ? "Good cleanup candidates"
                            : key === "finance" || key === "opportunity"
                              ? "Keep these visible and labeled"
                              : "Part of the unread working set"}
                        </p>
                      </div>
                      <Badge variant="outline">{value}</Badge>
                    </div>
                  ))}
            </div>
          </div>
        </section>
      </main>
    </div>
  );
}

function WorkflowCard({
  title,
  icon,
  description,
  impact,
  cta,
  loading,
  onClick,
  href,
  featured = false,
}: {
  title: string;
  icon: ReactNode;
  description: string;
  impact?: string;
  cta: string;
  loading?: boolean;
  onClick?: () => void;
  href?: string;
  featured?: boolean;
}) {
  const body = (
    <div
      className={`rounded-2xl border p-5 ${
        featured
          ? "border-primary/30 bg-primary/5"
          : "border-border bg-background"
      }`}
    >
      <div className="flex items-center gap-2 text-foreground">
        {icon}
        <h4 className="text-sm font-semibold">{title}</h4>
      </div>
      <p className="mt-3 text-sm leading-6 text-muted-foreground">{description}</p>
      <p className="mt-3 text-xs leading-5 text-muted-foreground">{impact}</p>
      <div className="mt-4">
        {href ? (
          <Link
            to={href}
            className="inline-flex items-center gap-1.5 rounded-md border border-border bg-card px-3 py-2 text-xs font-medium text-foreground transition-colors hover:bg-secondary"
          >
            {cta}
            <ArrowRight className="h-3.5 w-3.5" />
          </Link>
        ) : (
          <Button onClick={onClick} disabled={loading}>
            {loading ? "Running..." : cta}
          </Button>
        )}
      </div>
    </div>
  );
  return body;
}
