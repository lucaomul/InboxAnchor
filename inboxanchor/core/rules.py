from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

from inboxanchor.mail_intelligence import (
    is_high_value_newsletter,
    looks_automated_email,
    recommend_mailbox_labels,
)
from inboxanchor.models import (
    EmailClassification,
    EmailMessage,
    EmailRecommendation,
    WorkspacePolicy,
)
from inboxanchor.models.email import EmailCategory, RecommendationStatus


class RulesEngine:
    def recommend(
        self,
        email: EmailMessage,
        classification: EmailClassification,
        *,
        now: Optional[datetime] = None,
        policy: Optional[WorkspacePolicy] = None,
    ) -> EmailRecommendation:
        now = now or datetime.now(timezone.utc)
        policy = policy or WorkspacePolicy()
        age = now - email.received_at
        labels = (
            recommend_mailbox_labels(
                sender=email.sender,
                subject=email.subject,
                snippet=email.snippet,
                body=email.content_for_processing(),
                has_attachments=email.has_attachments,
                category=classification.category,
                priority=classification.priority,
            )
            if policy.auto_label_recommendations
            else []
        )
        automated = looks_automated_email(
            sender=email.sender,
            subject=email.subject,
            snippet=email.snippet,
            body=email.content_for_processing(),
        )
        high_value_newsletter = is_high_value_newsletter(
            sender=email.sender,
            subject=email.subject,
            snippet=email.snippet,
            body=email.content_for_processing(),
        )

        if (
            policy.allow_newsletter_mark_read
            and classification.category == EmailCategory.newsletter
            and classification.confidence > policy.newsletter_confidence_threshold
            and automated
            and not high_value_newsletter
        ):
            return EmailRecommendation(
                email_id=email.id,
                recommended_action="mark_read",
                reason="Low-value automated newsletter can be safely marked as read.",
                confidence=classification.confidence,
                status=RecommendationStatus.safe,
                requires_approval=False,
                proposed_labels=labels,
            )

        if (
            policy.allow_promo_archive
            and classification.category == EmailCategory.promo
            and age > timedelta(days=policy.promo_archive_age_days)
            and automated
        ):
            return EmailRecommendation(
                email_id=email.id,
                recommended_action="archive",
                reason="Older automated promotion is a good archive candidate.",
                confidence=max(classification.confidence, 0.85),
                status=RecommendationStatus.safe,
                requires_approval=False,
                proposed_labels=labels,
            )

        if classification.category == EmailCategory.spam_like:
            return EmailRecommendation(
                email_id=email.id,
                recommended_action="trash" if policy.allow_spam_trash_recommendations else "review",
                reason=(
                    "Spam-like indicators detected, but destructive action must stay gated."
                    if policy.allow_spam_trash_recommendations
                    else "Spam-like indicators detected, but policy keeps this in review."
                ),
                confidence=classification.confidence,
                status=RecommendationStatus.requires_approval,
                requires_approval=True,
                proposed_labels=labels or ["cleanup/low-priority"],
            )

        if (
            policy.allow_low_priority_cleanup
            and classification.category == EmailCategory.low_priority
            and age > timedelta(days=policy.low_priority_age_days)
            and automated
        ):
            return EmailRecommendation(
                email_id=email.id,
                recommended_action="mark_read",
                reason="Older automated low-priority message can be considered for cleanup.",
                confidence=max(classification.confidence, 0.75),
                status=RecommendationStatus.safe,
                requires_approval=False,
                proposed_labels=labels,
            )

        return EmailRecommendation(
            email_id=email.id,
            recommended_action="review",
            reason="Keep this email in the human review queue.",
            confidence=max(classification.confidence, 0.6),
            status=RecommendationStatus.requires_approval,
            requires_approval=True,
            proposed_labels=labels,
        )
