from __future__ import annotations

from typing import Optional

from inboxanchor.config.settings import SETTINGS
from inboxanchor.core.triage_engine import TriageEngine
from inboxanchor.infra.database import session_scope
from inboxanchor.infra.repository import InboxRepository


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
    def __init__(self, engine: TriageEngine, *, provider_name: str):
        self.engine = engine
        self.provider_name = provider_name

    @property
    def provider(self):
        return self.engine.provider

    def _get_checkpoint(self):
        with session_scope() as session:
            return InboxRepository(session).get_sync_checkpoint(self.provider_name)

    def _save_checkpoint(self, checkpoint_value: str) -> None:
        with session_scope() as session:
            InboxRepository(session).save_sync_checkpoint(self.provider_name, checkpoint_value)

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
        return result.model_copy(
            update={
                "sync_type": sync_type,
                "history_id_used": history_id_used,
                "history_id_saved": checkpoint_value,
            }
        )

    def __getattr__(self, item):
        return getattr(self.engine, item)
