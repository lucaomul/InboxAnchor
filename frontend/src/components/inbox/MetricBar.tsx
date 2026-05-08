import { type InboxDigest } from "@/lib/mock-data";

interface MetricBarProps {
  digest: InboxDigest;
}

export function MetricBar({ digest }: MetricBarProps) {
  const metrics = [
    { label: "Unread", value: digest.totalUnread, note: "messages" },
    { label: "Critical", value: digest.highPriorityIds.length, note: "need attention" },
    { label: "Categories", value: Object.keys(digest.categoryCounts).length, note: "detected" },
    { label: "Safe Actions", value: 4, note: "auto-ready" },
  ];

  return (
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
      {metrics.map((m) => (
        <div key={m.label} className="rounded-lg bg-card p-4 border border-border">
          <p className="text-2xl font-bold text-foreground">{m.value}</p>
          <p className="text-sm font-medium text-foreground">{m.label}</p>
          <p className="text-xs text-muted-foreground">{m.note}</p>
        </div>
      ))}
    </div>
  );
}