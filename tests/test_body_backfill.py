from datetime import datetime, timezone

from inboxanchor.connectors.fake_provider import FakeEmailProvider
from inboxanchor.core.body_backfill import BodyBackfillJob
from inboxanchor.infra.database import session_scope
from inboxanchor.infra.repository import InboxRepository
from inboxanchor.models import EmailClassification, EmailMessage
from inboxanchor.models.email import EmailCategory, PriorityLevel


def _seed_low_confidence_mailbox(provider_name: str) -> FakeEmailProvider:
    now = datetime.now(timezone.utc)
    emails = [
        EmailMessage(
            id="email-1",
            thread_id="thread-1",
            sender="alerts@example.com",
            subject="Ambiguous update",
            snippet="Snippet one",
            body_preview="Snippet one",
            body_full="Full body one",
            body_fetched=True,
            body_stored=True,
            received_at=now,
            labels=["UNREAD", "INBOX"],
            has_attachments=False,
            unread=True,
        ),
        EmailMessage(
            id="email-2",
            thread_id="thread-2",
            sender="alerts@example.com",
            subject="Ambiguous update two",
            snippet="Snippet two",
            body_preview="Snippet two",
            body_full="Full body two",
            body_fetched=True,
            body_stored=True,
            received_at=now,
            labels=["UNREAD", "INBOX"],
            has_attachments=False,
            unread=True,
        ),
    ]
    provider = FakeEmailProvider(emails, provider_name=provider_name)
    with session_scope() as session:
        repo = InboxRepository(session)
        for email in emails:
            metadata_email = email.model_copy(
                update={
                    "body_full": "",
                    "body_preview": email.snippet,
                    "body_fetched": False,
                    "body_stored": False,
                }
            )
            repo.upsert_mailbox_email(provider_name, metadata_email)
            repo.upsert_mailbox_classification(
                provider_name,
                email.id,
                EmailClassification(
                    category=EmailCategory.unknown,
                    priority=PriorityLevel.low,
                    confidence=0.4,
                    reason="low confidence",
                ),
                source="test",
            )
    return provider


def test_body_backfill_reclassifies_low_confidence():
    provider = _seed_low_confidence_mailbox("backfill-reclassify")

    class ReclassifyingClassifier:
        def classify(self, email, intelligence=None, allow_llm=True):
            del email, intelligence, allow_llm
            return EmailClassification(
                category=EmailCategory.work,
                priority=PriorityLevel.medium,
                confidence=0.9,
                reason="reclassified",
            )

    stats = BodyBackfillJob(
        provider,
        classifier=ReclassifyingClassifier(),
    ).run(confidence_threshold=0.75, batch_size=2, max_emails=2)

    assert stats["processed"] == 2
    assert stats["reclassified"] == 2


def test_body_backfill_handles_fetch_error():
    provider = _seed_low_confidence_mailbox("backfill-error")

    def failing_fetch(email_id: str) -> str:
        if email_id == "email-1":
            raise RuntimeError("boom")
        return "Recovered body"

    provider.fetch_email_body = failing_fetch  # type: ignore[method-assign]

    class StableClassifier:
        def classify(self, email, intelligence=None, allow_llm=True):
            del email, intelligence, allow_llm
            return EmailClassification(
                category=EmailCategory.personal,
                priority=PriorityLevel.medium,
                confidence=0.82,
                reason="stable",
            )

    stats = BodyBackfillJob(
        provider,
        classifier=StableClassifier(),
    ).run(confidence_threshold=0.75, batch_size=2, max_emails=2)

    assert stats["errors"] == 1
    assert stats["processed"] == 1
