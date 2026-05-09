from __future__ import annotations

from typing import Optional

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
            return InboxRepository(session).get_checkpoint(self.provider_name)

    def _save_checkpoint(self, checkpoint_value: str) -> None:
        with session_scope() as session:
            InboxRepository(session).save_checkpoint(self.provider_name, checkpoint_value)

    def run(self, **kwargs):
        original_provider = self.engine.provider
        checkpoint = self._get_checkpoint()
        incremental = bool(kwargs.pop("incremental", False))
        use_incremental = (
            incremental
            and checkpoint
            and callable(getattr(original_provider, "supports_incremental_sync", None))
            and original_provider.supports_incremental_sync()
        )

        if use_incremental:
            self.engine.provider = _IncrementalProviderProxy(original_provider, checkpoint)
        try:
            result = self.engine.run(**kwargs)
        finally:
            self.engine.provider = original_provider

        checkpoint_value = original_provider.get_incremental_checkpoint()
        if checkpoint_value:
            self._save_checkpoint(checkpoint_value)
        return result

    def __getattr__(self, item):
        return getattr(self.engine, item)
