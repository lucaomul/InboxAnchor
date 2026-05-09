from __future__ import annotations

from typing import Optional

from inboxanchor.connectors.base import EmailProvider, ProviderActionResult
from inboxanchor.core.time_windows import in_time_window
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

    def list_unread(
        self,
        limit: int = 50,
        include_body: bool = True,
        time_range: Optional[str] = None,
    ) -> list[EmailMessage]:
        emails = [
            item.model_copy(deep=True)
            for item in self._messages.values()
            if item.unread and in_time_window(item.received_at, time_range)
        ]
        emails.sort(key=lambda item: item.received_at, reverse=True)
        return emails[:limit]

    def iter_unread_batches(
        self,
        *,
        limit: int = 50,
        batch_size: int = 100,
        include_body: bool = True,
        time_range: Optional[str] = None,
    ):
        emails = self.list_unread(
            limit=limit,
            include_body=include_body,
            time_range=time_range,
        )
        for start in range(0, len(emails), batch_size):
            yield emails[start : start + batch_size]

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
        emails = [item.model_copy(deep=True) for item in self._messages.values()]
        if unread_only:
            emails = [item for item in emails if item.unread]
        if time_range:
            emails = [item for item in emails if in_time_window(item.received_at, time_range)]
        emails.sort(key=lambda item: item.received_at, reverse=True)
        emails = emails[offset : offset + limit]
        if not include_body:
            emails = [
                email.model_copy(update={"body_full": "", "body_preview": email.snippet})
                for email in emails
            ]
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

    def remove_labels(
        self,
        email_ids: list[str],
        labels: list[str],
        *,
        dry_run: bool = True,
    ) -> ProviderActionResult:
        if not dry_run:
            for email_id in email_ids:
                self._messages[email_id].labels = sorted(
                    label for label in self._messages[email_id].labels if label not in labels
                )
        return ProviderActionResult(
            provider=self.provider_name,
            action="remove_labels",
            email_ids=email_ids,
            dry_run=dry_run,
            executed=not dry_run,
            details=f"IMAP label removal prepared: {', '.join(labels)}",
        )

    def delete_labels(
        self,
        labels: list[str],
        *,
        dry_run: bool = True,
    ) -> ProviderActionResult:
        if not dry_run:
            for message in self._messages.values():
                message.labels = sorted(label for label in message.labels if label not in labels)
        return ProviderActionResult(
            provider=self.provider_name,
            action="delete_labels",
            email_ids=[],
            dry_run=dry_run,
            executed=not dry_run,
            details=f"IMAP label deletion prepared: {', '.join(labels)}",
        )

    def send_reply(
        self,
        email_id: str,
        body: str,
        *,
        from_address: Optional[str] = None,
        dry_run: bool = True,
    ) -> ProviderActionResult:
        del email_id, body, from_address, dry_run
        raise NotImplementedError(
            "Direct sending for IMAP-family inboxes is not configured yet. "
            "Use Gmail for in-app replies for now."
        )
