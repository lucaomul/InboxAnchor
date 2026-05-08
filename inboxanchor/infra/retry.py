from __future__ import annotations

import logging
import random
import time
from typing import Callable, Optional, TypeVar

T = TypeVar("T")

logger = logging.getLogger(__name__)


def _extract_status_code(error: Exception) -> Optional[int]:
    for attribute in ("status_code", "code"):
        value = getattr(error, attribute, None)
        if isinstance(value, int):
            return value

    response = getattr(error, "response", None)
    if response is not None:
        status_code = getattr(response, "status_code", None)
        if isinstance(status_code, int):
            return status_code

    resp = getattr(error, "resp", None)
    if resp is not None:
        status = getattr(resp, "status", None)
        if isinstance(status, int):
            return status

    return None


def _is_retryable(error: Exception) -> bool:
    status_code = _extract_status_code(error)
    if status_code in {401, 403, 400, 404}:
        return False
    if status_code == 429 or (status_code is not None and 500 <= status_code <= 599):
        return True

    if isinstance(error, TimeoutError):
        return True

    name = error.__class__.__name__.lower()
    if any(token in name for token in ("timeout", "connection", "ratelimit", "temporar")):
        return True

    message = str(error).lower()
    if "429" in message or "rate limit" in message:
        return True
    if any(token in message for token in ("timed out", "timeout", "connection reset")):
        return True
    if any(token in message for token in ("502", "503", "504", "server error")):
        return True
    return False


def with_retry(
    fn: Callable[[], T],
    *,
    max_attempts: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 30.0,
    jitter: bool = True,
) -> T:
    attempt = 1
    while True:
        try:
            return fn()
        except Exception as error:
            if attempt >= max_attempts or not _is_retryable(error):
                raise

            delay = min(max_delay, base_delay * (2 ** (attempt - 1)))
            if jitter:
                delay *= random.uniform(0.8, 1.2)
            logger.warning(
                "Retrying provider call after failure",
                extra={
                    "attempt": attempt,
                    "delay_seconds": round(delay, 3),
                    "error_type": error.__class__.__name__,
                },
            )
            time.sleep(delay)
            attempt += 1
