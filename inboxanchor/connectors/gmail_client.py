from __future__ import annotations

from typing import Optional, Protocol

from inboxanchor.config.settings import SETTINGS
from inboxanchor.connectors.base import EmailProvider, ProviderActionResult
from inboxanchor.core.time_windows import ALL_TIME_RANGE, normalize_time_range
from inboxanchor.models import EmailMessage


class GmailTransport(Protocol):
    def list_unread(
        self,
        limit: int,
        *,
        include_body: bool = True,
        time_range: Optional[str] = None,
    ) -> list[EmailMessage]: ...
    def list_unread_page(
        self,
        limit: int,
        offset: int,
        *,
        include_body: bool = True,
        time_range: Optional[str] = None,
    ) -> list[EmailMessage]: ...
    def get_message(self, email_id: str, include_body: bool = True) -> EmailMessage: ...
    def get_body(self, email_id: str) -> str: ...
    def iter_mailbox_batches(
        self,
        *,
        limit: Optional[int] = 500,
        batch_size: int = 100,
        include_body: bool = False,
        unread_only: bool = False,
        offset: int = 0,
        time_range: Optional[str] = None,
    ): ...
    def iter_all_unread(
        self,
        *,
        batch_size: int = 500,
        include_body: bool = True,
        max_workers: Optional[int] = None,
        time_range: Optional[str] = None,
    ): ...
    def mark_read(self, email_ids: list[str]) -> None: ...
    def archive(self, email_ids: list[str]) -> None: ...
    def trash(self, email_ids: list[str]) -> None: ...
    def apply_labels(self, email_ids: list[str], labels: list[str]) -> None: ...
    def remove_labels(self, email_ids: list[str], labels: list[str]) -> None: ...
    def delete_labels(self, labels: list[str]) -> None: ...
    def list_labels(self) -> list[str]: ...
    def ensure_alias_routing(self, alias_address: str, *, label_name: str) -> None: ...
    def remove_alias_routing(self, alias_address: str) -> None: ...
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
        normalized_time_range = normalize_time_range(time_range)
        if normalized_time_range != ALL_TIME_RANGE:
            return transport.list_unread(
                limit,
                include_body=include_body,
                time_range=normalized_time_range,
            )
        return transport.list_unread(limit, include_body=include_body)

    def iter_unread_batches(
        self,
        *,
        limit: int = 50,
        batch_size: int = 100,
        include_body: bool = True,
        time_range: Optional[str] = None,
    ):
        transport = self._require_transport()
        normalized_time_range = normalize_time_range(time_range)
        industrial_iterator = getattr(transport, "iter_all_unread", None)
        if normalized_time_range == ALL_TIME_RANGE and callable(industrial_iterator):
            fetched = 0
            page_fetch_size = min(max(batch_size, 1), SETTINGS.gmail_batch_size)
            for batch in industrial_iterator(
                batch_size=page_fetch_size,
                include_body=include_body,
                max_workers=SETTINGS.gmail_fetch_workers,
                time_range=normalized_time_range,
            ):
                if fetched >= limit:
                    break
                next_batch = batch[: max(0, limit - fetched)]
                if not next_batch:
                    break
                yield next_batch
                fetched += len(next_batch)
                if len(next_batch) < len(batch):
                    break
            return

        if hasattr(transport, "list_unread_page"):
            if normalized_time_range == ALL_TIME_RANGE:
                fetched = 0
                offset = 0
                page_fetch_size = min(batch_size, 25 if include_body else 100)
                while fetched < limit:
                    page = transport.list_unread_page(
                        min(page_fetch_size, limit - fetched),
                        offset,
                        include_body=include_body,
                        time_range=normalized_time_range,
                    )
                    if not page:
                        break
                    yield page
                    fetched += len(page)
                    offset += len(page)
                return

        emails = (
            transport.list_unread(
                limit,
                include_body=include_body,
                time_range=normalized_time_range,
            )
            if normalized_time_range != ALL_TIME_RANGE
            else transport.list_unread(limit, include_body=include_body)
        )
        for start in range(0, len(emails), batch_size):
            yield emails[start : start + batch_size]

    def iter_all_unread_batches(
        self,
        *,
        batch_size: int = 500,
        include_body: bool = True,
        time_range: Optional[str] = None,
    ):
        """
        Industrial-scale unread streaming without offset math when the transport supports it.
        """
        transport = self._require_transport()
        industrial_iterator = getattr(transport, "iter_all_unread", None)
        if callable(industrial_iterator):
            yield from industrial_iterator(
                batch_size=batch_size,
                include_body=include_body,
                max_workers=SETTINGS.gmail_fetch_workers,
                time_range=normalize_time_range(time_range),
            )
            return
        yield from self.iter_unread_batches(
            limit=999_999,
            batch_size=batch_size,
            include_body=include_body,
            time_range=time_range,
        )

    def iter_mailbox_batches(
        self,
        *,
        limit: Optional[int] = 500,
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
                transport.list_unread(
                    (limit + offset) if limit is not None else 999_999_999,
                    time_range=time_range,
                )
                if time_range
                else transport.list_unread((limit + offset) if limit is not None else 999_999_999)
            )
            emails = emails[offset:] if limit is None else emails[offset : offset + limit]
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

    def remove_labels(
        self,
        email_ids: list[str],
        labels: list[str],
        *,
        dry_run: bool = True,
    ) -> ProviderActionResult:
        if not dry_run:
            self._require_transport().remove_labels(email_ids, labels)
        return ProviderActionResult(
            provider=self.provider_name,
            action="remove_labels",
            email_ids=email_ids,
            dry_run=dry_run,
            executed=not dry_run,
            details=f"Gmail label removal prepared: {', '.join(labels)}",
        )

    def delete_labels(
        self,
        labels: list[str],
        *,
        dry_run: bool = True,
    ) -> ProviderActionResult:
        if not dry_run:
            self._require_transport().delete_labels(labels)
        return ProviderActionResult(
            provider=self.provider_name,
            action="delete_labels",
            email_ids=[],
            dry_run=dry_run,
            executed=not dry_run,
            details=f"Gmail label deletion prepared: {', '.join(labels)}",
        )

    def list_labels(self) -> list[str]:
        transport = self._require_transport()
        list_labels = getattr(transport, "list_labels", None)
        if callable(list_labels):
            return list_labels()
        return []

    def ensure_alias_routing(
        self,
        alias_address: str,
        *,
        label_name: str,
        dry_run: bool = True,
    ) -> ProviderActionResult:
        if not dry_run:
            self._require_transport().ensure_alias_routing(
                alias_address,
                label_name=label_name,
            )
        return ProviderActionResult(
            provider=self.provider_name,
            action="configure_alias_routing",
            email_ids=[],
            dry_run=dry_run,
            executed=not dry_run,
            details=(
                f"Gmail alias routing prepared for {alias_address} -> {label_name}"
                if dry_run
                else f"Gmail alias routing installed for {alias_address} -> {label_name}"
            ),
        )

    def remove_alias_routing(
        self,
        alias_address: str,
        *,
        dry_run: bool = True,
    ) -> ProviderActionResult:
        if not dry_run:
            self._require_transport().remove_alias_routing(alias_address)
        return ProviderActionResult(
            provider=self.provider_name,
            action="remove_alias_routing",
            email_ids=[],
            dry_run=dry_run,
            executed=not dry_run,
            details=(
                f"Gmail alias routing removal prepared for {alias_address}"
                if dry_run
                else f"Gmail alias routing removed for {alias_address}"
            ),
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
