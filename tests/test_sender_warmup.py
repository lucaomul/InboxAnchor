from __future__ import annotations

from unittest.mock import Mock

from fastapi.testclient import TestClient

import inboxanchor.api.v1.routers.frontend as frontend_router
from inboxanchor.api.main import app
from inboxanchor.bootstrap import build_demo_emails
from inboxanchor.connectors.fake_provider import FakeEmailProvider
from inboxanchor.core.sender_warmup import SenderWarmupJob
from inboxanchor.infra.repository import InboxRepository

client = TestClient(app)


def test_warmup_observes_each_email(monkeypatch):
    emails = build_demo_emails()
    provider = FakeEmailProvider(emails, provider_name="gmail")
    observed_ids: list[str] = []

    original_observe = InboxRepository.observe_sender_intelligence

    def tracking_observe(self, provider, email, *, count_message=True):
        observed_ids.append(email.id)
        return original_observe(self, provider, email, count_message=count_message)

    monkeypatch.setattr(
        InboxRepository,
        "observe_sender_intelligence",
        tracking_observe,
    )

    stats = SenderWarmupJob(provider, "gmail").run(batch_size=3, max_emails=6)

    assert stats.emails_scanned == 6
    assert len(observed_ids) == 6
    assert set(observed_ids) == {email.id for email in emails}


def test_warmup_counts_unique_senders():
    seed = build_demo_emails()[0]
    emails = [
        seed.model_copy(
            update={"id": "one", "thread_id": "thr-one", "sender": "a@example.com"}
        ),
        seed.model_copy(
            update={"id": "two", "thread_id": "thr-two", "sender": "a@example.com"}
        ),
        seed.model_copy(
            update={"id": "three", "thread_id": "thr-three", "sender": "b@example.com"}
        ),
    ]
    provider = FakeEmailProvider(emails, provider_name="gmail")

    stats = SenderWarmupJob(provider, "gmail").run(batch_size=10, max_emails=10)

    assert stats.senders_discovered == 2
    assert stats.senders_updated == 1


def test_warmup_handles_email_error_gracefully(monkeypatch):
    emails = build_demo_emails()[:3]
    provider = FakeEmailProvider(emails, provider_name="gmail")
    original_observe = InboxRepository.observe_sender_intelligence

    def flaky_observe(self, provider, email, *, count_message=True):
        if email.id == emails[1].id:
            raise RuntimeError("boom")
        return original_observe(self, provider, email, count_message=count_message)

    monkeypatch.setattr(
        InboxRepository,
        "observe_sender_intelligence",
        flaky_observe,
    )

    stats = SenderWarmupJob(provider, "gmail").run(batch_size=3, max_emails=10)

    assert stats.errors == 1
    assert stats.emails_scanned == 2


def test_warmup_respects_max_emails():
    seed = build_demo_emails()[0]
    emails = [
        seed.model_copy(
            update={
                "id": f"msg-{index}",
                "thread_id": f"thr-{index}",
                "sender": f"user{index}@example.com",
            }
        )
        for index in range(250)
    ]
    provider = FakeEmailProvider(emails, provider_name="gmail")

    stats = SenderWarmupJob(provider, "gmail").run(batch_size=40, max_emails=100)

    assert stats.emails_scanned == 100


def test_warmup_fallback_provider():
    seed = build_demo_emails()[0]
    batches = [
        [
            seed.model_copy(update={"id": "one", "thread_id": "thr-one"}),
            seed.model_copy(update={"id": "two", "thread_id": "thr-two"}),
        ]
    ]

    class FallbackProvider:
        provider_name = "gmail"

        def iter_unread_batches(self, **kwargs):
            del kwargs
            yield from batches

    stats = SenderWarmupJob(FallbackProvider(), "gmail").run(batch_size=50, max_emails=50)

    assert stats.emails_scanned == 2


def test_warmup_calls_progress_callback():
    emails = build_demo_emails()
    provider = FakeEmailProvider(emails, provider_name="gmail")
    callback = Mock()

    SenderWarmupJob(provider, "gmail").run(
        batch_size=2,
        max_emails=6,
        progress_callback=callback,
    )

    assert callback.call_count >= 3
    payload = callback.call_args[0][0]
    assert "emails_scanned" in payload
    assert "senders_discovered" in payload


def test_warmup_endpoint_starts_background_job(monkeypatch):
    started: dict[str, object] = {}

    class DummyThread:
        def __init__(self, target=None, daemon=None, name=None):
            started["target"] = target
            started["daemon"] = daemon
            started["name"] = name

        def start(self):
            started["started"] = True

    monkeypatch.setattr(frontend_router.threading, "Thread", DummyThread)
    monkeypatch.setattr(frontend_router, "_get_provider_name", lambda provider=None: "gmail")

    response = client.post(
        "/ops/warmup",
        json={"provider": "gmail", "months_back": 6, "max_emails": 1000, "batch_size": 100},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "started"
    assert started["started"] is True
