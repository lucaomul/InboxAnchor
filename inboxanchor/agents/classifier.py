from __future__ import annotations

from typing import Optional

from inboxanchor.agents._llm_utils import parse_json_content
from inboxanchor.infra.llm_client import LLMClient
from inboxanchor.infra.llm_providers import build_llm_client
from inboxanchor.mail_intelligence import signal_text
from inboxanchor.models import EmailClassification, EmailMessage
from inboxanchor.models.email import EmailCategory, PriorityLevel
from inboxanchor.sender_intelligence import (
    SenderIntelligenceContext,
    analyze_message_signals,
    profile_scores,
)

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

    def classify(
        self,
        email: EmailMessage,
        *,
        intelligence: Optional[SenderIntelligenceContext] = None,
        allow_llm: bool = True,
    ) -> EmailClassification:
        heuristic = self._heuristic_classify(email, intelligence=intelligence)
        if not allow_llm or not self._should_use_llm(email, heuristic, intelligence=intelligence):
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
        *,
        intelligence: Optional[SenderIntelligenceContext] = None,
    ) -> bool:
        signals = intelligence.message_signals if intelligence else analyze_message_signals(email)
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
        if signals.automated:
            return False
        if heuristic.category == EmailCategory.urgent and signals.deadline:
            return False
        if signals.security or signals.recruiter:
            return heuristic.confidence < 0.78
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

    def _heuristic_classify(
        self,
        email: EmailMessage,
        *,
        intelligence: Optional[SenderIntelligenceContext] = None,
    ) -> EmailClassification:
        context = intelligence or SenderIntelligenceContext(
            sender_profile=None,
            domain_profile=None,
            message_signals=analyze_message_signals(email),
        )
        signals = context.message_signals
        sender_scores = profile_scores(context.sender_profile)
        domain_scores = profile_scores(context.domain_profile)
        text = signal_text(
            sender=email.sender,
            subject=email.subject,
            snippet=email.snippet,
            body=email.content_for_processing(),
        )
        scores = {category.value: 0.0 for category in EmailCategory}
        evidence: list[str] = []

        def add(category: EmailCategory, weight: float, reason: str) -> None:
            scores[category.value] += weight
            if reason and reason not in evidence:
                evidence.append(reason)

        if signals.spam_like:
            add(EmailCategory.spam_like, 7.0, "spam or scam markers detected")
        if signals.finance_invoice:
            add(EmailCategory.finance, 5.5, "invoice or payment-due context detected")
        if signals.finance_receipt:
            add(EmailCategory.finance, 4.2, "receipt or payment confirmation detected")
        if signals.recruiter:
            add(EmailCategory.opportunity, 5.0, "direct recruiter or interview context detected")
        if signals.job_alert:
            add(EmailCategory.low_priority, 4.8, "automated job-platform alert detected")
        if signals.work_dev:
            add(EmailCategory.work, 5.0, "developer tooling, GitHub, or AI workflow detected")
        if signals.promo:
            add(EmailCategory.promo, 4.6, "promotional or discount language detected")
        if signals.newsletter:
            add(
                EmailCategory.newsletter,
                4.4 if signals.high_value_newsletter else 4.0,
                "newsletter or digest pattern detected",
            )
        if signals.security:
            add(EmailCategory.urgent, 3.8, "account or security-sensitive notice detected")
        if signals.deadline and not signals.automated:
            add(EmailCategory.urgent, 3.2, "explicit deadline or same-day urgency detected")
            add(EmailCategory.work, 0.7, "deadline pressure often implies work follow-up")
            add(EmailCategory.opportunity, 0.7, "deadline pressure often implies active follow-up")
            add(EmailCategory.finance, 0.5, "deadline pressure can matter for finance mail")
        if signals.opportunity and not signals.job_alert:
            add(EmailCategory.opportunity, 2.2, "opportunity or partnership language detected")
        if signals.personal:
            add(EmailCategory.personal, 2.4, "personal-life context detected")
        if signals.social and not signals.security:
            add(EmailCategory.low_priority, 2.4, "social media update pattern detected")
            add(EmailCategory.personal, 0.6, "social updates are usually personal context")
        if signals.automated:
            add(EmailCategory.low_priority, 1.0, "automated delivery pattern detected")

        work_prior = max(sender_scores["work"], domain_scores["work"])
        opportunity_prior = max(sender_scores["opportunity"], domain_scores["opportunity"])
        jobs_prior = max(sender_scores["jobs"], domain_scores["jobs"])
        recruiter_prior = max(sender_scores["recruiter"], domain_scores["recruiter"])
        finance_prior = max(sender_scores["finance"], domain_scores["finance"])
        promo_prior = max(sender_scores["promo"], domain_scores["promo"])
        newsletter_prior = max(sender_scores["newsletter"], domain_scores["newsletter"])
        social_prior = max(sender_scores["social"], domain_scores["social"])
        security_prior = max(sender_scores["security"], domain_scores["security"])
        spam_prior = max(sender_scores["spam"], domain_scores["spam"])
        personal_prior = max(sender_scores["personal"], domain_scores["personal"])
        automation_prior = max(sender_scores["automated"], domain_scores["automated"])
        human_prior = max(sender_scores["human"], domain_scores["human"])

        if work_prior > 0.1:
            add(EmailCategory.work, 2.6 * work_prior, "sender history leans strongly toward work")
        if opportunity_prior > 0.1:
            add(
                EmailCategory.opportunity,
                2.0 * opportunity_prior,
                "sender history leans toward opportunities or active threads",
            )
        if jobs_prior > 0.1:
            if signals.automated or automation_prior >= 0.5:
                add(
                    EmailCategory.low_priority,
                    2.2 * jobs_prior,
                    "sender history points to automated job-platform mail",
                )
            else:
                add(
                    EmailCategory.opportunity,
                    1.8 * jobs_prior,
                    "sender history points to job-related correspondence",
                )
        if recruiter_prior > 0.1:
            add(
                EmailCategory.opportunity,
                2.5 * recruiter_prior,
                "sender history looks like direct recruiting outreach",
            )
        if finance_prior > 0.1:
            add(EmailCategory.finance, 2.3 * finance_prior, "sender history is finance-heavy")
        if promo_prior > 0.1:
            add(EmailCategory.promo, 2.2 * promo_prior, "sender history is mostly promotional")
        if newsletter_prior > 0.1:
            add(
                EmailCategory.newsletter,
                2.0 * newsletter_prior,
                "sender history is mostly newsletter traffic",
            )
        if social_prior > 0.1:
            add(
                EmailCategory.low_priority,
                1.6 * social_prior,
                "sender history looks like social-media updates",
            )
        if security_prior > 0.1:
            add(
                EmailCategory.urgent,
                2.0 * security_prior,
                "sender history includes security-sensitive notices",
            )
        if spam_prior > 0.1:
            add(EmailCategory.spam_like, 2.2 * spam_prior, "sender history trends spam-like")
        if personal_prior > 0.1 and human_prior >= 0.3:
            add(
                EmailCategory.personal,
                1.6 * personal_prior,
                "sender history looks like personal correspondence",
            )

        if not any(score > 0 for score in scores.values()):
            if human_prior >= 0.55:
                add(EmailCategory.personal, 1.2, "human sender pattern detected")
            elif automation_prior >= 0.55:
                add(EmailCategory.low_priority, 1.1, "automated sender pattern detected")

        ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)
        top_category, top_score = ranked[0]
        second_score = ranked[1][1] if len(ranked) > 1 else 0.0
        if top_score < 1.0:
            return EmailClassification(
                category=EmailCategory.unknown,
                priority=PriorityLevel.medium if email.has_attachments else PriorityLevel.low,
                confidence=0.55,
                reason="Signals were too weak or contradictory; keep for review.",
            )

        priority = self._priority_for_category(
            category=top_category,
            email=email,
            signals=signals,
            human_prior=human_prior,
            importance_prior=max(sender_scores["importance"], domain_scores["importance"]),
            text=text,
        )
        confidence = self._confidence_from_scores(top_score, second_score, evidence)
        reason = self._reason_from_evidence(evidence, default=top_category)
        return EmailClassification(
            category=EmailCategory(top_category),
            priority=priority,
            confidence=confidence,
            reason=reason,
        )

    def _priority_for_category(
        self,
        *,
        category: str,
        email: EmailMessage,
        signals,
        human_prior: float,
        importance_prior: float,
        text: str,
    ) -> PriorityLevel:
        if category in {
            EmailCategory.spam_like.value,
            EmailCategory.promo.value,
            EmailCategory.low_priority.value,
        }:
            return PriorityLevel.low
        if category == EmailCategory.newsletter.value:
            return (
                PriorityLevel.medium
                if signals.high_value_newsletter or importance_prior >= 0.55
                else PriorityLevel.low
            )
        if category == EmailCategory.finance.value:
            if signals.finance_invoice and (signals.deadline or email.has_attachments):
                return PriorityLevel.high
            return PriorityLevel.medium
        if category == EmailCategory.opportunity.value:
            if (
                signals.recruiter
                or signals.deadline
                or importance_prior >= 0.65
                or (signals.opportunity and not signals.automated)
            ):
                return PriorityLevel.high
            return PriorityLevel.medium
        if category == EmailCategory.work.value:
            if signals.deadline:
                return PriorityLevel.high
            if email.has_attachments and not signals.automated:
                return PriorityLevel.high
            if human_prior >= 0.7 and importance_prior >= 0.6:
                return PriorityLevel.high
            return PriorityLevel.medium
        if category == EmailCategory.urgent.value:
            if signals.deadline and not signals.automated:
                return PriorityLevel.critical
            if signals.security and ("immediately" in text or "urgent" in text):
                return PriorityLevel.critical
            return PriorityLevel.high
        if category == EmailCategory.personal.value:
            if signals.reply_needed or human_prior >= 0.65:
                return PriorityLevel.medium
            return PriorityLevel.low
        return PriorityLevel.medium if email.has_attachments else PriorityLevel.low

    def _confidence_from_scores(
        self,
        top_score: float,
        second_score: float,
        evidence: list[str],
    ) -> float:
        gap = max(top_score - second_score, 0.0)
        confidence = 0.58
        confidence += min(0.14, top_score / 8.0 * 0.14)
        confidence += min(0.18, gap / 3.5 * 0.18)
        if top_score >= 4.0:
            confidence += 0.08
        if len(evidence) >= 2:
            confidence += 0.04
        return min(confidence, 0.98)

    def _reason_from_evidence(self, evidence: list[str], *, default: str) -> str:
        if not evidence:
            return f"Classified as {default} from weak fallback signals."
        if len(evidence) == 1:
            return evidence[0].capitalize() + "."
        return f"{evidence[0].capitalize()}; {evidence[1]}."
