from datetime import datetime, timezone

from inboxanchor.connectors.gmail_client import GmailClient
from inboxanchor.models import EmailMessage


class StubGmailTransport:
    def __init__(self):
        self.marked_read: list[str] = []
        self.archived: list[str] = []
        self.trashed: list[str] = []
        self.labels_applied: list[tuple[list[str], list[str]]] = []
        self.labels_deleted: list[list[str]] = []
        self.available_labels: list[str] = ["priority/high", "jobs/alert", "InboxAnchor/Aliases"]
        self.alias_routes_created: list[tuple[str, str]] = []
        self.alias_routes_removed: list[str] = []
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

    def list_unread(self, limit: int, *, include_body=True, time_range=None):
        del include_body
        del time_range
        return [self.message]

    def get_message(self, email_id: str, include_body: bool = True):
        del email_id, include_body
        return self.message

    def get_body(self, email_id: str):
        del email_id
        return self.message.body_preview

    def mark_read(self, email_ids: list[str]):
        self.marked_read.extend(email_ids)

    def archive(self, email_ids: list[str]):
        self.archived.extend(email_ids)

    def trash(self, email_ids: list[str]):
        self.trashed.extend(email_ids)

    def apply_labels(self, email_ids: list[str], labels: list[str]):
        self.labels_applied.append((email_ids, labels))

    def delete_labels(self, labels: list[str]):
        self.labels_deleted.append(labels)

    def list_labels(self):
        return list(self.available_labels)

    def ensure_alias_routing(self, alias_address: str, *, label_name: str):
        self.alias_routes_created.append((alias_address, label_name))

    def remove_alias_routing(self, alias_address: str):
        self.alias_routes_removed.append(alias_address)

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


def test_gmail_connector_can_delete_label_definitions_through_transport():
    transport = StubGmailTransport()
    client = GmailClient(transport=transport)

    result = client.delete_labels(["priority/high", "jobs/alert"], dry_run=False)

    assert result.executed is True
    assert transport.labels_deleted == [["priority/high", "jobs/alert"]]


def test_gmail_connector_can_list_provider_labels_through_transport():
    transport = StubGmailTransport()
    client = GmailClient(transport=transport)

    labels = client.list_labels()

    assert labels == ["priority/high", "jobs/alert", "InboxAnchor/Aliases"]


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


def test_gmail_connector_can_manage_alias_routing_through_transport():
    transport = StubGmailTransport()
    client = GmailClient(transport=transport)

    create_result = client.ensure_alias_routing(
        "owner+ia-travel1234567@gmail.com",
        label_name="InboxAnchor/Aliases/Travel",
        dry_run=False,
    )
    remove_result = client.remove_alias_routing(
        "owner+ia-travel1234567@gmail.com",
        dry_run=False,
    )

    assert create_result.executed is True
    assert remove_result.executed is True
    assert transport.alias_routes_created == [
        ("owner+ia-travel1234567@gmail.com", "InboxAnchor/Aliases/Travel")
    ]
    assert transport.alias_routes_removed == ["owner+ia-travel1234567@gmail.com"]


def test_gmail_iter_unread_batches_uses_paged_path_for_all_time():
    calls: list[tuple[int, int, str | None]] = []

    class PagedTransport(StubGmailTransport):
        def list_unread(self, limit: int, *, include_body=True, time_range=None):
            del limit, include_body, time_range
            raise AssertionError("all_time should use list_unread_page, not list_unread")

        def list_unread_page(self, limit: int, offset: int, *, include_body=True, time_range=None):
            calls.append((limit, offset, include_body, time_range))
            if offset >= 4:
                return []
            return [
                self.message.model_copy(update={"id": f"gmail-{offset + index}"})
                for index in range(limit)
            ]

    client = GmailClient(transport=PagedTransport())

    batches = list(client.iter_unread_batches(limit=4, batch_size=100, time_range="all_time"))

    assert len(batches) == 1
    assert len(batches[0]) == 4
    assert calls == [(4, 0, True, "all_time")]


def test_gmail_iter_unread_batches_caps_initial_page_size_when_fetching_bodies():
    calls: list[tuple[int, int, str | None]] = []

    class PagedTransport(StubGmailTransport):
        def list_unread(self, limit: int, *, include_body=True, time_range=None):
            del limit, include_body, time_range
            raise AssertionError("all_time should use list_unread_page, not list_unread")

        def list_unread_page(self, limit: int, offset: int, *, include_body=True, time_range=None):
            calls.append((limit, offset, include_body, time_range))
            remaining = max(0, 60 - offset)
            count = min(limit, remaining)
            return [
                self.message.model_copy(update={"id": f"gmail-{offset + index}"})
                for index in range(count)
            ]

    client = GmailClient(transport=PagedTransport())

    batches = list(
        client.iter_unread_batches(
            limit=60,
            batch_size=100,
            include_body=True,
            time_range="all_time",
        )
    )

    assert [len(batch) for batch in batches] == [25, 25, 10]
    assert calls == [
        (25, 0, True, "all_time"),
        (25, 25, True, "all_time"),
        (10, 50, True, "all_time"),
    ]


def test_gmail_iter_unread_batches_uses_metadata_pages_for_large_lightweight_scan():
    calls: list[tuple[int, int, bool, str | None]] = []

    class PagedTransport(StubGmailTransport):
        def list_unread(self, limit: int, *, include_body=True, time_range=None):
            del limit, include_body, time_range
            raise AssertionError("all_time should use list_unread_page, not list_unread")

        def list_unread_page(self, limit: int, offset: int, *, include_body=True, time_range=None):
            calls.append((limit, offset, include_body, time_range))
            remaining = max(0, 600 - offset)
            count = min(limit, remaining)
            return [
                self.message.model_copy(
                    update={
                        "id": f"gmail-{offset + index}",
                        "body_full": "" if not include_body else "Full body",
                    }
                )
                for index in range(count)
            ]

    client = GmailClient(transport=PagedTransport())

    batches = list(
        client.iter_unread_batches(
            limit=600,
            batch_size=250,
            include_body=False,
            time_range="all_time",
        )
    )

    assert [len(batch) for batch in batches] == [100, 100, 100, 100, 100, 100]
    assert all(email.body_full == "" for batch in batches for email in batch)
    assert calls == [
        (100, 0, False, "all_time"),
        (100, 100, False, "all_time"),
        (100, 200, False, "all_time"),
        (100, 300, False, "all_time"),
        (100, 400, False, "all_time"),
        (100, 500, False, "all_time"),
    ]
