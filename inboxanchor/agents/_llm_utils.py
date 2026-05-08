from __future__ import annotations

import json
import re
from typing import Any, Optional


def parse_json_content(content: str) -> Optional[Any]:
    if not content:
        return None

    cleaned = content.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\s*```$", "", cleaned)

    candidates = (
        cleaned,
        _slice_json_fragment(cleaned, "{", "}"),
        _slice_json_fragment(cleaned, "[", "]"),
    )
    for candidate in candidates:
        if not candidate:
            continue
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            continue
    return None


def _slice_json_fragment(value: str, opener: str, closer: str) -> Optional[str]:
    start = value.find(opener)
    end = value.rfind(closer)
    if start == -1 or end == -1 or end < start:
        return None
    return value[start : end + 1]
