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

    def supports_incremental_sync(self) -> bool:
        return False

    def iter_unread_batches_since(
        self,
        checkpoint: str,
        *,
        limit: int = 50,
        batch_size: int = 100,
        include_body: bool = True,
    ):
        return self.iter_unread_batches(
            limit=limit,
            batch_size=batch_size,
            include_body=include_body,
        )

    def get_incremental_checkpoint(self) -> Optional[str]:
        return None

    @abstractmethod
    def list_unread(self, limit: int = 50, include_body: bool = True) -> list[EmailMessage]:
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
