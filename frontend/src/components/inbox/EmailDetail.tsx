import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  type EmailMessage,
  type EmailClassification,
  type EmailRecommendation,
  type EmailActionItem,
  CATEGORY_CONFIG,
  PRIORITY_CONFIG,
} from "@/lib/mock-data";
import { Archive, CheckCircle, Flag, Loader2, Reply, Shield, ShieldAlert, ShieldOff, XCircle } from "lucide-react";
import {
  useApplyRecommendation,
  useApproveRecommendation,
  useBlockRecommendation,
} from "@/hooks/use-inbox-data";

interface EmailDetailProps {
  email: EmailMessage;
  classification: EmailClassification;
  recommendations: EmailRecommendation[];
  actionItems: EmailActionItem[];
}

const ACTION_ICONS: Record<string, React.ReactNode> = {
  mark_read: <CheckCircle className="w-4 h-4" />,
  archive: <Archive className="w-4 h-4" />,
  label: <Flag className="w-4 h-4" />,
  flag_urgent: <ShieldAlert className="w-4 h-4" />,
  none: <Shield className="w-4 h-4" />,
};

const STATUS_STYLES: Record<string, { badge: "safe" | "warning" | "critical"; icon: React.ReactNode }> = {
  safe: { badge: "safe", icon: <Shield className="w-3.5 h-3.5" /> },
  requires_approval: { badge: "warning", icon: <ShieldAlert className="w-3.5 h-3.5" /> },
  blocked: { badge: "critical", icon: <ShieldOff className="w-3.5 h-3.5" /> },
};

export function EmailDetail({ email, classification, recommendations, actionItems }: EmailDetailProps) {
  const catCfg =
    CATEGORY_CONFIG[classification.category] ?? {
      label: classification.category || "Unknown",
      color: "bg-muted text-muted-foreground",
    };
  const priCfg =
    PRIORITY_CONFIG[classification.priority] ?? {
      label: classification.priority || "Unknown",
      color: "bg-muted text-muted-foreground",
    };
  const applyMutation = useApplyRecommendation();
  const approveMutation = useApproveRecommendation();
  const blockMutation = useBlockRecommendation();
  const fullBody = email.bodyFull?.trim() || email.bodyPreview?.trim() || email.snippet;

  return (
    <div className="flex flex-col gap-5 p-5">
      {/* Header */}
      <div>
        <h2 className="text-lg font-semibold text-foreground">{email.subject}</h2>
        <p className="text-sm text-muted-foreground mt-1">From: {email.sender}</p>
        <div className="flex items-center gap-2 mt-2">
          <Badge variant="muted" className={catCfg.color}>{catCfg.label}</Badge>
          <Badge
            variant={
              classification.priority === "critical"
                ? "critical"
                : classification.priority === "high"
                  ? "warning"
                  : "muted"
            }
            className={classification.priority === "medium" || classification.priority === "low" ? priCfg.color : undefined}
          >
            {priCfg.label}
          </Badge>
          <span className="text-xs text-muted-foreground">
            {Math.round(classification.confidence * 100)}% confidence
          </span>
        </div>
        <p className="text-xs text-muted-foreground mt-1 italic">{classification.reason}</p>
      </div>

      {/* Preview */}
      <div className="rounded-lg bg-secondary/50 p-4 border border-border">
        <p className="text-xs font-medium uppercase tracking-[0.16em] text-muted-foreground">
          Message body
        </p>
        <p className="mt-3 whitespace-pre-wrap text-sm text-foreground leading-relaxed">
          {fullBody}
        </p>
      </div>

      {/* Action Items */}
      {actionItems.length > 0 && (
        <div>
          <h3 className="text-sm font-semibold text-foreground mb-2">Action Items</h3>
          <div className="flex flex-col gap-2">
            {actionItems.map((item, i) => (
              <div key={i} className="flex items-start gap-2 rounded-md bg-card p-3 border border-border">
                <Reply className="w-4 h-4 text-primary mt-0.5 shrink-0" />
                <div>
                  <p className="text-sm text-foreground">{item.description}</p>
                  {item.requiresReply && (
                    <Badge variant="warning" className="mt-1 text-[10px]">Reply needed</Badge>
                  )}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Recommendations */}
      {recommendations.length > 0 && (
        <div>
          <h3 className="text-sm font-semibold text-foreground mb-2">Recommendations</h3>
          <div className="flex flex-col gap-2">
            {recommendations.map((rec) => {
              const statusStyle = STATUS_STYLES[rec.status] ?? STATUS_STYLES.requires_approval;
              return (
                <div key={rec.emailId + rec.recommendedAction} className="flex items-start gap-3 rounded-md bg-card p-3 border border-border">
                  <div className="shrink-0 mt-0.5 text-muted-foreground">
                    {ACTION_ICONS[rec.recommendedAction] || <Flag className="w-4 h-4" />}
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2">
                      <span className="text-sm font-medium text-foreground capitalize">
                        {rec.recommendedAction.replace("_", " ")}
                      </span>
                      <Badge variant={statusStyle.badge} className="text-[10px] gap-1">
                        {statusStyle.icon}
                        {rec.status.replace("_", " ")}
                      </Badge>
                    </div>
                    <p className="text-xs text-muted-foreground mt-0.5">{rec.reason}</p>
                    {rec.proposedLabels.length > 0 && (
                      <div className="flex gap-1 mt-1.5">
                        {rec.proposedLabels.map((l) => (
                          <Badge key={l} variant="outline" className="text-[10px] px-1.5 py-0">{l}</Badge>
                        ))}
                      </div>
                    )}
                  </div>
                  {rec.status === "safe" && (
                    <Button
                      size="sm"
                      variant="ghost"
                      className="text-safe shrink-0"
                      disabled={applyMutation.isPending}
                      onClick={() => applyMutation.mutate({ emailId: rec.emailId, action: rec.recommendedAction })}
                    >
                      {applyMutation.isPending ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : null}
                      Apply
                    </Button>
                  )}
                  {rec.status === "requires_approval" && (
                    <div className="flex gap-1 shrink-0">
                    <Button
                      size="sm"
                      variant="outline"
                      className="text-safe"
                      disabled={approveMutation.isPending}
                      onClick={() => approveMutation.mutate({ emailId: rec.emailId, action: rec.recommendedAction })}
                    >
                      {approveMutation.isPending ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : null}
                      Approve
                    </Button>
                    <Button
                      size="sm"
                      variant="ghost"
                      className="text-destructive"
                      disabled={blockMutation.isPending}
                      onClick={() => blockMutation.mutate({ emailId: rec.emailId, action: rec.recommendedAction })}
                    >
                      <XCircle className="w-3.5 h-3.5" />
                    </Button>
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}
