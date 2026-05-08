from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

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
        newsletter_labels = ["newsletter"] if policy.auto_label_recommendations else []
        promo_labels = ["promo"] if policy.auto_label_recommendations else []
        spam_labels = ["spam-review"] if policy.auto_label_recommendations else []
        low_priority_labels = ["low-priority"] if policy.auto_label_recommendations else []
        review_labels = ["needs-review"] if policy.auto_label_recommendations else []

        if (
            policy.allow_newsletter_mark_read
            and classification.category == EmailCategory.newsletter
            and classification.confidence > policy.newsletter_confidence_threshold
        ):
            return EmailRecommendation(
                email_id=email.id,
                recommended_action="mark_read",
                reason="High-confidence newsletter can be safely reviewed for mark-as-read.",
                confidence=classification.confidence,
                status=RecommendationStatus.safe,
                requires_approval=False,
                proposed_labels=newsletter_labels,
            )

        if (
            policy.allow_promo_archive
            and classification.category == EmailCategory.promo
            and age > timedelta(days=policy.promo_archive_age_days)
        ):
            return EmailRecommendation(
                email_id=email.id,
                recommended_action="archive",
                reason="Older promotional email is a good archive candidate.",
                confidence=max(classification.confidence, 0.85),
                status=RecommendationStatus.requires_approval,
                requires_approval=True,
                proposed_labels=promo_labels,
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
                proposed_labels=spam_labels,
            )

        if (
            policy.allow_low_priority_cleanup
            and classification.category == EmailCategory.low_priority
            and age > timedelta(days=policy.low_priority_age_days)
        ):
            return EmailRecommendation(
                email_id=email.id,
                recommended_action="mark_read",
                reason="Older low-priority message can be considered for cleanup.",
                confidence=max(classification.confidence, 0.75),
                status=RecommendationStatus.requires_approval,
                requires_approval=True,
                proposed_labels=low_priority_labels,
            )

        return EmailRecommendation(
            email_id=email.id,
            recommended_action="review",
            reason="Keep this email in the human review queue.",
            confidence=max(classification.confidence, 0.6),
            status=RecommendationStatus.requires_approval,
            requires_approval=True,
            proposed_labels=review_labels,
        )
