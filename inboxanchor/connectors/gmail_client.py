from __future__ import annotations

from typing import Optional, Protocol

from inboxanchor.connectors.base import EmailProvider, ProviderActionResult
from inboxanchor.models import EmailMessage


class GmailTransport(Protocol):
    def list_unread(
        self,
        limit: int,
        *,
        time_range: Optional[str] = None,
    ) -> list[EmailMessage]: ...
    def list_unread_page(self, limit: int, offset: int) -> list[EmailMessage]: ...
    def get_message(self, email_id: str, include_body: bool = True) -> EmailMessage: ...
    def get_body(self, email_id: str) -> str: ...
    def iter_mailbox_batches(
        self,
        *,
        limit: int = 500,
        batch_size: int = 100,
        include_body: bool = False,
        unread_only: bool = False,
        offset: int = 0,
        time_range: Optional[str] = None,
    ): ...
    def mark_read(self, email_ids: list[str]) -> None: ...
    def archive(self, email_ids: list[str]) -> None: ...
    def trash(self, email_ids: list[str]) -> None: ...
    def apply_labels(self, email_ids: list[str], labels: list[str]) -> None: ...
    def send_reply(
        self,
        email_id: str,
        body: str,
        *,
        from_address: Optional[str] = None,
    ) -> dict: ...


class GmailClient(EmailProvider):
    """
    OAuth-ready Gmail connector.

    The transport stays abstract so tests can use a fake transport and production
    code can plug in the Gmail API client without changing the rest of the app.
    """

    provider_name = "gmail"

    def __init__(self, transport: Optional[GmailTransport] = None):
        self.transport = transport

    def _require_transport(self) -> GmailTransport:
        if self.transport is None:
            raise RuntimeError(
                "Gmail transport is not configured. Wire a Gmail API transport "
                "or use a fake transport in tests."
            )
        return self.transport

    def list_unread(
        self,
        limit: int = 50,
        include_body: bool = True,
        time_range: Optional[str] = None,
    ) -> list[EmailMessage]:
        transport = self._require_transport()
        if time_range:
            return transport.list_unread(limit, time_range=time_range)
        return transport.list_unread(limit)

    def iter_unread_batches(
        self,
        *,
        limit: int = 50,
        batch_size: int = 100,
        include_body: bool = True,
        time_range: Optional[str] = None,
    ):
        transport = self._require_transport()
        if hasattr(transport, "list_unread_page"):
            if not time_range:
                fetched = 0
                offset = 0
                while fetched < limit:
                    page = transport.list_unread_page(min(batch_size, limit - fetched), offset)
                    if not page:
                        break
                    yield page
                    fetched += len(page)
                    offset += len(page)
                return

        emails = (
            transport.list_unread(limit, time_range=time_range)
            if time_range
            else transport.list_unread(limit)
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
        transport = self._require_transport()
        if callable(getattr(transport, "iter_mailbox_batches", None)):
            yield from transport.iter_mailbox_batches(
                limit=limit,
                batch_size=batch_size,
                include_body=include_body,
                unread_only=unread_only,
                offset=offset,
                time_range=time_range,
            )
            return

        if unread_only:
            emails = (
                transport.list_unread(limit + offset, time_range=time_range)
                if time_range
                else transport.list_unread(limit + offset)
            )
            emails = emails[offset : offset + limit]
            for start in range(0, len(emails), batch_size):
                yield emails[start : start + batch_size]
            return

        raise NotImplementedError("The current Gmail transport cannot iterate the mailbox yet.")

    def supports_incremental_sync(self) -> bool:
        transport = self._require_transport()
        return callable(getattr(transport, "iter_unread_batches_since", None)) and callable(
            getattr(transport, "get_incremental_checkpoint", None)
        )

    def iter_unread_batches_since(
        self,
        checkpoint: str,
        *,
        limit: int = 50,
        batch_size: int = 100,
        include_body: bool = True,
        time_range: Optional[str] = None,
    ):
        transport = self._require_transport()
        if callable(getattr(transport, "iter_unread_batches_since", None)):
            return transport.iter_unread_batches_since(
                checkpoint,
                limit=limit,
                batch_size=batch_size,
                include_body=include_body,
                time_range=time_range,
            )
        return self.iter_unread_batches(
            limit=limit,
            batch_size=batch_size,
            include_body=include_body,
            time_range=time_range,
        )

    def get_incremental_checkpoint(self) -> Optional[str]:
        transport = self._require_transport()
        checkpoint_getter = getattr(transport, "get_incremental_checkpoint", None)
        if callable(checkpoint_getter):
            return checkpoint_getter()
        return None

    def fetch_email_metadata(self, email_id: str) -> EmailMessage:
        return self._require_transport().get_message(email_id, include_body=False)

    def fetch_email_body(self, email_id: str) -> str:
        return self._require_transport().get_body(email_id)

    def supports_outbound_email(self) -> bool:
        return True

    def batch_mark_as_read(
        self,
        email_ids: list[str],
        *,
        dry_run: bool = True,
    ) -> ProviderActionResult:
        if not dry_run:
            self._require_transport().mark_read(email_ids)
        return ProviderActionResult(
            provider=self.provider_name,
            action="mark_read",
            email_ids=email_ids,
            dry_run=dry_run,
            executed=not dry_run,
            details=(
                "Gmail batch read update prepared."
                if dry_run
                else "Gmail batch read update executed."
            ),
        )

    def archive_emails(
        self,
        email_ids: list[str],
        *,
        dry_run: bool = True,
    ) -> ProviderActionResult:
        if not dry_run:
            self._require_transport().archive(email_ids)
        return ProviderActionResult(
            provider=self.provider_name,
            action="archive",
            email_ids=email_ids,
            dry_run=dry_run,
            executed=not dry_run,
            details="Gmail archive prepared." if dry_run else "Gmail archive executed.",
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
                details="Explicit confirmation required before moving Gmail messages to trash.",
            )
        if not dry_run:
            self._require_transport().trash(email_ids)
        return ProviderActionResult(
            provider=self.provider_name,
            action="trash",
            email_ids=email_ids,
            dry_run=dry_run,
            executed=not dry_run,
            details="Gmail trash action prepared." if dry_run else "Gmail trash action executed.",
        )

    def apply_labels(
        self,
        email_ids: list[str],
        labels: list[str],
        *,
        dry_run: bool = True,
    ) -> ProviderActionResult:
        if not dry_run:
            self._require_transport().apply_labels(email_ids, labels)
        return ProviderActionResult(
            provider=self.provider_name,
            action="apply_labels",
            email_ids=email_ids,
            dry_run=dry_run,
            executed=not dry_run,
            details=f"Gmail labels prepared: {', '.join(labels)}",
        )

    def send_reply(
        self,
        email_id: str,
        body: str,
        *,
        from_address: Optional[str] = None,
        dry_run: bool = True,
    ) -> ProviderActionResult:
        details = "Gmail reply prepared."
        if not dry_run:
            result = self._require_transport().send_reply(
                email_id,
                body,
                from_address=from_address,
            )
            details = (
                f"Reply sent to {result.get('to_address', 'recipient')} "
                f"with subject {result.get('subject', 'reply')}."
            )
        return ProviderActionResult(
            provider=self.provider_name,
            action="reply",
            email_ids=[email_id],
            dry_run=dry_run,
            executed=not dry_run,
            details=details,
        )
