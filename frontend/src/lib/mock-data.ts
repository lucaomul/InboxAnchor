export type EmailCategory = "urgent" | "work" | "finance" | "newsletter" | "promo" | "personal" | "opportunity" | "low_priority" | "spam_like";
export type PriorityLevel = "critical" | "high" | "medium" | "low";
export type RecommendationStatus = "safe" | "requires_approval" | "blocked";
export type SafetyStatus = "allowed" | "requires_review" | "blocked";

export interface EmailMessage {
  id: string;
  threadId: string;
  sender: string;
  subject: string;
  snippet: string;
  receivedAt: string;
  labels: string[];
  hasAttachments: boolean;
  unread: boolean;
}

export interface EmailClassification {
  category: EmailCategory;
  priority: PriorityLevel;
  confidence: number;
  reason: string;
}

export interface EmailRecommendation {
  emailId: string;
  recommendedAction: string;
  reason: string;
  confidence: number;
  status: RecommendationStatus;
  requiresApproval: boolean;
  proposedLabels: string[];
}

export interface EmailActionItem {
  emailId: string;
  actionType: string;
  description: string;
  requiresReply: boolean;
}

export interface InboxDigest {
  totalUnread: number;
  categoryCounts: Record<string, number>;
  highPriorityIds: string[];
  summary: string;
}

export const MOCK_EMAILS: EmailMessage[] = [
  { id: "e1", threadId: "t1", sender: "cfo@acmecorp.com", subject: "Q3 Budget Review — Action Required", snippet: "Please review the attached Q3 projections and confirm the marketing allocation by EOD Friday...", receivedAt: "2026-05-08T09:15:00Z", labels: ["INBOX", "IMPORTANT"], hasAttachments: true, unread: true },
  { id: "e2", threadId: "t2", sender: "sarah@designstudio.io", subject: "Final mockups ready for sign-off", snippet: "Hi! The landing page redesign mockups are ready. Three options attached — let me know your pick...", receivedAt: "2026-05-08T08:42:00Z", labels: ["INBOX"], hasAttachments: true, unread: true },
  { id: "e3", threadId: "t3", sender: "noreply@stripe.com", subject: "Your May invoice is available", snippet: "Your invoice for May 2026 is ready. Total: $2,340.00. View and download from your dashboard...", receivedAt: "2026-05-08T07:30:00Z", labels: ["INBOX"], hasAttachments: false, unread: true },
  { id: "e4", threadId: "t4", sender: "newsletter@techcrunch.com", subject: "TechCrunch Daily: AI startups raise $4B in Q2", snippet: "Good morning. Here's your daily briefing on the latest in tech, startups, and venture capital...", receivedAt: "2026-05-08T06:00:00Z", labels: ["INBOX", "CATEGORY_UPDATES"], hasAttachments: false, unread: true },
  { id: "e5", threadId: "t5", sender: "deals@shopify.com", subject: "🎉 50% off all premium themes this week", snippet: "Upgrade your storefront with premium themes at half price. Offer valid through Sunday...", receivedAt: "2026-05-07T22:15:00Z", labels: ["INBOX", "CATEGORY_PROMOTIONS"], hasAttachments: false, unread: true },
  { id: "e6", threadId: "t6", sender: "mike.chen@partnervc.com", subject: "Re: Series A term sheet follow-up", snippet: "Thanks for the call yesterday. We've reviewed the terms internally and have a few clarifications...", receivedAt: "2026-05-08T10:05:00Z", labels: ["INBOX", "STARRED"], hasAttachments: true, unread: true },
  { id: "e7", threadId: "t7", sender: "hr@company.com", subject: "Updated PTO policy — please acknowledge", snippet: "We've updated our paid time off policy effective June 1. Please review and acknowledge receipt...", receivedAt: "2026-05-08T08:00:00Z", labels: ["INBOX"], hasAttachments: false, unread: true },
  { id: "e8", threadId: "t8", sender: "mom@gmail.com", subject: "Dinner Sunday?", snippet: "Hey! Are you free for dinner this Sunday? Dad wants to try that new Italian place downtown...", receivedAt: "2026-05-07T19:30:00Z", labels: ["INBOX"], hasAttachments: false, unread: false },
  { id: "e9", threadId: "t9", sender: "no-reply@linkedin.com", subject: "5 people viewed your profile this week", snippet: "See who's looking at your profile and new job recommendations based on your experience...", receivedAt: "2026-05-07T18:00:00Z", labels: ["INBOX"], hasAttachments: false, unread: true },
  { id: "e10", threadId: "t10", sender: "support@saastool.com", subject: "Your trial expires in 3 days", snippet: "Don't lose access to your workspace. Upgrade to Pro and keep all your data...", receivedAt: "2026-05-07T14:00:00Z", labels: ["INBOX"], hasAttachments: false, unread: true },
];

export const MOCK_CLASSIFICATIONS: Record<string, EmailClassification> = {
  e1: { category: "finance", priority: "critical", confidence: 0.94, reason: "Budget review with deadline and executive sender" },
  e2: { category: "work", priority: "high", confidence: 0.91, reason: "Design deliverable awaiting sign-off" },
  e3: { category: "finance", priority: "medium", confidence: 0.88, reason: "Automated billing notification" },
  e4: { category: "newsletter", priority: "low", confidence: 0.96, reason: "Daily digest newsletter from media outlet" },
  e5: { category: "promo", priority: "low", confidence: 0.97, reason: "Promotional discount offer" },
  e6: { category: "opportunity", priority: "critical", confidence: 0.92, reason: "Active fundraising thread with investor" },
  e7: { category: "work", priority: "medium", confidence: 0.85, reason: "Internal HR policy requiring acknowledgment" },
  e8: { category: "personal", priority: "medium", confidence: 0.93, reason: "Family dinner invitation" },
  e9: { category: "low_priority", priority: "low", confidence: 0.95, reason: "Automated LinkedIn notification" },
  e10: { category: "promo", priority: "low", confidence: 0.89, reason: "SaaS trial expiration upsell" },
};

export const MOCK_RECOMMENDATIONS: EmailRecommendation[] = [
  { emailId: "e4", recommendedAction: "mark_read", reason: "Newsletter with no actionable content", confidence: 0.96, status: "safe", requiresApproval: false, proposedLabels: ["newsletter"] },
  { emailId: "e5", recommendedAction: "archive", reason: "Promotional offer, no urgency", confidence: 0.97, status: "safe", requiresApproval: false, proposedLabels: ["promo"] },
  { emailId: "e9", recommendedAction: "archive", reason: "Low-priority automated notification", confidence: 0.95, status: "safe", requiresApproval: false, proposedLabels: ["low_priority"] },
  { emailId: "e10", recommendedAction: "mark_read", reason: "Trial upsell, review if needed", confidence: 0.89, status: "safe", requiresApproval: false, proposedLabels: ["promo"] },
  { emailId: "e3", recommendedAction: "label", reason: "Financial document — apply finance label for tracking", confidence: 0.88, status: "requires_approval", requiresApproval: true, proposedLabels: ["finance", "invoices"] },
  { emailId: "e7", recommendedAction: "label", reason: "HR policy — needs human review before any action", confidence: 0.85, status: "requires_approval", requiresApproval: true, proposedLabels: ["hr", "action_needed"] },
  { emailId: "e1", recommendedAction: "flag_urgent", reason: "Budget review with hard deadline from executive", confidence: 0.94, status: "requires_approval", requiresApproval: true, proposedLabels: ["urgent", "finance"] },
  { emailId: "e6", recommendedAction: "flag_urgent", reason: "Active investor thread — high sensitivity", confidence: 0.92, status: "blocked", requiresApproval: true, proposedLabels: ["opportunity", "sensitive"] },
  { emailId: "e8", recommendedAction: "none", reason: "Personal email — no automated action recommended", confidence: 0.93, status: "blocked", requiresApproval: true, proposedLabels: [] },
];

export const MOCK_ACTION_ITEMS: Record<string, EmailActionItem[]> = {
  e1: [{ emailId: "e1", actionType: "review", description: "Review Q3 budget projections and confirm marketing allocation", requiresReply: true }],
  e2: [{ emailId: "e2", actionType: "decision", description: "Choose preferred landing page mockup option", requiresReply: true }],
  e6: [{ emailId: "e6", actionType: "reply", description: "Respond to Series A term sheet clarifications", requiresReply: true }],
  e7: [{ emailId: "e7", actionType: "acknowledge", description: "Acknowledge updated PTO policy", requiresReply: false }],
};

export const MOCK_DIGEST: InboxDigest = {
  totalUnread: 9,
  categoryCounts: { work: 2, finance: 2, newsletter: 1, promo: 2, opportunity: 1, personal: 1, low_priority: 1 },
  highPriorityIds: ["e1", "e6"],
  summary: "9 unread emails. 2 critical items need attention: Q3 budget review (deadline Friday) and Series A follow-up from Partner VC. 4 items can be safely archived or marked read.",
};

export const CATEGORY_CONFIG: Record<EmailCategory, { label: string; color: string }> = {
  urgent: { label: "Urgent", color: "bg-critical text-critical-foreground" },
  work: { label: "Work", color: "bg-primary/20 text-primary" },
  finance: { label: "Finance", color: "bg-warning/20 text-warning" },
  newsletter: { label: "Newsletter", color: "bg-muted text-muted-foreground" },
  promo: { label: "Promo", color: "bg-muted text-muted-foreground" },
  personal: { label: "Personal", color: "bg-accent/20 text-accent" },
  opportunity: { label: "Opportunity", color: "bg-safe/20 text-safe" },
  low_priority: { label: "Low Priority", color: "bg-muted text-muted-foreground" },
  spam_like: { label: "Spam", color: "bg-destructive/20 text-destructive" },
};

export const PRIORITY_CONFIG: Record<PriorityLevel, { label: string; color: string }> = {
  critical: { label: "Critical", color: "bg-critical text-critical-foreground" },
  high: { label: "High", color: "bg-warning/20 text-warning" },
  medium: { label: "Medium", color: "bg-primary/20 text-primary" },
  low: { label: "Low", color: "bg-muted text-muted-foreground" },
};