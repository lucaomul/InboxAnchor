from __future__ import annotations

import json
import re
from html import unescape
from typing import Any

TEXT_KEYS = (
    "text",
    "body",
    "body_text",
    "bodytext",
    "plain",
    "plain_text",
    "content",
    "message",
    "description",
    "summary",
    "snippet",
    "html",
    "markdown",
)

SKIP_KEYS = {
    "id",
    "thread_id",
    "email_id",
    "mime_type",
    "content_type",
    "attachments",
    "headers",
    "metadata",
    "labels",
    "timestamp",
    "created_at",
    "updated_at",
}


def strip_html_to_text(value: str) -> str:
    if not value:
        return ""
    cleaned = re.sub(r"(?i)<br\s*/?>", "\n", value)
    cleaned = re.sub(r"(?i)</p\s*>", "\n\n", cleaned)
    cleaned = re.sub(r"<[^>]+>", " ", cleaned)
    return _collapse_text(unescape(cleaned))


def normalize_email_body_text(value: str) -> str:
    text = (value or "").strip()
    if not text:
        return ""

    parsed = _try_parse_json(text)
    if parsed is not None:
        extracted = _extract_text_from_payload(parsed)
        if extracted:
            return extracted

    if _looks_like_html(text):
        return strip_html_to_text(text)

    return _collapse_text(unescape(text))


def _try_parse_json(value: str) -> Any | None:
    candidate = value.strip()
    if not candidate or candidate[0] not in "[{":
        return None
    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        return None


def _extract_text_from_payload(payload: Any) -> str:
    collected: list[str] = []
    _walk_payload(payload, collected, depth=0)
    return _collapse_text("\n\n".join(part for part in collected if part.strip()))


def _walk_payload(payload: Any, collected: list[str], *, depth: int) -> None:
    if depth > 6 or payload is None:
        return
    if isinstance(payload, str):
        normalized = payload.strip()
        if not normalized:
            return
        if _looks_like_html(normalized):
            normalized = strip_html_to_text(normalized)
        else:
            normalized = _collapse_text(unescape(normalized))
        if len(normalized) >= 8:
            collected.append(normalized)
        return
    if isinstance(payload, list):
        for item in payload[:20]:
            _walk_payload(item, collected, depth=depth + 1)
        return
    if isinstance(payload, dict):
        prioritized: list[Any] = []
        fallback: list[str] = []
        for key, value in payload.items():
            key_name = str(key).strip().lower()
            if key_name in SKIP_KEYS:
                continue
            if key_name in TEXT_KEYS:
                prioritized.append(value)
                continue
            if isinstance(value, str):
                normalized = normalize_email_body_text(value)
                if normalized and len(normalized) >= 12:
                    fallback.append(f"{key_name.replace('_', ' ').title()}: {normalized}")
            else:
                prioritized.append(value)
        for item in prioritized:
            _walk_payload(item, collected, depth=depth + 1)
        if not collected and fallback:
            collected.extend(fallback[:8])


def _looks_like_html(value: str) -> bool:
    return bool(re.search(r"<[a-z][\s\S]*>", value, flags=re.IGNORECASE))


def _collapse_text(value: str) -> str:
    text = value.replace("\r", "\n")
    text = re.sub(r"\n{3,}", "\n\n", text)
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.split("\n")]
    return "\n".join(line for line in lines if line).strip()
