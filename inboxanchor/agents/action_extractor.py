from __future__ import annotations

import re
from typing import Optional

from inboxanchor.agents._llm_utils import parse_json_content
from inboxanchor.infra.llm_client import LLMClient
from inboxanchor.infra.llm_providers import build_llm_client
from inboxanchor.models import EmailActionItem, EmailMessage

ACTION_EXTRACTOR_SYSTEM_PROMPT = """
You are an email action extractor.
Extract concrete follow-up actions from the email.
Return ONLY valid JSON: a list of objects.

Each object must contain:
- action_type
- description
- requires_reply

Allowed action_type values:
- reply_needed
- meeting_scheduling
- invoice_payment
- document_review
- deadline
- follow_up
- other

Return [] if no action is needed.
Return at most 3 items.
description must be one short sentence.
requires_reply must be true or false.
""".strip()


class ActionExtractorAgent:
    def __init__(self, llm_client: Optional[LLMClient] = None):
        self.llm_client = llm_client or build_llm_client()

    def extract(self, email: EmailMessage) -> list[EmailActionItem]:
        preview = email.body_preview.strip()
        heuristic_items = self._heuristic_extract(email)
        if len(preview) < 50:
            return heuristic_items

        llm_result = self.llm_client.complete(
            self._build_prompt(email),
            system_prompt=ACTION_EXTRACTOR_SYSTEM_PROMPT,
        )
        if llm_result.error:
            return heuristic_items

        payload = parse_json_content(llm_result.content)
        if not isinstance(payload, list):
            return heuristic_items
        if not payload:
            return []

        items: list[EmailActionItem] = []
        try:
            for entry in payload[:3]:
                if not isinstance(entry, dict):
                    continue
                item_payload = {
                    "email_id": email.id,
                    "action_type": entry.get("action_type", "other"),
                    "description": entry.get("description", "Follow-up may be required."),
                    "requires_reply": bool(entry.get("requires_reply", False)),
                }
                items.append(EmailActionItem.model_validate(item_payload))
        except Exception:
            return heuristic_items

        return items if items else heuristic_items

    def _build_prompt(self, email: EmailMessage) -> str:
        return (
            "Extract follow-up actions from this email.\n"
            f"Sender: {email.sender}\n"
            f"Subject: {email.subject}\n"
            f"Snippet: {email.snippet}\n"
            f"Body preview: {email.body_preview}\n"
        )

    def _heuristic_extract(self, email: EmailMessage) -> list[EmailActionItem]:
        text = f"{email.subject}\n{email.snippet}\n{email.body_preview}".lower()
        items: list[EmailActionItem] = []

        if any(token in text for token in ["reply", "respond", "let me know"]):
            items.append(
                EmailActionItem(
                    email_id=email.id,
                    action_type="reply_needed",
                    description="A response is likely needed.",
                    requires_reply=True,
                )
            )
        if any(token in text for token in ["schedule", "calendar", "meeting", "availability"]):
            items.append(
                EmailActionItem(
                    email_id=email.id,
                    action_type="meeting_scheduling",
                    description="Meeting coordination or scheduling detected.",
                )
            )
        if any(token in text for token in ["invoice", "payment", "due", "receipt"]):
            items.append(
                EmailActionItem(
                    email_id=email.id,
                    action_type="invoice_payment",
                    description="Financial follow-up may be required.",
                )
            )
        if any(token in text for token in ["review attached", "document review", "please review"]):
            items.append(
                EmailActionItem(
                    email_id=email.id,
                    action_type="document_review",
                    description="A document review step appears to be required.",
                )
            )
        has_deadline_phrase = any(
            token in text for token in ["deadline", "by eod", "tomorrow", "friday"]
        ) or re.search(r"\b(before|by)\s+\d", text)
        if has_deadline_phrase:
            items.append(
                EmailActionItem(
                    email_id=email.id,
                    action_type="deadline",
                    description="A deadline or time-sensitive commitment was detected.",
                )
            )
        if any(token in text for token in ["follow up", "checking in", "circling back"]):
            items.append(
                EmailActionItem(
                    email_id=email.id,
                    action_type="follow_up",
                    description="A follow-up action may be required.",
                )
            )
        return items
