from __future__ import annotations

import logging
from typing import Optional

from inboxanchor.agents.classifier import ClassifierAgent
from inboxanchor.connectors.base import EmailProvider
from inboxanchor.infra.database import session_scope
from inboxanchor.infra.repository import InboxRepository

logger = logging.getLogger(__name__)


class BodyBackfillJob:
    """
    Fetch full bodies for low-confidence mailbox rows and re-classify them.
    """

    def __init__(
        self,
        provider: EmailProvider,
        *,
        classifier: Optional[ClassifierAgent] = None,
    ):
        self.provider = provider
        self.classifier = classifier or ClassifierAgent()

    def run(
        self,
        *,
        confidence_threshold: float = 0.75,
        batch_size: int = 50,
        max_emails: int = 500,
    ) -> dict:
        stats = {
            "processed": 0,
            "reclassified": 0,
            "skipped": 0,
            "errors": 0,
        }

        with session_scope() as session:
            repo = InboxRepository(session)
            candidates = repo.get_low_confidence_emails(
                self.provider.provider_name,
                confidence_threshold=confidence_threshold,
                body_fetched=False,
                limit=max_emails,
            )

        for start in range(0, len(candidates), batch_size):
            batch = candidates[start : start + batch_size]
            for email, existing_classification in batch:
                try:
                    body = self.provider.fetch_email_body(email.id)
                    if not body.strip():
                        stats["skipped"] += 1
                        continue
                    hydrated = email.model_copy(
                        update={
                            "body_full": body,
                            "body_preview": (body or email.body_preview or email.snippet)[:500],
                            "body_fetched": True,
                            "body_stored": True,
                        }
                    )
                    new_classification = self.classifier.classify(hydrated)
                    with session_scope() as session:
                        repo = InboxRepository(session)
                        repo.update_email_body_and_classification(
                            self.provider.provider_name,
                            hydrated,
                            new_classification,
                        )
                    stats["processed"] += 1
                    if new_classification.category != existing_classification.category:
                        stats["reclassified"] += 1
                except Exception as exc:
                    logger.warning(
                        "Body backfill failed for mailbox email.",
                        extra={"email_id": email.id, "error": str(exc)},
                    )
                    stats["errors"] += 1

        logger.info("Body backfill complete", extra=stats)
        return stats
