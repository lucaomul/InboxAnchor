from inboxanchor.infra.retry import with_retry


class RateLimitError(Exception):
    status_code = 429


class AuthError(Exception):
    status_code = 401


def test_with_retry_retries_transient_failures(monkeypatch):
    attempts = {"count": 0}
    monkeypatch.setattr("inboxanchor.infra.retry.time.sleep", lambda *_args, **_kwargs: None)

    def flaky():
        attempts["count"] += 1
        if attempts["count"] < 3:
            raise RateLimitError("slow down")
        return "ok"

    result = with_retry(flaky, max_attempts=3, base_delay=0.01, jitter=False)

    assert result == "ok"
    assert attempts["count"] == 3


def test_with_retry_does_not_retry_auth_failures(monkeypatch):
    attempts = {"count": 0}
    monkeypatch.setattr("inboxanchor.infra.retry.time.sleep", lambda *_args, **_kwargs: None)

    def auth_failure():
        attempts["count"] += 1
        raise AuthError("nope")

    try:
        with_retry(auth_failure, max_attempts=3, base_delay=0.01, jitter=False)
    except AuthError:
        pass
    else:  # pragma: no cover - defensive
        raise AssertionError("AuthError should have been raised")

    assert attempts["count"] == 1
