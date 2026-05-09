from datetime import datetime, timezone

from inboxanchor.connectors.gmail_client import GmailClient
from inboxanchor.models import EmailMessage


class StubGmailTransport:
    def __init__(self):
        self.marked_read: list[str] = []
        self.archived: list[str] = []
        self.trashed: list[str] = []
        self.labels_applied: list[tuple[list[str], list[str]]] = []
        self.replies_sent: list[tuple[str, str, str | None]] = []
        self.message = EmailMessage(
            id="gmail-1",
            thread_id="thread-1",
            sender="hello@example.com",
            subject="Hello",
            snippet="Hi there",
            body_preview="Hi there",
            received_at=datetime.now(timezone.utc),
            labels=["inbox"],
            has_attachments=False,
            unread=True,
        )

    def list_unread(self, limit: int, *, time_range=None):
        del time_range
        return [self.message]

    def get_message(self, email_id: str):
        return self.message

    def get_body(self, email_id: str):
        return self.message.body_preview

    def mark_read(self, email_ids: list[str]):
        self.marked_read.extend(email_ids)

    def archive(self, email_ids: list[str]):
        self.archived.extend(email_ids)

    def trash(self, email_ids: list[str]):
        self.trashed.extend(email_ids)

    def apply_labels(self, email_ids: list[str], labels: list[str]):
        self.labels_applied.append((email_ids, labels))

    def send_reply(self, email_id: str, body: str, *, from_address=None):
        self.replies_sent.append((email_id, body, from_address))
        return {
            "email_id": email_id,
            "to_address": "hello@example.com",
            "subject": "Re: Hello",
        }


def test_gmail_connector_mocked_behavior():
    transport = StubGmailTransport()
    client = GmailClient(transport=transport)

    unread = client.list_unread(limit=10)
    result = client.batch_mark_as_read(["gmail-1"], dry_run=False)
    client.apply_labels(["gmail-1"], ["review"], dry_run=False)

    assert unread[0].id == "gmail-1"
    assert result.executed is True
    assert transport.marked_read == ["gmail-1"]
    assert transport.labels_applied == [(["gmail-1"], ["review"])]


def test_gmail_connector_can_send_reply_through_transport():
    transport = StubGmailTransport()
    client = GmailClient(transport=transport)

    result = client.send_reply(
        "gmail-1",
        "Thanks, I will send an update today.",
        from_address="alias@example.com",
        dry_run=False,
    )

    assert result.executed is True
    assert transport.replies_sent == [
        ("gmail-1", "Thanks, I will send an update today.", "alias@example.com")
    ]
