from __future__ import annotations

from typing import Optional

from inboxanchor.models import (
    EmailClassification,
    EmailMessage,
    EmailRecommendation,
    WorkspacePolicy,
)
from inboxanchor.models.email import EmailCategory, PriorityLevel, RecommendationStatus


class SafetyVerifierAgent:
    def verify(
        self,
        email: EmailMessage,
        classification: EmailClassification,
        recommendation: EmailRecommendation,
        policy: Optional[WorkspacePolicy] = None,
    ) -> EmailRecommendation:
        policy = policy or WorkspacePolicy()
        blocked_reason: Optional[str] = None
        requires_approval = recommendation.requires_approval
        status = recommendation.status

        risky_categories = {
            EmailCategory.work,
            EmailCategory.opportunity,
            EmailCategory.urgent,
        }
        if policy.require_review_for_finance:
            risky_categories.add(EmailCategory.finance)
        if policy.require_review_for_personal:
            risky_categories.add(EmailCategory.personal)

        if recommendation.recommended_action == "trash":
            status = RecommendationStatus.requires_approval
            requires_approval = True
            blocked_reason = "Trash actions always require explicit human confirmation."

        if policy.require_review_for_attachments and email.has_attachments:
            status = RecommendationStatus.requires_approval
            requires_approval = True
            blocked_reason = "Emails with attachments require human review."

        if classification.confidence < 0.7:
            status = RecommendationStatus.requires_approval
            requires_approval = True
            blocked_reason = "Low-confidence classification requires review."

        if classification.category in risky_categories:
            status = RecommendationStatus.requires_approval
            requires_approval = True
            blocked_reason = "This category should not be auto-processed."

        if (
            classification.priority in {PriorityLevel.critical, PriorityLevel.high}
            and recommendation.recommended_action == "mark_read"
        ):
            status = RecommendationStatus.blocked
            requires_approval = True
            blocked_reason = "Critical/high-priority email cannot be auto-marked as read."

        return recommendation.model_copy(
            update={
                "status": status,
                "requires_approval": requires_approval,
                "blocked_reason": blocked_reason,
            }
        )
