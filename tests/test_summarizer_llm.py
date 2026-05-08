from __future__ import annotations

from inboxanchor.agents.summarizer import SummarizerAgent
from inboxanchor.bootstrap import build_demo_emails
from inboxanchor.infra.llm_client import LLMResult
from inboxanchor.models import EmailClassification


class StubLLMClient:
    def __init__(self, result: LLMResult):
        self.result = result
        self.calls = 0

    def complete(self, prompt: str, *, system_prompt: str = "") -> LLMResult:
        del prompt, system_prompt
        self.calls += 1
        return self.result


def _classifications(emails):
    return {
        email.id: EmailClassification(
            category="work" if index % 2 == 0 else "newsletter",
            priority="high" if index == 0 else "low",
            confidence=0.9,
            reason="test",
        )
        for index, email in enumerate(emails)
    }


def test_summarizer_uses_llm_for_digest_text():
    emails = build_demo_emails()[:3]
    llm = StubLLMClient(
        LLMResult(
            content=(
                '{"summary":"Three unread emails need sorting.",'
                '"daily_digest":"Start with the high-priority client thread.",'
                '"weekly_digest":"Batch newsletters later this week."}'
            ),
            provider="openai",
            model="gpt-4o-mini",
            latency_ms=10,
        )
    )
    agent = SummarizerAgent(llm_client=llm)

    digest = agent.build_digest(emails, _classifications(emails))

    assert digest.summary == "Three unread emails need sorting."
    assert digest.daily_digest == "Start with the high-priority client thread."
    assert digest.weekly_digest == "Batch newsletters later this week."
    assert llm.calls == 1


def test_summarizer_falls_back_when_llm_errors():
    emails = build_demo_emails()[:3]
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
    agent = SummarizerAgent(llm_client=llm)

    digest = agent.build_digest(emails, _classifications(emails))

    assert "You have 3 unread emails." in digest.summary
    assert "Today: focus on" in digest.daily_digest
