from __future__ import annotations

import base64
import json
import time
from unittest.mock import Mock

from fastapi.testclient import TestClient

import inboxanchor.api.v1.routers.frontend as frontend_router
import inboxanchor.api.v1.routers.webhooks as webhook_router
import inboxanchor.connectors.gmail_webhook as gmail_webhook
from inboxanchor.api.main import app

client = TestClient(app)


def _pubsub_payload(data: dict) -> dict:
    encoded = base64.urlsafe_b64encode(json.dumps(data).encode("utf-8")).decode("utf-8")
    return {"message": {"data": encoded, "messageId": "msg-1", "publishTime": "now"}}


def test_gmail_webhook_decodes_pubsub_message(monkeypatch):
    started: dict[str, object] = {}

    class DummyThread:
        def __init__(self, target=None, daemon=None, name=None):
            started["target"] = target
            started["daemon"] = daemon
            started["name"] = name

        def start(self):
            started["started"] = True

    monkeypatch.setattr(webhook_router.threading, "Thread", DummyThread)

    response = client.post(
        "/webhooks/gmail",
        json=_pubsub_payload({"emailAddress": "hello@gmail.com", "historyId": "123"}),
    )

    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert started["started"] is True


def test_gmail_webhook_handles_malformed_body():
    response = client.post(
        "/webhooks/gmail",
        content="{",
        headers={"content-type": "application/json"},
    )

    assert response.status_code == 200
    assert response.json()["reason"] == "malformed_body"


def test_gmail_webhook_handles_missing_fields():
    response = client.post(
        "/webhooks/gmail",
        json=_pubsub_payload({"historyId": "123"}),
    )

    assert response.status_code == 200
    assert response.json()["reason"] == "missing_fields"


def test_register_gmail_watch_calls_api():
    service = Mock()
    service.users.return_value.watch.return_value.execute.return_value = {
        "historyId": "abc",
        "expiration": "123456",
    }

    class Transport:
        user_id = "me"

        def _build_service(self):
            return service

    result = gmail_webhook.register_gmail_watch(
        Transport(),
        topic_name="projects/x/topics/y",
    )

    assert result == {"history_id": "abc", "expiration": "123456"}
    service.users.return_value.watch.assert_called_once()


def test_stop_gmail_watch_calls_api():
    service = Mock()
    service.users.return_value.stop.return_value.execute.return_value = {}

    class Transport:
        user_id = "me"

        def _build_service(self):
            return service

    gmail_webhook.stop_gmail_watch(Transport())

    service.users.return_value.stop.assert_called_once()


def test_watch_renewal_starts_background_thread(monkeypatch):
    calls: list[str] = []

    monkeypatch.setattr(gmail_webhook, "_watch_renewal_thread", None)
    gmail_webhook.stop_watch_renewal()

    def fake_register(transport, *, topic_name, label_ids=None):
        del transport, label_ids
        calls.append(topic_name)
        return {"history_id": "1", "expiration": "2"}

    monkeypatch.setattr(gmail_webhook, "register_gmail_watch", fake_register)

    gmail_webhook.start_watch_renewal(
        object(),
        topic_name="projects/x/topics/y",
        renew_every_seconds=0.05,
    )
    time.sleep(0.12)
    gmail_webhook.stop_watch_renewal()
    time.sleep(0.02)
    monkeypatch.setattr(gmail_webhook, "_watch_renewal_thread", None)

    assert calls


def test_watch_start_endpoint(monkeypatch):
    emitted: list[dict] = []
    fake_transport_pair = (object(), object())

    monkeypatch.setattr(frontend_router, "_get_provider_name", lambda provider=None: "gmail")
    monkeypatch.setattr(
        frontend_router,
        "_require_live_gmail_transport",
        lambda: fake_transport_pair,
    )
    monkeypatch.setattr(
        gmail_webhook,
        "register_gmail_watch",
        lambda transport, *, topic_name, label_ids=None: {
            "history_id": "abc",
            "expiration": "123456",
        },
    )
    monkeypatch.setattr(gmail_webhook, "start_watch_renewal", lambda transport, *, topic_name: None)
    monkeypatch.setattr(frontend_router.STREAM_HUB, "emit", lambda payload: emitted.append(payload))

    response = client.post(
        "/ops/watch/start",
        json={"topic_name": "projects/x/topics/y", "label_ids": ["UNREAD"]},
    )

    assert response.status_code == 200
    assert response.json()["history_id"] == "abc"
    assert emitted[0]["type"] == "watch_registered"


def test_watch_start_rejected_for_non_gmail(monkeypatch):
    monkeypatch.setattr(frontend_router, "_get_provider_name", lambda provider=None: "imap")

    response = client.post(
        "/ops/watch/start",
        json={"topic_name": "projects/x/topics/y"},
    )

    assert response.status_code == 400
