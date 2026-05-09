from __future__ import annotations

from inboxanchor.mail_intelligence import (
    has_deadline_pressure,
    is_job_alert,
    is_recruiter_or_interview,
    looks_automated_email,
)
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
        automated = looks_automated_email(
            sender=email.sender,
            subject=email.subject,
            snippet=email.snippet,
            body=email.content_for_processing(),
        )
        deadline = has_deadline_pressure(
            sender=email.sender,
            subject=email.subject,
            snippet=email.snippet,
            body=email.content_for_processing(),
        )
        direct_jobs = is_recruiter_or_interview(
            sender=email.sender,
            subject=email.subject,
            snippet=email.snippet,
            body=email.content_for_processing(),
        )
        automated_job_alert = is_job_alert(
            sender=email.sender,
            subject=email.subject,
            snippet=email.snippet,
            body=email.content_for_processing(),
        )

        if classification.category in {"promo", "newsletter", "low_priority", "spam_like"}:
            priority = PriorityLevel.low
            confidence = max(confidence, 0.9)
            reason = (
                f"{reason} Kept low because the email looks promotional, automated, "
                "or low-value."
            )

        if automated_job_alert:
            priority = PriorityLevel.low
            confidence = max(confidence, 0.94)
            reason = (
                f"{reason} Automated job-site alerts stay low priority unless a "
                "human reply thread exists."
            )

        if (
            email.has_attachments
            and not automated
            and classification.category in {"work", "finance", "opportunity", "urgent"}
        ):
            if priority == PriorityLevel.low:
                priority = PriorityLevel.medium
            elif priority == PriorityLevel.medium:
                priority = PriorityLevel.high
            confidence = max(confidence, 0.78)
            reason = (
                f"{reason} Elevated because the email has attachments in a "
                "work-sensitive context."
            )

        if (
            ("ceo@" in email.sender.lower() or "founder@" in email.sender.lower())
            and not automated
            and classification.category in {"work", "finance", "opportunity", "urgent"}
        ):
            priority = PriorityLevel.critical
            confidence = max(confidence, 0.85)
            reason = f"{reason} Elevated because the sender appears executive."

        if deadline and classification.category in {"work", "finance", "opportunity", "urgent"}:
            if priority == PriorityLevel.low:
                priority = PriorityLevel.medium
            elif priority == PriorityLevel.medium:
                priority = PriorityLevel.high
            elif priority == PriorityLevel.high:
                priority = PriorityLevel.critical
            confidence = max(confidence, 0.86)
            reason = f"{reason} Elevated because the message has explicit deadline pressure."

        if direct_jobs and priority == PriorityLevel.medium:
            priority = PriorityLevel.high
            confidence = max(confidence, 0.82)
            reason = (
                f"{reason} Elevated because this looks like direct recruiter or "
                "interview mail."
            )

        return classification.model_copy(
            update={
                "priority": priority,
                "confidence": min(confidence, 0.99),
                "reason": reason,
            }
        )
