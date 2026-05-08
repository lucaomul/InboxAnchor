from __future__ import annotations

from typing import Optional

from inboxanchor.connectors.base import EmailProvider, ProviderActionResult
from inboxanchor.models import EmailMessage


class IMAPEmailClient(EmailProvider):
    """
    IMAP-oriented provider surface for Yahoo, Outlook, and other compatible inboxes.

    This v1 keeps the runtime implementation intentionally thin and safe while
    exposing the same contract as Gmail. A future iteration can wire real imaplib
    flows behind these methods without changing the core engine.
    """

    provider_name = "imap"

    def __init__(
        self,
        seed_messages: Optional[list[EmailMessage]] = None,
        *,
        provider_name: str = "imap",
    ):
        self.provider_name = provider_name
        self._messages = {
            message.id: message.model_copy(deep=True)
            for message in seed_messages or []
        }

    def list_unread(self, limit: int = 50, include_body: bool = True) -> list[EmailMessage]:
        emails = [item.model_copy(deep=True) for item in self._messages.values() if item.unread]
        emails.sort(key=lambda item: item.received_at, reverse=True)
        return emails[:limit]

    def iter_unread_batches(
        self,
        *,
        limit: int = 50,
        batch_size: int = 100,
        include_body: bool = True,
    ):
        emails = self.list_unread(limit=limit, include_body=include_body)
        for start in range(0, len(emails), batch_size):
            yield emails[start : start + batch_size]

    def fetch_email_metadata(self, email_id: str) -> EmailMessage:
        return self._messages[email_id].model_copy(deep=True)

    def fetch_email_body(self, email_id: str) -> str:
        return self._messages[email_id].body_preview

    def batch_mark_as_read(
        self,
        email_ids: list[str],
        *,
        dry_run: bool = True,
    ) -> ProviderActionResult:
        if not dry_run:
            for email_id in email_ids:
                self._messages[email_id].unread = False
        return ProviderActionResult(
            provider=self.provider_name,
            action="mark_read",
            email_ids=email_ids,
            dry_run=dry_run,
            executed=not dry_run,
            details="IMAP read state prepared." if dry_run else "IMAP read state executed.",
        )

    def archive_emails(
        self,
        email_ids: list[str],
        *,
        dry_run: bool = True,
    ) -> ProviderActionResult:
        if not dry_run:
            for email_id in email_ids:
                self._messages[email_id].labels = sorted(
                    set(self._messages[email_id].labels + ["archived"])
                )
                self._messages[email_id].unread = False
        return ProviderActionResult(
            provider=self.provider_name,
            action="archive",
            email_ids=email_ids,
            dry_run=dry_run,
            executed=not dry_run,
            details="IMAP archive prepared." if dry_run else "IMAP archive executed.",
        )

    def move_to_trash(
        self,
        email_ids: list[str],
        *,
        explicit_confirmation: bool,
        dry_run: bool = True,
    ) -> ProviderActionResult:
        if not explicit_confirmation:
            return ProviderActionResult(
                provider=self.provider_name,
                action="trash",
                email_ids=email_ids,
                dry_run=dry_run,
                executed=False,
                details="Explicit confirmation required before IMAP trash actions.",
            )
        if not dry_run:
            for email_id in email_ids:
                self._messages[email_id].labels = sorted(
                    set(self._messages[email_id].labels + ["trash"])
                )
        return ProviderActionResult(
            provider=self.provider_name,
            action="trash",
            email_ids=email_ids,
            dry_run=dry_run,
            executed=not dry_run,
            details="IMAP trash prepared." if dry_run else "IMAP trash executed.",
        )

    def apply_labels(
        self,
        email_ids: list[str],
        labels: list[str],
        *,
        dry_run: bool = True,
    ) -> ProviderActionResult:
        if not dry_run:
            for email_id in email_ids:
                self._messages[email_id].labels = sorted(
                    set(self._messages[email_id].labels + labels)
                )
        return ProviderActionResult(
            provider=self.provider_name,
            action="apply_labels",
            email_ids=email_ids,
            dry_run=dry_run,
            executed=not dry_run,
            details=f"IMAP labels prepared: {', '.join(labels)}",
        )
