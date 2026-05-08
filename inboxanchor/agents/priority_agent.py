from __future__ import annotations

from inboxanchor.models import EmailClassification, EmailMessage
from inboxanchor.models.email import PriorityLevel


class PriorityAgent:
    def prioritize(
        self,
        email: EmailMessage,
        classification: EmailClassification,
    ) -> EmailClassification:
        priority = classification.priority
        confidence = classification.confidence
        reason = classification.reason

        if email.has_attachments and priority in {PriorityLevel.medium, PriorityLevel.low}:
            priority = PriorityLevel.high
            confidence = max(confidence, 0.75)
            reason = f"{reason} Elevated because the email has attachments."

        if "ceo@" in email.sender.lower() or "founder@" in email.sender.lower():
            priority = PriorityLevel.critical
            confidence = max(confidence, 0.85)
            reason = f"{reason} Elevated because the sender appears executive."

        return classification.model_copy(
            update={
                "priority": priority,
                "confidence": min(confidence, 0.99),
                "reason": reason,
            }
        )
