from __future__ import annotations

import imaplib
import logging
import re
from contextlib import contextmanager
from datetime import datetime, timezone
from email import message_from_bytes
from email.header import decode_header, make_header
from email.message import Message
from email.utils import parsedate_to_datetime
from html import unescape
from typing import Optional

from inboxanchor.connectors.base import EmailProvider, ProviderActionResult
from inboxanchor.core.time_windows import imap_since_before_for_time_range, resolve_time_window
from inboxanchor.infra.text_normalizer import normalize_email_body_text
from inboxanchor.models import EmailMessage

logger = logging.getLogger(__name__)


class IMAPTransportError(RuntimeError):
    pass


class IMAPAuthenticationError(IMAPTransportError):
    pass


class IMAPFolderError(IMAPTransportError):
    pass


class ImaplibTransport(EmailProvider):
    provider_name = "imap"

    def __init__(
        self,
        host: str,
        port: int,
        username: str,
        password: str,
        *,
        use_ssl: bool = True,
        mailbox: str = "INBOX",
        provider_name: str = "imap",
        archive_mailbox: Optional[str] = None,
        trash_mailbox: Optional[str] = None,
    ):
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.use_ssl = use_ssl
        self.mailbox = mailbox
        self.provider_name = provider_name
        self.archive_mailbox = archive_mailbox or self._default_archive_mailbox()
        self.trash_mailbox = trash_mailbox or self._default_trash_mailbox()
        self._client = None
        self._capabilities: set[str] = set()

    def __enter__(self):
        self._connect()
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()
        return False

    def _default_archive_mailbox(self) -> str:
        if "gmail" in self.host.lower():
            return "[Gmail]/All Mail"
        return "Archive"

    def _default_trash_mailbox(self) -> str:
        if "gmail" in self.host.lower():
            return "[Gmail]/Trash"
        return "Trash"

    def _connect(self):
        if self._client is not None:
            return self._client
        try:
            client_cls = imaplib.IMAP4_SSL if self.use_ssl else imaplib.IMAP4
            self._client = client_cls(self.host, self.port)
            status, _ = self._client.login(self.username, self.password)
        except imaplib.IMAP4.error as error:
            raise IMAPAuthenticationError(f"IMAP login failed for {self.username}.") from error
        except OSError as error:
            raise IMAPTransportError(
                f"Unable to connect to IMAP host {self.host}:{self.port}."
            ) from error
        if status != "OK":
            raise IMAPAuthenticationError(f"IMAP login failed for {self.username}.")
        self._capabilities = {
            item.decode("utf-8", errors="ignore") if isinstance(item, bytes) else str(item)
            for item in getattr(self._client, "capabilities", [])
        }
        self._select_mailbox(self.mailbox)
        return self._client

    def close(self) -> None:
        if self._client is None:
            return
        try:
            self._client.close()
        except Exception:
            pass
        try:
            self._client.logout()
        except Exception:
            pass
        self._client = None

    def _select_mailbox(self, mailbox: str) -> None:
        client = self._connect()
        status, _ = client.select(mailbox)
        if status != "OK":
            raise IMAPFolderError(f"Could not select mailbox '{mailbox}'.")

    def _uid_command(self, command: str, *args):
        client = self._connect()
        status, data = client.uid(command, *args)
        if status != "OK":
            raise IMAPTransportError(f"IMAP UID {command} failed for mailbox '{self.mailbox}'.")
        return data

    def _format_since_date(self, checkpoint: str) -> str:
        parsed = datetime.fromisoformat(checkpoint.replace("Z", "+00:00"))
        return parsed.astimezone(timezone.utc).strftime("%d-%b-%Y")

    def _search_uids(
        self,
        *,
        limit: int,
        since: Optional[str] = None,
        before: Optional[str] = None,
        unread_only: bool = True,
    ) -> list[str]:
        criteria = ["UNSEEN"] if unread_only else ["ALL"]
        if since:
            criteria.extend(["SINCE", since])
        if before:
            criteria.extend(["BEFORE", before])
        raw = self._uid_command("search", None, *criteria)
        if not raw or not raw[0]:
            return []
        uids = raw[0].decode("utf-8").split()
        if limit:
            uids = uids[-limit:]
        uids.reverse()
        return uids

    def _fetch_raw_message(self, uid: str) -> tuple[bytes, list[str], list[str]]:
        spec = "(BODY.PEEK[] FLAGS)"
        if "X-GM-EXT-1" in self._capabilities:
            spec = "(BODY.PEEK[] FLAGS X-GM-LABELS)"
        data = self._uid_command("fetch", uid, spec)
        raw_message = b""
        flags: list[str] = []
        labels: list[str] = []

        for item in data:
            if not item or not isinstance(item, tuple):
                continue
            metadata, payload = item
            if isinstance(payload, bytes):
                raw_message = payload
            if isinstance(metadata, bytes):
                flags.extend(imaplib.ParseFlags(metadata))
                if b"X-GM-LABELS" in metadata:
                    match = re.search(rb"X-GM-LABELS \((.*?)\)", metadata)
                    if match:
                        labels = [
                            piece.decode("utf-8", errors="ignore").strip('"')
                            for piece in match.group(1).split()
                        ]
        return raw_message, flags, labels

    def _decode_header(self, value: Optional[str]) -> str:
        if not value:
            return ""
        return str(make_header(decode_header(value)))

    def _parse_received_at(self, raw_date: str) -> datetime:
        if not raw_date:
            return datetime.now(timezone.utc)
        try:
            parsed = parsedate_to_datetime(raw_date)
        except (TypeError, ValueError):
            return datetime.now(timezone.utc)
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)

    def _message_body(self, message: Message) -> str:
        plain_body = None
        html_body = None
        if message.is_multipart():
            for part in message.walk():
                disposition = (part.get("Content-Disposition") or "").lower()
                if "attachment" in disposition:
                    continue
                content_type = part.get_content_type()
                payload = part.get_payload(decode=True)
                if payload is None:
                    continue
                text = payload.decode(part.get_content_charset() or "utf-8", errors="replace")
                if content_type == "text/plain" and plain_body is None:
                    plain_body = normalize_email_body_text(text.strip())
                elif content_type == "text/html" and html_body is None:
                    html_body = normalize_email_body_text(
                        re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", unescape(text))).strip()
                    )
        else:
            payload = message.get_payload(decode=True) or b""
            plain_body = normalize_email_body_text(payload.decode(
                message.get_content_charset() or "utf-8",
                errors="replace",
            ).strip())
        return normalize_email_body_text(plain_body or html_body or "")

    def _message_to_email(
        self,
        uid: str,
        raw_message: bytes,
        flags: list[str],
        labels: list[str],
    ) -> EmailMessage:
        parsed = message_from_bytes(raw_message)
        body = self._message_body(parsed)
        subject = self._decode_header(parsed.get("Subject"))
        sender = self._decode_header(parsed.get("From"))
        message_id = self._decode_header(parsed.get("Message-ID")) or uid
        received_at = self._parse_received_at(parsed.get("Date", ""))
        has_attachments = any(part.get_filename() for part in parsed.walk())
        decoded_flags = [
            flag.decode("utf-8", errors="ignore") if isinstance(flag, bytes) else str(flag)
            for flag in flags
        ]
        normalized_labels = sorted(
            set(labels + decoded_flags)
        )
        return EmailMessage(
            id=uid,
            thread_id=message_id,
            sender=sender,
            subject=subject,
            snippet=(body or subject)[:180],
            body_preview=(body or subject)[:500],
            body_full=body or subject,
            received_at=received_at,
            labels=normalized_labels,
            has_attachments=has_attachments,
            unread="\\Seen" not in normalized_labels,
        )

    def _build_messages(self, uids: list[str], *, include_body: bool = True) -> list[EmailMessage]:
        emails: list[EmailMessage] = []
        for uid in uids:
            raw_message, flags, labels = self._fetch_raw_message(uid)
            email = self._message_to_email(uid, raw_message, flags, labels)
            if not include_body:
                email = email.model_copy(update={"body_preview": email.snippet, "body_full": ""})
            emails.append(email)
        emails.sort(key=lambda item: item.received_at, reverse=True)
        return emails

    def supports_incremental_sync(self) -> bool:
        return True

    def list_unread(
        self,
        limit: int = 50,
        include_body: bool = True,
        time_range: Optional[str] = None,
    ) -> list[EmailMessage]:
        since, before = imap_since_before_for_time_range(time_range)
        uids = self._search_uids(limit=limit, since=since, before=before)
        return self._build_messages(uids, include_body=include_body)

    def iter_unread_batches(
        self,
        *,
        limit: int = 50,
        batch_size: int = 100,
        include_body: bool = True,
        time_range: Optional[str] = None,
    ):
        since, before = imap_since_before_for_time_range(time_range)
        uids = self._search_uids(limit=limit, since=since, before=before)
        for start in range(0, len(uids), batch_size):
            yield self._build_messages(uids[start : start + batch_size], include_body=include_body)

    def iter_mailbox_batches(
        self,
        *,
        limit: Optional[int] = 500,
        batch_size: int = 100,
        include_body: bool = False,
        unread_only: bool = False,
        offset: int = 0,
        time_range: Optional[str] = None,
    ):
        since, before = imap_since_before_for_time_range(time_range)
        uids = self._search_uids(
            limit=(limit + offset) if limit is not None else 999_999_999,
            since=since,
            before=before,
            unread_only=unread_only,
        )
        uids = uids[offset:] if limit is None else uids[offset : offset + limit]
        for start in range(0, len(uids), batch_size):
            yield self._build_messages(
                uids[start : start + batch_size],
                include_body=include_body,
            )

    def iter_unread_batches_since(
        self,
        checkpoint: str,
        *,
        limit: int = 50,
        batch_size: int = 100,
        include_body: bool = True,
        time_range: Optional[str] = None,
    ):
        checkpoint_dt = datetime.fromisoformat(checkpoint.replace("Z", "+00:00")).astimezone(
            timezone.utc
        )
        time_window = resolve_time_window(time_range)
        since_dt = checkpoint_dt
        if time_window.start_at and time_window.start_at > since_dt:
            since_dt = time_window.start_at
        since = since_dt.strftime("%d-%b-%Y")
        _, before = imap_since_before_for_time_range(time_range)
        uids = self._search_uids(
            limit=limit,
            since=since,
            before=before,
        )
        for start in range(0, len(uids), batch_size):
            yield self._build_messages(uids[start : start + batch_size], include_body=include_body)

    def get_incremental_checkpoint(self) -> Optional[str]:
        return datetime.now(timezone.utc).isoformat()

    def fetch_email_metadata(self, email_id: str) -> EmailMessage:
        raw_message, flags, labels = self._fetch_raw_message(email_id)
        return self._message_to_email(email_id, raw_message, flags, labels)

    def fetch_email_body(self, email_id: str) -> str:
        raw_message, _, _ = self._fetch_raw_message(email_id)
        return self._message_body(message_from_bytes(raw_message))

    def _ensure_folder(self, mailbox: str) -> None:
        client = self._connect()
        status, _ = client.create(mailbox)
        if status not in {"OK", "NO"}:
            raise IMAPFolderError(f"Could not create or verify mailbox '{mailbox}'.")

    def _move_to_mailbox(self, email_ids: list[str], mailbox: str) -> None:
        client = self._connect()
        self._ensure_folder(mailbox)
        uid_csv = ",".join(email_ids)
        if "MOVE" in self._capabilities:
            status, _ = client.uid("MOVE", uid_csv, mailbox)
            if status == "OK":
                return

        copy_result = self._uid_command("copy", uid_csv, mailbox)
        if copy_result is None:
            raise IMAPFolderError(f"Could not copy messages to '{mailbox}'.")
        self._uid_command("store", uid_csv, "+FLAGS.SILENT", "(\\Deleted)")
        expunge_status, _ = client.expunge()
        if expunge_status != "OK":
            raise IMAPFolderError(f"Could not expunge messages after moving to '{mailbox}'.")

    def batch_mark_as_read(
        self,
        email_ids: list[str],
        *,
        dry_run: bool = True,
    ) -> ProviderActionResult:
        if not dry_run and email_ids:
            self._uid_command("store", ",".join(email_ids), "+FLAGS.SILENT", "(\\Seen)")
        return ProviderActionResult(
            provider=self.provider_name,
            action="mark_read",
            email_ids=email_ids,
            dry_run=dry_run,
            executed=not dry_run,
            details="IMAP read state prepared." if dry_run else "IMAP read state executed.",
        )

    def archive_emails(
        self,
        email_ids: list[str],
        *,
        dry_run: bool = True,
    ) -> ProviderActionResult:
        details = f"IMAP archive prepared for {self.archive_mailbox}."
        if not dry_run and email_ids:
            try:
                self._move_to_mailbox(email_ids, self.archive_mailbox)
                details = f"IMAP archive executed via move to {self.archive_mailbox}."
            except IMAPFolderError:
                self.apply_labels(email_ids, ["archived"], dry_run=False)
                details = "IMAP archive fallback executed via labels/folder copies."
        return ProviderActionResult(
            provider=self.provider_name,
            action="archive",
            email_ids=email_ids,
            dry_run=dry_run,
            executed=not dry_run,
            details=details,
        )

    def move_to_trash(
        self,
        email_ids: list[str],
        *,
        explicit_confirmation: bool,
        dry_run: bool = True,
    ) -> ProviderActionResult:
        if not explicit_confirmation:
            return ProviderActionResult(
                provider=self.provider_name,
                action="trash",
                email_ids=email_ids,
                dry_run=dry_run,
                executed=False,
                details="Explicit confirmation required before IMAP trash actions.",
            )
        details = f"IMAP trash prepared for {self.trash_mailbox}."
        if not dry_run and email_ids:
            self._move_to_mailbox(email_ids, self.trash_mailbox)
            details = f"IMAP trash executed via move to {self.trash_mailbox}."
        return ProviderActionResult(
            provider=self.provider_name,
            action="trash",
            email_ids=email_ids,
            dry_run=dry_run,
            executed=not dry_run,
            details=details,
        )

    def apply_labels(
        self,
        email_ids: list[str],
        labels: list[str],
        *,
        dry_run: bool = True,
    ) -> ProviderActionResult:
        details = f"IMAP labels prepared: {', '.join(labels)}"
        if not dry_run and email_ids and labels:
            client = self._connect()
            uid_csv = ",".join(email_ids)
            if "X-GM-EXT-1" in self._capabilities:
                label_payload = "(" + " ".join(f'"{label}"' for label in labels) + ")"
                status, _ = client.uid("STORE", uid_csv, "+X-GM-LABELS", label_payload)
                if status != "OK":
                    raise IMAPTransportError("Could not apply Gmail IMAP labels.")
                details = f"IMAP labels executed via X-GM-LABELS: {', '.join(labels)}"
            else:
                for label in labels:
                    self._ensure_folder(label)
                    self._uid_command("copy", uid_csv, label)
                details = f"IMAP labels executed via folder copies: {', '.join(labels)}"
        return ProviderActionResult(
            provider=self.provider_name,
            action="apply_labels",
            email_ids=email_ids,
            dry_run=dry_run,
            executed=not dry_run,
            details=details,
        )

    def remove_labels(
        self,
        email_ids: list[str],
        labels: list[str],
        *,
        dry_run: bool = True,
    ) -> ProviderActionResult:
        details = f"IMAP label removal prepared: {', '.join(labels)}"
        executed = not dry_run
        if not dry_run and email_ids and labels:
            client = self._connect()
            uid_csv = ",".join(email_ids)
            if "X-GM-EXT-1" in self._capabilities:
                label_payload = "(" + " ".join(f'"{label}"' for label in labels) + ")"
                status, _ = client.uid("STORE", uid_csv, "-X-GM-LABELS", label_payload)
                if status != "OK":
                    raise IMAPTransportError("Could not remove Gmail IMAP labels.")
                details = f"IMAP labels removed via X-GM-LABELS: {', '.join(labels)}"
            else:
                executed = False
                details = (
                    "This IMAP provider does not expose safe label removal through folders. "
                    "InboxAnchor skipped label cleanup."
                )
        return ProviderActionResult(
            provider=self.provider_name,
            action="remove_labels",
            email_ids=email_ids,
            dry_run=dry_run,
            executed=executed,
            details=details,
        )

    @contextmanager
    def connection(self):
        try:
            yield self._connect()
        finally:
            self.close()
