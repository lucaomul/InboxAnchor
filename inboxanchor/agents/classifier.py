from __future__ import annotations

from typing import Optional

from inboxanchor.agents._llm_utils import parse_json_content
from inboxanchor.infra.llm_client import LLMClient
from inboxanchor.infra.llm_providers import build_llm_client
from inboxanchor.mail_intelligence import (
    has_deadline_pressure,
    is_finance_invoice,
    is_finance_receipt,
    is_high_value_newsletter,
    is_job_alert,
    is_newsletter,
    is_promo,
    is_recruiter_or_interview,
    is_spam_like,
    is_work_dev_or_ai,
    looks_automated_email,
)
from inboxanchor.models import EmailClassification, EmailMessage
from inboxanchor.models.email import EmailCategory, PriorityLevel

CLASSIFIER_SYSTEM_PROMPT = """
You are an expert email classifier for a safety-first inbox system.
Classify the email into exactly one category and one priority.
Return ONLY valid JSON with keys: category, priority, confidence, reason.

Allowed categories:
- finance
- spam_like
- promo
- urgent
- newsletter
- opportunity
- personal
- work
- low_priority
- unknown

Allowed priorities:
- critical
- high
- medium
- low

Classification guidance:
- Distinguish direct recruiter or interview mail from automated job alerts.
- GitHub, developer tooling, AI tooling, CI failures, pull requests,
  and issue threads should usually be work.
- Automated job digests, profile-view notifications, and generic
  platform alerts should usually be low_priority, not work.
- High-value editorial digests can stay newsletter, but they should not be treated like urgent work.
- Promotions, discounts, trials, and upsells should usually be promo with low priority.
- Invoice/payment requests are finance; receipts are finance too, but
  usually lower priority unless a deadline is explicit.

confidence must be a number between 0.0 and 1.0.
reason must be one short sentence.
""".strip()


class ClassifierAgent:
    def __init__(self, llm_client: Optional[LLMClient] = None):
        self.llm_client = llm_client or build_llm_client()

    def classify(self, email: EmailMessage) -> EmailClassification:
        heuristic = self._heuristic_classify(email)
        if not self._should_use_llm(email, heuristic):
            return heuristic

        llm_result = self.llm_client.complete(
            self._build_prompt(email),
            system_prompt=CLASSIFIER_SYSTEM_PROMPT,
        )
        if llm_result.error:
            return heuristic

        payload = parse_json_content(llm_result.content)
        if not isinstance(payload, dict):
            return heuristic

        try:
            return EmailClassification.model_validate(payload)
        except Exception:
            return heuristic

    def _should_use_llm(
        self,
        email: EmailMessage,
        heuristic: EmailClassification,
    ) -> bool:
        if heuristic.confidence >= 0.9:
            return False
        if heuristic.category in {
            EmailCategory.finance,
            EmailCategory.newsletter,
            EmailCategory.promo,
            EmailCategory.spam_like,
            EmailCategory.low_priority,
        }:
            return False
        if self._looks_automated(email):
            return False
        return heuristic.category in {
            EmailCategory.work,
            EmailCategory.opportunity,
            EmailCategory.personal,
            EmailCategory.unknown,
            EmailCategory.urgent,
        }

    def _build_prompt(self, email: EmailMessage) -> str:
        full_body = email.content_for_processing(max_chars=4000)
        return (
            "Classify this email.\n"
            f"Sender: {email.sender}\n"
            f"Subject: {email.subject}\n"
            f"Snippet: {email.snippet}\n"
            f"Body preview: {email.body_preview}\n"
            f"Body full: {full_body}\n"
            f"Has attachments: {email.has_attachments}\n"
        )

    def _heuristic_classify(self, email: EmailMessage) -> EmailClassification:
        text = f"{email.subject}\n{email.snippet}\n{email.content_for_processing()}".lower()
        automated = self._looks_automated(email)
        deadline = has_deadline_pressure(
            sender=email.sender,
            subject=email.subject,
            snippet=email.snippet,
            body=email.content_for_processing(),
        )

        if is_spam_like(
            sender=email.sender,
            subject=email.subject,
            snippet=email.snippet,
            body=email.content_for_processing(),
        ):
            return EmailClassification(
                category=EmailCategory.spam_like,
                priority=PriorityLevel.low,
                confidence=0.97,
                reason="Spam-like scam or claim-now language detected.",
            )

        if is_finance_invoice(
            sender=email.sender,
            subject=email.subject,
            snippet=email.snippet,
            body=email.content_for_processing(),
        ):
            return EmailClassification(
                category=EmailCategory.finance,
                priority=(
                    PriorityLevel.high
                    if deadline or email.has_attachments
                    else PriorityLevel.medium
                ),
                confidence=0.96,
                reason="Invoice or payment-due language detected.",
            )
        if is_finance_receipt(
            sender=email.sender,
            subject=email.subject,
            snippet=email.snippet,
            body=email.content_for_processing(),
        ):
            return EmailClassification(
                category=EmailCategory.finance,
                priority=PriorityLevel.medium,
                confidence=0.92,
                reason="Receipt or payment-confirmation language detected.",
            )

        if is_recruiter_or_interview(
            sender=email.sender,
            subject=email.subject,
            snippet=email.snippet,
            body=email.content_for_processing(),
        ) and not automated:
            return EmailClassification(
                category=EmailCategory.opportunity,
                priority=PriorityLevel.high if deadline else PriorityLevel.medium,
                confidence=0.91,
                reason="Recruiter, interview, or active application context detected.",
            )

        if is_work_dev_or_ai(
            sender=email.sender,
            subject=email.subject,
            snippet=email.snippet,
            body=email.content_for_processing(),
        ):
            return EmailClassification(
                category=EmailCategory.work,
                priority=PriorityLevel.high if deadline else PriorityLevel.medium,
                confidence=0.9,
                reason="Developer workflow, GitHub, or AI tooling context detected.",
            )

        if is_job_alert(
            sender=email.sender,
            subject=email.subject,
            snippet=email.snippet,
            body=email.content_for_processing(),
        ):
            return EmailClassification(
                category=EmailCategory.low_priority,
                priority=PriorityLevel.low,
                confidence=0.96,
                reason="Automated job-site alert detected.",
            )

        if is_promo(
            sender=email.sender,
            subject=email.subject,
            snippet=email.snippet,
            body=email.content_for_processing(),
        ):
            return EmailClassification(
                category=EmailCategory.promo,
                priority=PriorityLevel.low,
                confidence=0.95,
                reason="Promotional or discount language detected.",
            )

        if is_newsletter(
            sender=email.sender,
            subject=email.subject,
            snippet=email.snippet,
            body=email.content_for_processing(),
        ):
            return EmailClassification(
                category=EmailCategory.newsletter,
                priority=PriorityLevel.medium if is_high_value_newsletter(
                    sender=email.sender,
                    subject=email.subject,
                    snippet=email.snippet,
                    body=email.content_for_processing(),
                ) else PriorityLevel.low,
                confidence=0.95,
                reason="Newsletter or digest markers detected.",
            )

        if deadline and not automated:
            return EmailClassification(
                category=EmailCategory.urgent,
                priority=PriorityLevel.critical,
                confidence=0.9,
                reason="Clear deadline or same-day urgency detected.",
            )

        if any(
            token in text
            for token in ["partnership", "proposal", "term sheet", "investor", "opportunity"]
        ):
            return EmailClassification(
                category=EmailCategory.opportunity,
                priority=PriorityLevel.high if not automated else PriorityLevel.medium,
                confidence=0.88,
                reason="Opportunity-related terms detected.",
            )
        if any(token in text for token in ["family", "birthday", "trip", "weekend"]):
            return EmailClassification(
                category=EmailCategory.personal,
                priority=PriorityLevel.medium,
                confidence=0.8,
                reason="Personal context markers detected.",
            )
        if any(
            token in text
            for token in [
                "project",
                "client",
                "review",
                "contract",
                "meeting",
                "github",
                "pull request",
                "issue",
            ]
        ):
            return EmailClassification(
                category=EmailCategory.work,
                priority=(
                    PriorityLevel.high
                    if email.has_attachments and not automated
                    else PriorityLevel.medium
                ),
                confidence=0.86,
                reason="Work-oriented keywords detected.",
            )
        if automated or any(
            token in text
            for token in [
                "fyi",
                "no action required",
                "for your records",
                "profile viewed",
                "system update",
            ]
        ):
            return EmailClassification(
                category=EmailCategory.low_priority,
                priority=PriorityLevel.low,
                confidence=0.84,
                reason="Automated or low-action informational language detected.",
            )
        return EmailClassification(
            category=EmailCategory.unknown,
            priority=PriorityLevel.medium if email.has_attachments else PriorityLevel.low,
            confidence=0.55,
            reason="No strong heuristic matched; keep for review.",
        )

    def _looks_automated(self, email: EmailMessage) -> bool:
        return looks_automated_email(
            sender=email.sender,
            subject=email.subject,
            snippet=email.snippet,
            body=email.content_for_processing(),
        )
