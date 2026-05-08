from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional

try:
    from enum import StrEnum
except ImportError:  # pragma: no cover - Python < 3.11 fallback
    class StrEnum(str, Enum):
        pass

from pydantic import BaseModel, ConfigDict, Field


class EmailCategory(StrEnum):
    urgent = "urgent"
    work = "work"
    finance = "finance"
    newsletter = "newsletter"
    promo = "promo"
    spam_like = "spam_like"
    personal = "personal"
    opportunity = "opportunity"
    low_priority = "low_priority"
    unknown = "unknown"


class PriorityLevel(StrEnum):
    critical = "critical"
    high = "high"
    medium = "medium"
    low = "low"


class RecommendationStatus(StrEnum):
    safe = "safe"
    requires_approval = "requires_approval"
    blocked = "blocked"


class SafetyStatus(StrEnum):
    allowed = "allowed"
    requires_review = "requires_review"
    blocked = "blocked"


class EmailMessage(BaseModel):
    model_config = ConfigDict(use_enum_values=True)

    id: str
    thread_id: str
    sender: str
    subject: str
    snippet: str
    body_preview: str
    received_at: datetime
    labels: list[str] = Field(default_factory=list)
    has_attachments: bool = False
    unread: bool = True


class EmailThread(BaseModel):
    thread_id: str
    messages: list[EmailMessage]
    summary: Optional[str] = None


class EmailClassification(BaseModel):
    model_config = ConfigDict(use_enum_values=True)

    category: EmailCategory
    priority: PriorityLevel
    confidence: float = Field(ge=0.0, le=1.0)
    reason: str


class EmailActionItem(BaseModel):
    email_id: str
    action_type: str
    description: str
    due_hint: Optional[str] = None
    requires_reply: bool = False


class EmailRecommendation(BaseModel):
    email_id: str
    recommended_action: str
    reason: str
    confidence: float = Field(ge=0.0, le=1.0)
    status: RecommendationStatus = RecommendationStatus.requires_approval
    requires_approval: bool = True
    blocked_reason: Optional[str] = None
    proposed_labels: list[str] = Field(default_factory=list)


class InboxDigest(BaseModel):
    total_unread: int
    category_counts: dict[str, int]
    high_priority_ids: list[str]
    summary: str
    daily_digest: str
    weekly_digest: str


class AutomationDecision(BaseModel):
    email_id: str
    proposed_action: str
    final_action: Optional[str] = None
    approved_by_user: bool = False
    reason: str
    confidence: float = Field(ge=0.0, le=1.0)
    safety_verifier_status: SafetyStatus


class AuditLogEntry(BaseModel):
    email_id: str
    proposed_action: str
    final_action: str
    approved_by_user: bool
    timestamp: datetime
    reason: str
    confidence: float = Field(ge=0.0, le=1.0)
    agent_decision: str
    safety_verifier_status: SafetyStatus


class TriageRunResult(BaseModel):
    run_id: str
    provider: str
    dry_run: bool
    total_emails: int
    scanned_emails: int
    batch_size: int
    batch_count: int
    email_preview_limit: int
    recommendation_preview_limit: int
    email_preview_truncated: bool = False
    recommendation_preview_truncated: bool = False
    emails: list[EmailMessage]
    classifications: dict[str, EmailClassification]
    action_items: dict[str, list[EmailActionItem]]
    recommendations: list[EmailRecommendation]
    digest: InboxDigest
    reply_drafts: dict[str, str] = Field(default_factory=dict)
    approvals_required: list[str]
    blocked_actions: list[str]
