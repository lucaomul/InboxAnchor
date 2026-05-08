from datetime import timedelta

from inboxanchor.bootstrap import build_demo_emails
from inboxanchor.connectors.fake_provider import FakeEmailProvider
from inboxanchor.core.triage_engine import TriageEngine


def test_triage_engine_with_fake_emails_produces_digest_and_recommendations():
    engine = TriageEngine(FakeEmailProvider(build_demo_emails()))

    result = engine.run(dry_run=True, limit=10)

    assert result.total_emails >= 5
    assert result.digest.total_unread == result.total_emails
    assert result.recommendations
    assert any(rec.recommended_action == "trash" for rec in result.recommendations)
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
