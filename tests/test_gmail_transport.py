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
