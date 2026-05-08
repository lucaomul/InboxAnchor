from datetime import datetime, timedelta, timezone

import inboxanchor.app.dashboard as dashboard
from inboxanchor.models import (
    EmailActionItem,
    EmailClassification,
    EmailMessage,
    EmailRecommendation,
    InboxDigest,
    TriageRunResult,
)
from inboxanchor.models.email import RecommendationStatus


def test_dashboard_provider_options_falls_back_when_bootstrap_symbol_is_missing(monkeypatch):
    monkeypatch.delattr(dashboard.bootstrap_module, "PROVIDER_OPTIONS", raising=False)

    assert dashboard._provider_options()[0] == "fake"
    assert "gmail" in dashboard._provider_options()


def test_dashboard_provider_profile_falls_back_when_bootstrap_resolver_is_missing(monkeypatch):
    monkeypatch.delattr(dashboard.bootstrap_module, "get_provider_profile", raising=False)

    profile = dashboard._provider_profile("outlook")

    assert profile.slug == "outlook"
    assert profile.auth_mode == "app-password-or-oauth-later"


def test_dashboard_engine_runner_filters_kwargs_for_older_signatures():
    class OldEngine:
        def run(self, *, dry_run=True, limit=50):
            return {"dry_run": dry_run, "limit": limit}

    result = dashboard._run_engine_compat(
        OldEngine(),
        dry_run=False,
        limit=200,
        batch_size=500,
        confidence_threshold=0.75,
    )

    assert result == {"dry_run": False, "limit": 200}


def test_dashboard_playbook_definition_falls_back_to_balanced():
    playbook = dashboard._playbook_definition("does-not-exist")

    assert playbook["label"] == "Balanced Triage"


def test_dashboard_build_focus_views_groups_emails_by_operator_need():
    now = datetime.now(timezone.utc)
    result = TriageRunResult(
        run_id="triage_test",
        provider="fake",
        dry_run=True,
        total_emails=3,
        scanned_emails=3,
        batch_size=100,
        batch_count=1,
        email_preview_limit=100,
        recommendation_preview_limit=100,
        emails=[
            EmailMessage(
                id="reply_now",
                thread_id="thread_1",
                sender="ceo@example.com",
                subject="Need your reply today",
                snippet="Please confirm the plan.",
                body_preview="Please confirm the plan before noon.",
                received_at=now,
            ),
            EmailMessage(
                id="approval_needed",
                thread_id="thread_2",
                sender="finance@example.com",
                subject="Invoice review",
                snippet="Please approve the invoice.",
                body_preview="Invoice attached and needs approval.",
                received_at=now,
                has_attachments=True,
            ),
            EmailMessage(
                id="cleanup_ready",
                thread_id="thread_3",
                sender="newsletter@example.com",
                subject="Weekly product news",
                snippet="This week's updates.",
                body_preview="A weekly digest of product updates.",
                received_at=now,
            ),
        ],
        classifications={
            "reply_now": EmailClassification(
                category="work",
                priority="high",
                confidence=0.92,
                reason="Direct work request.",
            ),
            "approval_needed": EmailClassification(
                category="finance",
                priority="medium",
                confidence=0.88,
                reason="Finance-related email with attachment.",
            ),
            "cleanup_ready": EmailClassification(
                category="newsletter",
                priority="low",
                confidence=0.95,
                reason="Recurring newsletter.",
            ),
        },
        action_items={
            "reply_now": [
                EmailActionItem(
                    email_id="reply_now",
                    action_type="reply_needed",
                    description="Reply to confirm the plan.",
                    requires_reply=True,
                )
            ],
            "approval_needed": [],
            "cleanup_ready": [],
        },
        recommendations=[
            EmailRecommendation(
                email_id="reply_now",
                recommended_action="apply_labels",
                reason="Keep visible until replied.",
                confidence=0.8,
                status=RecommendationStatus.requires_approval,
            ),
            EmailRecommendation(
                email_id="approval_needed",
                recommended_action="archive",
                reason="Finance mail stays gated for review.",
                confidence=0.84,
                status=RecommendationStatus.requires_approval,
                blocked_reason="Finance mail requires review.",
            ),
            EmailRecommendation(
                email_id="cleanup_ready",
                recommended_action="mark_read",
                reason="Low-risk recurring newsletter.",
                confidence=0.97,
                status=RecommendationStatus.safe,
                requires_approval=False,
            ),
        ],
        digest=InboxDigest(
            total_unread=3,
            category_counts={"work": 1, "finance": 1, "newsletter": 1},
            high_priority_ids=["reply_now"],
            summary="Three unread emails need attention.",
            daily_digest="One reply, one finance review, one cleanup candidate.",
            weekly_digest="Inbox mix remains light.",
        ),
        reply_drafts={"reply_now": "Thanks — I will confirm the plan shortly."},
        approvals_required=["reply_now", "approval_needed"],
        blocked_actions=[],
    )

    focus_views = dashboard._build_focus_views(result)

    assert [entry["email"].id for entry in focus_views["reply_now"]] == ["reply_now"]
    assert [entry["email"].id for entry in focus_views["needs_approval"]] == [
        "reply_now",
        "approval_needed",
    ]
    assert [entry["email"].id for entry in focus_views["sensitive"]] == ["approval_needed"]
    assert [entry["email"].id for entry in focus_views["cleanup"]] == ["cleanup_ready"]


def test_dashboard_build_follow_up_radar_respects_threshold_and_priority_floor():
    now = datetime.now(timezone.utc)
    result = TriageRunResult(
        run_id="triage_follow_up",
        provider="fake",
        dry_run=True,
        total_emails=2,
        scanned_emails=2,
        batch_size=100,
        batch_count=1,
        email_preview_limit=100,
        recommendation_preview_limit=100,
        emails=[
            EmailMessage(
                id="stale_high",
                thread_id="thread_a",
                sender="client@example.com",
                subject="Need an answer",
                snippet="Checking in on this.",
                body_preview="Checking in on this thread.",
                received_at=now - timedelta(hours=30),
            ),
            EmailMessage(
                id="fresh_medium",
                thread_id="thread_b",
                sender="ops@example.com",
                subject="Fresh follow-up",
                snippet="Quick reminder.",
                body_preview="Quick reminder on this item.",
                received_at=now - timedelta(hours=4),
            ),
        ],
        classifications={
            "stale_high": EmailClassification(
                category="work",
                priority="high",
                confidence=0.9,
                reason="High priority client thread.",
            ),
            "fresh_medium": EmailClassification(
                category="work",
                priority="medium",
                confidence=0.88,
                reason="Medium priority reminder.",
            ),
        },
        action_items={
            "stale_high": [
                EmailActionItem(
                    email_id="stale_high",
                    action_type="follow_up",
                    description="Reply before the thread goes cold.",
                    requires_reply=True,
                )
            ],
            "fresh_medium": [
                EmailActionItem(
                    email_id="fresh_medium",
                    action_type="reply_needed",
                    description="Reply soon.",
                    requires_reply=True,
                )
            ],
        },
        recommendations=[
            EmailRecommendation(
                email_id="stale_high",
                recommended_action="apply_labels",
                reason="Keep visible for follow-up.",
                confidence=0.82,
                status=RecommendationStatus.requires_approval,
            ),
            EmailRecommendation(
                email_id="fresh_medium",
                recommended_action="apply_labels",
                reason="Keep visible for follow-up.",
                confidence=0.81,
                status=RecommendationStatus.requires_approval,
            ),
        ],
        digest=InboxDigest(
            total_unread=2,
            category_counts={"work": 2},
            high_priority_ids=["stale_high"],
            summary="Two follow-up threads are active.",
            daily_digest="One stale and one fresh follow-up need tracking.",
            weekly_digest="Follow-up pressure is manageable.",
        ),
        reply_drafts={},
        approvals_required=["stale_high", "fresh_medium"],
        blocked_actions=[],
    )

    settings = dashboard.SimpleNamespace(
        follow_up_radar_enabled=True,
        follow_up_after_hours=24,
        follow_up_priority_floor="medium",
    )
    radar_entries = dashboard._build_follow_up_radar(result, settings)

    assert [entry["email"].id for entry in radar_entries] == ["stale_high"]


def test_dashboard_format_due_label_handles_future_and_overdue_windows():
    now = datetime.now(timezone.utc)

    future_label = dashboard._format_due_label(now + timedelta(hours=6))
    overdue_label = dashboard._format_due_label(now - timedelta(hours=3))

    assert future_label.startswith("due in ")
    assert overdue_label.startswith("overdue by ")
