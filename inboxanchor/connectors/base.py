from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional

from pydantic import BaseModel, Field

from inboxanchor.models import EmailMessage


class ProviderActionResult(BaseModel):
    provider: str
    action: str
    email_ids: list[str] = Field(default_factory=list)
    dry_run: bool = True
    executed: bool = False
    details: str = ""


class EmailProvider(ABC):
    provider_name: str

    def supports_outbound_email(self) -> bool:
        return False

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
        if unread_only:
            emails = self.list_unread(
                limit=limit + offset,
                include_body=include_body,
                time_range=time_range,
            )
            emails = emails[offset : offset + limit]
            for start in range(0, len(emails), batch_size):
                yield emails[start : start + batch_size]
            return
        raise NotImplementedError(
            f"{self.__class__.__name__} does not support historical mailbox iteration."
        )

    def supports_incremental_sync(self) -> bool:
        return False

    def iter_unread_batches_since(
        self,
        checkpoint: str,
        *,
        limit: int = 50,
        batch_size: int = 100,
        include_body: bool = True,
        time_range: Optional[str] = None,
    ):
        return self.iter_unread_batches(
            limit=limit,
            batch_size=batch_size,
            include_body=include_body,
            time_range=time_range,
        )

    def get_incremental_checkpoint(self) -> Optional[str]:
        return None

    @abstractmethod
    def list_unread(
        self,
        limit: int = 50,
        include_body: bool = True,
        time_range: Optional[str] = None,
    ) -> list[EmailMessage]:
        raise NotImplementedError

    @abstractmethod
    def fetch_email_metadata(self, email_id: str) -> EmailMessage:
        raise NotImplementedError

    @abstractmethod
    def fetch_email_body(self, email_id: str) -> str:
        raise NotImplementedError

    @abstractmethod
    def batch_mark_as_read(
        self,
        email_ids: list[str],
        *,
        dry_run: bool = True,
    ) -> ProviderActionResult:
        raise NotImplementedError

    @abstractmethod
    def archive_emails(
        self,
        email_ids: list[str],
        *,
        dry_run: bool = True,
    ) -> ProviderActionResult:
        raise NotImplementedError

    @abstractmethod
    def move_to_trash(
        self,
        email_ids: list[str],
        *,
        explicit_confirmation: bool,
        dry_run: bool = True,
    ) -> ProviderActionResult:
        raise NotImplementedError

    @abstractmethod
    def apply_labels(
        self,
        email_ids: list[str],
        labels: list[str],
        *,
        dry_run: bool = True,
    ) -> ProviderActionResult:
        raise NotImplementedError

    @abstractmethod
    def remove_labels(
        self,
        email_ids: list[str],
        labels: list[str],
        *,
        dry_run: bool = True,
    ) -> ProviderActionResult:
        raise NotImplementedError

    def delete_labels(
        self,
        labels: list[str],
        *,
        dry_run: bool = True,
    ) -> ProviderActionResult:
        return ProviderActionResult(
            provider=self.provider_name,
            action="delete_labels",
            email_ids=[],
            dry_run=dry_run,
            executed=False,
            details=(
                f"{self.__class__.__name__} cannot delete label definitions from the provider."
            ),
        )

    def list_labels(self) -> list[str]:
        return []

    def send_reply(
        self,
        email_id: str,
        body: str,
        *,
        from_address: Optional[str] = None,
        dry_run: bool = True,
    ) -> ProviderActionResult:
        raise NotImplementedError(
            f"{self.__class__.__name__} does not support sending replies."
        )
