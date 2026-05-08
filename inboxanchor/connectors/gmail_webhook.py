from __future__ import annotations

import base64
import json
from typing import Iterable, Optional

from inboxanchor.connectors.gmail_transport import GoogleAPITransport


class GmailPushSubscription:
    def __init__(self, transport: GoogleAPITransport):
        try:
            from google.cloud import pubsub_v1  # noqa: F401
        except ImportError as error:  # pragma: no cover - optional dependency
            raise ImportError(
                "google-cloud-pubsub is required for Gmail push subscriptions. "
                "Install it to enable watch and webhook flows."
            ) from error
        self.transport = transport

    def setup_watch(self, topic_name: str, label_ids: Optional[Iterable[str]] = None) -> dict:
        service = self.transport._build_service()
        body = {
            "topicName": topic_name,
            "labelIds": list(label_ids or ["INBOX"]),
            "labelFilterBehavior": "INCLUDE",
        }
        return self.transport._execute(
            service.users().watch(
                userId=self.transport.user_id,
                body=body,
            )
        )

    def stop_watch(self) -> None:
        service = self.transport._build_service()
        self.transport._execute(service.users().stop(userId=self.transport.user_id, body={}))

    @staticmethod
    def parse_notification(pubsub_message: dict) -> dict:
        payload = pubsub_message.get("message", {})
        encoded = payload.get("data", "")
        padded = encoded + "=" * (-len(encoded) % 4)
        decoded = base64.urlsafe_b64decode(padded.encode("utf-8")).decode("utf-8")
        parsed = json.loads(decoded)
        return {
            "email_address": parsed.get("emailAddress", ""),
            "history_id": parsed.get("historyId", ""),
            "message_id": payload.get("messageId", ""),
            "publish_time": payload.get("publishTime", ""),
        }
