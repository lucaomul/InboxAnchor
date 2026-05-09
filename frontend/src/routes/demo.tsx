import { createFileRoute, Link } from "@tanstack/react-router";
import { type ReactNode, useEffect, useMemo, useState } from "react";
import { StickmanLoader } from "@/components/StickmenAnimations";
import { EmailDetail } from "@/components/inbox/EmailDetail";
import { EmailList } from "@/components/inbox/EmailList";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  type EmailMessage,
  type EmailActionItem,
  type EmailRecommendation,
  MOCK_ACTION_ITEMS,
  MOCK_CLASSIFICATIONS,
  MOCK_DIGEST,
  MOCK_EMAILS,
  MOCK_RECOMMENDATIONS,
} from "@/lib/mock-data";
import type { MailboxTimeRange } from "@/lib/time-range";
import {
  Activity,
  Anchor,
  ArrowRight,
  Inbox,
  Layers3,
  MailCheck,
  PlayCircle,
  ShieldCheck,
  Sparkles,
  Tags,
} from "lucide-react";

type DemoScene = "overview" | "scan" | "triage" | "upgrade" | "privacy";

type DemoStat = {
  label: string;
  value: string | number;
  note?: string;
};

const DEMO_TIME_RANGE: MailboxTimeRange = "last_3_years";
const SCENE_ORDER: DemoScene[] = ["overview", "scan", "triage", "upgrade", "privacy"];
const SCENE_DURATION_MS = 3200;

const SCENE_COPY: Record<
  DemoScene,
  {
    eyebrow: string;
    title: string;
    body: string;
  }
> = {
  overview: {
    eyebrow: "Command center",
    title: "Map the overloaded mailbox before touching the real inbox.",
    body:
      "InboxAnchor starts with a clear operating picture: unread volume, high-priority pressure, safe cleanup candidates, and how much mailbox memory is already cached.",
  },
  scan: {
    eyebrow: "Unread scan",
    title: "Show useful progress while the mailbox is being read.",
    body:
      "The demo reel keeps the same promise as the live app: real-time progress, clear counters, and a serious or playful wait state instead of a dead screen.",
  },
  triage: {
    eyebrow: "Inbox workspace",
    title: "Bring categories, priorities, and safe recommendations into one view.",
    body:
      "The triage view highlights what needs a human, what can be cleaned safely, and what deserves a reply without pretending every email should be automated.",
  },
  upgrade: {
    eyebrow: "Mailbox upgrade",
    title: "Apply labels and safe cleanup without losing the audit trail.",
    body:
      "InboxAnchor is an operations layer on top of the mailbox itself, not just another inbox client. Labels, safe cleanup, and follow-up structure all stay visible.",
  },
  privacy: {
    eyebrow: "Privacy aliases",
    title: "Route product-owned aliases into labels without exposing the real address.",
    body:
      "Managed aliases like travel5726815@inboxanchor.com forward into the inbox, skip the primary feed, and stay revocable from one control surface.",
  },
};

const OVERVIEW_STATS: DemoStat[] = [
  { label: "Unread mapped", value: "3,548", note: "last 3 years" },
  { label: "High priority", value: "112", note: "needs human eyes" },
  { label: "Safe cleanups", value: "1,126", note: "ready now" },
  { label: "Mailbox memory", value: "12,480", note: "cached threads" },
];

const FEATURE_RAIL: DemoStat[] = [
  { label: "Provider", value: "Demo workspace", note: "deterministic product reel" },
  { label: "Window", value: "Last 3 years", note: "time-ranged cleanup" },
  { label: "Mode", value: "Rules first", note: "LLM only on edge cases" },
  { label: "Safety", value: "Human approved", note: "audit-ready actions" },
];

const WORKFLOW_STATS: DemoStat[] = [
  { label: "Labeled", value: "1,126", note: "category and priority" },
  { label: "Archived", value: "824", note: "low-risk cleanup" },
  { label: "Marked read", value: "302", note: "promos and newsletters" },
  { label: "Needs review", value: "41", note: "kept in human lane" },
];

const PRIVACY_ALIASES = [
  {
    alias: "travel5726815@inboxanchor.com",
    label: "InboxAnchor/Aliases/Travel",
    target: "founder@company.com",
    status: "Active",
  },
  {
    alias: "news6082214@inboxanchor.com",
    label: "InboxAnchor/Aliases/Newsletter",
    target: "founder@company.com",
    status: "Active",
  },
  {
    alias: "vendors1911051@inboxanchor.com",
    label: "InboxAnchor/Aliases/Vendors",
    target: "founder@company.com",
    status: "Revocable",
  },
];

const DEMO_EMAIL_IDS = ["e6", "e1", "e2", "e3", "e4", "e5"];
const TRIAGE_HIGHLIGHT_ID = "e6";

export const Route = createFileRoute("/demo")({
  head: () => ({
    meta: [
      { title: "InboxAnchor Demo Reel" },
      {
        name: "description",
        content:
          "Autoplay product reel for InboxAnchor showing unread scans, mailbox triage, safe cleanup, and privacy aliases.",
      },
    ],
  }),
  component: DemoRoute,
});

function DemoRoute() {
  const [sceneIndex, setSceneIndex] = useState(0);
  const scene = SCENE_ORDER[sceneIndex];

  useEffect(() => {
    const handle = window.setInterval(() => {
      setSceneIndex((current) => (current + 1) % SCENE_ORDER.length);
    }, SCENE_DURATION_MS);
    return () => window.clearInterval(handle);
  }, []);

  const demoEmails = useMemo(
    () =>
      DEMO_EMAIL_IDS.map((id) => {
        const email = MOCK_EMAILS.find((item) => item.id === id)!;
        return {
          ...email,
          classification: MOCK_CLASSIFICATIONS[id],
          canReply: true,
          replyDraft:
            id === "e6"
              ? "Thanks for the follow-up. I reviewed the notes and can send the clarifications this afternoon."
              : undefined,
          replyToAddress: email.sender,
        } satisfies EmailMessage;
      }),
    [],
  );

  const selectedEmail =
    demoEmails.find((email) => email.id === TRIAGE_HIGHLIGHT_ID) ?? demoEmails[0];
  const selectedRecommendations = MOCK_RECOMMENDATIONS.filter(
    (item) => item.emailId === selectedEmail.id,
  ) as EmailRecommendation[];
  const selectedActionItems = MOCK_ACTION_ITEMS[selectedEmail.id] ?? [];

  return (
    <div className="h-screen overflow-hidden bg-background px-5 py-5">
      <div className="mx-auto flex h-[calc(100vh-2.5rem)] max-w-[1360px] flex-col overflow-hidden rounded-[30px] border border-border bg-card shadow-[0_24px_80px_rgba(15,23,42,0.16)]">
        <header className="border-b border-border px-6 py-4">
          <div className="flex items-center justify-between gap-4">
            <div className="flex items-center gap-3">
              <div className="flex h-11 w-11 items-center justify-center rounded-2xl border border-border bg-background">
                <Anchor className="h-5 w-5 text-primary" />
              </div>
              <div>
                <div className="flex items-center gap-2">
                  <h1 className="text-base font-semibold tracking-tight text-foreground">
                    InboxAnchor
                  </h1>
                  <Badge variant="outline" className="gap-1 text-[10px] uppercase tracking-[0.18em]">
                    <PlayCircle className="h-3 w-3" />
                    Demo reel
                  </Badge>
                </div>
                <p className="text-xs text-muted-foreground">
                  Safety-first inbox operations for cleanup, labeling, and unread control
                </p>
              </div>
            </div>
            <div className="flex items-center gap-2">
              <Badge variant="safe" className="gap-1">
                <Sparkles className="h-3 w-3" />
                Demo workspace
              </Badge>
              <Badge variant="muted">Last 3 years</Badge>
              <Link
                to="/"
                className="inline-flex items-center gap-1.5 rounded-md border border-border bg-background px-3 py-2 text-xs font-medium text-foreground transition-colors hover:bg-secondary"
              >
                Open app
                <ArrowRight className="h-3.5 w-3.5" />
              </Link>
            </div>
          </div>
        </header>

        <main className="grid flex-1 gap-0 overflow-hidden lg:grid-cols-[1.45fr_0.8fr]">
          <section className="border-r border-border p-6">
            <DemoStageHeader scene={scene} />
            <div className="mt-6">
              {scene === "overview" ? (
                <OverviewStage />
              ) : null}
              {scene === "scan" ? (
                <ScanStage />
              ) : null}
              {scene === "triage" ? (
                <TriageStage
                  emails={demoEmails}
                  selectedEmail={selectedEmail}
                  selectedRecommendations={selectedRecommendations}
                  selectedActionItems={selectedActionItems}
                />
              ) : null}
              {scene === "upgrade" ? (
                <UpgradeStage />
              ) : null}
              {scene === "privacy" ? (
                <PrivacyStage />
              ) : null}
            </div>
          </section>

          <aside className="flex flex-col justify-between bg-background/60 p-6">
            <div className="space-y-6">
              <div className="rounded-3xl border border-border bg-card p-5">
                <p className="text-[11px] uppercase tracking-[0.18em] text-muted-foreground">
                  What this demo proves
                </p>
                <div className="mt-4 grid gap-3">
                  {FEATURE_RAIL.map((item) => (
                    <div key={item.label} className="rounded-2xl border border-border bg-background px-4 py-3">
                      <p className="text-lg font-semibold text-foreground">{item.value}</p>
                      <p className="mt-1 text-[11px] uppercase tracking-[0.18em] text-muted-foreground">
                        {item.label}
                      </p>
                      {item.note ? (
                        <p className="mt-1 text-xs text-muted-foreground">{item.note}</p>
                      ) : null}
                    </div>
                  ))}
                </div>
              </div>

              <div className="rounded-3xl border border-border bg-card p-5">
                <p className="text-[11px] uppercase tracking-[0.18em] text-muted-foreground">
                  Product narrative
                </p>
                <div className="mt-4 space-y-3">
                  <DemoNarrativeRow
                    icon={<Inbox className="h-4 w-4" />}
                    title="Read the real working set"
                    body="Map unread pressure by time window, not just by whatever landed this morning."
                    active={scene === "scan" || scene === "triage"}
                  />
                  <DemoNarrativeRow
                    icon={<ShieldCheck className="h-4 w-4" />}
                    title="Keep risky actions visible"
                    body="Approval, blocked lanes, and audit-friendly execution are part of the product story."
                    active={scene === "triage" || scene === "upgrade"}
                  />
                  <DemoNarrativeRow
                    icon={<Tags className="h-4 w-4" />}
                    title="Upgrade the mailbox itself"
                    body="Labels, cleanup, and privacy aliases act on the inbox, not in a disconnected mirror UI."
                    active={scene === "upgrade" || scene === "privacy"}
                  />
                </div>
              </div>
            </div>

            <div className="mt-6 rounded-3xl border border-border bg-card p-5">
              <div className="flex items-center justify-between gap-4">
                <div>
                  <p className="text-[11px] uppercase tracking-[0.18em] text-muted-foreground">
                    Demo timeline
                  </p>
                  <p className="mt-1 text-sm text-muted-foreground">
                    Autoplay loop designed for GitHub, LinkedIn, and Reddit captures.
                  </p>
                </div>
                <Badge variant="outline">{sceneIndex + 1}/{SCENE_ORDER.length}</Badge>
              </div>
              <div className="mt-4 flex gap-2">
                {SCENE_ORDER.map((candidate, index) => (
                  <div
                    key={candidate}
                    className={`h-2 flex-1 rounded-full transition-colors ${
                      index <= sceneIndex ? "bg-primary" : "bg-border"
                    }`}
                  />
                ))}
              </div>
            </div>
          </aside>
        </main>
      </div>
    </div>
  );
}

function DemoStageHeader({ scene }: { scene: DemoScene }) {
  const copy = SCENE_COPY[scene];

  return (
    <div className="grid gap-4 lg:grid-cols-[1.15fr_0.85fr] lg:items-end">
      <div>
        <Badge variant="outline" className="gap-1 text-[10px] uppercase tracking-[0.18em]">
          <Activity className="h-3 w-3" />
          {copy.eyebrow}
        </Badge>
        <h2 className="mt-3 text-3xl font-semibold tracking-tight text-foreground">
          {copy.title}
        </h2>
        <p className="mt-3 max-w-3xl text-sm leading-6 text-muted-foreground">
          {copy.body}
        </p>
      </div>
      <div className="grid gap-3 sm:grid-cols-2">
        {OVERVIEW_STATS.slice(0, 2).map((item) => (
          <div key={item.label} className="rounded-2xl border border-border bg-background px-4 py-3">
            <p className="text-2xl font-semibold text-foreground">{item.value}</p>
            <p className="mt-1 text-[11px] uppercase tracking-[0.18em] text-muted-foreground">
              {item.label}
            </p>
            {item.note ? <p className="mt-1 text-xs text-muted-foreground">{item.note}</p> : null}
          </div>
        ))}
      </div>
    </div>
  );
}

function OverviewStage() {
  return (
    <div className="grid gap-5 xl:grid-cols-[1.2fr_0.8fr]">
      <div className="rounded-[28px] border border-border bg-background p-6">
        <div className="flex items-center justify-between gap-3">
          <div>
            <p className="text-[11px] uppercase tracking-[0.18em] text-muted-foreground">
              Command center
            </p>
            <h3 className="mt-2 text-xl font-semibold text-foreground">
              Make the mailbox cleaner without losing trust.
            </h3>
          </div>
          <Badge variant="safe">Demo workspace</Badge>
        </div>
        <div className="mt-6 grid gap-3 md:grid-cols-2">
          {OVERVIEW_STATS.map((item) => (
            <div key={item.label} className="rounded-2xl border border-border bg-card p-4">
              <p className="text-3xl font-semibold text-foreground">{item.value}</p>
              <p className="mt-2 text-[11px] uppercase tracking-[0.18em] text-muted-foreground">
                {item.label}
              </p>
              {item.note ? <p className="mt-1 text-xs text-muted-foreground">{item.note}</p> : null}
            </div>
          ))}
        </div>
        <div className="mt-6 flex flex-wrap gap-3">
          <Button>
            <MailCheck className="mr-2 h-4 w-4" />
            Refresh unread scan
          </Button>
          <Button variant="outline">
            <Layers3 className="mr-2 h-4 w-4" />
            Build mailbox memory
          </Button>
        </div>
      </div>

      <div className="rounded-[28px] border border-border bg-card p-6">
        <p className="text-[11px] uppercase tracking-[0.18em] text-muted-foreground">
          Live digest
        </p>
        <p className="mt-3 text-2xl font-semibold text-foreground">
          {MOCK_DIGEST.totalUnread} unread emails need sorting.
        </p>
        <p className="mt-3 text-sm leading-6 text-muted-foreground">
          {MOCK_DIGEST.summary}
        </p>
        <div className="mt-5 flex flex-wrap gap-2">
          {Object.entries(MOCK_DIGEST.categoryCounts).map(([label, value]) => (
            <Badge key={label} variant="outline" className="px-3 py-1 text-xs">
              {label.replaceAll("_", " ")} · {value}
            </Badge>
          ))}
        </div>
      </div>
    </div>
  );
}

function ScanStage() {
  return (
    <div className="rounded-[28px] border border-border bg-background p-6">
      <StickmanLoader
        playful
        modeOverride="fun"
        showModeToggle={false}
        stage="Last 3 years · Demo workspace"
        message="InboxAnchor is reading the working set, applying time-window rules, and preparing safe recommendations before touching the mailbox."
        activity="classified investor thread · hydrated invoice body · prepared 14 safe cleanup suggestions"
        runnerProps={{ autoplay: true, showControlsHint: false }}
        stats={[
          { label: "Emails read", value: 1842 },
          { label: "Processed", value: 1842 },
          { label: "Actions", value: 206 },
          { label: "Suggestions", value: 944 },
        ]}
      />
    </div>
  );
}

function TriageStage({
  emails,
  selectedEmail,
  selectedRecommendations,
  selectedActionItems,
}: {
  emails: EmailMessage[];
  selectedEmail: EmailMessage;
  selectedRecommendations: EmailRecommendation[];
  selectedActionItems: EmailActionItem[];
}) {
  return (
    <div className="overflow-hidden rounded-[28px] border border-border bg-background">
      <div className="grid min-h-[620px] xl:grid-cols-[0.44fr_0.56fr]">
        <div className="border-r border-border">
          <div className="flex items-center justify-between border-b border-border px-4 py-3">
            <div>
              <p className="text-[11px] uppercase tracking-[0.18em] text-muted-foreground">
                Inbox workspace
              </p>
              <p className="text-sm font-medium text-foreground">Selected window: Last 3 years</p>
            </div>
            <Badge variant="outline">6 preview emails</Badge>
          </div>
          <EmailList emails={emails} selectedId={selectedEmail.id} onSelect={() => undefined} />
        </div>
        <EmailDetail
          email={selectedEmail}
          classification={MOCK_CLASSIFICATIONS[selectedEmail.id]}
          recommendations={selectedRecommendations}
          actionItems={selectedActionItems}
          timeRange={DEMO_TIME_RANGE}
        />
      </div>
    </div>
  );
}

function UpgradeStage() {
  return (
    <div className="grid gap-5 xl:grid-cols-[1.1fr_0.9fr]">
      <div className="rounded-[28px] border border-border bg-background p-6">
        <p className="text-[11px] uppercase tracking-[0.18em] text-muted-foreground">
          Mailbox upgrade report
        </p>
        <h3 className="mt-2 text-2xl font-semibold text-foreground">
          Safe cleanup shipped without hiding the risky stuff.
        </h3>
        <div className="mt-6 grid gap-3 sm:grid-cols-2">
          {WORKFLOW_STATS.map((item) => (
            <div key={item.label} className="rounded-2xl border border-border bg-card p-4">
              <p className="text-3xl font-semibold text-foreground">{item.value}</p>
              <p className="mt-2 text-[11px] uppercase tracking-[0.18em] text-muted-foreground">
                {item.label}
              </p>
              {item.note ? <p className="mt-1 text-xs text-muted-foreground">{item.note}</p> : null}
            </div>
          ))}
        </div>
      </div>
      <div className="rounded-[28px] border border-border bg-card p-6">
        <p className="text-[11px] uppercase tracking-[0.18em] text-muted-foreground">
          Why it feels different
        </p>
        <div className="mt-4 space-y-3">
          <DemoNarrativeRow
            icon={<ShieldCheck className="h-4 w-4" />}
            title="Safe by default"
            body="Trash actions still require explicit confirmation. Safe cleanup focuses on archive, labels, and mark-as-read."
            active
          />
          <DemoNarrativeRow
            icon={<Tags className="h-4 w-4" />}
            title="Label the real inbox"
            body="Categories, priority markers, and alias routing apply back to the provider instead of living only inside a mirror UI."
            active
          />
          <DemoNarrativeRow
            icon={<MailCheck className="h-4 w-4" />}
            title="Keep the human in the loop"
            body="Blocked and approval-required recommendations stay visible so the operator decides what crosses the line."
            active
          />
        </div>
      </div>
    </div>
  );
}

function PrivacyStage() {
  return (
    <div className="grid gap-5 xl:grid-cols-[1fr_1fr]">
      <div className="rounded-[28px] border border-border bg-background p-6">
        <p className="text-[11px] uppercase tracking-[0.18em] text-muted-foreground">
          Managed aliases
        </p>
        <h3 className="mt-2 text-2xl font-semibold text-foreground">
          Product-owned addresses that route into labels, not into chaos.
        </h3>
        <div className="mt-6 space-y-3">
          {PRIVACY_ALIASES.map((alias) => (
            <div key={alias.alias} className="rounded-2xl border border-border bg-card p-4">
              <div className="flex items-center justify-between gap-3">
                <p className="font-medium text-foreground">{alias.alias}</p>
                <Badge variant={alias.status === "Active" ? "safe" : "outline"}>
                  {alias.status}
                </Badge>
              </div>
              <p className="mt-2 text-xs text-muted-foreground">Routes to {alias.target}</p>
              <p className="mt-2 text-xs text-muted-foreground">Label: {alias.label}</p>
            </div>
          ))}
        </div>
      </div>

      <div className="rounded-[28px] border border-border bg-card p-6">
        <p className="text-[11px] uppercase tracking-[0.18em] text-muted-foreground">
          Demo capture takeaway
        </p>
        <div className="mt-4 space-y-4">
          <div className="rounded-2xl border border-border bg-background p-4">
            <p className="text-sm font-medium text-foreground">
              Good for GitHub
            </p>
            <p className="mt-2 text-sm leading-6 text-muted-foreground">
              The reel shows the command center, wait-state UX, inbox triage, safe cleanup, and privacy infrastructure in one clean loop.
            </p>
          </div>
          <div className="rounded-2xl border border-border bg-background p-4">
            <p className="text-sm font-medium text-foreground">
              Good for LinkedIn and Reddit
            </p>
            <p className="mt-2 text-sm leading-6 text-muted-foreground">
              It tells a product story quickly: overloaded inbox, safe operations, real provider actions, and a privacy layer that makes the brand feel serious.
            </p>
          </div>
          <div className="rounded-2xl border border-border bg-background p-4">
            <p className="text-sm font-medium text-foreground">
              Good for live demos
            </p>
            <p className="mt-2 text-sm leading-6 text-muted-foreground">
              This route is deterministic, so you can record it anytime without needing a risky real mailbox session.
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}

function DemoNarrativeRow({
  icon,
  title,
  body,
  active = false,
}: {
  icon: ReactNode;
  title: string;
  body: string;
  active?: boolean;
}) {
  return (
    <div
      className={`rounded-2xl border px-4 py-3 transition-colors ${
        active
          ? "border-primary/30 bg-primary/5"
          : "border-border bg-background"
      }`}
    >
      <div className="flex items-center gap-2">
        <div className={active ? "text-primary" : "text-muted-foreground"}>{icon}</div>
        <p className="text-sm font-medium text-foreground">{title}</p>
      </div>
      <p className="mt-2 text-xs leading-5 text-muted-foreground">{body}</p>
    </div>
  );
}
