from __future__ import annotations

import logging
import threading
from typing import Optional

from inboxanchor.config.settings import SETTINGS
from inboxanchor.core.triage_engine import TriageEngine
from inboxanchor.infra.database import session_scope
from inboxanchor.infra.repository import InboxRepository

logger = logging.getLogger(__name__)


class _IncrementalProviderProxy:
    def __init__(self, provider, checkpoint: str):
        self.provider = provider
        self.checkpoint = checkpoint

    @property
    def provider_name(self):
        return self.provider.provider_name

    def iter_unread_batches(
        self,
        *,
        limit: int = 50,
        batch_size: int = 100,
        include_body: bool = True,
        time_range: Optional[str] = None,
    ):
        if time_range:
            try:
                return self.provider.iter_unread_batches_since(
                    self.checkpoint,
                    limit=limit,
                    batch_size=batch_size,
                    include_body=include_body,
                    time_range=time_range,
                )
            except TypeError as exc:
                if "time_range" not in str(exc):
                    raise
        return self.provider.iter_unread_batches_since(
            self.checkpoint,
            limit=limit,
            batch_size=batch_size,
            include_body=include_body,
        )

    def __getattr__(self, item):
        return getattr(self.provider, item)


class IncrementalTriageEngine:
    def __init__(
        self,
        engine: TriageEngine,
        *,
        provider_name: str,
        owner_email: Optional[str] = None,
    ):
        self.engine = engine
        self.provider_name = provider_name
        self.owner_email = (owner_email or "").strip().lower() or None

    @property
    def provider(self):
        return self.engine.provider

    def _get_checkpoint(self):
        with session_scope() as session:
            return InboxRepository(session).get_sync_checkpoint(
                self.provider_name,
                owner_email=self.owner_email,
            )

    def _save_checkpoint(self, checkpoint_value: str) -> None:
        with session_scope() as session:
            InboxRepository(session).save_sync_checkpoint(
                self.provider_name,
                checkpoint_value,
                owner_email=self.owner_email,
            )

    def _count_sender_profiles(self) -> int:
        with session_scope() as session:
            return InboxRepository(session).count_sender_profiles(self.provider_name)

    def _should_auto_warmup(self, provider, checkpoint: Optional[str], sync_type: str) -> bool:
        if checkpoint:
            return False
        if sync_type != "full":
            return False
        if not SETTINGS.sender_warmup_auto_on_first_run:
            return False
        if self.provider_name not in {"gmail", "imap", "yahoo", "outlook"}:
            return False
        if provider.__class__.__name__ in {"FakeEmailProvider", "IMAPEmailClient"}:
            return False
        return self._count_sender_profiles() < 10

    def _start_sender_warmup(self, provider) -> None:
        from inboxanchor.core.sender_warmup import SenderWarmupJob

        logger.info(
            "Auto-starting sender warmup — first run detected",
            extra={"provider": self.provider_name},
        )

        def _runner() -> None:
            try:
                SenderWarmupJob(provider, self.provider_name).run(
                    months_back=SETTINGS.sender_warmup_months_back,
                    batch_size=SETTINGS.sender_warmup_batch_size,
                    max_emails=SETTINGS.sender_warmup_max_emails,
                    include_body=False,
                )
            except Exception as exc:
                logger.warning(
                    "Sender warmup failed",
                    extra={"provider": self.provider_name, "error": str(exc)},
                )

        threading.Thread(
            target=_runner,
            name=f"inboxanchor-sender-warmup-{self.provider_name}",
            daemon=True,
        ).start()

    @staticmethod
    def _is_expired_history_error(exc: Exception) -> bool:
        lowered = str(exc).lower()
        return "404" in lowered and "history" in lowered

    def run(self, **kwargs):
        original_provider = self.engine.provider
        checkpoint = self._get_checkpoint()
        incremental = kwargs.pop("incremental", None)
        metadata_only_requested = kwargs.get("metadata_only")
        if (
            metadata_only_requested is None
            and SETTINGS.gmail_metadata_only_first_pass
            and original_provider.provider_name == "gmail"
            and not checkpoint
        ):
            kwargs["metadata_only"] = True
        use_incremental = (
            incremental is not False
            and checkpoint
            and callable(getattr(original_provider, "supports_incremental_sync", None))
            and original_provider.supports_incremental_sync()
        )
        sync_type = "incremental" if use_incremental else "full"
        history_id_used = checkpoint if use_incremental else None

        if use_incremental:
            self.engine.provider = _IncrementalProviderProxy(original_provider, checkpoint)
        try:
            result = self.engine.run(**kwargs)
        except Exception as exc:
            if use_incremental and self._is_expired_history_error(exc):
                self.engine.provider = original_provider
                sync_type = "full"
                result = self.engine.run(**kwargs)
            else:
                raise
        finally:
            self.engine.provider = original_provider

        checkpoint_value = original_provider.get_incremental_checkpoint()
        if checkpoint_value:
            self._save_checkpoint(checkpoint_value)
        if self._should_auto_warmup(original_provider, checkpoint, sync_type):
            self._start_sender_warmup(original_provider)
        return result.model_copy(
            update={
                "sync_type": sync_type,
                "history_id_used": history_id_used,
                "history_id_saved": checkpoint_value,
            }
        )

    def __getattr__(self, item):
        return getattr(self.engine, item)
