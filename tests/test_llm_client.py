from inboxanchor.infra.llm_client import LLMClient, LLMResult


class FlakyBackend:
    provider_name = "flaky"
    model_name = "demo"

    def __init__(self):
        self.calls = 0

    def complete(self, prompt: str, *, system_prompt: str = "", timeout_seconds: int = 30):
        del prompt, system_prompt, timeout_seconds
        self.calls += 1
        if self.calls < 3:
            error = RuntimeError("rate limit")
            error.status_code = 429  # type: ignore[attr-defined]
            raise error
        return LLMResult(
            content="done",
            provider=self.provider_name,
            model=self.model_name,
            latency_ms=1,
        )


class BrokenBackend:
    provider_name = "broken"
    model_name = "demo"

    def complete(self, prompt: str, *, system_prompt: str = "", timeout_seconds: int = 30):
        del prompt, system_prompt, timeout_seconds
        raise RuntimeError("provider offline")


def test_llm_client_retries_and_recovers(monkeypatch):
    monkeypatch.setattr("inboxanchor.infra.retry.time.sleep", lambda *_args, **_kwargs: None)
    client = LLMClient(backend=FlakyBackend())

    result = client.complete("hello")

    assert result.content == "done"
    assert result.error is False


def test_llm_client_returns_structured_error_result():
    client = LLMClient(backend=BrokenBackend())

    result = client.complete("hello")

    assert result.error is True
    assert result.error_type == "provider_unavailable"
    assert result.provider == "broken"
