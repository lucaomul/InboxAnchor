from inboxanchor.bootstrap import build_demo_emails
from inboxanchor.connectors.fake_provider import FakeEmailProvider
from inboxanchor.core.incremental_triage import IncrementalTriageEngine
from inboxanchor.core.triage_engine import TriageEngine
from inboxanchor.infra.database import session_scope
from inboxanchor.infra.repository import InboxRepository


class IncrementalProvider(FakeEmailProvider):
    provider_name = "incremental"

    def __init__(self, emails):
        super().__init__(emails, provider_name="incremental")
        self.received_checkpoint = None

    def supports_incremental_sync(self) -> bool:
        return True

    def iter_unread_batches_since(
        self,
        checkpoint: str,
        *,
        limit: int = 50,
        batch_size: int = 100,
        include_body: bool = True,
    ):
        self.received_checkpoint = checkpoint
        return super().iter_unread_batches(
            limit=min(limit, 2),
            batch_size=batch_size,
            include_body=include_body,
        )

    def get_incremental_checkpoint(self):
        return "next-history"


def test_incremental_triage_uses_checkpoint_if_available_by_default():
    provider = IncrementalProvider(build_demo_emails())
    base_engine = TriageEngine(provider)
    engine = IncrementalTriageEngine(base_engine, provider_name="incremental")

    with session_scope() as session:
        InboxRepository(session).save_sync_checkpoint("incremental", "history-1")

    result = engine.run(dry_run=True, limit=10)

    assert provider.received_checkpoint == "history-1"
    assert result.total_emails == 2
    assert result.sync_type == "incremental"
    assert result.history_id_used == "history-1"

    with session_scope() as session:
        checkpoint = InboxRepository(session).get_sync_checkpoint("incremental")
    assert checkpoint == "next-history"


def test_incremental_triage_falls_back_to_full_sync_if_no_checkpoint():
    provider = IncrementalProvider(build_demo_emails())
    base_engine = TriageEngine(provider)
    engine = IncrementalTriageEngine(base_engine, provider_name="incremental")

    result = engine.run(dry_run=True, limit=10)

    assert provider.received_checkpoint is None
    assert result.total_emails == len(build_demo_emails())
    assert result.sync_type == "full"


def test_incremental_triage_can_force_full_scan_even_with_checkpoint():
    provider = IncrementalProvider(build_demo_emails())
    base_engine = TriageEngine(provider)
    engine = IncrementalTriageEngine(base_engine, provider_name="incremental")

    with session_scope() as session:
        InboxRepository(session).save_sync_checkpoint("incremental", "history-1")

    result = engine.run(dry_run=True, limit=10, incremental=False)

    assert provider.received_checkpoint is None
    assert result.sync_type == "full"
    assert result.total_emails == len(build_demo_emails())


def test_incremental_triage_auto_starts_sender_warmup_on_first_live_like_full_run(monkeypatch):
    class LiveLikeProvider(FakeEmailProvider):
        provider_name = "gmail"

    provider = LiveLikeProvider(build_demo_emails(), provider_name="gmail")
    base_engine = TriageEngine(provider)
    engine = IncrementalTriageEngine(base_engine, provider_name="gmail")
    started: list[str] = []

    monkeypatch.setattr(
        engine,
        "_start_sender_warmup",
        lambda provider: started.append(provider.provider_name),
    )

    result = engine.run(dry_run=True, limit=10)

    assert result.sync_type == "full"
    assert started == ["gmail"]
