from datetime import datetime, timedelta, timezone

from inboxanchor.core.rules import RulesEngine
from inboxanchor.models import EmailClassification, EmailMessage, WorkspacePolicy
from inboxanchor.models.email import EmailCategory, PriorityLevel, RecommendationStatus


def test_newsletter_rule_recommends_mark_read():
    email = EmailMessage(
        id="newsletter-1",
        thread_id="thread-1",
        sender="newsletter@example.com",
        subject="Weekly digest",
        snippet="Top updates for the week",
        body_preview="Newsletter digest with unsubscribe footer.",
        received_at=datetime.now(timezone.utc) - timedelta(days=1),
        labels=["inbox"],
        has_attachments=False,
        unread=True,
    )
    classification = EmailClassification(
        category=EmailCategory.newsletter,
        priority=PriorityLevel.low,
        confidence=0.96,
        reason="Newsletter markers detected.",
    )

    recommendation = RulesEngine().recommend(email, classification)

    assert recommendation.recommended_action == "mark_read"
    assert recommendation.status == RecommendationStatus.safe


def test_newsletter_rule_respects_workspace_policy_threshold():
    email = EmailMessage(
        id="newsletter-2",
        thread_id="thread-2",
        sender="newsletter@example.com",
        subject="Weekly digest",
        snippet="Top updates for the week",
        body_preview="Newsletter digest with unsubscribe footer.",
        received_at=datetime.now(timezone.utc) - timedelta(days=1),
        labels=["inbox"],
        has_attachments=False,
        unread=True,
    )
    classification = EmailClassification(
        category=EmailCategory.newsletter,
        priority=PriorityLevel.low,
        confidence=0.91,
        reason="Newsletter markers detected.",
    )
    policy = WorkspacePolicy(newsletter_confidence_threshold=0.95)

    recommendation = RulesEngine().recommend(email, classification, policy=policy)

    assert recommendation.recommended_action == "review"
    assert recommendation.status == RecommendationStatus.requires_approval
