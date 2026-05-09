from __future__ import annotations

from inboxanchor.connectors.gmail_transport import GoogleAPITransport


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

    def request(self, method, url, params=None, json=None, timeout=30):
        self.calls.append((method, url, params, json, timeout))
        return self.responses.pop(0)


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
