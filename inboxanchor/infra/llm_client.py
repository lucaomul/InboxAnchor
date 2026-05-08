from __future__ import annotations

from dataclasses import dataclass
from time import perf_counter
from typing import Optional

from inboxanchor.config.settings import SETTINGS


@dataclass
class LLMResult:
    content: str
    provider: str
    model: str
    latency_ms: int
    cost_estimate_usd: float = 0.0
    used_fallback: bool = False


class MockLLMClient:
    def __init__(self, provider_name: str = "mock", model_name: str = "heuristic-v1"):
        self.provider_name = provider_name
        self.model_name = model_name

    def complete(self, prompt: str, *, system_prompt: str = "") -> LLMResult:
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

    V1 intentionally keeps live-provider logic light while exposing a stable
    interface. The agents can remain deterministic in tests and use this client
    opportunistically during manual runs.
    """

    def __init__(self, backend: Optional[MockLLMClient] = None):
        self.backend = backend or MockLLMClient(provider_name=SETTINGS.llm_provider)

    def complete(self, prompt: str, *, system_prompt: str = "") -> LLMResult:
        return self.backend.complete(prompt, system_prompt=system_prompt)
