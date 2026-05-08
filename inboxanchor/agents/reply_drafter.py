from __future__ import annotations

from typing import Optional

from inboxanchor.infra.llm_client import LLMClient
from inboxanchor.infra.llm_providers import build_llm_client
from inboxanchor.models import EmailActionItem, EmailMessage

REPLY_DRAFTER_SYSTEM_PROMPT = """
You are a professional email assistant.
Draft a brief, polite acknowledgment reply.

The reply must:
- be 2-4 sentences maximum
- acknowledge the main topic
- reference the specific action items that need follow-up
- sound natural and professional
- never include a subject line
- end with:
Best,
Luca

Return only the reply text.
""".strip()


class ReplyDrafterAgent:
    def __init__(self, llm_client: Optional[LLMClient] = None):
        self.llm_client = llm_client or build_llm_client()

    def draft(
        self,
        email: EmailMessage,
        action_items: list[EmailActionItem],
    ) -> Optional[str]:
        if not action_items:
            return None
        if len(email.body_preview.strip()) <= 30:
            return self._fallback_template(email)

        llm_result = self.llm_client.complete(
            self._build_prompt(email, action_items),
            system_prompt=REPLY_DRAFTER_SYSTEM_PROMPT,
        )
        if llm_result.error or not llm_result.content.strip():
            return self._fallback_template(email)

        return llm_result.content.strip()

    def _build_prompt(
        self,
        email: EmailMessage,
        action_items: list[EmailActionItem],
    ) -> str:
        actions = "\n".join(f"- {item.description}" for item in action_items)
        return (
            "Draft a reply for this email.\n"
            f"Sender: {email.sender}\n"
            f"Subject: {email.subject}\n"
            f"Body preview: {email.body_preview}\n"
            "Action items:\n"
            f"{actions}\n"
        )

    def _fallback_template(self, email: EmailMessage) -> str:
        return (
            f"Hi,\n\nThanks for the message about \"{email.subject}\". "
            "I reviewed the thread and noted the next steps. "
            "I will follow up with a fuller response shortly.\n\nBest,\nLuca"
        )
