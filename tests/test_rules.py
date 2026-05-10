from datetime import datetime, timedelta, timezone

from inboxanchor.core.rules import RulesEngine
from inboxanchor.mail_intelligence import (
    extract_project_slug,
    is_work_dev_or_ai,
    recommend_mailbox_labels,
)
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


def test_high_value_newsletter_stays_in_review():
    email = EmailMessage(
        id="newsletter-3",
        thread_id="thread-3",
        sender="briefing@techcrunch.com",
        subject="TechCrunch Daily: the latest in AI",
        snippet="Your daily startup and AI briefing is here.",
        body_preview="Daily briefing with startup, venture, and AI news. Unsubscribe anytime.",
        received_at=datetime.now(timezone.utc) - timedelta(days=1),
        labels=["inbox"],
        has_attachments=False,
        unread=True,
    )
    classification = EmailClassification(
        category=EmailCategory.newsletter,
        priority=PriorityLevel.medium,
        confidence=0.97,
        reason="Newsletter markers detected.",
    )

    recommendation = RulesEngine().recommend(email, classification)

    assert recommendation.recommended_action == "review"
    assert recommendation.status == RecommendationStatus.requires_approval
    assert "newsletters/high-value" in recommendation.proposed_labels


def test_recommend_mailbox_labels_keeps_job_alerts_low_signal():
    labels = recommend_mailbox_labels(
        sender="jobs-noreply@linkedin.com",
        subject="Gabriel Luca, your application was sent to Adecco",
        snippet="See similar jobs and recommended roles for your profile.",
        body="LinkedIn found more jobs for you this week. Manage preferences or unsubscribe.",
        category="low_priority",
        priority="low",
    )

    assert "jobs/alert" in labels
    assert "cleanup/low-priority" in labels
    assert "automation/notification" in labels
    assert not any(label.startswith("needs-reply/") for label in labels)
    assert not any(label.startswith("projects/") for label in labels)
    assert "priority/high" not in labels


def test_recommend_mailbox_labels_keeps_github_threads_in_work_lane():
    labels = recommend_mailbox_labels(
        sender="notifications@github.com",
        subject="[lucaomul/InboxAnchor] Run failed: CI - main",
        snippet="The latest CI run failed on main after the last push.",
        body="GitHub Actions reported a failed workflow run and linked the logs.",
        category="work",
        priority="high",
    )

    assert "work/github" in labels
    assert "projects/inboxanchor" in labels
    assert "jobs/alert" not in labels
    assert not any(label.startswith("needs-reply/") for label in labels)


def test_extract_project_slug_requires_explicit_project_signal():
    slug = extract_project_slug(
        sender="billing@service.com",
        subject="Invoice update",
        snippet="Your monthly invoice is ready.",
        body="Download the invoice PDF from the dashboard.",
    )

    assert slug is None


def test_is_work_dev_or_ai_does_not_match_ci_inside_normal_words():
    assert not is_work_dev_or_ai(
        sender='"Booking.com" <email.campaign@sg.booking.com>',
        subject="O calatorie la Bucuresti, ultimele preturi sunt aici",
        snippet="Vezi ultimele preturi si oferte de sezon.",
        body="Planifica o escapada si vezi ofertele disponibile.",
    )
