from __future__ import annotations

from types import SimpleNamespace

from inboxanchor.infra.llm_client import LLMResult, MockLLMClient
from inboxanchor.infra.llm_providers import (
    FallbackBackend,
    GroqBackend,
    OpenAIBackend,
    ProviderRequestError,
    build_llm_client,
)


class FakeCompletionsAPI:
    def __init__(self, response=None, error=None):
        self.response = response
        self.error = error

    def create(self, **kwargs):
        del kwargs
        if self.error is not None:
            raise self.error
        return self.response


def _fake_client(response=None, error=None):
    return SimpleNamespace(
        chat=SimpleNamespace(completions=FakeCompletionsAPI(response=response, error=error))
    )


def _fake_response(content: str, prompt_tokens: int = 20, completion_tokens: int = 10):
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content))],
        usage=SimpleNamespace(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
        ),
    )


def test_openai_backend_returns_llm_result():
    backend = OpenAIBackend(
        api_key="test-key",
        client=_fake_client(response=_fake_response('{"ok": true}')),
    )

    result = backend.complete("hello", system_prompt="system")

    assert result.provider == "openai"
    assert result.model == "gpt-4o-mini"
    assert result.content == '{"ok": true}'
    assert result.cost_estimate_usd > 0


def test_groq_backend_returns_llm_result():
    backend = GroqBackend(
        api_key="test-key",
        client=_fake_client(response=_fake_response("done")),
    )

    result = backend.complete("hello", system_prompt="system")

    assert result.provider == "groq"
    assert result.model == "llama-3.1-8b-instant"
    assert result.content == "done"
    assert result.cost_estimate_usd > 0


def test_openai_backend_normalizes_rate_limit_errors():
    error = RuntimeError("rate limit")
    error.status_code = 429  # type: ignore[attr-defined]
    backend = OpenAIBackend(api_key="test-key", client=_fake_client(error=error))

    try:
        backend.complete("hello")
    except ProviderRequestError as raised:
        assert raised.status_code == 429
    else:  # pragma: no cover - defensive
        raise AssertionError("Expected ProviderRequestError to be raised.")


def test_fallback_backend_uses_secondary_provider():
    class PrimaryBackend:
        provider_name = "openai"
        model_name = "primary"

        def complete(self, prompt: str, *, system_prompt: str = "", timeout_seconds=None):
            del prompt, system_prompt, timeout_seconds
            error = RuntimeError("rate limit")
            error.status_code = 429  # type: ignore[attr-defined]
            raise error

    class SecondaryBackend:
        provider_name = "groq"
        model_name = "secondary"

        def complete(self, prompt: str, *, system_prompt: str = "", timeout_seconds=None):
            del prompt, system_prompt, timeout_seconds
            return LLMResult(
                content="fallback",
                provider="groq",
                model="secondary",
                latency_ms=1,
            )

    backend = FallbackBackend(PrimaryBackend(), SecondaryBackend())

    result = backend.complete("hello")

    assert result.content == "fallback"
    assert result.provider == "groq"
    assert result.used_fallback is True


def test_build_llm_client_uses_configured_provider(monkeypatch):
    monkeypatch.setenv("INBOXANCHOR_LLM_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "openai-key")
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.setattr(
        "inboxanchor.infra.llm_providers._build_openai_backend",
        lambda: MockLLMClient(provider_name="openai", model_name="gpt-4o-mini"),
    )
    monkeypatch.setattr("inboxanchor.infra.llm_providers._build_groq_backend", lambda: None)

    client = build_llm_client()

    assert client.backend.provider_name == "openai"


def test_build_llm_client_falls_back_to_mock_without_keys(monkeypatch):
    monkeypatch.setenv("INBOXANCHOR_LLM_PROVIDER", "openai")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("GROQ_API_KEY", raising=False)

    client = build_llm_client()

    assert client.backend.provider_name == "mock"
