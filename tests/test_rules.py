from datetime import datetime, timedelta, timezone

from inboxanchor.core.rules import RulesEngine
from inboxanchor.models import EmailClassification, EmailMessage, WorkspacePolicy
from inboxanchor.models.email import EmailCategory, PriorityLevel, RecommendationStatus


def _email(
    *,
    sender: str,
    subject: str,
    snippet: str,
    body_preview: str,
    age_days: int = 1,
    has_attachments: bool = False,
) -> EmailMessage:
    return EmailMessage(
        id=f"email-{abs(hash((sender, subject))) % 100000}",
        thread_id="thread-1",
        sender=sender,
        subject=subject,
        snippet=snippet,
        body_preview=body_preview,
        received_at=datetime.now(timezone.utc) - timedelta(days=age_days),
        labels=["inbox"],
        has_attachments=has_attachments,
        unread=True,
    )


def _classification(
    category: EmailCategory,
    *,
    priority: PriorityLevel = PriorityLevel.low,
    confidence: float = 0.9,
    reason: str = "test",
) -> EmailClassification:
    return EmailClassification(
        category=category,
        priority=priority,
        confidence=confidence,
        reason=reason,
    )


def test_auto_archive_spam_like_cleanup_fires():
    email = _email(
        sender="winner@totally-safe.biz",
        subject="Claim now",
        snippet="Lottery winnings are waiting.",
        body_preview="Claim now and verify your wallet transfer today.",
    )
    classification = _classification(EmailCategory.spam_like, confidence=0.9)

    recommendation = RulesEngine().recommend(email, classification)

    assert recommendation.recommended_action == "archive"
    assert recommendation.requires_approval is False
    assert recommendation.status == RecommendationStatus.safe
    assert recommendation.proposed_labels == ["cleanup"]


def test_auto_archive_cleanup_fires_for_automated_promo():
    email = _email(
        sender="deals@shop.example",
        subject="Limited offer just for you",
        snippet="Save big this weekend.",
        body_preview="Unsubscribe or manage preferences if you do not want more promo email.",
    )
    classification = _classification(EmailCategory.promo, confidence=0.86)

    recommendation = RulesEngine().recommend(email, classification)

    assert recommendation.recommended_action == "archive"
    assert recommendation.requires_approval is False
    assert recommendation.status == RecommendationStatus.safe
    assert recommendation.proposed_labels == ["cleanup"]


def test_auto_archive_attachment_guard_blocks_cleanup():
    email = _email(
        sender="winner@totally-safe.biz",
        subject="Claim now",
        snippet="Lottery winnings are waiting.",
        body_preview="Claim now and verify your wallet transfer today.",
        has_attachments=True,
    )
    classification = _classification(EmailCategory.spam_like, confidence=0.9)

    recommendation = RulesEngine().recommend(email, classification)

    assert recommendation.requires_approval is True
    assert recommendation.status == RecommendationStatus.requires_approval
    assert recommendation.recommended_action == "trash"


def test_auto_archive_finance_guard_blocks_cleanup():
    email = _email(
        sender="deals@shop.example",
        subject="Limited offer and invoice reminder",
        snippet="Save big this weekend.",
        body_preview="Your invoice is ready. Unsubscribe from future promos if needed.",
        age_days=1,
    )
    classification = _classification(EmailCategory.promo, confidence=0.9)

    recommendation = RulesEngine().recommend(email, classification)

    assert recommendation.requires_approval is True
    assert recommendation.status == RecommendationStatus.requires_approval
    assert recommendation.recommended_action == "review"


def test_auto_archive_cleanup_newsletter():
    email = _email(
        sender="newsletter@example.com",
        subject="Weekly digest",
        snippet="Top updates for the week",
        body_preview="Newsletter digest with unsubscribe footer.",
    )
    classification = _classification(EmailCategory.newsletter, confidence=0.9)

    recommendation = RulesEngine().recommend(email, classification)

    assert recommendation.recommended_action == "archive"
    assert recommendation.requires_approval is False
    assert recommendation.status == RecommendationStatus.safe
    assert recommendation.proposed_labels == ["cleanup"]


def test_high_value_newsletter_not_auto_archived():
    email = _email(
        sender="briefing@techcrunch.com",
        subject="TechCrunch Daily: the latest in AI",
        snippet="Your daily startup and AI briefing is here.",
        body_preview="Daily briefing with startup, venture, and AI news. Unsubscribe anytime.",
    )
    classification = _classification(
        EmailCategory.newsletter,
        priority=PriorityLevel.medium,
        confidence=0.97,
    )

    recommendation = RulesEngine().recommend(email, classification)

    assert recommendation.recommended_action != "archive"
    assert recommendation.requires_approval is True
    assert recommendation.status == RecommendationStatus.requires_approval
    assert recommendation.proposed_labels == ["newsletter"]


def test_newsletter_rule_respects_workspace_policy_threshold_for_high_value_mail():
    email = _email(
        sender="briefing@techcrunch.com",
        subject="TechCrunch Daily: the latest in AI",
        snippet="Your daily startup and AI briefing is here.",
        body_preview="Daily briefing with startup, venture, and AI news. Unsubscribe anytime.",
    )
    classification = _classification(
        EmailCategory.newsletter,
        priority=PriorityLevel.medium,
        confidence=0.91,
    )
    policy = WorkspacePolicy(newsletter_confidence_threshold=0.95)

    recommendation = RulesEngine().recommend(email, classification, policy=policy)

    assert recommendation.recommended_action == "review"
    assert recommendation.status == RecommendationStatus.requires_approval
