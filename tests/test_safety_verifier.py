from datetime import datetime, timezone

from inboxanchor.agents.safety_verifier import SafetyVerifierAgent
from inboxanchor.models import (
    EmailClassification,
    EmailMessage,
    EmailRecommendation,
    WorkspacePolicy,
)
from inboxanchor.models.email import (
    EmailCategory,
    PriorityLevel,
    RecommendationStatus,
)


def test_safety_verifier_blocks_high_priority_mark_read():
    email = EmailMessage(
        id="1",
        thread_id="thread-1",
        sender="finance@example.com",
        subject="Invoice due today",
        snippet="Pay this today",
        body_preview="Invoice due today.",
        received_at=datetime.now(timezone.utc),
        labels=["inbox"],
        has_attachments=False,
        unread=True,
    )
    classification = EmailClassification(
        category=EmailCategory.finance,
        priority=PriorityLevel.high,
        confidence=0.93,
        reason="Finance markers detected.",
    )
    recommendation = EmailRecommendation(
        email_id="1",
        recommended_action="mark_read",
        reason="Would normally clean this up.",
        confidence=0.9,
        status=RecommendationStatus.safe,
        requires_approval=False,
    )

    reviewed = SafetyVerifierAgent().verify(email, classification, recommendation)

    assert reviewed.status == RecommendationStatus.blocked
    assert reviewed.requires_approval is True


def test_safety_verifier_can_relax_personal_review_when_policy_allows_it():
    email = EmailMessage(
        id="2",
        thread_id="thread-2",
        sender="friend@example.com",
        subject="Weekend plan",
        snippet="Want to catch up?",
        body_preview="Let me know if you want to grab coffee this weekend.",
        received_at=datetime.now(timezone.utc),
        labels=["inbox"],
        has_attachments=False,
        unread=True,
    )
    classification = EmailClassification(
        category=EmailCategory.personal,
        priority=PriorityLevel.low,
        confidence=0.92,
        reason="Personal sender and informal tone detected.",
    )
    recommendation = EmailRecommendation(
        email_id="2",
        recommended_action="mark_read",
        reason="Low-risk cleanup candidate.",
        confidence=0.88,
        status=RecommendationStatus.safe,
        requires_approval=False,
    )
    policy = WorkspacePolicy(require_review_for_personal=False)

    reviewed = SafetyVerifierAgent().verify(email, classification, recommendation, policy=policy)

    assert reviewed.status == RecommendationStatus.safe
    assert reviewed.blocked_reason is None
