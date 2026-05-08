from __future__ import annotations

from typing import Optional

from inboxanchor.infra.llm_client import LLMClient
from inboxanchor.models import EmailClassification, EmailMessage
from inboxanchor.models.email import EmailCategory, PriorityLevel


class ClassifierAgent:
    def __init__(self, llm_client: Optional[LLMClient] = None):
        self.llm_client = llm_client or LLMClient()

    def classify(self, email: EmailMessage) -> EmailClassification:
        text = f"{email.subject}\n{email.snippet}\n{email.body_preview}".lower()

        if any(token in text for token in ["invoice", "payment", "receipt", "bank", "refund"]):
            return EmailClassification(
                category=EmailCategory.finance,
                priority=PriorityLevel.high,
                confidence=0.94,
                reason="Finance-related language detected.",
            )
        if any(token in text for token in ["winner", "claim now", "bitcoin", "wire transfer"]):
            return EmailClassification(
                category=EmailCategory.spam_like,
                priority=PriorityLevel.low,
                confidence=0.9,
                reason="Spam-like patterns detected.",
            )
        if any(
            token in text
            for token in ["sale", "discount", "limited offer", "promo code", "special offer"]
        ):
            return EmailClassification(
                category=EmailCategory.promo,
                priority=PriorityLevel.low,
                confidence=0.93,
                reason="Promotional language detected.",
            )
        if any(token in text for token in ["urgent", "asap", "today", "immediately", "deadline"]):
            return EmailClassification(
                category=EmailCategory.urgent,
                priority=PriorityLevel.critical,
                confidence=0.92,
                reason="Urgency markers detected in the subject or preview.",
            )
        if any(token in text for token in ["unsubscribe", "newsletter", "digest", "issue #"]):
            return EmailClassification(
                category=EmailCategory.newsletter,
                priority=PriorityLevel.low,
                confidence=0.95,
                reason="Newsletter markers detected.",
            )
        if any(token in text for token in ["interview", "opportunity", "partnership", "proposal"]):
            return EmailClassification(
                category=EmailCategory.opportunity,
                priority=PriorityLevel.high,
                confidence=0.89,
                reason="Opportunity-related terms detected.",
            )
        if any(token in text for token in ["family", "birthday", "trip", "weekend"]):
            return EmailClassification(
                category=EmailCategory.personal,
                priority=PriorityLevel.medium,
                confidence=0.8,
                reason="Personal context markers detected.",
            )
        if any(token in text for token in ["project", "client", "review", "contract", "meeting"]):
            return EmailClassification(
                category=EmailCategory.work,
                priority=PriorityLevel.high if email.has_attachments else PriorityLevel.medium,
                confidence=0.82,
                reason="Work-oriented keywords detected.",
            )
        return EmailClassification(
            category=EmailCategory.unknown,
            priority=PriorityLevel.medium if email.has_attachments else PriorityLevel.low,
            confidence=0.55,
            reason="No strong heuristic matched; keep for review.",
        )
