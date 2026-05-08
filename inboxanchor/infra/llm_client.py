from __future__ import annotations

import inspect
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError
from dataclasses import dataclass
from time import perf_counter
from typing import Optional

from inboxanchor.config.settings import SETTINGS
from inboxanchor.infra.retry import with_retry


@dataclass
class LLMResult:
    content: str
    provider: str
    model: str
    latency_ms: int
    cost_estimate_usd: float = 0.0
    used_fallback: bool = False
    error: bool = False
    error_type: Optional[str] = None
    message: str = ""


class MockLLMClient:
    def __init__(self, provider_name: str = "mock", model_name: str = "heuristic-v1"):
        self.provider_name = provider_name
        self.model_name = model_name

    def complete(
        self,
        prompt: str,
        *,
        system_prompt: str = "",
        timeout_seconds: Optional[int] = None,
    ) -> LLMResult:
        del system_prompt, timeout_seconds
        started = perf_counter()
        content = prompt[:300]
        latency_ms = int((perf_counter() - started) * 1000)
        return LLMResult(
            content=content,
            provider=self.provider_name,
            model=self.model_name,
            latency_ms=latency_ms,
        )


class LLMClient:
    """
    Provider-neutral LLM façade.

    Live providers are wrapped with retries and timeouts so agent calls fail
    gracefully instead of tearing down the inbox workflow.
    """

    def __init__(self, backend: Optional[MockLLMClient] = None):
        self.backend = backend or MockLLMClient(provider_name=SETTINGS.llm_provider)

    def _backend_call(self, prompt: str, *, system_prompt: str) -> LLMResult:
        signature = inspect.signature(self.backend.complete)
        kwargs = {"system_prompt": system_prompt}
        if "timeout_seconds" in signature.parameters:
            kwargs["timeout_seconds"] = SETTINGS.llm_timeout_seconds

        def invoke():
            return self.backend.complete(prompt, **kwargs)

        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(invoke)
            try:
                return future.result(timeout=SETTINGS.llm_timeout_seconds)
            except FutureTimeoutError as error:  # pragma: no cover - timing dependent
                raise TimeoutError(
                    f"Provider call exceeded {SETTINGS.llm_timeout_seconds} seconds."
                ) from error

    def complete(self, prompt: str, *, system_prompt: str = "") -> LLMResult:
        started = perf_counter()
        try:
            result = with_retry(
                lambda: self._backend_call(prompt, system_prompt=system_prompt),
                max_attempts=max(1, SETTINGS.llm_retry_attempts),
                base_delay=SETTINGS.llm_retry_base_delay_seconds,
                max_delay=SETTINGS.llm_retry_max_delay_seconds,
            )
            if result.latency_ms <= 0:
                result.latency_ms = int((perf_counter() - started) * 1000)
            return result
        except Exception as error:
            latency_ms = int((perf_counter() - started) * 1000)
            return LLMResult(
                content="",
                provider=getattr(self.backend, "provider_name", SETTINGS.llm_provider),
                model=getattr(self.backend, "model_name", "unknown"),
                latency_ms=latency_ms,
                error=True,
                error_type="provider_unavailable",
                message=str(error),
            )
