from datetime import timedelta

from inboxanchor.bootstrap import build_demo_emails
from inboxanchor.connectors.fake_provider import FakeEmailProvider
from inboxanchor.core.triage_engine import TriageEngine
from inboxanchor.models import EmailClassification
from inboxanchor.models.email import EmailCategory, PriorityLevel


def test_triage_engine_with_fake_emails_produces_digest_and_recommendations():
    engine = TriageEngine(FakeEmailProvider(build_demo_emails()))

    result = engine.run(dry_run=True, limit=10)

    assert result.total_emails >= 5
    assert result.digest.total_unread == result.total_emails
    assert result.recommendations
    assert any(rec.recommended_action == "archive" for rec in result.recommendations)
    assert any(rec.email_id in result.reply_drafts for rec in result.recommendations)


def test_triage_engine_batches_large_inboxes_and_caps_previews():
    seed = build_demo_emails()[0]
    emails = [
        seed.model_copy(
            update={
                "id": f"msg_scale_{index}",
                "thread_id": f"thr_scale_{index}",
                "subject": f"Scale email {index}",
                "received_at": seed.received_at - timedelta(minutes=index),
                "has_attachments": index % 7 == 0,
            }
        )
        for index in range(1250)
    ]
    engine = TriageEngine(FakeEmailProvider(emails))

    result = engine.run(
        dry_run=True,
        limit=1250,
        batch_size=250,
        email_preview_limit=80,
        recommendation_preview_limit=90,
    )

    assert result.scanned_emails == 1250
    assert result.total_emails == 1250
    assert result.batch_count == 5
    assert len(result.emails) >= 80
    assert len(result.recommendations) == 90
    assert result.email_preview_truncated is True
    assert result.recommendation_preview_truncated is True


def test_clear_body_releases_memory():
    email = build_demo_emails()[0].model_copy(
        update={
            "body_full": "Long body",
            "body_fetched": True,
            "body_stored": True,
        }
    )

    email.clear_body()

    assert email.body_full == ""
    assert email.body_stored is False


def test_triage_run_metadata_only_skips_body_agents():
    class CountingClassifier:
        def __init__(self):
            self.calls = 0

        def classify(self, email, intelligence=None, allow_llm=True):
            del email, intelligence, allow_llm
            self.calls += 1
            return EmailClassification(
                category=EmailCategory.work,
                priority=PriorityLevel.medium,
                confidence=0.8,
                reason="test",
            )

    class ForbiddenSummarizer:
        def build_digest(self, emails, classifications):
            raise AssertionError("metadata_only should skip summarizer")

    class ForbiddenActionExtractor:
        def extract(self, email, classification=None):
            raise AssertionError("metadata_only should skip action extractor")

    class ForbiddenReplyDrafter:
        def draft(self, email, items, classification=None):
            raise AssertionError("metadata_only should skip reply drafter")

    classifier = CountingClassifier()
    engine = TriageEngine(
        FakeEmailProvider(build_demo_emails()),
        classifier=classifier,
        summarizer=ForbiddenSummarizer(),
        action_extractor=ForbiddenActionExtractor(),
        reply_drafter=ForbiddenReplyDrafter(),
    )

    result = engine.run(
        dry_run=True,
        limit=10,
        metadata_only=True,
        include_body=True,
        extract_actions=True,
        draft_replies=True,
    )

    assert classifier.calls == result.total_emails
    assert result.metadata_only is True
    assert result.digest.total_unread == result.total_emails
    assert result.reply_drafts == {}
