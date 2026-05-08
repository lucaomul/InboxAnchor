import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  type EmailRecommendation,
  type EmailMessage,
} from "@/lib/mock-data";
import { Archive, CheckCircle, Flag, Loader2, Shield, ShieldAlert, ShieldOff, XCircle } from "lucide-react";
import {
  useApplyRecommendation,
  useApproveRecommendation,
  useBlockRecommendation,
  useApplyAllSafe,
} from "@/hooks/use-inbox-data";

interface RecommendationLanesProps {
  recommendations: EmailRecommendation[];
  emails?: EmailMessage[];
  onSelectEmail: (id: string) => void;
}

function LaneCard({
  rec,
  onSelect,
  emailMap,
  onApprove,
  onBlock,
  loading,
}: {
  rec: EmailRecommendation;
  onSelect: () => void;
  emailMap: Map<string, EmailMessage>;
  onApprove?: () => void;
  onBlock?: () => void;
  loading?: boolean;
}) {
  const email = emailMap.get(rec.emailId);
  const actionIcons: Record<string, React.ReactNode> = {
    mark_read: <CheckCircle className="w-3.5 h-3.5" />,
    archive: <Archive className="w-3.5 h-3.5" />,
    label: <Flag className="w-3.5 h-3.5" />,
    flag_urgent: <ShieldAlert className="w-3.5 h-3.5" />,
  };

  return (
    <button onClick={onSelect} className="flex items-start gap-3 rounded-md bg-card p-3 border border-border text-left hover:bg-secondary/50 transition-colors w-full">
      <div className="text-muted-foreground shrink-0 mt-0.5">
        {actionIcons[rec.recommendedAction] || <Flag className="w-3.5 h-3.5" />}
      </div>
      <div className="flex-1 min-w-0">
        <p className="text-sm font-medium text-foreground truncate">{email?.subject || rec.emailId}</p>
        <p className="text-xs text-muted-foreground truncate">{rec.reason}</p>
        <div className="flex gap-1 mt-1">
          <span className="text-[10px] text-muted-foreground capitalize">{rec.recommendedAction.replace("_", " ")}</span>
          <span className="text-[10px] text-muted-foreground">• {Math.round(rec.confidence * 100)}%</span>
        </div>
        {(onApprove || onBlock) && (
          <div className="flex gap-1 mt-2" onClick={(e) => e.stopPropagation()}>
            {onApprove && (
              <Button size="sm" variant="outline" className="text-safe h-6 text-[10px] px-2" onClick={onApprove} disabled={loading}>
                {loading ? <Loader2 className="w-3 h-3 animate-spin" /> : "Approve"}
              </Button>
            )}
            {onBlock && (
              <Button size="sm" variant="ghost" className="text-destructive h-6 text-[10px] px-2" onClick={onBlock} disabled={loading}>
                <XCircle className="w-3 h-3" />
              </Button>
            )}
          </div>
        )}
      </div>
    </button>
  );
}

export function RecommendationLanes({ recommendations, emails = [], onSelectEmail }: RecommendationLanesProps) {
  const emailMap = new Map(emails.map((e) => [e.id, e]));
  const applyMutation = useApplyRecommendation();
  const approveMutation = useApproveRecommendation();
  const blockMutation = useBlockRecommendation();
  const applyAllMutation = useApplyAllSafe();

  const safe = recommendations.filter((r) => r.status === "safe");
  const approval = recommendations.filter((r) => r.status === "requires_approval");
  const blocked = recommendations.filter((r) => r.status === "blocked");

  const lanes = [
    { title: "Safe", subtitle: "Auto-ready actions", items: safe, icon: <Shield className="w-4 h-4 text-safe" />, badgeVariant: "safe" as const },
    { title: "Needs Approval", subtitle: "Review before applying", items: approval, icon: <ShieldAlert className="w-4 h-4 text-warning" />, badgeVariant: "warning" as const },
    { title: "Blocked", subtitle: "Human-only decisions", items: blocked, icon: <ShieldOff className="w-4 h-4 text-critical" />, badgeVariant: "critical" as const },
  ];

  return (
    <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
      {lanes.map((lane) => (
        <div key={lane.title} className="rounded-lg border border-border bg-card/50 overflow-hidden">
          <div className="flex items-center gap-2 px-4 py-3 border-b border-border">
            {lane.icon}
            <div className="flex-1">
              <h3 className="text-sm font-semibold text-foreground">{lane.title}</h3>
              <p className="text-xs text-muted-foreground">{lane.subtitle}</p>
            </div>
            <Badge variant={lane.badgeVariant} className="text-[10px]">{lane.items.length}</Badge>
          </div>
          <div className="flex flex-col gap-1 p-2">
            {lane.items.length === 0 && (
              <p className="text-xs text-muted-foreground text-center py-4">No items</p>
            )}
            {lane.items.map((rec) => (
              <LaneCard
                key={rec.emailId}
                rec={rec}
                emailMap={emailMap}
                onSelect={() => onSelectEmail(rec.emailId)}
                onApprove={
                  rec.status === "requires_approval"
                    ? () => approveMutation.mutate({ emailId: rec.emailId, action: rec.recommendedAction })
                    : rec.status === "safe"
                      ? () => applyMutation.mutate({ emailId: rec.emailId, action: rec.recommendedAction })
                      : undefined
                }
                onBlock={
                  rec.status !== "blocked"
                    ? () => blockMutation.mutate({ emailId: rec.emailId, action: rec.recommendedAction })
                    : undefined
                }
                loading={applyMutation.isPending || approveMutation.isPending || blockMutation.isPending}
              />
            ))}
          </div>
          {lane.title === "Safe" && lane.items.length > 0 && (
            <div className="px-3 pb-3">
              <Button
                size="sm"
                className="w-full bg-safe text-safe-foreground hover:bg-safe/90"
                disabled={applyAllMutation.isPending}
                onClick={() => applyAllMutation.mutate()}
              >
                {applyAllMutation.isPending && <Loader2 className="w-3.5 h-3.5 animate-spin mr-1" />}
                Apply All Safe Actions
              </Button>
            </div>
          )}
        </div>
      ))}
    </div>
  );
}