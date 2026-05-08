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


def test_incremental_triage_uses_and_updates_checkpoint():
    provider = IncrementalProvider(build_demo_emails())
    base_engine = TriageEngine(provider)
    engine = IncrementalTriageEngine(base_engine, provider_name="incremental")

    with session_scope() as session:
        InboxRepository(session).save_checkpoint("incremental", "history-1")

    result = engine.run(dry_run=True, limit=10)

    assert provider.received_checkpoint == "history-1"
    assert result.total_emails == 2

    with session_scope() as session:
        checkpoint = InboxRepository(session).get_checkpoint("incremental")
    assert checkpoint == "next-history"
