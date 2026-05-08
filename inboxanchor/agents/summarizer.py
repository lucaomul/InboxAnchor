from __future__ import annotations

from collections import Counter

from inboxanchor.models import EmailClassification, EmailMessage, InboxDigest
from inboxanchor.models.email import PriorityLevel


class SummarizerAgent:
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
        top_senders = ", ".join(sorted({email.sender for email in emails[:5]})) or "No senders"
        summary = (
            f"You have {len(emails)} unread emails. "
            f"Highest concentration: {', '.join(f'{k}={v}' for k, v in counts.items()) or 'none'}."
        )
        daily_digest = (
            f"Today: focus on {len(high_priority_ids)} high-priority emails first. "
            f"Top visible senders: {top_senders}."
        )
        weekly_digest = (
            "Weekly pattern: newsletters and promo mail can usually be batched, "
            "while finance, work, and opportunity messages should stay human-reviewed."
        )
        return InboxDigest(
            total_unread=len(emails),
            category_counts=dict(counts),
            high_priority_ids=high_priority_ids,
            summary=summary,
            daily_digest=daily_digest,
            weekly_digest=weekly_digest,
        )
