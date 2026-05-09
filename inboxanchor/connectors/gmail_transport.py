from __future__ import annotations

# NOTE: This transport requires OAuth credentials. See docs/gmail_setup.md for setup instructions.
import base64
import logging
import re
import time
from datetime import datetime, timezone
from email.message import EmailMessage as MimeEmailMessage
from email.utils import parseaddr, parsedate_to_datetime
from html import unescape
from pathlib import Path
from typing import Iterable, Optional
from urllib.parse import quote

from inboxanchor.connectors.gmail_client import GmailTransport
from inboxanchor.connectors.oauth_flow import get_credentials
from inboxanchor.core.time_windows import gmail_query_with_time_range
from inboxanchor.models import EmailMessage

logger = logging.getLogger(__name__)

GMAIL_MODIFY_SCOPE = "https://www.googleapis.com/auth/gmail.modify"
GMAIL_SEND_SCOPE = "https://www.googleapis.com/auth/gmail.send"
GMAIL_API_BASE_URL = "https://gmail.googleapis.com/gmail/v1"


class GoogleAPITransport(GmailTransport):
    def __init__(
        self,
        credentials_path: str,
        token_path: str,
        *,
        scopes: Optional[Iterable[str]] = None,
        user_id: str = "me",
        service=None,
        session=None,
    ):
        self.credentials_path = str(Path(credentials_path).expanduser())
        self.token_path = str(Path(token_path).expanduser())
        self.scopes = list(scopes or [GMAIL_MODIFY_SCOPE, GMAIL_SEND_SCOPE])
        self.user_id = user_id
        self._service = service
        self._session = session
        self._page_tokens: dict[int, Optional[str]] = {0: None}
        self._label_cache: dict[str, str] = {}
        self._last_history_id: Optional[str] = None

    def _build_session(self):
        if self._session is not None:
            return self._session

        try:
            from google.auth.transport.requests import AuthorizedSession
        except ImportError as error:  # pragma: no cover - optional dependency
            raise ImportError(
                "Google API client dependencies are missing. Install "
                "'google-api-python-client', 'google-auth', and "
                "'google-auth-oauthlib' to enable live Gmail transport."
            ) from error

        creds = get_credentials(self.credentials_path, self.token_path, self.scopes)
        self._session = AuthorizedSession(creds)
        return self._session

    def _build_service(self):
        if self._service is not None:
            return self._service

        try:
            from googleapiclient.discovery import build
        except ImportError as error:  # pragma: no cover - optional dependency
            raise ImportError(
                "Google API client dependencies are missing. Install "
                "'google-api-python-client', 'google-auth', and "
                "'google-auth-oauthlib' to enable live Gmail transport."
            ) from error

        creds = get_credentials(self.credentials_path, self.token_path, self.scopes)
        self._service = build("gmail", "v1", credentials=creds, cache_discovery=False)
        return self._service

    def _execute_legacy(self, request):
        delay = 1.0
        for attempt in range(1, 6):
            try:
                return request.execute()
            except Exception as error:
                status_code = getattr(getattr(error, "resp", None), "status", None)
                retryable = status_code in {429, 500, 502, 503, 504}
                if not retryable or attempt >= 5:
                    raise
                logger.warning(
                    "Retrying Gmail API call after transient failure",
                    extra={
                        "attempt": attempt,
                        "status_code": status_code,
                        "delay_seconds": delay,
                    },
                )
                time.sleep(delay)
                delay = min(delay * 2, 16.0)

    def _gmail_resource_url(self, resource: str) -> str:
        user_id = quote(self.user_id, safe="")
        return f"{GMAIL_API_BASE_URL}/users/{user_id}/{resource.lstrip('/')}"

    def _request_json(
        self,
        method: str,
        resource: str,
        *,
        params: Optional[dict] = None,
        json_body: Optional[dict] = None,
    ) -> dict:
        session = self._build_session()
        url = self._gmail_resource_url(resource)
        delay = 1.0

        for attempt in range(1, 6):
            try:
                response = session.request(
                    method,
                    url,
                    params=params,
                    json=json_body,
                    timeout=30,
                )
            except Exception:
                if attempt >= 5:
                    raise
                logger.warning(
                    "Retrying Gmail API call after transport failure",
                    extra={
                        "attempt": attempt,
                        "delay_seconds": delay,
                        "resource": resource,
                    },
                )
                time.sleep(delay)
                delay = min(delay * 2, 16.0)
                continue

            if response.status_code in {429, 500, 502, 503, 504} and attempt < 5:
                logger.warning(
                    "Retrying Gmail API call after transient HTTP failure",
                    extra={
                        "attempt": attempt,
                        "status_code": response.status_code,
                        "delay_seconds": delay,
                        "resource": resource,
                    },
                )
                time.sleep(delay)
                delay = min(delay * 2, 16.0)
                continue

            response.raise_for_status()
            if not response.content:
                return {}
            return response.json()

        return {}

    def _chunk_email_ids(self, email_ids: list[str], *, chunk_size: int = 1000):
        for start in range(0, len(email_ids), chunk_size):
            yield email_ids[start : start + chunk_size]

    def _list_message_refs(
        self,
        *,
        limit: int,
        page_token: Optional[str] = None,
        q: Optional[str] = None,
    ) -> dict:
        if self._service is not None:
            service = self._build_service()
            request = service.users().messages().list(
                userId=self.user_id,
                q=q,
                maxResults=min(limit, 500),
                pageToken=page_token,
                includeSpamTrash=False,
            )
            return self._execute_legacy(request)

        return self._request_json(
            "GET",
            "messages",
            params={
                "q": q,
                "maxResults": min(limit, 500),
                "pageToken": page_token,
                "includeSpamTrash": "false",
            },
        )

    def _fetch_message_resource(self, email_id: str, *, include_body: bool = True) -> dict:
        format_name = "full" if include_body else "metadata"
        if self._service is not None:
            service = self._build_service()
            params = {
                "userId": self.user_id,
                "id": email_id,
                "format": format_name,
            }
            if not include_body:
                params["metadataHeaders"] = ["From", "To", "Subject", "Date", "Message-ID"]
            request = service.users().messages().get(**params)
            return self._execute_legacy(request)

        return self._request_json(
            "GET",
            f"messages/{quote(email_id, safe='')}",
            params={
                "format": format_name,
                **(
                    {
                        "metadataHeaders": [
                            "From",
                            "To",
                            "Subject",
                            "Date",
                            "Message-ID",
                        ]
                    }
                    if not include_body
                    else {}
                ),
            },
        )

    def _decode_body_data(self, data: str) -> str:
        if not data:
            return ""
        padded = data + "=" * (-len(data) % 4)
        decoded = base64.urlsafe_b64decode(padded.encode("utf-8"))
        return decoded.decode("utf-8", errors="replace")

    def _strip_html(self, value: str) -> str:
        return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", unescape(value))).strip()

    def _iter_parts(self, payload: dict):
        for part in payload.get("parts", []) or []:
            yield part
            yield from self._iter_parts(part)

    def _extract_best_body(self, payload: dict) -> str:
        mime_type = payload.get("mimeType", "")
        body_data = payload.get("body", {}).get("data")
        if mime_type == "text/plain" and body_data:
            return self._decode_body_data(body_data).strip()

        text_plain = None
        text_html = None
        for part in self._iter_parts(payload):
            part_data = part.get("body", {}).get("data")
            if not part_data:
                continue
            if part.get("mimeType") == "text/plain" and text_plain is None:
                text_plain = self._decode_body_data(part_data).strip()
            elif part.get("mimeType") == "text/html" and text_html is None:
                text_html = self._strip_html(self._decode_body_data(part_data))
        return text_plain or text_html or ""

    def _has_attachments(self, payload: dict) -> bool:
        if payload.get("filename"):
            return True
        return any(part.get("filename") for part in self._iter_parts(payload))

    def _extract_headers(self, payload: dict) -> dict[str, str]:
        headers = {}
        for item in payload.get("headers", []) or []:
            name = item.get("name", "").lower()
            value = item.get("value", "")
            if name:
                headers[name] = value
        return headers

    def _parse_received_at(self, raw_value: str) -> datetime:
        if not raw_value:
            return datetime.now(timezone.utc)
        try:
            parsed = parsedate_to_datetime(raw_value)
        except (TypeError, ValueError):
            return datetime.now(timezone.utc)
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)

    def _message_to_email(self, message: dict, *, include_body: bool = True) -> EmailMessage:
        payload = message.get("payload", {})
        headers = self._extract_headers(payload)
        body = self._extract_best_body(payload) if include_body else ""
        labels = message.get("labelIds", []) or []
        snippet = message.get("snippet", "")
        return EmailMessage(
            id=message["id"],
            thread_id=message.get("threadId") or message["id"],
            sender=headers.get("from", ""),
            subject=headers.get("subject", ""),
            snippet=snippet,
            body_preview=(body or snippet)[:500],
            body_full=body if include_body else "",
            received_at=self._parse_received_at(headers.get("date", "")),
            labels=labels,
            has_attachments=self._has_attachments(payload),
            unread="UNREAD" in labels,
        )

    def _prime_page_token(
        self,
        *,
        limit: int,
        offset: int,
        time_range: Optional[str] = None,
    ) -> Optional[str]:
        current_offset = 0
        token = None
        query = gmail_query_with_time_range("is:unread", time_range)
        while current_offset < offset:
            token = self._page_tokens.get(current_offset)
            if token is None and current_offset != 0:
                return None
            response = self._list_message_refs(limit=limit, page_token=token, q=query)
            refs = response.get("messages", []) or []
            if not refs:
                return None
            current_offset += len(refs)
            next_token = response.get("nextPageToken")
            self._page_tokens[current_offset] = next_token
            token = next_token
        return self._page_tokens.get(offset)

    def list_unread(
        self,
        limit: int,
        *,
        time_range: Optional[str] = None,
    ) -> list[EmailMessage]:
        emails: list[EmailMessage] = []
        fetched = 0
        self._page_tokens = {0: None}
        while fetched < limit:
            page = self.list_unread_page(
                min(100, limit - fetched),
                fetched,
                time_range=time_range,
            )
            if not page:
                break
            emails.extend(page)
            fetched += len(page)
        return emails

    def list_unread_page(
        self,
        limit: int,
        offset: int,
        *,
        time_range: Optional[str] = None,
    ) -> list[EmailMessage]:
        page_token = self._page_tokens.get(offset)
        if offset and offset not in self._page_tokens:
            page_token = self._prime_page_token(
                limit=limit,
                offset=offset,
                time_range=time_range,
            )
        elif offset and page_token is None:
            return []
        response = self._list_message_refs(
            limit=limit,
            page_token=page_token,
            q=gmail_query_with_time_range("is:unread", time_range),
        )
        refs = response.get("messages", []) or []
        self._page_tokens[offset + len(refs)] = response.get("nextPageToken")
        return [
            self._message_to_email(self._fetch_message_resource(item["id"], include_body=True))
            for item in refs
        ]

    def get_message(self, email_id: str, include_body: bool = True) -> EmailMessage:
        return self._message_to_email(
            self._fetch_message_resource(email_id, include_body=include_body),
            include_body=include_body,
        )

    def get_body(self, email_id: str) -> str:
        message = self._fetch_message_resource(email_id, include_body=True)
        return self._extract_best_body(message.get("payload", {}))

    def iter_mailbox_batches(
        self,
        *,
        limit: int = 500,
        batch_size: int = 100,
        include_body: bool = False,
        unread_only: bool = False,
        offset: int = 0,
        time_range: Optional[str] = None,
    ):
        remaining = limit
        page_token = None
        skipped = 0
        query = gmail_query_with_time_range("is:unread" if unread_only else None, time_range)
        page_size = min(max(batch_size, 1), 500)

        while skipped < offset:
            response = self._list_message_refs(
                limit=min(page_size, offset - skipped),
                page_token=page_token,
                q=query,
            )
            refs = response.get("messages", []) or []
            if not refs:
                return
            skipped += len(refs)
            page_token = response.get("nextPageToken")
            if not page_token and skipped < offset:
                return

        while remaining > 0:
            page_limit = min(page_size, remaining)
            response = self._list_message_refs(limit=page_limit, page_token=page_token, q=query)
            refs = response.get("messages", []) or []
            if not refs:
                break
            yield [
                self.get_message(ref["id"], include_body=include_body)
                for ref in refs
            ]
            remaining -= len(refs)
            page_token = response.get("nextPageToken")
            if not page_token:
                break

    def _batch_modify(
        self,
        email_ids: list[str],
        *,
        add_label_ids: Optional[list[str]] = None,
        remove_label_ids: Optional[list[str]] = None,
    ) -> None:
        if not email_ids:
            return

        body_base = {}
        if add_label_ids:
            body_base["addLabelIds"] = add_label_ids
        if remove_label_ids:
            body_base["removeLabelIds"] = remove_label_ids
        if not body_base:
            return

        for chunk in self._chunk_email_ids(email_ids):
            body = {"ids": chunk, **body_base}
            if self._service is not None:
                service = self._build_service()
                request = service.users().messages().batchModify(
                    userId=self.user_id,
                    body=body,
                )
                self._execute_legacy(request)
            else:
                self._request_json(
                    "POST",
                    "messages/batchModify",
                    json_body=body,
                )

    def mark_read(self, email_ids: list[str]) -> None:
        self._batch_modify(email_ids, remove_label_ids=["UNREAD"])

    def archive(self, email_ids: list[str]) -> None:
        self._batch_modify(email_ids, remove_label_ids=["INBOX"])

    def trash(self, email_ids: list[str]) -> None:
        for email_id in email_ids:
            if self._service is not None:
                service = self._build_service()
                request = service.users().messages().trash(userId=self.user_id, id=email_id)
                self._execute_legacy(request)
            else:
                self._request_json(
                    "POST",
                    f"messages/{quote(email_id, safe='')}/trash",
                )

    def _label_name_to_id(self, label_name: str) -> str:
        if label_name in self._label_cache:
            return self._label_cache[label_name]

        if self._service is not None:
            service = self._build_service()
            labels = self._execute_legacy(service.users().labels().list(userId=self.user_id)).get(
                "labels",
                [],
            )
        else:
            labels = self._request_json("GET", "labels").get("labels", [])
        for item in labels:
            self._label_cache[item["name"]] = item["id"]

        if label_name in self._label_cache:
            return self._label_cache[label_name]

        if self._service is not None:
            service = self._build_service()
            created = self._execute_legacy(
                service.users().labels().create(
                    userId=self.user_id,
                    body={
                        "name": label_name,
                        "messageListVisibility": "show",
                        "labelListVisibility": "labelShow",
                    },
                )
            )
        else:
            created = self._request_json(
                "POST",
                "labels",
                json_body={
                    "name": label_name,
                    "messageListVisibility": "show",
                    "labelListVisibility": "labelShow",
                },
            )
        self._label_cache[label_name] = created["id"]
        return created["id"]

    def apply_labels(self, email_ids: list[str], labels: list[str]) -> None:
        if not labels:
            return
        label_ids = [self._label_name_to_id(label) for label in labels]
        self._batch_modify(email_ids, add_label_ids=label_ids)

    def send_reply(
        self,
        email_id: str,
        body: str,
        *,
        from_address: Optional[str] = None,
    ) -> dict:
        message = self._fetch_message_resource(email_id, include_body=False)
        payload = message.get("payload", {})
        headers = self._extract_headers(payload)
        target_address = parseaddr(headers.get("reply-to") or headers.get("from", ""))[1]
        if not target_address:
            raise ValueError("InboxAnchor could not determine who this reply should go to.")

        original_subject = headers.get("subject", "").strip()
        reply_subject = (
            original_subject
            if original_subject.lower().startswith("re:")
            else f"Re: {original_subject}"
        )
        mime = MimeEmailMessage()
        mime["To"] = target_address
        mime["Subject"] = reply_subject
        if from_address:
            mime["From"] = from_address

        message_id = headers.get("message-id", "").strip()
        references = headers.get("references", "").strip()
        if message_id:
            mime["In-Reply-To"] = message_id
            reply_references = " ".join(
                candidate for candidate in (references, message_id) if candidate
            ).strip()
            if reply_references:
                mime["References"] = reply_references

        mime.set_content(body.strip())
        raw_message = base64.urlsafe_b64encode(mime.as_bytes()).decode("utf-8")
        request_body = {"raw": raw_message}
        if message.get("threadId"):
            request_body["threadId"] = message["threadId"]

        if self._service is not None:
            service = self._build_service()
            request = service.users().messages().send(
                userId=self.user_id,
                body=request_body,
            )
            self._execute_legacy(request)
        else:
            self._request_json("POST", "messages/send", json_body=request_body)

        return {
            "email_id": email_id,
            "thread_id": message.get("threadId"),
            "to_address": target_address,
            "subject": reply_subject,
        }

    def list_changed_message_ids(
        self,
        start_history_id: str,
        *,
        max_results: int = 500,
    ) -> tuple[list[str], Optional[str]]:
        service = self._build_service()
        collected: list[str] = []
        seen: set[str] = set()
        page_token = None
        last_history_id = start_history_id

        while len(collected) < max_results:
            if self._service is not None:
                service = self._build_service()
                request = service.users().history().list(
                    userId=self.user_id,
                    startHistoryId=start_history_id,
                    pageToken=page_token,
                    maxResults=min(max_results, 500),
                    historyTypes=["messageAdded", "labelAdded", "labelRemoved"],
                )
                response = self._execute_legacy(request)
            else:
                response = self._request_json(
                    "GET",
                    "history",
                    params={
                        "startHistoryId": start_history_id,
                        "pageToken": page_token,
                        "maxResults": min(max_results, 500),
                        "historyTypes": [
                            "messageAdded",
                            "labelAdded",
                            "labelRemoved",
                        ],
                    },
                )
            last_history_id = response.get("historyId", last_history_id)
            for record in response.get("history", []) or []:
                for bucket in ("messagesAdded", "messages", "labelsAdded", "labelsRemoved"):
                    for item in record.get(bucket, []) or []:
                        message = item.get("message", item)
                        message_id = message.get("id")
                        if message_id and message_id not in seen:
                            seen.add(message_id)
                            collected.append(message_id)
                            if len(collected) >= max_results:
                                break
                    if len(collected) >= max_results:
                        break
                if len(collected) >= max_results:
                    break
            page_token = response.get("nextPageToken")
            if not page_token:
                break

        self._last_history_id = last_history_id
        return collected, last_history_id

    def iter_unread_batches_since(
        self,
        checkpoint: str,
        *,
        limit: int = 50,
        batch_size: int = 100,
        include_body: bool = True,
    ):
        del include_body
        message_ids, _ = self.list_changed_message_ids(checkpoint, max_results=limit)
        batch: list[EmailMessage] = []
        for message_id in message_ids:
            email = self.get_message(message_id)
            if not email.unread:
                continue
            batch.append(email)
            if len(batch) >= batch_size:
                yield batch
                batch = []
        if batch:
            yield batch

    def get_incremental_checkpoint(self) -> Optional[str]:
        if self._last_history_id:
            return self._last_history_id
        if self._service is not None:
            service = self._build_service()
            profile = self._execute_legacy(service.users().getProfile(userId=self.user_id))
        else:
            profile = self._request_json("GET", "profile")
        self._last_history_id = profile.get("historyId")
        return self._last_history_id
