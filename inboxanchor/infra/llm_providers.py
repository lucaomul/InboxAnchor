from __future__ import annotations

import logging
import os
from time import perf_counter
from typing import Optional

from inboxanchor.config.settings import SETTINGS
from inboxanchor.infra.llm_client import LLMClient, LLMResult, MockLLMClient

logger = logging.getLogger(__name__)


class ProviderRequestError(Exception):
    def __init__(self, message: str, *, status_code: int):
        super().__init__(message)
        self.status_code = status_code


class OpenAIBackend:
    provider_name = "openai"

    def __init__(
        self,
        api_key: str,
        model: str = "gpt-4o-mini",
        timeout: int = 30,
        client=None,
    ):
        self.api_key = api_key
        self.model_name = model
        self.timeout = timeout
        if client is not None:
            self.client = client
            return
        if not api_key:
            raise ProviderRequestError("OpenAI API key is missing.", status_code=401)
        try:
            from openai import OpenAI
        except ImportError as error:  # pragma: no cover - optional dependency
            raise ImportError(
                "The OpenAI SDK is not installed. Install 'openai' to enable the "
                "OpenAI backend."
            ) from error
        self.client = OpenAI(api_key=api_key, timeout=timeout)

    def complete(
        self,
        prompt: str,
        *,
        system_prompt: str = "",
        timeout_seconds: Optional[int] = None,
    ) -> LLMResult:
        started = perf_counter()
        try:
            response = self.client.chat.completions.create(
                model=self.model_name,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.2,
                timeout=timeout_seconds or self.timeout,
            )
        except Exception as error:
            self._raise_normalized(error)

        usage = getattr(response, "usage", None)
        prompt_tokens = getattr(usage, "prompt_tokens", None) or max(1, len(prompt) // 4)
        completion_text = response.choices[0].message.content or ""
        completion_tokens = getattr(usage, "completion_tokens", None) or max(
            1, len(completion_text) // 4
        )

        return LLMResult(
            content=completion_text.strip(),
            provider=self.provider_name,
            model=self.model_name,
            latency_ms=int((perf_counter() - started) * 1000),
            cost_estimate_usd=self._estimate_cost(prompt_tokens, completion_tokens),
        )

    def _estimate_cost(self, prompt_tokens: int, completion_tokens: int) -> float:
        # Based on the current GPT-4o mini model page, which lists
        # $0.15 / 1M input tokens and $0.60 / 1M output tokens.
        return round((prompt_tokens * 0.15 + completion_tokens * 0.60) / 1_000_000, 6)

    def _raise_normalized(self, error: Exception) -> None:
        status_code = getattr(error, "status_code", None)
        response = getattr(error, "response", None)
        if status_code is None and response is not None:
            status_code = getattr(response, "status_code", None)
        if status_code is None:
            message = str(error).lower()
            if "rate limit" in message or "429" in message:
                status_code = 429
            elif any(token in message for token in ("502", "503", "504", "server error")):
                status_code = 503
            elif any(token in message for token in ("401", "403", "auth", "invalid api key")):
                status_code = 401
            else:
                raise error
        raise ProviderRequestError(str(error), status_code=int(status_code))


class GroqBackend:
    provider_name = "groq"

    def __init__(
        self,
        api_key: str,
        model: str = "llama-3.1-8b-instant",
        timeout: int = 30,
        client=None,
    ):
        self.api_key = api_key
        self.model_name = model
        self.timeout = timeout
        if client is not None:
            self.client = client
            return
        if not api_key:
            raise ProviderRequestError("Groq API key is missing.", status_code=401)
        try:
            from groq import Groq
        except ImportError as error:  # pragma: no cover - optional dependency
            raise ImportError(
                "The Groq SDK is not installed. Install 'groq' to enable the Groq backend."
            ) from error
        self.client = Groq(api_key=api_key, timeout=timeout)

    def complete(
        self,
        prompt: str,
        *,
        system_prompt: str = "",
        timeout_seconds: Optional[int] = None,
    ) -> LLMResult:
        started = perf_counter()
        try:
            response = self.client.chat.completions.create(
                model=self.model_name,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.2,
                timeout=timeout_seconds or self.timeout,
            )
        except Exception as error:
            self._raise_normalized(error)

        usage = getattr(response, "usage", None)
        prompt_tokens = getattr(usage, "prompt_tokens", None) or max(1, len(prompt) // 4)
        completion_text = response.choices[0].message.content or ""
        completion_tokens = getattr(usage, "completion_tokens", None) or max(
            1, len(completion_text) // 4
        )

        return LLMResult(
            content=completion_text.strip(),
            provider=self.provider_name,
            model=self.model_name,
            latency_ms=int((perf_counter() - started) * 1000),
            cost_estimate_usd=self._estimate_cost(prompt_tokens, completion_tokens),
        )

    def _estimate_cost(self, prompt_tokens: int, completion_tokens: int) -> float:
        # Based on the current Groq model page for llama-3.1-8b-instant,
        # which lists $0.05 / 1M input tokens and $0.08 / 1M output tokens.
        return round((prompt_tokens * 0.05 + completion_tokens * 0.08) / 1_000_000, 6)

    def _raise_normalized(self, error: Exception) -> None:
        status_code = getattr(error, "status_code", None)
        response = getattr(error, "response", None)
        if status_code is None and response is not None:
            status_code = getattr(response, "status_code", None)
        if status_code is None:
            message = str(error).lower()
            if "rate limit" in message or "429" in message:
                status_code = 429
            elif any(token in message for token in ("502", "503", "504", "server error")):
                status_code = 503
            elif any(token in message for token in ("401", "403", "auth", "invalid api key")):
                status_code = 401
            else:
                raise error
        raise ProviderRequestError(str(error), status_code=int(status_code))


class FallbackBackend:
    def __init__(self, primary, secondary):
        self.primary = primary
        self.secondary = secondary
        self.provider_name = getattr(primary, "provider_name", "fallback")
        self.model_name = getattr(primary, "model_name", "unknown")

    def complete(
        self,
        prompt: str,
        *,
        system_prompt: str = "",
        timeout_seconds: Optional[int] = None,
    ) -> LLMResult:
        try:
            return self.primary.complete(
                prompt,
                system_prompt=system_prompt,
                timeout_seconds=timeout_seconds,
            )
        except Exception as primary_error:
            if self.secondary is None:
                raise
            logger.warning(
                "Primary LLM backend failed; trying fallback backend.",
                extra={
                    "primary_provider": getattr(self.primary, "provider_name", "unknown"),
                    "fallback_provider": getattr(self.secondary, "provider_name", "unknown"),
                    "error_type": primary_error.__class__.__name__,
                },
            )
            result = self.secondary.complete(
                prompt,
                system_prompt=system_prompt,
                timeout_seconds=timeout_seconds,
            )
            result.used_fallback = True
            return result


def _build_openai_backend() -> Optional[OpenAIBackend]:
    if not (os.getenv("OPENAI_API_KEY") or SETTINGS.openai_api_key):
        return None
    return OpenAIBackend(
        api_key=os.getenv("OPENAI_API_KEY", SETTINGS.openai_api_key),
        model=os.getenv("INBOXANCHOR_OPENAI_MODEL", SETTINGS.openai_model),
        timeout=SETTINGS.llm_timeout_seconds,
    )


def _build_groq_backend() -> Optional[GroqBackend]:
    if not (os.getenv("GROQ_API_KEY") or SETTINGS.groq_api_key):
        return None
    return GroqBackend(
        api_key=os.getenv("GROQ_API_KEY", SETTINGS.groq_api_key),
        model=os.getenv("INBOXANCHOR_GROQ_MODEL", SETTINGS.groq_model),
        timeout=SETTINGS.llm_timeout_seconds,
    )


def _mock_client(reason: str) -> LLMClient:
    logger.warning("Falling back to mock LLM backend: %s", reason)
    return LLMClient(MockLLMClient(provider_name="mock", model_name="heuristic-v1"))


def build_llm_client() -> LLMClient:
    provider = os.getenv("INBOXANCHOR_LLM_PROVIDER", SETTINGS.llm_provider).strip().lower()

    try:
        if provider == "openai":
            primary = _build_openai_backend()
            if primary is None:
                fallback = _build_groq_backend()
                if fallback is not None:
                    logger.warning(
                        "OpenAI key is missing; using Groq as the active LLM backend."
                    )
                    return LLMClient(fallback)
                return _mock_client("OpenAI provider selected but no API key is configured.")

            fallback = _build_groq_backend()
            backend = FallbackBackend(primary, fallback) if fallback is not None else primary
            return LLMClient(backend)

        if provider == "groq":
            primary = _build_groq_backend()
            if primary is None:
                fallback = _build_openai_backend()
                if fallback is not None:
                    logger.warning(
                        "Groq key is missing; using OpenAI as the active LLM backend."
                    )
                    return LLMClient(fallback)
                return _mock_client("Groq provider selected but no API key is configured.")

            fallback = _build_openai_backend()
            backend = FallbackBackend(primary, fallback) if fallback is not None else primary
            return LLMClient(backend)

        return LLMClient()
    except ImportError as error:
        return _mock_client(str(error))
