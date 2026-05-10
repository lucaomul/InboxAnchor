from __future__ import annotations

# NOTE: This transport requires OAuth credentials. See docs/gmail_setup.md for setup instructions.
import base64
import json
import logging
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from email.message import EmailMessage as MimeEmailMessage
from email.utils import parseaddr, parsedate_to_datetime
from html import unescape
from pathlib import Path
from typing import Iterable, Optional
from urllib.parse import quote

from inboxanchor.config.settings import SETTINGS
from inboxanchor.connectors.gmail_client import GmailTransport
from inboxanchor.connectors.oauth_flow import get_credentials
from inboxanchor.core.time_windows import gmail_query_with_time_range, in_time_window
from inboxanchor.infra.text_normalizer import normalize_email_body_text
from inboxanchor.mail_intelligence import dedupe_labels
from inboxanchor.models import EmailMessage

logger = logging.getLogger(__name__)

GMAIL_MODIFY_SCOPE = "https://www.googleapis.com/auth/gmail.modify"
GMAIL_SEND_SCOPE = "https://www.googleapis.com/auth/gmail.send"
GMAIL_SETTINGS_BASIC_SCOPE = "https://www.googleapis.com/auth/gmail.settings.basic"
GMAIL_API_BASE_URL = "https://gmail.googleapis.com/gmail/v1"
RETRYABLE_GMAIL_403_REASONS = {
    "backendError",
    "internalError",
    "quotaExceeded",
    "rateLimitExceeded",
    "userRateLimitExceeded",
}
RETRYABLE_FETCH_STATUS_CODES = {403, 429, 500, 502, 503, 504}


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
        self.scopes = list(
            scopes or [GMAIL_MODIFY_SCOPE, GMAIL_SEND_SCOPE, GMAIL_SETTINGS_BASIC_SCOPE]
        )
        self.user_id = user_id
        self._service = service
        self._session = session
        self._page_tokens: dict[int, Optional[str]] = {0: None}
        self._label_cache: dict[str, str] = {}
        self._last_history_id: Optional[str] = None
        self._configured_fetch_workers = max(1, SETTINGS.gmail_fetch_workers)
        self._fetch_workers = self._configured_fetch_workers
        self._min_fetch_workers = 2 if self._configured_fetch_workers > 2 else 1
        self._fetch_workers_lock = threading.Lock()
        self._thread_local = threading.local()

    def _build_session(self):
        if self._session is not None:
            return self._session
        thread_session = getattr(self._thread_local, "session", None)
        if thread_session is not None:
            return thread_session

        try:
            from google.auth.transport.requests import AuthorizedSession
        except ImportError as error:  # pragma: no cover - optional dependency
            raise ImportError(
                "Google API client dependencies are missing. Install "
                "'google-api-python-client', 'google-auth', and "
                "'google-auth-oauthlib' to enable live Gmail transport."
            ) from error

        creds = get_credentials(self.credentials_path, self.token_path, self.scopes)
        thread_session = AuthorizedSession(creds)
        self._thread_local.session = thread_session
        return thread_session

    def _build_service(self):
        if self._service is not None:
            return self._service
        thread_service = getattr(self._thread_local, "service", None)
        if thread_service is not None:
            return thread_service

        try:
            from googleapiclient.discovery import build
        except ImportError as error:  # pragma: no cover - optional dependency
            raise ImportError(
                "Google API client dependencies are missing. Install "
                "'google-api-python-client', 'google-auth', and "
                "'google-auth-oauthlib' to enable live Gmail transport."
            ) from error

        creds = get_credentials(self.credentials_path, self.token_path, self.scopes)
        thread_service = build("gmail", "v1", credentials=creds, cache_discovery=False)
        self._thread_local.service = thread_service
        return thread_service

    @staticmethod
    def _error_status_code(exc: Exception) -> Optional[int]:
        status_code = getattr(getattr(exc, "response", None), "status_code", None)
        if status_code is not None:
            return int(status_code)
        legacy_status = getattr(getattr(exc, "resp", None), "status", None)
        if legacy_status is not None:
            return int(legacy_status)
        return None

    @staticmethod
    def _extract_error_reasons(payload: object) -> set[str]:
        if not isinstance(payload, dict):
            return set()
        error = payload.get("error")
        if not isinstance(error, dict):
            return set()
        return {
            str(item.get("reason"))
            for item in error.get("errors", []) or []
            if isinstance(item, dict) and item.get("reason")
        }

    def _legacy_error_has_retryable_reason(self, error: Exception) -> bool:
        content = getattr(error, "content", None)
        if not content:
            return False
        try:
            payload = json.loads(content.decode("utf-8", errors="replace"))
        except Exception:
            return False
        reasons = self._extract_error_reasons(payload)
        return any(reason in RETRYABLE_GMAIL_403_REASONS for reason in reasons)

    def _response_has_retryable_403(self, response) -> bool:
        try:
            payload = response.json()
        except Exception:
            return False
        reasons = self._extract_error_reasons(payload)
        return any(reason in RETRYABLE_GMAIL_403_REASONS for reason in reasons)

    def _execute_legacy(self, request):
        delay = 1.0
        for attempt in range(1, 6):
            try:
                return request.execute()
            except Exception as error:
                status_code = getattr(getattr(error, "resp", None), "status", None)
                retryable = status_code in {429, 500, 502, 503, 504} or (
                    status_code == 403 and self._legacy_error_has_retryable_reason(error)
                )
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
        message_fetch_resource = method.upper() == "GET" and resource.startswith("messages/")
        max_attempts = 3 if message_fetch_resource else 5
        max_delay = 4.0 if message_fetch_resource else 16.0
        delay = 1.0

        for attempt in range(1, max_attempts + 1):
            try:
                response = session.request(
                    method,
                    url,
                    params=params,
                    json=json_body,
                    timeout=30,
                )
            except Exception:
                if attempt >= max_attempts:
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
                delay = min(delay * 2, max_delay)
                continue

            retryable_http = response.status_code in {429, 500, 502, 503, 504} or (
                response.status_code == 403 and self._response_has_retryable_403(response)
            )
            if retryable_http and attempt < max_attempts:
                if message_fetch_resource:
                    self._reduce_fetch_workers(
                        status_code=response.status_code,
                        reason="transient Gmail message fetch pressure",
                    )
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
                delay = min(delay * 2, max_delay)
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
            body = normalize_email_body_text(self._decode_body_data(body_data).strip())
            max_chars = max(0, SETTINGS.gmail_body_max_chars)
            return body[:max_chars] if max_chars else body

        text_plain = None
        text_html = None
        for part in self._iter_parts(payload):
            part_data = part.get("body", {}).get("data")
            if not part_data:
                continue
            if part.get("mimeType") == "text/plain" and text_plain is None:
                text_plain = normalize_email_body_text(self._decode_body_data(part_data).strip())
            elif part.get("mimeType") == "text/html" and text_html is None:
                text_html = normalize_email_body_text(
                    self._strip_html(self._decode_body_data(part_data))
                )
        body = normalize_email_body_text(text_plain or text_html or "")
        max_chars = max(0, SETTINGS.gmail_body_max_chars)
        return body[:max_chars] if max_chars else body

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
            body_fetched=include_body,
            body_stored=bool(body) if include_body else False,
            received_at=self._parse_received_at(headers.get("date", "")),
            labels=labels,
            has_attachments=self._has_attachments(payload),
            unread="UNREAD" in labels,
        )

    @staticmethod
    def _is_retryable_fetch_status(status_code: Optional[int]) -> bool:
        return status_code in RETRYABLE_FETCH_STATUS_CODES

    def _reduce_fetch_workers(self, *, status_code: Optional[int], reason: str) -> None:
        with self._fetch_workers_lock:
            if self._fetch_workers <= self._min_fetch_workers:
                return
            if status_code in {403, 429}:
                reduced_workers = max(self._min_fetch_workers, self._fetch_workers - 1)
            else:
                reduced_workers = max(self._min_fetch_workers, self._fetch_workers // 2)
            if reduced_workers >= self._fetch_workers:
                return
            logger.warning(
                "Reducing Gmail fetch worker count from %s to %s after %s (status=%s).",
                self._fetch_workers,
                reduced_workers,
                reason,
                status_code,
            )
            self._fetch_workers = reduced_workers

    def _restore_fetch_workers(self) -> None:
        with self._fetch_workers_lock:
            if self._fetch_workers < self._configured_fetch_workers:
                self._fetch_workers = min(self._configured_fetch_workers, self._fetch_workers + 1)

    def _recover_failed_parallel_fetches(
        self,
        failures: list[tuple[str, Exception]],
        *,
        include_body: bool,
    ) -> dict[str, EmailMessage]:
        recovered: dict[str, EmailMessage] = {}
        retryable_failures = 0

        for email_id, original_exc in failures:
            retry_exc: Exception = original_exc
            status_code = self._error_status_code(original_exc)
            retryable = self._is_retryable_fetch_status(status_code)
            if retryable:
                retryable_failures += 1

            max_attempts = 3 if retryable else 1
            for attempt in range(1, max_attempts + 1):
                if attempt > 1:
                    time.sleep(min(0.5 * attempt, 2.0))
                try:
                    resource = self._fetch_message_resource(
                        email_id,
                        include_body=include_body,
                    )
                    recovered[email_id] = self._message_to_email(
                        resource,
                        include_body=include_body,
                    )
                    break
                except Exception as exc:
                    retry_exc = exc
                    status_code = self._error_status_code(exc)
                    retryable = self._is_retryable_fetch_status(status_code)
                    if not retryable or status_code == 404:
                        break
            else:
                status_code = self._error_status_code(retry_exc)

            if email_id in recovered:
                continue

            logger.warning(
                "Failed to fetch Gmail message %s after serial recovery "
                "(status=%s, type=%s): %s",
                email_id,
                status_code,
                type(retry_exc).__name__,
                retry_exc,
            )

        if retryable_failures:
            self._reduce_fetch_workers(
                status_code=429,
                reason=f"{retryable_failures} retryable message fetch failures",
            )
        else:
            self._restore_fetch_workers()

        return recovered

    def _fetch_messages_parallel(
        self,
        refs: list[dict],
        *,
        include_body: bool = True,
        max_workers: int = 10,
    ) -> list[EmailMessage]:
        """
        Fetch multiple messages in parallel while preserving the input order.
        Failed individual fetches are logged and skipped.
        """
        if not refs:
            return []
        results: dict[str, EmailMessage] = {}
        failures: list[tuple[str, Exception]] = []
        worker_count = max(1, min(max_workers, len(refs)))
        with ThreadPoolExecutor(max_workers=worker_count) as executor:
            futures = {
                executor.submit(
                    self._fetch_message_resource,
                    item["id"],
                    include_body=include_body,
                ): item["id"]
                for item in refs
            }
            for future in as_completed(futures):
                email_id = futures[future]
                try:
                    resource = future.result()
                    results[email_id] = self._message_to_email(
                        resource,
                        include_body=include_body,
                    )
                except Exception as exc:
                    failures.append((email_id, exc))
        if failures:
            results.update(
                self._recover_failed_parallel_fetches(
                    failures,
                    include_body=include_body,
                )
            )
        else:
            self._restore_fetch_workers()
        return [results[item["id"]] for item in refs if item["id"] in results]

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
        include_body: bool = True,
        time_range: Optional[str] = None,
    ) -> list[EmailMessage]:
        emails: list[EmailMessage] = []
        fetched = 0
        self._page_tokens = {0: None}
        page_size = 100 if include_body else 500
        while fetched < limit:
            page = self.list_unread_page(
                min(page_size, limit - fetched),
                fetched,
                include_body=include_body,
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
        include_body: bool = True,
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
        return self._fetch_messages_parallel(
            refs,
            include_body=include_body,
            max_workers=self._fetch_workers,
        )

    def get_message(self, email_id: str, include_body: bool = True) -> EmailMessage:
        return self._message_to_email(
            self._fetch_message_resource(email_id, include_body=include_body),
            include_body=include_body,
        )

    def get_body(self, email_id: str) -> str:
        message = self._fetch_message_resource(email_id, include_body=True)
        return normalize_email_body_text(self._extract_best_body(message.get("payload", {})))

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

        while remaining is None or remaining > 0:
            page_limit = page_size if remaining is None else min(page_size, remaining)
            response = self._list_message_refs(limit=page_limit, page_token=page_token, q=query)
            refs = response.get("messages", []) or []
            if not refs:
                break
            batch = self._fetch_messages_parallel(
                refs,
                include_body=include_body,
                max_workers=self._fetch_workers,
            )
            if batch:
                yield batch
            if remaining is not None:
                remaining -= len(refs)
            page_token = response.get("nextPageToken")
            if not page_token:
                break

    def iter_all_unread(
        self,
        *,
        batch_size: int = 500,
        include_body: bool = True,
        max_workers: Optional[int] = None,
        time_range: Optional[str] = None,
    ):
        """
        Stream all unread Gmail messages with nextPageToken pagination.
        """
        page_token = None
        query = gmail_query_with_time_range("is:unread", time_range)
        page_size = min(max(batch_size, 1), SETTINGS.gmail_batch_size, 500)
        worker_count = max_workers or self._fetch_workers

        while True:
            response = self._list_message_refs(
                limit=page_size,
                page_token=page_token,
                q=query,
            )
            refs = response.get("messages", []) or []
            if not refs:
                break
            batch = self._fetch_messages_parallel(
                refs,
                include_body=include_body,
                max_workers=worker_count,
            )
            if batch:
                yield batch
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

        self._refresh_label_cache()
        if label_name in self._label_cache:
            return self._label_cache[label_name]

        try:
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
        except Exception as exc:
            if self._is_label_conflict_error(exc):
                self._refresh_label_cache()
                existing_id = self._label_cache.get(label_name)
                if existing_id:
                    return existing_id
            raise
        self._label_cache[label_name] = created["id"]
        return created["id"]

    def _refresh_label_cache(self) -> None:
        if self._service is not None:
            service = self._build_service()
            labels = self._execute_legacy(service.users().labels().list(userId=self.user_id)).get(
                "labels",
                [],
            )
        else:
            labels = self._request_json("GET", "labels").get("labels", [])
        self._label_cache.clear()
        for item in labels:
            self._label_cache[item["name"]] = item["id"]

    def _existing_label_id(self, label_name: str) -> Optional[str]:
        normalized = label_name.strip()
        if not normalized:
            return None
        if normalized not in self._label_cache:
            self._refresh_label_cache()
        return self._label_cache.get(normalized)

    def list_labels(self) -> list[str]:
        self._refresh_label_cache()
        return sorted(self._label_cache.keys())

    @staticmethod
    def _is_missing_label_error(exc: Exception) -> bool:
        status_code = getattr(getattr(exc, "response", None), "status_code", None)
        if status_code == 404:
            return True
        legacy_status = getattr(getattr(exc, "resp", None), "status", None)
        if legacy_status == 404:
            return True
        return "404" in str(exc)

    @staticmethod
    def _is_label_conflict_error(exc: Exception) -> bool:
        status_code = getattr(getattr(exc, "response", None), "status_code", None)
        if status_code == 409:
            return True
        legacy_status = getattr(getattr(exc, "resp", None), "status", None)
        if legacy_status == 409:
            return True
        lowered = str(exc).lower()
        return "409" in lowered

    def apply_labels(self, email_ids: list[str], labels: list[str]) -> None:
        if not labels:
            return
        label_ids = [self._label_name_to_id(label) for label in labels]
        self._batch_modify(email_ids, add_label_ids=label_ids)

    def remove_labels(self, email_ids: list[str], labels: list[str]) -> None:
        if not labels:
            return
        label_ids = [self._label_name_to_id(label) for label in labels]
        self._batch_modify(email_ids, remove_label_ids=label_ids)

    def _delete_label(self, label_id: str) -> None:
        if self._service is not None:
            service = self._build_service()
            self._execute_legacy(
                service.users().labels().delete(
                    userId=self.user_id,
                    id=label_id,
                )
            )
            return
        self._request_json(
            "DELETE",
            f"labels/{quote(label_id, safe='')}",
        )

    def delete_labels(self, labels: list[str]) -> None:
        if not labels:
            return
        deduped = dedupe_labels(labels)
        if not self._label_cache:
            self._refresh_label_cache()
        label_ids = {
            label_name.strip(): self._label_cache.get(label_name.strip())
            for label_name in deduped
            if label_name.strip()
        }
        for normalized, label_id in label_ids.items():
            if not label_id:
                continue
            try:
                self._delete_label(label_id)
            except Exception as exc:
                if self._is_missing_label_error(exc):
                    self._label_cache.pop(normalized, None)
                    continue
                raise
            self._label_cache.pop(normalized, None)

    def _list_filters(self) -> list[dict]:
        if self._service is not None:
            service = self._build_service()
            return self._execute_legacy(
                service.users().settings().filters().list(userId=self.user_id)
            ).get("filter", [])
        return self._request_json("GET", "settings/filters").get("filter", [])

    def _delete_filter(self, filter_id: str) -> None:
        if self._service is not None:
            service = self._build_service()
            self._execute_legacy(
                service.users().settings().filters().delete(
                    userId=self.user_id,
                    id=filter_id,
                )
            )
            return
        self._request_json(
            "DELETE",
            f"settings/filters/{quote(filter_id, safe='')}",
        )

    def ensure_alias_routing(self, alias_address: str, *, label_name: str) -> None:
        alias_address = alias_address.strip().lower()
        if not alias_address:
            raise ValueError("Alias address is required to configure Gmail routing.")

        label_id = self._label_name_to_id(label_name)
        existing = self._list_filters()
        for item in existing:
            criteria = item.get("criteria", {}) or {}
            if (criteria.get("to") or "").strip().lower() == alias_address:
                return

        body = {
            "criteria": {"to": alias_address},
            "action": {
                "addLabelIds": [label_id],
                "removeLabelIds": ["INBOX"],
            },
        }
        if self._service is not None:
            service = self._build_service()
            self._execute_legacy(
                service.users().settings().filters().create(
                    userId=self.user_id,
                    body=body,
                )
            )
            return
        self._request_json(
            "POST",
            "settings/filters",
            json_body=body,
        )

    def remove_alias_routing(self, alias_address: str) -> None:
        alias_address = alias_address.strip().lower()
        if not alias_address:
            return
        for item in self._list_filters():
            criteria = item.get("criteria", {}) or {}
            if (criteria.get("to") or "").strip().lower() == alias_address:
                filter_id = str(item.get("id", "")).strip()
                if filter_id:
                    self._delete_filter(filter_id)

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
        time_range: Optional[str] = None,
    ):
        message_ids, _ = self.list_changed_message_ids(checkpoint, max_results=limit)
        for start in range(0, len(message_ids), batch_size):
            refs = [{"id": message_id} for message_id in message_ids[start : start + batch_size]]
            batch = self._fetch_messages_parallel(
                refs,
                include_body=include_body,
                max_workers=self._fetch_workers,
            )
            batch = [
                email
                for email in batch
                if email.unread
                and (not time_range or in_time_window(email.received_at, time_range))
            ]
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
