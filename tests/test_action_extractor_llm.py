from __future__ import annotations

from inboxanchor.agents.action_extractor import ActionExtractorAgent
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


def test_action_extractor_uses_llm_for_richer_emails():
    email = build_demo_emails()[4].model_copy(
        update={
            "body_full": (
                "We're interested in a partnership and would love to schedule a meeting next week. "
                "Please review the draft agenda, confirm your availability, and let us know "
                "if your legal "
                "team wants to review the draft commercial terms before the call."
            )
        }
    )
    llm = StubLLMClient(
        LLMResult(
            content=(
                "["
                '{"action_type":"meeting_scheduling",'
                '"description":"Schedule a partnership call next week.",'
                '"requires_reply":true}'
                "]"
            ),
            provider="openai",
            model="gpt-4o-mini",
            latency_ms=10,
        )
    )
    agent = ActionExtractorAgent(llm_client=llm)

    items = agent.extract(email)

    assert len(items) == 1
    assert items[0].action_type == "meeting_scheduling"
    assert items[0].requires_reply is True
    assert llm.calls == 1


def test_action_extractor_falls_back_on_llm_error():
    email = build_demo_emails()[2]
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
    agent = ActionExtractorAgent(llm_client=llm)

    items = agent.extract(email)

    assert any(item.action_type == "document_review" for item in items)
    assert any(item.action_type == "deadline" for item in items)


def test_action_extractor_skips_llm_for_short_preview():
    email = build_demo_emails()[0].model_copy(update={"body_preview": "Reply soon"})
    llm = StubLLMClient(
        LLMResult(content="[]", provider="openai", model="gpt-4o-mini", latency_ms=10)
    )
    agent = ActionExtractorAgent(llm_client=llm)

    items = agent.extract(email)

    assert llm.calls == 0
    assert any(item.action_type == "reply_needed" for item in items)


def test_action_extractor_skips_llm_for_automated_newsletter():
    email = build_demo_emails()[1]
    llm = StubLLMClient(
        LLMResult(content="[]", provider="openai", model="gpt-4o-mini", latency_ms=10)
    )
    agent = ActionExtractorAgent(llm_client=llm)

    items = agent.extract(email)

    assert items == []
    assert llm.calls == 0
