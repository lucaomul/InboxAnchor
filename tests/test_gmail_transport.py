from __future__ import annotations

import base64
import threading
import time
from datetime import datetime, timedelta, timezone

from inboxanchor.config.settings import SETTINGS
from inboxanchor.connectors.gmail_transport import GoogleAPITransport
from inboxanchor.models import EmailMessage


class StubResponse:
    def __init__(self, payload: dict, status_code: int = 200):
        self._payload = payload
        self.status_code = status_code
        self.content = b"{}"

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"http {self.status_code}")

    def json(self):
        return self._payload


class StubSession:
    def __init__(self, responses: list[StubResponse]):
        self.responses = responses
        self.calls: list[tuple[str, str, dict | None, dict | None, int]] = []
        self._lock = threading.Lock()

    def request(self, method, url, params=None, json=None, timeout=30):
        with self._lock:
            self.calls.append((method, url, params, json, timeout))
            if "/messages/" in url and not url.endswith("/messages"):
                message_id = url.rsplit("/", 1)[-1]
                for index, response in enumerate(self.responses):
                    payload = getattr(response, "_payload", {})
                    if isinstance(payload, dict) and payload.get("id") == message_id:
                        return self.responses.pop(index)
            return self.responses.pop(0)


def _message_resource(
    email_id: str,
    *,
    subject: str | None = None,
    snippet: str = "Snippet",
    label_ids: list[str] | None = None,
    body_text: str = "",
):
    body_payload = {}
    if body_text:
        body_payload["data"] = base64.urlsafe_b64encode(body_text.encode("utf-8")).decode("utf-8")
    payload = {
        "headers": [
            {"name": "From", "value": "sender@example.com"},
            {"name": "Subject", "value": subject or f"Subject {email_id}"},
            {"name": "Date", "value": "Fri, 08 May 2026 12:00:00 +0000"},
        ],
    }
    if body_payload:
        payload["body"] = body_payload
    return {
        "id": email_id,
        "threadId": f"thread-{email_id}",
        "snippet": snippet,
        "labelIds": label_ids or ["UNREAD", "INBOX"],
        "payload": payload,
    }


def test_google_api_transport_lists_unread_via_authorized_session():
    session = StubSession(
        [
            StubResponse({"messages": [{"id": "msg-1", "threadId": "thread-1"}]}),
            StubResponse(
                {
                    "id": "msg-1",
                    "threadId": "thread-1",
                    "snippet": "Review this contract please",
                    "labelIds": ["UNREAD", "INBOX"],
                    "payload": {
                        "headers": [
                            {"name": "From", "value": "ceo@example.com"},
                            {"name": "Subject", "value": "Contract review"},
                            {"name": "Date", "value": "Fri, 08 May 2026 12:00:00 +0000"},
                        ],
                        "body": {
                            "data": "UmV2aWV3IHRoaXMgY29udHJhY3QgcGxlYXNl",
                        },
                    },
                }
            ),
        ]
    )

    transport = GoogleAPITransport(
        credentials_path="~/credentials.json",
        token_path="~/token.json",
        session=session,
    )

    emails = transport.list_unread(limit=5)

    assert len(emails) == 1
    assert emails[0].id == "msg-1"
    assert emails[0].subject == "Contract review"
    assert emails[0].unread is True
    assert session.calls[0][0] == "GET"
    assert session.calls[0][1].endswith("/users/me/messages")
    assert session.calls[1][1].endswith("/users/me/messages/msg-1")


def test_google_api_transport_reads_profile_history_id_via_authorized_session():
    session = StubSession([StubResponse({"historyId": "12345"})])
    transport = GoogleAPITransport(
        credentials_path="~/credentials.json",
        token_path="~/token.json",
        session=session,
    )

    checkpoint = transport.get_incremental_checkpoint()

    assert checkpoint == "12345"
    assert session.calls[0][1].endswith("/users/me/profile")


def test_fetch_messages_parallel_preserves_order():
    transport = GoogleAPITransport(
        credentials_path="~/credentials.json",
        token_path="~/token.json",
        session=StubSession([]),
    )
    delays = {"msg-1": 0.03, "msg-2": 0.01, "msg-3": 0.02}

    def fake_fetch(email_id: str, *, include_body: bool = True):
        del include_body
        time.sleep(delays[email_id])
        return _message_resource(email_id, subject=f"Parallel {email_id}", snippet=email_id)

    transport._fetch_message_resource = fake_fetch  # type: ignore[method-assign]

    emails = transport._fetch_messages_parallel(
        [{"id": "msg-1"}, {"id": "msg-2"}, {"id": "msg-3"}],
        include_body=False,
        max_workers=3,
    )

    assert [email.id for email in emails] == ["msg-1", "msg-2", "msg-3"]


def test_fetch_messages_parallel_partial_failure():
    transport = GoogleAPITransport(
        credentials_path="~/credentials.json",
        token_path="~/token.json",
        session=StubSession([]),
    )

    def fake_fetch(email_id: str, *, include_body: bool = True):
        del include_body
        if email_id == "msg-2":
            raise RuntimeError("boom")
        return _message_resource(email_id, subject=f"Parallel {email_id}", snippet=email_id)

    transport._fetch_message_resource = fake_fetch  # type: ignore[method-assign]

    emails = transport._fetch_messages_parallel(
        [{"id": "msg-1"}, {"id": "msg-2"}, {"id": "msg-3"}],
        include_body=False,
        max_workers=3,
    )

    assert [email.id for email in emails] == ["msg-1", "msg-3"]


def test_google_api_transport_backfills_mailbox_metadata_without_full_bodies():
    session = StubSession(
        [
            StubResponse(
                {
                    "messages": [
                        {"id": "msg-1", "threadId": "thread-1"},
                        {"id": "msg-2", "threadId": "thread-2"},
                    ]
                }
            ),
            StubResponse(
                {
                    "id": "msg-1",
                    "threadId": "thread-1",
                    "snippet": "Quarterly planning notes",
                    "labelIds": ["INBOX"],
                    "payload": {
                        "headers": [
                            {"name": "From", "value": "ops@example.com"},
                            {"name": "Subject", "value": "Quarterly planning"},
                            {"name": "Date", "value": "Fri, 08 May 2026 12:00:00 +0000"},
                        ],
                    },
                }
            ),
            StubResponse(
                {
                    "id": "msg-2",
                    "threadId": "thread-2",
                    "snippet": "Hiring pipeline update",
                    "labelIds": ["UNREAD", "INBOX"],
                    "payload": {
                        "headers": [
                            {"name": "From", "value": "talent@example.com"},
                            {"name": "Subject", "value": "Hiring update"},
                            {"name": "Date", "value": "Thu, 07 May 2026 12:00:00 +0000"},
                        ],
                    },
                }
            ),
        ]
    )

    transport = GoogleAPITransport(
        credentials_path="~/credentials.json",
        token_path="~/token.json",
        session=session,
    )

    batches = list(
        transport.iter_mailbox_batches(
            limit=2,
            batch_size=2,
            include_body=False,
            unread_only=False,
        )
    )

    assert len(batches) == 1
    assert [email.id for email in batches[0]] == ["msg-1", "msg-2"]
    assert batches[0][0].body_full == ""
    assert batches[0][0].body_preview == "Quarterly planning notes"
    assert batches[0][0].body_fetched is False
    assert batches[0][1].unread is True
    assert session.calls[0][2]["q"] is None


def test_google_api_transport_mailbox_backfill_can_resume_from_offset():
    session = StubSession(
        [
            StubResponse(
                {
                    "messages": [
                        {"id": "msg-1", "threadId": "thread-1"},
                        {"id": "msg-2", "threadId": "thread-2"},
                    ],
                    "nextPageToken": "page-2",
                }
            ),
            StubResponse(
                {
                    "messages": [
                        {"id": "msg-3", "threadId": "thread-3"},
                        {"id": "msg-4", "threadId": "thread-4"},
                    ]
                }
            ),
            StubResponse(
                {
                    "id": "msg-3",
                    "threadId": "thread-3",
                    "snippet": "Third message",
                    "labelIds": ["INBOX"],
                    "payload": {
                        "headers": [
                            {"name": "From", "value": "ops@example.com"},
                            {"name": "Subject", "value": "Message three"},
                            {"name": "Date", "value": "Fri, 08 May 2026 12:00:00 +0000"},
                        ],
                    },
                }
            ),
            StubResponse(
                {
                    "id": "msg-4",
                    "threadId": "thread-4",
                    "snippet": "Fourth message",
                    "labelIds": ["INBOX"],
                    "payload": {
                        "headers": [
                            {"name": "From", "value": "ops@example.com"},
                            {"name": "Subject", "value": "Message four"},
                            {"name": "Date", "value": "Thu, 07 May 2026 12:00:00 +0000"},
                        ],
                    },
                }
            ),
        ]
    )

    transport = GoogleAPITransport(
        credentials_path="~/credentials.json",
        token_path="~/token.json",
        session=session,
    )

    batches = list(
        transport.iter_mailbox_batches(
            limit=2,
            batch_size=2,
            include_body=False,
            unread_only=False,
            offset=2,
        )
    )

    assert len(batches) == 1
    assert [email.id for email in batches[0]] == ["msg-3", "msg-4"]
    assert session.calls[0][2]["pageToken"] is None
    assert session.calls[1][2]["pageToken"] == "page-2"


def test_iter_all_unread_streams_multiple_pages():
    transport = GoogleAPITransport(
        credentials_path="~/credentials.json",
        token_path="~/token.json",
        session=StubSession([]),
    )
    pages = {
        None: {
            "messages": [{"id": "msg-1"}, {"id": "msg-2"}],
            "nextPageToken": "page-2",
        },
        "page-2": {
            "messages": [{"id": "msg-3"}, {"id": "msg-4"}],
            "nextPageToken": "page-3",
        },
        "page-3": {
            "messages": [{"id": "msg-5"}],
        },
    }

    transport._list_message_refs = lambda limit, page_token=None, q=None: pages[page_token]  # type: ignore[method-assign]
    transport._fetch_messages_parallel = lambda refs, include_body=True, max_workers=10: [  # type: ignore[method-assign]
        EmailMessage(
            id=item["id"],
            thread_id=f"thread-{item['id']}",
            sender="sender@example.com",
            subject=f"Subject {item['id']}",
            snippet=item["id"],
            body_preview=item["id"],
            body_full="" if not include_body else item["id"],
            body_fetched=include_body,
            body_stored=include_body,
            received_at=datetime.now(timezone.utc),
            labels=["UNREAD", "INBOX"],
            has_attachments=False,
            unread=True,
        )
        for item in refs
    ]

    batches = list(
        transport.iter_all_unread(
            batch_size=2,
            include_body=False,
            time_range="all_time",
        )
    )

    assert len(batches) == 3
    assert [email.id for batch in batches for email in batch] == [
        "msg-1",
        "msg-2",
        "msg-3",
        "msg-4",
        "msg-5",
    ]


def test_iter_all_unread_stops_without_next_page_token():
    transport = GoogleAPITransport(
        credentials_path="~/credentials.json",
        token_path="~/token.json",
        session=StubSession([]),
    )
    pages = {
        None: {
            "messages": [{"id": "msg-1"}],
            "nextPageToken": "page-2",
        },
        "page-2": {
            "messages": [{"id": "msg-2"}],
        },
    }

    transport._list_message_refs = lambda limit, page_token=None, q=None: pages[page_token]  # type: ignore[method-assign]
    transport._fetch_messages_parallel = lambda refs, include_body=True, max_workers=10: [  # type: ignore[method-assign]
        EmailMessage(
            id=item["id"],
            thread_id=f"thread-{item['id']}",
            sender="sender@example.com",
            subject=f"Subject {item['id']}",
            snippet=item["id"],
            body_preview=item["id"],
            body_full="",
            body_fetched=False,
            body_stored=False,
            received_at=datetime.now(timezone.utc),
            labels=["UNREAD", "INBOX"],
            has_attachments=False,
            unread=True,
        )
        for item in refs
    ]

    batches = list(
        transport.iter_all_unread(
            batch_size=1,
            include_body=False,
            time_range="all_time",
        )
    )

    assert len(batches) == 2
    assert [email.id for batch in batches for email in batch] == ["msg-1", "msg-2"]


def test_google_api_transport_applies_time_range_query_to_unread_listing():
    session = StubSession(
        [
            StubResponse({"messages": []}),
        ]
    )

    transport = GoogleAPITransport(
        credentials_path="~/credentials.json",
        token_path="~/token.json",
        session=session,
    )

    transport.list_unread(limit=5, time_range="last_6_months")

    query = session.calls[0][2]["q"]
    assert "is:unread" in query
    assert "after:" in query


def test_google_api_transport_unread_page_can_fetch_metadata_only():
    session = StubSession(
        [
            StubResponse({"messages": [{"id": "msg-1", "threadId": "thread-1"}]}),
            StubResponse(
                {
                    "id": "msg-1",
                    "threadId": "thread-1",
                    "snippet": "Metadata only snippet",
                    "labelIds": ["UNREAD", "INBOX"],
                    "payload": {
                        "headers": [
                            {"name": "From", "value": "ops@example.com"},
                            {"name": "Subject", "value": "Metadata only"},
                            {"name": "Date", "value": "Fri, 08 May 2026 12:00:00 +0000"},
                        ],
                    },
                }
            ),
        ]
    )

    transport = GoogleAPITransport(
        credentials_path="~/credentials.json",
        token_path="~/token.json",
        session=session,
    )

    page = transport.list_unread_page(limit=1, offset=0, include_body=False, time_range="all_time")

    assert len(page) == 1
    assert page[0].body_full == ""
    assert page[0].body_preview == "Metadata only snippet"
    assert session.calls[1][2]["format"] == "metadata"


def test_body_truncated_at_max_chars():
    transport = GoogleAPITransport(
        credentials_path="~/credentials.json",
        token_path="~/token.json",
        session=StubSession([]),
    )
    previous = SETTINGS.gmail_body_max_chars
    SETTINGS.gmail_body_max_chars = 12
    try:
        payload = {
            "mimeType": "text/plain",
            "body": {
                "data": base64.urlsafe_b64encode(
                    b"abcdefghijklmnopqrstuvwxyz"
                ).decode("utf-8")
            },
        }
        body = transport._extract_best_body(payload)
    finally:
        SETTINGS.gmail_body_max_chars = previous

    assert body == "abcdefghijkl"


def test_google_api_transport_applies_time_range_query_to_mailbox_backfill():
    session = StubSession(
        [
            StubResponse({"messages": []}),
        ]
    )

    transport = GoogleAPITransport(
        credentials_path="~/credentials.json",
        token_path="~/token.json",
        session=session,
    )

    list(
        transport.iter_mailbox_batches(
            limit=50,
            batch_size=25,
            include_body=False,
            unread_only=False,
            time_range="older_than_10_years",
        )
    )

    query = session.calls[0][2]["q"]
    assert "before:" in query


def test_google_api_transport_incremental_batches_accept_time_range_and_filter_results():
    transport = GoogleAPITransport(
        credentials_path="~/credentials.json",
        token_path="~/token.json",
        session=StubSession([]),
    )
    transport.list_changed_message_ids = lambda checkpoint, max_results=500: (  # type: ignore[method-assign]
        ["recent", "old"],
        "next-history",
    )

    include_body_calls: list[bool] = []

    def fake_parallel(refs: list[dict], *, include_body: bool = True, max_workers: int = 10):
        del max_workers
        include_body_calls.append(include_body)
        emails = []
        now = datetime.now(timezone.utc)
        for ref in refs:
            email_id = ref["id"]
            received_at = (
                now - timedelta(days=1)
                if email_id == "recent"
                else now - timedelta(days=3650)
            )
            emails.append(
                EmailMessage(
                    id=email_id,
                    thread_id=f"thread-{email_id}",
                    sender="sender@example.com",
                    subject=f"Subject {email_id}",
                    snippet="Snippet",
                    body_preview="Body preview",
                    body_full="" if not include_body else "Full body",
                    body_fetched=include_body,
                    body_stored=include_body,
                    received_at=received_at,
                    labels=["UNREAD", "INBOX"],
                    has_attachments=False,
                    unread=True,
                )
            )
        return emails

    transport._fetch_messages_parallel = fake_parallel  # type: ignore[method-assign]

    batches = list(
        transport.iter_unread_batches_since(
            "history-1",
            limit=10,
            batch_size=10,
            include_body=False,
            time_range="last_7_days",
        )
    )

    assert len(batches) == 1
    assert [email.id for email in batches[0]] == ["recent"]
    assert include_body_calls == [False]


def test_google_api_transport_mark_read_uses_batch_modify_endpoint():
    session = StubSession([StubResponse({})])
    transport = GoogleAPITransport(
        credentials_path="~/credentials.json",
        token_path="~/token.json",
        session=session,
    )

    transport.mark_read(["msg-1", "msg-2"])

    assert session.calls[0][0] == "POST"
    assert session.calls[0][1].endswith("/users/me/messages/batchModify")
    assert session.calls[0][3]["ids"] == ["msg-1", "msg-2"]
    assert session.calls[0][3]["removeLabelIds"] == ["UNREAD"]


def test_google_api_transport_apply_labels_uses_batch_modify_endpoint():
    session = StubSession(
        [
            StubResponse({"labels": [{"id": "Label_1", "name": "Priority/high"}]}),
            StubResponse({}),
        ]
    )
    transport = GoogleAPITransport(
        credentials_path="~/credentials.json",
        token_path="~/token.json",
        session=session,
    )

    transport.apply_labels(["msg-1", "msg-2"], ["Priority/high"])

    assert session.calls[0][0] == "GET"
    assert session.calls[0][1].endswith("/users/me/labels")
    assert session.calls[1][0] == "POST"
    assert session.calls[1][1].endswith("/users/me/messages/batchModify")
    assert session.calls[1][3]["ids"] == ["msg-1", "msg-2"]
    assert session.calls[1][3]["addLabelIds"] == ["Label_1"]


def test_google_api_transport_reuses_existing_label_after_conflict():
    session = StubSession(
        [
            StubResponse({"labels": []}),
            StubResponse({}, status_code=409),
            StubResponse({"labels": [{"id": "Label_1", "name": "work"}]}),
            StubResponse({}),
        ]
    )
    transport = GoogleAPITransport(
        credentials_path="~/credentials.json",
        token_path="~/token.json",
        session=session,
    )

    transport.apply_labels(["msg-1"], ["work"])

    assert session.calls[0][0] == "GET"
    assert session.calls[1][0] == "POST"
    assert session.calls[1][1].endswith("/users/me/labels")
    assert session.calls[2][0] == "GET"
    assert session.calls[3][0] == "POST"
    assert session.calls[3][1].endswith("/users/me/messages/batchModify")
    assert session.calls[3][3]["addLabelIds"] == ["Label_1"]


def test_google_api_transport_can_delete_labels_from_gmail():
    session = StubSession(
        [
            StubResponse(
                {
                    "labels": [
                        {"id": "Label_1", "name": "priority/high"},
                        {"id": "Label_2", "name": "jobs/alert"},
                    ]
                }
            ),
            StubResponse({}),
            StubResponse({}),
        ]
    )
    transport = GoogleAPITransport(
        credentials_path="~/credentials.json",
        token_path="~/token.json",
        session=session,
    )

    transport.delete_labels(["priority/high", "jobs/alert"])

    assert session.calls[0][0] == "GET"
    assert session.calls[0][1].endswith("/users/me/labels")
    assert session.calls[1][0] == "DELETE"
    assert session.calls[1][1].endswith("/users/me/labels/Label_1")
    assert session.calls[2][0] == "DELETE"
    assert session.calls[2][1].endswith("/users/me/labels/Label_2")


def test_google_api_transport_can_list_labels_from_gmail():
    session = StubSession(
        [
            StubResponse(
                {
                    "labels": [
                        {"id": "Label_1", "name": "priority/high"},
                        {"id": "Label_2", "name": "jobs/alert"},
                    ]
                }
            ),
        ]
    )
    transport = GoogleAPITransport(
        credentials_path="~/credentials.json",
        token_path="~/token.json",
        session=session,
    )

    labels = transport.list_labels()

    assert labels == ["jobs/alert", "priority/high"]
    assert session.calls[0][0] == "GET"
    assert session.calls[0][1].endswith("/users/me/labels")


def test_google_api_transport_skips_missing_labels_during_delete():
    session = StubSession(
        [
            StubResponse(
                {
                    "labels": [
                        {"id": "Label_1", "name": "priority/high"},
                    ]
                }
            ),
            StubResponse({}),
        ]
    )
    transport = GoogleAPITransport(
        credentials_path="~/credentials.json",
        token_path="~/token.json",
        session=session,
    )

    transport.delete_labels(["priority/high", "jobs/alert"])

    assert session.calls[0][0] == "GET"
    assert session.calls[1][0] == "DELETE"
    assert len(session.calls) == 2


def test_google_api_transport_ignores_404_when_label_was_already_deleted():
    session = StubSession(
        [
            StubResponse(
                {
                    "labels": [
                        {"id": "Label_1", "name": "priority/high"},
                    ]
                }
            ),
            StubResponse({}, status_code=404),
        ]
    )
    transport = GoogleAPITransport(
        credentials_path="~/credentials.json",
        token_path="~/token.json",
        session=session,
    )

    transport.delete_labels(["priority/high"])

    assert session.calls[0][0] == "GET"
    assert session.calls[1][0] == "DELETE"


def test_google_api_transport_can_create_alias_routing_filter():
    session = StubSession(
        [
            StubResponse({"labels": []}),
            StubResponse({"id": "Label_123"}),
            StubResponse({"filter": []}),
            StubResponse({"id": "Filter_123"}),
        ]
    )
    transport = GoogleAPITransport(
        credentials_path="~/credentials.json",
        token_path="~/token.json",
        session=session,
    )

    transport.ensure_alias_routing(
        "owner+ia-travel1234567@gmail.com",
        label_name="InboxAnchor/Aliases/Travel",
    )

    assert session.calls[0][1].endswith("/users/me/labels")
    assert session.calls[1][0] == "POST"
    assert session.calls[2][1].endswith("/users/me/settings/filters")
    assert session.calls[3][3]["criteria"]["to"] == "owner+ia-travel1234567@gmail.com"
    assert session.calls[3][3]["action"]["removeLabelIds"] == ["INBOX"]
    assert session.calls[3][3]["action"]["addLabelIds"] == ["Label_123"]


def test_google_api_transport_can_remove_alias_routing_filter():
    session = StubSession(
        [
            StubResponse(
                {
                    "filter": [
                        {
                            "id": "Filter_123",
                            "criteria": {"to": "owner+ia-travel1234567@gmail.com"},
                        }
                    ]
                }
            ),
            StubResponse({}),
        ]
    )
    transport = GoogleAPITransport(
        credentials_path="~/credentials.json",
        token_path="~/token.json",
        session=session,
    )

    transport.remove_alias_routing("owner+ia-travel1234567@gmail.com")

    assert session.calls[0][1].endswith("/users/me/settings/filters")
    assert session.calls[1][0] == "DELETE"
    assert session.calls[1][1].endswith("/users/me/settings/filters/Filter_123")


def test_google_api_transport_can_send_reply_via_authorized_session():
    session = StubSession(
        [
            StubResponse(
                {
                    "id": "msg-1",
                    "threadId": "thread-1",
                    "payload": {
                        "headers": [
                            {"name": "From", "value": "CEO <ceo@example.com>"},
                            {"name": "Subject", "value": "Contract review"},
                            {"name": "Message-ID", "value": "<msg-1@example.com>"},
                        ],
                    },
                }
            ),
            StubResponse({"id": "sent-1"}),
        ]
    )
    transport = GoogleAPITransport(
        credentials_path="~/credentials.json",
        token_path="~/token.json",
        session=session,
    )

    payload = transport.send_reply("msg-1", "Thanks, I will review this today.")

    assert payload["to_address"] == "ceo@example.com"
    assert payload["subject"] == "Re: Contract review"
    assert session.calls[1][0] == "POST"
    assert session.calls[1][1].endswith("/users/me/messages/send")
    assert "raw" in session.calls[1][3]
