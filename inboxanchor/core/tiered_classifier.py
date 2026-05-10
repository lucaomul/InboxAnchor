from __future__ import annotations

from inboxanchor.models.email import EmailCategory, EmailClassification, EmailMessage, PriorityLevel
from inboxanchor.sender_intelligence import MessageSignals, analyze_message_signals

ARCHETYPE_TO_CATEGORY: dict[str, EmailCategory] = {
    "job_platform_alert": EmailCategory.opportunity,
    "shopping_promo": EmailCategory.promo,
    "social_update": EmailCategory.low_priority,
    "social_security": EmailCategory.urgent,
    "finance_vendor": EmailCategory.finance,
    "newsletter_editorial": EmailCategory.newsletter,
    "newsletter_routine": EmailCategory.low_priority,
    "dev_tooling": EmailCategory.work,
    "recruiter_human": EmailCategory.opportunity,
    "spam_risk": EmailCategory.spam_like,
    "human_work": EmailCategory.work,
    "human_personal": EmailCategory.personal,
}


class TieredClassifier:
    """
    Three-tier classifier. Tier 1 and Tier 2 avoid LLM calls entirely.
    Tier 3 falls back to the existing ClassifierAgent behavior.
    """

    ARCHETYPE_CONFIDENCE_THRESHOLD = 0.72
    SIGNAL_CONFIDENCE_THRESHOLD = 0.70

    def classify(
        self,
        email: EmailMessage,
        *,
        sender_profile: dict | None = None,
        domain_profile: dict | None = None,
    ) -> EmailClassification:
        result, _ = self.classify_with_tier(
            email,
            sender_profile=sender_profile,
            domain_profile=domain_profile,
        )
        return result

    def classify_with_tier(
        self,
        email: EmailMessage,
        *,
        sender_profile: dict | None = None,
        domain_profile: dict | None = None,
    ) -> tuple[EmailClassification, int]:
        """Return (classification, tier_used)."""
        tier1 = self._try_tier1(
            sender_profile=sender_profile,
            domain_profile=domain_profile,
        )
        if tier1 is not None:
            return tier1, 1

        signals = analyze_message_signals(email)
        tier2 = self._try_tier2(signals)
        if tier2 is not None:
            return tier2, 2

        from inboxanchor.agents.classifier import ClassifierAgent

        result = ClassifierAgent().classify(email)
        reason = (result.reason or "").strip()
        suffix = "(tier 3 - LLM fallback)"
        result = result.model_copy(
            update={
                "reason": f"{reason} {suffix}".strip() if reason else suffix,
            }
        )
        return result, 3

    def _try_tier1(
        self,
        *,
        sender_profile: dict | None,
        domain_profile: dict | None,
    ) -> EmailClassification | None:
        profile = sender_profile or domain_profile
        if not profile:
            return None

        archetype = str(profile.get("archetype") or "").strip()
        confidence = float(profile.get("archetype_confidence", 0.0) or 0.0)
        if not archetype or confidence < self.ARCHETYPE_CONFIDENCE_THRESHOLD:
            return None

        category = ARCHETYPE_TO_CATEGORY.get(archetype)
        if category is None:
            return None

        if archetype in {"social_security", "recruiter_human", "human_work"}:
            priority = PriorityLevel.high
        elif archetype in {"finance_vendor", "dev_tooling", "human_personal"}:
            priority = PriorityLevel.medium
        else:
            priority = PriorityLevel.low

        return EmailClassification(
            category=category,
            priority=priority,
            confidence=confidence,
            reason=f"Sender archetype: {archetype} (tier 1 - no LLM)",
        )

    def _try_tier2(self, signals: MessageSignals) -> EmailClassification | None:
        """
        Deterministic signal priority order. First match wins.
        """
        rules: list[tuple[bool, EmailCategory, PriorityLevel, float, str]] = [
            (
                signals.security,
                EmailCategory.urgent,
                PriorityLevel.critical,
                0.92,
                "Security signal detected",
            ),
            (
                signals.finance_invoice,
                EmailCategory.finance,
                PriorityLevel.high,
                0.91,
                "Finance invoice signal",
            ),
            (
                signals.finance_receipt,
                EmailCategory.finance,
                PriorityLevel.medium,
                0.90,
                "Finance receipt signal",
            ),
            (
                signals.spam_like,
                EmailCategory.spam_like,
                PriorityLevel.low,
                0.89,
                "Spam-like signal",
            ),
            (
                signals.reply_needed and signals.human_like and not signals.automated,
                EmailCategory.work,
                PriorityLevel.high,
                0.87,
                "Reply needed from human sender",
            ),
            (
                signals.recruiter and not signals.automated,
                EmailCategory.opportunity,
                PriorityLevel.high,
                0.87,
                "Recruiter signal from human sender",
            ),
            (
                signals.job_related and signals.automated,
                EmailCategory.opportunity,
                PriorityLevel.low,
                0.85,
                "Job alert from automated sender",
            ),
            (
                signals.work_dev,
                EmailCategory.work,
                PriorityLevel.high,
                0.86,
                "Dev tooling signal",
            ),
            (
                signals.high_value_newsletter,
                EmailCategory.newsletter,
                PriorityLevel.medium,
                0.87,
                "High-value newsletter signal",
            ),
            (
                signals.newsletter and not signals.high_value_newsletter,
                EmailCategory.low_priority,
                PriorityLevel.low,
                0.84,
                "Routine newsletter signal",
            ),
            (
                signals.promo and signals.automated,
                EmailCategory.promo,
                PriorityLevel.low,
                0.86,
                "Promotional automated signal",
            ),
            (
                signals.personal and signals.human_like,
                EmailCategory.personal,
                PriorityLevel.medium,
                0.78,
                "Personal signal from human sender",
            ),
        ]

        for condition, category, priority, confidence, reason in rules:
            if condition and confidence >= self.SIGNAL_CONFIDENCE_THRESHOLD:
                return EmailClassification(
                    category=category,
                    priority=priority,
                    confidence=confidence,
                    reason=f"{reason} (tier 2 - no LLM)",
                )
        return None
