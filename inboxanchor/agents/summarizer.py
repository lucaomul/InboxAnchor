from __future__ import annotations

from collections import Counter
from typing import Optional

from inboxanchor.agents._llm_utils import parse_json_content
from inboxanchor.infra.llm_client import LLMClient
from inboxanchor.infra.llm_providers import build_llm_client
from inboxanchor.models import EmailClassification, EmailMessage, InboxDigest
from inboxanchor.models.email import PriorityLevel

SUMMARIZER_SYSTEM_PROMPT = """
You are an inbox analyst.
Given inbox statistics, write three short text summaries.
Return ONLY valid JSON with keys: summary, daily_digest, weekly_digest.
Each value must be 1-2 sentences maximum, specific, and actionable.
""".strip()


class SummarizerAgent:
    def __init__(self, llm_client: Optional[LLMClient] = None):
        self.llm_client = llm_client or build_llm_client()

    def build_digest(
        self,
        emails: list[EmailMessage],
        classifications: dict[str, EmailClassification],
    ) -> InboxDigest:
        counts = Counter(classifications[email.id].category for email in emails)
        high_priority_ids = [
            email.id
            for email in emails
            if classifications[email.id].priority in {PriorityLevel.critical, PriorityLevel.high}
        ]
        top_senders = list(dict.fromkeys(email.sender for email in emails[:5] if email.sender))
        summary, daily_digest, weekly_digest = self._llm_or_fallback(
            total_unread=len(emails),
            category_counts=dict(counts),
            high_priority_count=len(high_priority_ids),
            top_senders=top_senders,
        )

        return InboxDigest(
            total_unread=len(emails),
            category_counts=dict(counts),
            high_priority_ids=high_priority_ids,
            summary=summary,
            daily_digest=daily_digest,
            weekly_digest=weekly_digest,
        )

    def _llm_or_fallback(
        self,
        *,
        total_unread: int,
        category_counts: dict[str, int],
        high_priority_count: int,
        top_senders: list[str],
    ) -> tuple[str, str, str]:
        fallback = self._fallback_copy(
            total_unread=total_unread,
            category_counts=category_counts,
            high_priority_count=high_priority_count,
            top_senders=top_senders,
        )
        if total_unread <= 2 and high_priority_count == 0:
            return fallback
        llm_result = self.llm_client.complete(
            self._build_prompt(
                total_unread=total_unread,
                category_counts=category_counts,
                high_priority_count=high_priority_count,
                top_senders=top_senders,
            ),
            system_prompt=SUMMARIZER_SYSTEM_PROMPT,
        )
        if llm_result.error:
            return fallback

        payload = parse_json_content(llm_result.content)
        if not isinstance(payload, dict):
            return fallback

        summary = str(payload.get("summary", "")).strip()
        daily_digest = str(payload.get("daily_digest", "")).strip()
        weekly_digest = str(payload.get("weekly_digest", "")).strip()
        if not summary or not daily_digest or not weekly_digest:
            return fallback
        return summary, daily_digest, weekly_digest

    def _build_prompt(
        self,
        *,
        total_unread: int,
        category_counts: dict[str, int],
        high_priority_count: int,
        top_senders: list[str],
    ) -> str:
        return (
            "Write inbox summaries from these stats.\n"
            f"Total unread: {total_unread}\n"
            f"Category counts: {category_counts}\n"
            f"High priority count: {high_priority_count}\n"
            f"Top senders: {top_senders}\n"
        )

    def _fallback_copy(
        self,
        *,
        total_unread: int,
        category_counts: dict[str, int],
        high_priority_count: int,
        top_senders: list[str],
    ) -> tuple[str, str, str]:
        top_senders_text = ", ".join(top_senders) or "No senders"
        category_summary = ", ".join(f"{key}={value}" for key, value in category_counts.items())
        summary = (
            f"You have {total_unread} unread emails. "
            f"Highest concentration: {category_summary or 'none'}."
        )
        daily_digest = (
            f"Today: focus on {high_priority_count} high-priority emails first. "
            f"Top visible senders: {top_senders_text}."
        )
        weekly_digest = (
            "Weekly pattern: newsletters and promo mail can usually be batched, "
            "while finance, work, and opportunity messages should stay human-reviewed."
        )
        return summary, daily_digest, weekly_digest
