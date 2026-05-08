from __future__ import annotations

from inboxanchor.agents.classifier import ClassifierAgent
from inboxanchor.bootstrap import build_demo_emails
from inboxanchor.infra.llm_client import LLMResult


class StubLLMClient:
    def __init__(self, result: LLMResult):
        self.result = result
        self.calls = 0

    def complete(self, prompt: str, *, system_prompt: str = "") -> LLMResult:
        del prompt, system_prompt
        self.calls += 1
        return self.result


def test_classifier_uses_llm_when_heuristic_is_not_high_confidence():
    email = build_demo_emails()[4]
    llm = StubLLMClient(
        LLMResult(
            content=(
                '{"category":"work","priority":"high","confidence":0.88,'
                '"reason":"Client follow-up context detected."}'
            ),
            provider="openai",
            model="gpt-4o-mini",
            latency_ms=10,
        )
    )
    agent = ClassifierAgent(llm_client=llm)

    result = agent.classify(email)

    assert result.category == "work"
    assert result.priority == "high"
    assert llm.calls == 1


def test_classifier_falls_back_to_heuristic_when_llm_errors():
    email = build_demo_emails()[4]
    llm = StubLLMClient(
        LLMResult(
            content="",
            provider="openai",
            model="gpt-4o-mini",
            latency_ms=10,
            error=True,
            error_type="provider_unavailable",
        )
    )
    agent = ClassifierAgent(llm_client=llm)

    result = agent.classify(email)

    assert result.category == "opportunity"
    assert result.priority == "high"


def test_classifier_skips_llm_for_high_confidence_newsletter():
    email = build_demo_emails()[1]
    llm = StubLLMClient(
        LLMResult(content="{}", provider="openai", model="gpt-4o-mini", latency_ms=10)
    )
    agent = ClassifierAgent(llm_client=llm)

    result = agent.classify(email)

    assert result.category == "newsletter"
    assert llm.calls == 0


def test_classifier_skips_llm_for_confident_urgent_case():
    email = build_demo_emails()[2]
    llm = StubLLMClient(
        LLMResult(content="{}", provider="openai", model="gpt-4o-mini", latency_ms=10)
    )
    agent = ClassifierAgent(llm_client=llm)

    result = agent.classify(email)

    assert result.category == "urgent"
    assert result.priority == "critical"
    assert llm.calls == 0
