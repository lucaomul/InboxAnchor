from __future__ import annotations

from datetime import datetime, timezone

from pydantic import BaseModel, Field


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class WorkspacePolicy(BaseModel):
    allow_newsletter_mark_read: bool = True
    newsletter_confidence_threshold: float = Field(default=0.9, ge=0.0, le=1.0)
    allow_promo_archive: bool = True
    promo_archive_age_days: int = Field(default=14, ge=1, le=365)
    allow_low_priority_cleanup: bool = True
    low_priority_age_days: int = Field(default=7, ge=1, le=365)
    allow_spam_trash_recommendations: bool = True
    auto_label_recommendations: bool = True
    require_review_for_attachments: bool = True
    require_review_for_finance: bool = True
    require_review_for_personal: bool = True


class WorkspaceSettings(BaseModel):
    preferred_provider: str = "fake"
    dry_run_default: bool = True
    default_scan_limit: int = Field(default=500, ge=25, le=10000)
    default_batch_size: int = Field(default=250, ge=25, le=1000)
    default_confidence_threshold: float = Field(default=0.65, ge=0.0, le=1.0)
    default_email_preview_limit: int = Field(default=120, ge=10, le=500)
    default_recommendation_preview_limit: int = Field(default=180, ge=10, le=1000)
    onboarding_completed: bool = False
    operator_mode: str = "safe"
    policy: WorkspacePolicy = Field(default_factory=WorkspacePolicy)
    updated_at: datetime = Field(default_factory=_utcnow)
