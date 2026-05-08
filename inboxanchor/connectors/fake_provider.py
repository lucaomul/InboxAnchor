from __future__ import annotations

from copy import deepcopy
from typing import Optional

from inboxanchor.connectors.base import EmailProvider, ProviderActionResult
from inboxanchor.models import EmailMessage


class FakeEmailProvider(EmailProvider):
    provider_name = "fake"

    def __init__(
        self,
        emails: Optional[list[EmailMessage]] = None,
        *,
        provider_name: str = "fake",
    ):
        self.provider_name = provider_name
        self._emails = {email.id: deepcopy(email) for email in emails or []}

    def list_unread(self, limit: int = 50, include_body: bool = True) -> list[EmailMessage]:
        unread = [deepcopy(email) for email in self._emails.values() if email.unread]
        unread.sort(key=lambda item: item.received_at, reverse=True)
        return unread[:limit]

    def iter_unread_batches(
        self,
        *,
        limit: int = 50,
        batch_size: int = 100,
        include_body: bool = True,
    ):
        unread = self.list_unread(limit=limit, include_body=include_body)
        for start in range(0, len(unread), batch_size):
            yield unread[start : start + batch_size]

    def fetch_email_metadata(self, email_id: str) -> EmailMessage:
        return deepcopy(self._emails[email_id])

    def fetch_email_body(self, email_id: str) -> str:
        return self._emails[email_id].body_preview

    def batch_mark_as_read(
        self,
        email_ids: list[str],
        *,
        dry_run: bool = True,
    ) -> ProviderActionResult:
        if not dry_run:
            for email_id in email_ids:
                self._emails[email_id].unread = False
        return ProviderActionResult(
            provider=self.provider_name,
            action="mark_read",
            email_ids=email_ids,
            dry_run=dry_run,
            executed=not dry_run,
            details="Marked emails as read." if not dry_run else "Dry run only.",
        )

    def archive_emails(
        self,
        email_ids: list[str],
        *,
        dry_run: bool = True,
    ) -> ProviderActionResult:
        if not dry_run:
            for email_id in email_ids:
                labels = set(self._emails[email_id].labels)
                labels.add("archived")
                self._emails[email_id].labels = sorted(labels)
                self._emails[email_id].unread = False
        return ProviderActionResult(
            provider=self.provider_name,
            action="archive",
            email_ids=email_ids,
            dry_run=dry_run,
            executed=not dry_run,
            details="Archived emails." if not dry_run else "Dry run only.",
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
                details="Explicit confirmation required.",
            )
        if not dry_run:
            for email_id in email_ids:
                labels = set(self._emails[email_id].labels)
                labels.add("trash")
                self._emails[email_id].labels = sorted(labels)
        return ProviderActionResult(
            provider=self.provider_name,
            action="trash",
            email_ids=email_ids,
            dry_run=dry_run,
            executed=not dry_run,
            details="Moved emails to trash." if not dry_run else "Dry run only.",
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
                existing = set(self._emails[email_id].labels)
                existing.update(labels)
                self._emails[email_id].labels = sorted(existing)
        return ProviderActionResult(
            provider=self.provider_name,
            action="apply_labels",
            email_ids=email_ids,
            dry_run=dry_run,
            executed=not dry_run,
            details=f"Labels: {', '.join(labels)}",
        )
