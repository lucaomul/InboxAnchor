from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Callable, Optional

from inboxanchor.connectors.base import EmailProvider
from inboxanchor.core.time_windows import ALL_TIME_RANGE
from inboxanchor.infra.database import session_scope
from inboxanchor.infra.repository import InboxRepository
from inboxanchor.sender_intelligence import sender_address

logger = logging.getLogger(__name__)


@dataclass
class WarmupStats:
    emails_scanned: int = 0
    senders_discovered: int = 0
    senders_updated: int = 0
    errors: int = 0
    skipped: int = 0


def _warmup_time_range(months_back: int) -> str:
    if months_back <= 0:
        return ALL_TIME_RANGE
    if months_back <= 3:
        return "last_3_months"
    if months_back <= 6:
        return "last_6_months"
    if months_back <= 12:
        return "last_1_year"
    if months_back <= 36:
        return "last_3_years"
    if months_back <= 60:
        return "last_5_years"
    if months_back <= 120:
        return "last_10_years"
    return ALL_TIME_RANGE


class SenderWarmupJob:
    """
    Build sender and domain profiles from mailbox history without triaging mail.
    """

    def __init__(
        self,
        provider: EmailProvider,
        provider_name: str = "unknown",
    ):
        self.provider = provider
        self.provider_name = provider_name or provider.provider_name or "unknown"

    def run(
        self,
        *,
        months_back: int = 6,
        batch_size: int = 500,
        max_emails: int = 50_000,
        include_body: bool = False,
        progress_callback: Optional[Callable[[dict], None]] = None,
    ) -> WarmupStats:
        stats = WarmupStats()
        seen_senders: set[str] = set()
        time_range = _warmup_time_range(months_back)
        total_processed = 0

        try:
            batch_iterator = self._iter_warmup_batches(
                batch_size=batch_size,
                include_body=include_body,
                max_emails=max_emails,
                time_range=time_range,
            )
        except Exception:
            logger.warning(
                "Provider does not support mailbox history warmup; falling back to unread batches",
                extra={"provider": self.provider_name},
            )
            batch_iterator = self.provider.iter_unread_batches(
                limit=max_emails,
                batch_size=batch_size,
                include_body=include_body,
                time_range=time_range,
            )

        for batch in batch_iterator:
            if total_processed >= max_emails:
                logger.info(
                    "Warmup reached max_emails limit",
                    extra={"provider": self.provider_name, "max_emails": max_emails},
                )
                break

            with session_scope() as session:
                repository = InboxRepository(session)
                for email in batch:
                    if total_processed >= max_emails:
                        break
                    try:
                        normalized_sender = (
                            sender_address(email.sender) or email.sender.strip().lower()
                        )
                        if not normalized_sender:
                            stats.skipped += 1
                            continue
                        existing_profile = repository.get_sender_profile(
                            self.provider_name,
                            email.sender,
                        )
                        repository.observe_sender_intelligence(
                            self.provider_name,
                            email,
                            count_message=True,
                        )
                        stats.emails_scanned += 1
                        total_processed += 1
                        if normalized_sender in seen_senders:
                            stats.senders_updated += 1
                            continue
                        seen_senders.add(normalized_sender)
                        if existing_profile is None:
                            stats.senders_discovered += 1
                        else:
                            stats.senders_updated += 1
                    except Exception as exc:
                        stats.errors += 1
                        logger.warning(
                            "Warmup failed for email",
                            extra={
                                "provider": self.provider_name,
                                "email_id": getattr(email, "id", "unknown"),
                                "error": str(exc),
                            },
                        )

            if progress_callback:
                progress_callback(
                    {
                        "emails_scanned": stats.emails_scanned,
                        "senders_discovered": stats.senders_discovered,
                        "senders_updated": stats.senders_updated,
                        "errors": stats.errors,
                        "skipped": stats.skipped,
                    }
                )

        logger.info(
            "Sender warmup complete",
            extra={
                "provider": self.provider_name,
                "emails_scanned": stats.emails_scanned,
                "senders_discovered": stats.senders_discovered,
                "senders_updated": stats.senders_updated,
                "errors": stats.errors,
                "skipped": stats.skipped,
            },
        )
        return stats

    def _iter_warmup_batches(
        self,
        *,
        batch_size: int,
        include_body: bool,
        max_emails: int,
        time_range: str,
    ):
        iterator = getattr(self.provider, "iter_mailbox_batches", None)
        if not callable(iterator):
            raise AttributeError("Provider does not support mailbox history iteration.")
        try:
            return iterator(
                limit=max_emails,
                batch_size=batch_size,
                include_body=include_body,
                unread_only=False,
                time_range=time_range,
            )
        except NotImplementedError as exc:
            raise AttributeError("Provider does not support mailbox history iteration.") from exc
