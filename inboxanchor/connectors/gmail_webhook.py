from __future__ import annotations

import base64
import json
import logging
import threading
from typing import Iterable, Optional

from inboxanchor.connectors.gmail_transport import GoogleAPITransport

logger = logging.getLogger(__name__)

_watch_renewal_thread: threading.Thread | None = None
_watch_renewal_stop = threading.Event()


def _execute_request(transport: GoogleAPITransport, request):
    executor = getattr(transport, "_execute_legacy", None)
    if callable(executor):
        return executor(request)
    return request.execute()


def register_gmail_watch(
    transport: GoogleAPITransport,
    *,
    topic_name: str,
    label_ids: list[str] | None = None,
) -> dict:
    service = transport._build_service()
    request_body = {
        "labelIds": list(label_ids or ["UNREAD"]),
        "topicName": topic_name,
    }
    response = _execute_request(
        transport,
        service.users().watch(
            userId=getattr(transport, "user_id", "me"),
            body=request_body,
        ),
    )
    return {
        "history_id": response.get("historyId"),
        "expiration": response.get("expiration"),
    }


def stop_gmail_watch(transport: GoogleAPITransport) -> None:
    service = transport._build_service()
    _execute_request(
        transport,
        service.users().stop(
            userId=getattr(transport, "user_id", "me"),
            body={},
        ),
    )


def start_watch_renewal(
    transport: GoogleAPITransport,
    *,
    topic_name: str,
    renew_every_seconds: int = 6 * 24 * 3600,
    label_ids: list[str] | None = None,
) -> None:
    global _watch_renewal_thread

    if _watch_renewal_thread is not None and _watch_renewal_thread.is_alive():
        return

    _watch_renewal_stop.clear()

    def _renew_loop() -> None:
        while not _watch_renewal_stop.wait(timeout=renew_every_seconds):
            try:
                register_gmail_watch(
                    transport,
                    topic_name=topic_name,
                    label_ids=label_ids,
                )
                logger.info("Gmail watch renewed successfully")
            except Exception as exc:  # pragma: no cover - background logging path
                logger.warning(
                    "Gmail watch renewal failed",
                    extra={"error": str(exc)},
                )

    _watch_renewal_thread = threading.Thread(
        target=_renew_loop,
        daemon=True,
        name="gmail-watch-renewal",
    )
    _watch_renewal_thread.start()


def stop_watch_renewal() -> None:
    _watch_renewal_stop.set()


def parse_gmail_notification(pubsub_message: dict) -> dict:
    payload = pubsub_message.get("message", {})
    encoded = payload.get("data", "")
    padded = encoded + "=" * (-len(encoded) % 4)
    decoded = base64.urlsafe_b64decode(padded.encode("utf-8")).decode("utf-8")
    parsed = json.loads(decoded)
    return {
        "email_address": parsed.get("emailAddress", ""),
        "history_id": str(parsed.get("historyId", "")),
        "message_id": payload.get("messageId", ""),
        "publish_time": payload.get("publishTime", ""),
    }


class GmailPushSubscription:
    """
    Backwards-compatible wrapper for the v1 Gmail push helper surface.
    """

    def __init__(self, transport: GoogleAPITransport):
        self.transport = transport

    def setup_watch(self, topic_name: str, label_ids: Optional[Iterable[str]] = None) -> dict:
        return register_gmail_watch(
            self.transport,
            topic_name=topic_name,
            label_ids=list(label_ids or ["UNREAD"]),
        )

    def stop_watch(self) -> None:
        stop_gmail_watch(self.transport)

    @staticmethod
    def parse_notification(pubsub_message: dict) -> dict:
        return parse_gmail_notification(pubsub_message)
