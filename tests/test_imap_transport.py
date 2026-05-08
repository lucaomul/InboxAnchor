
from inboxanchor.connectors.imap_transport import ImaplibTransport


class StubIMAPClient:
    capabilities = (b"IMAP4rev1", b"MOVE")

    def __init__(self, host, port):
        self.host = host
        self.port = port
        self.actions = []

    def login(self, username, password):
        self.actions.append(("login", username, password))
        return "OK", [b"Logged in"]

    def select(self, mailbox):
        self.actions.append(("select", mailbox))
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

    def logout(self):
        self.actions.append(("logout",))


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
