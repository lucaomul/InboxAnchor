
import imaplib

import pytest

from inboxanchor.connectors.imap_transport import IMAPAuthenticationError, ImaplibTransport


class StubIMAPClient:
    capabilities = (b"IMAP4rev1", b"MOVE")

    def __init__(self, host, port):
        self.host = host
        self.port = port
        self.actions = []
        self.state = "NONAUTH"

    def login(self, username, password):
        self.actions.append(("login", username, password))
        self.state = "AUTH"
        return "OK", [b"Logged in"]

    def select(self, mailbox):
        self.actions.append(("select", mailbox))
        self.state = "SELECTED"
        return "OK", [b"1"]

    def uid(self, command, *args):
        self.actions.append(("uid", command, args))
        command = command.lower()
        if command == "search":
            return "OK", [b"101 102"]
        if command == "fetch":
            raw_email = (
                b"From: sender@example.com\r\n"
                b"To: user@example.com\r\n"
                b"Subject: IMAP Hello\r\n"
                b"Date: Thu, 08 May 2026 10:00:00 +0000\r\n"
                b"Message-ID: <msg-101@example.com>\r\n"
                b"Content-Type: text/plain; charset=utf-8\r\n\r\n"
                b"Hello from IMAP"
            )
            metadata = b'101 (FLAGS (\\Seen) X-GM-LABELS ("Inbox"))'
            return "OK", [(metadata, raw_email)]
        if command in {"move", "store", "copy"}:
            return "OK", [b"done"]
        raise AssertionError(f"Unexpected command: {command}")

    def create(self, mailbox):
        self.actions.append(("create", mailbox))
        return "OK", [b"created"]

    def expunge(self):
        self.actions.append(("expunge",))
        return "OK", [b"expunged"]

    def close(self):
        self.actions.append(("close",))
        self.state = "LOGOUT"

    def logout(self):
        self.actions.append(("logout",))
        self.state = "LOGOUT"


class FlakyLoginIMAPClient(StubIMAPClient):
    login_attempts = 0

    def login(self, username, password):
        type(self).login_attempts += 1
        self.actions.append(("login", username, password))
        if type(self).login_attempts == 1:
            raise imaplib.IMAP4.error("invalid credentials")
        self.state = "AUTH"
        return "OK", [b"Logged in"]


class JsonBodyIMAPClient(StubIMAPClient):
    def uid(self, command, *args):
        self.actions.append(("uid", command, args))
        command = command.lower()
        if command == "search":
            return "OK", [b"201"]
        if command == "fetch":
            raw_email = (
                b"From: sender@example.com\r\n"
                b"To: user@example.com\r\n"
                b"Subject: JSON payload\r\n"
                b"Date: Thu, 08 May 2026 10:00:00 +0000\r\n"
                b"Message-ID: <msg-201@example.com>\r\n"
                b"MIME-Version: 1.0\r\n"
                b"Content-Type: multipart/mixed; boundary=\"json-boundary\"\r\n\r\n"
                b"--json-boundary\r\n"
                b"Content-Type: application/json; charset=utf-8\r\n\r\n"
                b'{\"message\":\"Your OTP is 123456\",\"summary\":\"Security verification\"}\r\n'
                b"--json-boundary--\r\n"
            )
            metadata = b'201 (FLAGS () X-GM-LABELS ("Inbox"))'
            return "OK", [(metadata, raw_email)]
        return super().uid(command, *args)


def test_imap_transport_lists_unread_messages(monkeypatch):
    monkeypatch.setattr("imaplib.IMAP4_SSL", StubIMAPClient)
    transport = ImaplibTransport(
        host="imap.example.com",
        port=993,
        username="user@example.com",
        password="secret",
        provider_name="imap",
    )

    emails = transport.list_unread(limit=10)

    assert len(emails) == 2
    assert emails[0].subject == "IMAP Hello"
    assert emails[0].sender == "sender@example.com"


def test_imap_transport_mark_read_and_archive(monkeypatch):
    monkeypatch.setattr("imaplib.IMAP4_SSL", StubIMAPClient)
    transport = ImaplibTransport(
        host="imap.example.com",
        port=993,
        username="user@example.com",
        password="secret",
        provider_name="imap",
    )

    read_result = transport.batch_mark_as_read(["101"], dry_run=False)
    archive_result = transport.archive_emails(["101"], dry_run=False)

    assert read_result.executed is True
    assert archive_result.executed is True
    assert "archive" in archive_result.details.lower()


def test_imap_transport_uses_date_window_search_criteria(monkeypatch):
    monkeypatch.setattr("imaplib.IMAP4_SSL", StubIMAPClient)
    transport = ImaplibTransport(
        host="imap.example.com",
        port=993,
        username="user@example.com",
        password="secret",
        provider_name="imap",
    )

    transport.list_unread(limit=10, time_range="last_month")

    search_actions = [
        action for action in transport._client.actions
        if action[0] == "uid" and action[1].lower() == "search"
    ]
    assert search_actions
    criteria = search_actions[0][2]
    assert "SINCE" in criteria
    assert "BEFORE" in criteria


def test_imap_transport_can_stream_all_unread_batches(monkeypatch):
    monkeypatch.setattr("imaplib.IMAP4_SSL", StubIMAPClient)
    transport = ImaplibTransport(
        host="imap.example.com",
        port=993,
        username="user@example.com",
        password="secret",
        provider_name="imap",
    )

    batches = list(
        transport.iter_all_unread_batches(
            batch_size=1,
            include_body=True,
            time_range="all_time",
        )
    )

    assert len(batches) == 2
    assert all(len(batch) == 1 for batch in batches)


def test_imap_transport_metadata_only_fetches_headers(monkeypatch):
    monkeypatch.setattr("imaplib.IMAP4_SSL", StubIMAPClient)
    transport = ImaplibTransport(
        host="imap.example.com",
        port=993,
        username="user@example.com",
        password="secret",
        provider_name="imap",
    )

    emails = transport.list_unread(limit=10, include_body=False)

    fetch_actions = [
        action for action in transport._client.actions
        if action[0] == "uid" and action[1].lower() == "fetch"
    ]
    assert emails
    assert fetch_actions
    assert "BODY.PEEK[HEADER.FIELDS" in fetch_actions[0][2][1]
    assert emails[0].body_full == ""


def test_imap_transport_extracts_json_message_text(monkeypatch):
    monkeypatch.setattr("imaplib.IMAP4_SSL", JsonBodyIMAPClient)
    transport = ImaplibTransport(
        host="imap.example.com",
        port=993,
        username="user@example.com",
        password="secret",
        provider_name="imap",
    )

    emails = transport.list_unread(limit=10, include_body=True)

    assert len(emails) == 1
    assert "Your OTP is 123456" in emails[0].body_full
    assert "Security verification" in emails[0].snippet


def test_imap_transport_does_not_cache_failed_login(monkeypatch):
    FlakyLoginIMAPClient.login_attempts = 0
    monkeypatch.setattr("imaplib.IMAP4_SSL", FlakyLoginIMAPClient)
    transport = ImaplibTransport(
        host="imap.example.com",
        port=993,
        username="user@example.com",
        password="secret",
        provider_name="imap",
    )

    with pytest.raises(IMAPAuthenticationError):
        transport.list_unread(limit=10)

    assert transport._client is None

    emails = transport.list_unread(limit=10)

    assert len(emails) == 2
    assert transport._client is not None
