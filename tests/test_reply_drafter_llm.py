from __future__ import annotations

from inboxanchor.agents.reply_drafter import ReplyDrafterAgent
from inboxanchor.bootstrap import build_demo_emails
from inboxanchor.infra.llm_client import LLMResult
from inboxanchor.models import EmailActionItem


class StubLLMClient:
    def __init__(self, result: LLMResult):
        self.result = result
        self.calls = 0

    def complete(self, prompt: str, *, system_prompt: str = "") -> LLMResult:
        del prompt, system_prompt
        self.calls += 1
        return self.result


def _action_items(email_id: str):
    return [
        EmailActionItem(
            email_id=email_id,
            action_type="reply_needed",
            description="Confirm the next partnership step.",
            requires_reply=True,
        )
    ]


def test_reply_drafter_uses_llm_output():
    email = build_demo_emails()[4]
    llm = StubLLMClient(
        LLMResult(
            content=(
                "Thanks for reaching out about the partnership. "
                "I noted the next steps and will follow up on scheduling shortly.\n\n"
                "Best,\nLuca"
            ),
            provider="openai",
            model="gpt-4o-mini",
            latency_ms=10,
        )
    )
    agent = ReplyDrafterAgent(llm_client=llm)

    draft = agent.draft(email, _action_items(email.id))

    assert "partnership" in draft.lower()
    assert llm.calls == 1


def test_reply_drafter_falls_back_to_template_on_error():
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
    agent = ReplyDrafterAgent(llm_client=llm)

    draft = agent.draft(email, _action_items(email.id))

    assert "Thanks for the message" in draft
    assert "Best,\nLuca" in draft


def test_reply_drafter_skips_non_reply_workflows():
    email = build_demo_emails()[0]
    llm = StubLLMClient(
        LLMResult(content="test", provider="openai", model="gpt-4o-mini", latency_ms=10)
    )
    agent = ReplyDrafterAgent(llm_client=llm)

    draft = agent.draft(
        email,
        [
            EmailActionItem(
                email_id=email.id,
                action_type="invoice_payment",
                description="Pay the invoice.",
                requires_reply=False,
            )
        ],
    )

    assert draft is None
    assert llm.calls == 0
