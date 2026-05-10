from __future__ import annotations

from copy import deepcopy
from typing import Optional

from inboxanchor.connectors.base import EmailProvider, ProviderActionResult
from inboxanchor.core.time_windows import in_time_window
from inboxanchor.mail_intelligence import dedupe_labels
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

    def list_unread(
        self,
        limit: int = 50,
        include_body: bool = True,
        time_range: Optional[str] = None,
    ) -> list[EmailMessage]:
        unread = [
            deepcopy(email)
            for email in self._emails.values()
            if email.unread and in_time_window(email.received_at, time_range)
        ]
        unread.sort(key=lambda item: item.received_at, reverse=True)
        unread = unread[:limit]
        if include_body:
            return [
                email.model_copy(
                    update={
                        "body_fetched": True,
                        "body_stored": bool(email.body_full),
                    }
                )
                for email in unread
            ]
        return [
            email.model_copy(
                update={
                    "body_full": "",
                    "body_preview": email.snippet,
                    "body_fetched": False,
                    "body_stored": False,
                }
            )
            for email in unread
        ]

    def iter_unread_batches(
        self,
        *,
        limit: int = 50,
        batch_size: int = 100,
        include_body: bool = True,
        time_range: Optional[str] = None,
    ):
        unread = self.list_unread(
            limit=limit,
            include_body=include_body,
            time_range=time_range,
        )
        for start in range(0, len(unread), batch_size):
            yield unread[start : start + batch_size]

    def iter_mailbox_batches(
        self,
        *,
        limit: int = 500,
        batch_size: int = 100,
        include_body: bool = False,
        unread_only: bool = False,
        offset: int = 0,
        time_range: Optional[str] = None,
    ):
        emails = [deepcopy(email) for email in self._emails.values()]
        if unread_only:
            emails = [email for email in emails if email.unread]
        if time_range:
            emails = [email for email in emails if in_time_window(email.received_at, time_range)]
        emails.sort(key=lambda item: item.received_at, reverse=True)
        emails = emails[offset : offset + limit]
        if not include_body:
            emails = [
                email.model_copy(
                    update={
                        "body_full": "",
                        "body_preview": email.snippet,
                        "body_fetched": False,
                        "body_stored": False,
                    }
                )
                for email in emails
            ]
        else:
            emails = [
                email.model_copy(
                    update={
                        "body_fetched": True,
                        "body_stored": bool(email.body_full),
                    }
                )
                for email in emails
            ]
        for start in range(0, len(emails), batch_size):
            yield emails[start : start + batch_size]

    def fetch_email_metadata(self, email_id: str) -> EmailMessage:
        return deepcopy(self._emails[email_id])

    def fetch_email_body(self, email_id: str) -> str:
        return self._emails[email_id].body_full or self._emails[email_id].body_preview

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

    def remove_labels(
        self,
        email_ids: list[str],
        labels: list[str],
        *,
        dry_run: bool = True,
    ) -> ProviderActionResult:
        if not dry_run:
            for email_id in email_ids:
                existing = {label for label in self._emails[email_id].labels if label not in labels}
                self._emails[email_id].labels = sorted(existing)
        return ProviderActionResult(
            provider=self.provider_name,
            action="remove_labels",
            email_ids=email_ids,
            dry_run=dry_run,
            executed=not dry_run,
            details=f"Removed labels: {', '.join(labels)}",
        )

    def delete_labels(
        self,
        labels: list[str],
        *,
        dry_run: bool = True,
    ) -> ProviderActionResult:
        if not dry_run:
            for email in self._emails.values():
                existing = {label for label in email.labels if label not in labels}
                email.labels = sorted(existing)
        return ProviderActionResult(
            provider=self.provider_name,
            action="delete_labels",
            email_ids=[],
            dry_run=dry_run,
            executed=not dry_run,
            details=f"Deleted label definitions: {', '.join(labels)}",
        )

    def list_labels(self) -> list[str]:
        labels: list[str] = []
        for email in self._emails.values():
            labels.extend(email.labels)
        return dedupe_labels(labels)

    def supports_outbound_email(self) -> bool:
        return True

    def send_reply(
        self,
        email_id: str,
        body: str,
        *,
        from_address: Optional[str] = None,
        dry_run: bool = True,
    ) -> ProviderActionResult:
        del body, from_address
        if not dry_run and email_id in self._emails:
            labels = set(self._emails[email_id].labels)
            labels.add("replied")
            self._emails[email_id].labels = sorted(labels)
            self._emails[email_id].unread = False
        return ProviderActionResult(
            provider=self.provider_name,
            action="reply",
            email_ids=[email_id],
            dry_run=dry_run,
            executed=not dry_run,
            details="Reply drafted for preview." if dry_run else "Reply sent in preview mode.",
        )
