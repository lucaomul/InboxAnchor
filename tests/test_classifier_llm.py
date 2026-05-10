from __future__ import annotations

from datetime import datetime, timezone

from inboxanchor.agents.classifier import ClassifierAgent
from inboxanchor.bootstrap import build_demo_emails
from inboxanchor.infra.llm_client import LLMResult
from inboxanchor.models import EmailMessage
from inboxanchor.sender_intelligence import SenderIntelligenceContext, analyze_message_signals


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


def test_classifier_uses_sender_profile_to_classify_plain_company_updates_as_work():
    email = EmailMessage(
        id="work-profile-1",
        thread_id="work-profile-1",
        sender="hello@acme.dev",
        subject="Quick update",
        snippet="Wanted to share a quick update before tomorrow.",
        body_preview="Sharing a quick update before tomorrow's review call.",
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
    intelligence = SenderIntelligenceContext(
        sender_profile={
            "sender_address": "hello@acme.dev",
            "scores": {
                "work": 0.92,
                "human": 0.82,
                "importance": 0.74,
            },
        },
        domain_profile={
            "domain": "acme.dev",
            "scores": {
                "work": 0.88,
                "human": 0.65,
                "importance": 0.7,
            },
        },
        message_signals=analyze_message_signals(email),
    )

    result = agent.classify(email, intelligence=intelligence)

    assert result.category == "work"
    assert result.priority in {"medium", "high"}


def test_classifier_treats_social_security_alerts_as_urgent():
    email = EmailMessage(
        id="social-sec-1",
        thread_id="social-sec-1",
        sender="security@mail.instagram.com",
        subject="Security alert: new login from a new device",
        snippet="We noticed a suspicious login to your Instagram account.",
        body_preview="Security alert. Suspicious login detected from a new device. Review now.",
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

    assert result.category == "urgent"
    assert result.priority in {"high", "critical"}


def test_classifier_uses_high_confidence_promo_archetype_for_plain_marketing_mail():
    email = EmailMessage(
        id="promo-arch-1",
        thread_id="promo-arch-1",
        sender="offers@store.example",
        subject="A quick update for you",
        snippet="Just checking in with a new campaign.",
        body_preview="Here is a quick store update for this week.",
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
    intelligence = SenderIntelligenceContext(
        sender_profile={
            "sender_address": "offers@store.example",
            "scores": {
                "promo": 0.92,
                "automated": 0.88,
            },
        },
        domain_profile=None,
        message_signals=analyze_message_signals(email),
    )

    result = agent.classify(email, intelligence=intelligence)

    assert result.category == "promo"
    assert result.priority == "low"


def test_classifier_uses_recruiter_archetype_for_plain_hiring_mail():
    email = EmailMessage(
        id="recruit-arch-1",
        thread_id="recruit-arch-1",
        sender="hello@talentpartners.example",
        subject="Quick note",
        snippet="Wanted to reach out about a role.",
        body_preview="I wanted to share a quick note about a possible fit.",
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
    intelligence = SenderIntelligenceContext(
        sender_profile={
            "sender_address": "hello@talentpartners.example",
            "scores": {
                "recruiter": 0.84,
                "human": 0.78,
                "importance": 0.72,
            },
        },
        domain_profile=None,
        message_signals=analyze_message_signals(email),
    )

    result = agent.classify(email, intelligence=intelligence)

    assert result.category == "opportunity"
    assert result.priority in {"medium", "high"}
