import { Badge } from "@/components/ui/badge";
import {
  type EmailMessage,
  type EmailClassification,
  CATEGORY_CONFIG,
  PRIORITY_CONFIG,
} from "@/lib/mock-data";
import { Paperclip } from "lucide-react";

interface EmailListProps {
  emails: EmailMessage[];
  classifications: Record<string, EmailClassification>;
  selectedId: string | null;
  onSelect: (id: string) => void;
}

function timeAgo(dateStr: string) {
  const diff = Date.now() - new Date(dateStr).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 60) return `${mins}m`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h`;
  return `${Math.floor(hrs / 24)}d`;
}

export function EmailList({ emails, classifications, selectedId, onSelect }: EmailListProps) {
  return (
    <div className="flex flex-col divide-y divide-border">
      {emails.map((email) => {
        const cls = classifications[email.id];
        const catCfg = cls ? CATEGORY_CONFIG[cls.category] : null;
        const priCfg = cls ? PRIORITY_CONFIG[cls.priority] : null;
        const isSelected = email.id === selectedId;

        return (
          <button
            key={email.id}
            onClick={() => onSelect(email.id)}
            className={`flex flex-col gap-1.5 px-4 py-3 text-left transition-colors hover:bg-secondary/50 ${
              isSelected ? "bg-secondary" : ""
            } ${email.unread ? "" : "opacity-60"}`}
          >
            <div className="flex items-center justify-between gap-2">
              <span className={`text-sm truncate ${email.unread ? "font-semibold text-foreground" : "text-muted-foreground"}`}>
                {email.sender}
              </span>
              <span className="text-xs text-muted-foreground shrink-0">{timeAgo(email.receivedAt)}</span>
            </div>
            <p className={`text-sm truncate ${email.unread ? "font-medium text-foreground" : "text-muted-foreground"}`}>
              {email.subject}
            </p>
            <p className="text-xs text-muted-foreground truncate">{email.snippet}</p>
            <div className="flex items-center gap-1.5 mt-0.5">
              {catCfg && <Badge variant="muted" className={`text-[10px] px-1.5 py-0 ${catCfg.color}`}>{catCfg.label}</Badge>}
              {priCfg && cls!.priority !== "low" && (
                <Badge
                  variant={cls!.priority === "critical" ? "critical" : cls!.priority === "high" ? "warning" : "muted"}
                  className="text-[10px] px-1.5 py-0"
                >
                  {priCfg.label}
                </Badge>
              )}
              {email.hasAttachments && <Paperclip className="w-3 h-3 text-muted-foreground" />}
            </div>
          </button>
        );
      })}
    </div>
  );
}