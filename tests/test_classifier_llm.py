from __future__ import annotations

from datetime import datetime, timezone

from inboxanchor.agents.classifier import ClassifierAgent
from inboxanchor.bootstrap import build_demo_emails
from inboxanchor.infra.llm_client import LLMResult
from inboxanchor.models import EmailMessage


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


def test_classifier_treats_github_mail_as_work_not_noise():
    email = EmailMessage(
        id="gh-1",
        thread_id="gh-1",
        sender="notifications@github.com",
        subject="[lucaomul/InboxAnchor] Run failed: CI - main",
        snippet="The latest CI run failed on main after the last push.",
        body_preview="GitHub Actions reported a failed workflow run and linked the logs.",
        received_at=datetime.now(timezone.utc),
        labels=["INBOX"],
        has_attachments=False,
        unread=True,
    )
    agent = ClassifierAgent(
        llm_client=StubLLMClient(
            LLMResult(content="{}", provider="mock", model="mock", latency_ms=1)
        )
    )

    result = agent.classify(email)

    assert result.category == "work"
    assert result.priority in {"medium", "high"}


def test_classifier_treats_linkedin_profile_updates_as_low_priority():
    email = EmailMessage(
        id="li-1",
        thread_id="li-1",
        sender="jobs-noreply@linkedin.com",
        subject="5 people viewed your profile this week",
        snippet="See profile views and job recommendations based on your recent activity.",
        body_preview="LinkedIn found new roles and profile-view updates for you this week.",
        received_at=datetime.now(timezone.utc),
        labels=["INBOX"],
        has_attachments=False,
        unread=True,
    )
    agent = ClassifierAgent(
        llm_client=StubLLMClient(
            LLMResult(content="{}", provider="mock", model="mock", latency_ms=1)
        )
    )

    result = agent.classify(email)

    assert result.category == "low_priority"
    assert result.priority == "low"
