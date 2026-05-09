from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Optional

from inboxanchor.mail_intelligence import (
    has_deadline_pressure,
    has_reply_needed_signal,
    is_finance_invoice,
    is_finance_receipt,
    is_high_value_newsletter,
    is_job_alert,
    is_job_related,
    is_newsletter,
    is_promo,
    is_recruiter_or_interview,
    is_spam_like,
    is_work_dev_or_ai,
    looks_automated_email,
    sender_address,
    sender_domain,
    signal_text,
)
from inboxanchor.models import EmailMessage

SOCIAL_MARKERS = {
    "instagram",
    "facebook",
    "messenger",
    "twitter",
    "x.com",
    "tiktok",
    "reddit",
    "discord",
    "youtube",
    "pinterest",
    "snapchat",
    "threads",
    "telegram",
}

SOCIAL_UPDATE_MARKERS = {
    "new follower",
    "liked your",
    "commented on",
    "mentioned you",
    "tagged you",
    "profile views",
    "new connection",
    "new subscribers",
}

SECURITY_MARKERS = {
    "security alert",
    "suspicious",
    "new login",
    "new sign-in",
    "signin",
    "sign-in",
    "password reset",
    "verify your account",
    "verification code",
    "two-factor",
    "2fa",
    "unusual activity",
    "new device",
    "recover your account",
}

PERSONAL_MARKERS = {
    "family",
    "birthday",
    "trip",
    "weekend",
    "dinner",
    "vacation",
    "wedding",
    "party",
    "photos",
}

OPPORTUNITY_MARKERS = {
    "partnership",
    "proposal",
    "term sheet",
    "investor",
    "opportunity",
    "collaboration",
}

PROFILE_COUNT_KEYS = (
    "total_messages",
    "unread_messages",
    "attachment_messages",
    "automated_messages",
    "human_messages",
    "work_messages",
    "opportunity_messages",
    "job_messages",
    "recruiter_messages",
    "finance_messages",
    "promo_messages",
    "newsletter_messages",
    "high_value_newsletter_messages",
    "social_messages",
    "security_messages",
    "urgent_messages",
    "personal_messages",
    "spam_messages",
    "reply_signal_messages",
)

PROFILE_SCORE_KEYS = (
    "automated",
    "human",
    "work",
    "opportunity",
    "jobs",
    "recruiter",
    "finance",
    "promo",
    "newsletter",
    "high_value_newsletter",
    "social",
    "security",
    "urgent",
    "personal",
    "spam",
    "reply_needed",
    "importance",
)


def _contains_any(text: str, markers: set[str]) -> bool:
    return any(marker in text for marker in markers)


def _display_name(sender: str) -> str:
    if "<" in sender and ">" in sender:
        return sender.rsplit("<", 1)[0].strip().strip('"')
    return sender.strip()


@dataclass(frozen=True)
class MessageSignals:
    automated: bool
    spam_like: bool
    finance_invoice: bool
    finance_receipt: bool
    job_related: bool
    job_alert: bool
    recruiter: bool
    work_dev: bool
    newsletter: bool
    high_value_newsletter: bool
    promo: bool
    social: bool
    security: bool
    deadline: bool
    reply_needed: bool
    personal: bool
    opportunity: bool
    human_like: bool


@dataclass(frozen=True)
class SenderIntelligenceContext:
    sender_profile: Optional[dict[str, Any]]
    domain_profile: Optional[dict[str, Any]]
    message_signals: MessageSignals


def analyze_message_signals(email: EmailMessage) -> MessageSignals:
    body = email.content_for_processing()
    text = signal_text(
        sender=email.sender,
        subject=email.subject,
        snippet=email.snippet,
        body=body,
    )
    domain = sender_domain(email.sender)
    automated = looks_automated_email(
        sender=email.sender,
        subject=email.subject,
        snippet=email.snippet,
        body=body,
    )
    newsletter = is_newsletter(
        sender=email.sender,
        subject=email.subject,
        snippet=email.snippet,
        body=body,
    )
    promo = is_promo(
        sender=email.sender,
        subject=email.subject,
        snippet=email.snippet,
        body=body,
    )
    job_related = is_job_related(
        sender=email.sender,
        subject=email.subject,
        snippet=email.snippet,
        body=body,
    )
    social = (
        _contains_any(text, SOCIAL_MARKERS)
        or (domain and any(marker in domain for marker in SOCIAL_MARKERS))
        or _contains_any(text, SOCIAL_UPDATE_MARKERS)
    )
    security = _contains_any(text, SECURITY_MARKERS)
    recruiter = (
        is_recruiter_or_interview(
            sender=email.sender,
            subject=email.subject,
            snippet=email.snippet,
            body=body,
        )
        and not automated
    )
    work_dev = is_work_dev_or_ai(
        sender=email.sender,
        subject=email.subject,
        snippet=email.snippet,
        body=body,
    )
    personal = (
        _contains_any(text, PERSONAL_MARKERS)
        and not automated
        and not job_related
        and not work_dev
    )
    opportunity = recruiter or _contains_any(text, OPPORTUNITY_MARKERS)
    high_value_newsletter = newsletter and is_high_value_newsletter(
        sender=email.sender,
        subject=email.subject,
        snippet=email.snippet,
        body=body,
    )
    if social and security:
        work_dev = False
    human_like = (
        not automated
        and not newsletter
        and not promo
        and not social
        and not is_job_alert(
            sender=email.sender,
            subject=email.subject,
            snippet=email.snippet,
            body=body,
        )
    )
    return MessageSignals(
        automated=automated,
        spam_like=is_spam_like(
            sender=email.sender,
            subject=email.subject,
            snippet=email.snippet,
            body=body,
        ),
        finance_invoice=is_finance_invoice(
            sender=email.sender,
            subject=email.subject,
            snippet=email.snippet,
            body=body,
        ),
        finance_receipt=is_finance_receipt(
            sender=email.sender,
            subject=email.subject,
            snippet=email.snippet,
            body=body,
        ),
        job_related=job_related,
        job_alert=is_job_alert(
            sender=email.sender,
            subject=email.subject,
            snippet=email.snippet,
            body=body,
        ),
        recruiter=recruiter,
        work_dev=work_dev,
        newsletter=newsletter,
        high_value_newsletter=high_value_newsletter,
        promo=promo,
        social=social,
        security=security,
        deadline=has_deadline_pressure(
            sender=email.sender,
            subject=email.subject,
            snippet=email.snippet,
            body=body,
        ),
        reply_needed=has_reply_needed_signal(
            sender=email.sender,
            subject=email.subject,
            snippet=email.snippet,
            body=body,
        ),
        personal=personal,
        opportunity=opportunity,
        human_like=human_like,
    )


def _new_profile_payload(provider: str, *, key_name: str, key_value: str) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "provider": provider,
        key_name: key_value,
        "first_seen_at": "",
        "last_seen_at": "",
        "last_subject": "",
        "archetype": "unknown",
        "archetype_confidence": 0.0,
        "scores": {},
    }
    for field in PROFILE_COUNT_KEYS:
        payload[field] = 0
    return payload


def new_sender_profile_payload(provider: str, sender: str) -> dict[str, Any]:
    payload = _new_profile_payload(provider, key_name="sender_address", key_value=sender)
    payload["sender_domain"] = sender_domain(sender)
    payload["display_name"] = ""
    return payload


def new_domain_profile_payload(provider: str, domain: str) -> dict[str, Any]:
    return _new_profile_payload(provider, key_name="domain", key_value=domain)


def _ratio(profile: Mapping[str, Any], numerator_key: str) -> float:
    total = max(int(profile.get("total_messages") or 0), 1)
    return min(1.0, float(profile.get(numerator_key) or 0) / total)


def profile_scores(profile: Optional[Mapping[str, Any]]) -> dict[str, float]:
    if not profile:
        return {key: 0.0 for key in PROFILE_SCORE_KEYS}
    stored_scores = profile.get("scores")
    if isinstance(stored_scores, Mapping) and stored_scores:
        return {key: float(stored_scores.get(key, 0.0) or 0.0) for key in PROFILE_SCORE_KEYS}

    scores = {
        "automated": _ratio(profile, "automated_messages"),
        "human": _ratio(profile, "human_messages"),
        "work": _ratio(profile, "work_messages"),
        "opportunity": _ratio(profile, "opportunity_messages"),
        "jobs": _ratio(profile, "job_messages"),
        "recruiter": _ratio(profile, "recruiter_messages"),
        "finance": _ratio(profile, "finance_messages"),
        "promo": _ratio(profile, "promo_messages"),
        "newsletter": _ratio(profile, "newsletter_messages"),
        "high_value_newsletter": _ratio(profile, "high_value_newsletter_messages"),
        "social": _ratio(profile, "social_messages"),
        "security": _ratio(profile, "security_messages"),
        "urgent": _ratio(profile, "urgent_messages"),
        "personal": _ratio(profile, "personal_messages"),
        "spam": _ratio(profile, "spam_messages"),
        "reply_needed": _ratio(profile, "reply_signal_messages"),
        "importance": 0.0,
    }
    weighted = (
        scores["human"] * 0.4
        + scores["work"] * 1.0
        + scores["opportunity"] * 1.1
        + scores["finance"] * 1.0
        + scores["security"] * 1.25
        + scores["urgent"] * 1.2
        + scores["recruiter"] * 1.0
    )
    scores["importance"] = min(1.0, weighted / 2.2)
    return scores


def infer_profile_archetype(profile: Mapping[str, Any]) -> tuple[str, float]:
    scores = profile_scores(profile)
    if scores["spam"] >= 0.55:
        return "spam_risk", min(0.99, 0.7 + scores["spam"] * 0.25)
    if scores["security"] >= 0.4 and scores["social"] >= 0.2:
        return "social_security", min(0.99, 0.65 + scores["security"] * 0.25)
    if scores["recruiter"] >= 0.3 and scores["human"] >= 0.35:
        return "recruiter_human", min(0.99, 0.62 + scores["recruiter"] * 0.3)
    if scores["jobs"] >= 0.45 and scores["automated"] >= 0.5:
        return "job_platform_alert", min(0.99, 0.62 + scores["jobs"] * 0.25)
    if scores["work"] >= 0.45 and scores["automated"] >= 0.35:
        return "dev_tooling", min(0.99, 0.62 + scores["work"] * 0.22)
    if scores["finance"] >= 0.45 and scores["promo"] < 0.35:
        return "finance_vendor", min(0.99, 0.6 + scores["finance"] * 0.25)
    if scores["promo"] >= 0.55:
        return "shopping_promo", min(0.99, 0.6 + scores["promo"] * 0.25)
    if scores["newsletter"] >= 0.55 and scores["high_value_newsletter"] >= 0.3:
        return "newsletter_editorial", min(0.99, 0.58 + scores["newsletter"] * 0.2)
    if scores["newsletter"] >= 0.55:
        return "newsletter_routine", min(0.99, 0.56 + scores["newsletter"] * 0.18)
    if scores["social"] >= 0.5 and scores["security"] < 0.3:
        return "social_update", min(0.99, 0.56 + scores["social"] * 0.18)
    if scores["human"] >= 0.6 and scores["work"] >= 0.3:
        return "human_work", min(0.99, 0.56 + scores["human"] * 0.16)
    if scores["human"] >= 0.6 and scores["personal"] >= 0.3:
        return "human_personal", min(0.99, 0.56 + scores["human"] * 0.16)
    return "unknown", 0.3


def observe_profile_email(
    profile: Optional[Mapping[str, Any]],
    *,
    provider: str,
    email: EmailMessage,
    signals: Optional[MessageSignals] = None,
    profile_kind: str = "sender",
    count_message: bool = True,
) -> dict[str, Any]:
    sender_value = sender_address(email.sender)
    domain_value = sender_domain(email.sender)
    base = (
        dict(profile)
        if profile is not None
        else (
            new_sender_profile_payload(provider, sender_value)
            if profile_kind == "sender"
            else new_domain_profile_payload(provider, domain_value)
        )
    )
    if signals is None:
        signals = analyze_message_signals(email)

    received_at = email.received_at.isoformat()
    first_seen_at = str(base.get("first_seen_at") or "")
    last_seen_at = str(base.get("last_seen_at") or "")
    if not first_seen_at or received_at < first_seen_at:
        base["first_seen_at"] = received_at
    if not last_seen_at or received_at > last_seen_at:
        base["last_seen_at"] = received_at
    base["last_subject"] = (email.subject or "")[:255]

    if profile_kind == "sender":
        base["sender_address"] = sender_value
        base["sender_domain"] = domain_value
        base["display_name"] = _display_name(email.sender)
    else:
        base["domain"] = domain_value

    if count_message:
        base["total_messages"] = int(base.get("total_messages") or 0) + 1
        if email.unread:
            base["unread_messages"] = int(base.get("unread_messages") or 0) + 1
        if email.has_attachments:
            base["attachment_messages"] = int(base.get("attachment_messages") or 0) + 1
        if signals.automated:
            base["automated_messages"] = int(base.get("automated_messages") or 0) + 1
        if signals.human_like:
            base["human_messages"] = int(base.get("human_messages") or 0) + 1
        if signals.work_dev:
            base["work_messages"] = int(base.get("work_messages") or 0) + 1
        if signals.opportunity:
            base["opportunity_messages"] = int(base.get("opportunity_messages") or 0) + 1
        if signals.job_related:
            base["job_messages"] = int(base.get("job_messages") or 0) + 1
        if signals.recruiter:
            base["recruiter_messages"] = int(base.get("recruiter_messages") or 0) + 1
        if signals.finance_invoice or signals.finance_receipt:
            base["finance_messages"] = int(base.get("finance_messages") or 0) + 1
        if signals.promo:
            base["promo_messages"] = int(base.get("promo_messages") or 0) + 1
        if signals.newsletter:
            base["newsletter_messages"] = int(base.get("newsletter_messages") or 0) + 1
        if signals.high_value_newsletter:
            base["high_value_newsletter_messages"] = (
                int(base.get("high_value_newsletter_messages") or 0) + 1
            )
        if signals.social:
            base["social_messages"] = int(base.get("social_messages") or 0) + 1
        if signals.security:
            base["security_messages"] = int(base.get("security_messages") or 0) + 1
        if signals.deadline:
            base["urgent_messages"] = int(base.get("urgent_messages") or 0) + 1
        if signals.personal:
            base["personal_messages"] = int(base.get("personal_messages") or 0) + 1
        if signals.spam_like:
            base["spam_messages"] = int(base.get("spam_messages") or 0) + 1
        if signals.reply_needed:
            base["reply_signal_messages"] = int(base.get("reply_signal_messages") or 0) + 1

    scores = profile_scores(base)
    archetype, confidence = infer_profile_archetype(base)
    base["scores"] = scores
    base["archetype"] = archetype
    base["archetype_confidence"] = confidence
    return base


class SenderIntelligenceResolver:
    def __init__(self, provider: str):
        self.provider = provider
        self._sender_cache: dict[str, Optional[dict[str, Any]]] = {}
        self._domain_cache: dict[str, Optional[dict[str, Any]]] = {}

    def _load_sender_profile(self, address: str) -> Optional[dict[str, Any]]:
        if address in self._sender_cache:
            return self._sender_cache[address]
        from inboxanchor.infra.database import session_scope
        from inboxanchor.infra.repository import InboxRepository

        with session_scope() as session:
            profile = InboxRepository(session).get_sender_profile(self.provider, address)
        self._sender_cache[address] = dict(profile) if profile else None
        return self._sender_cache[address]

    def _load_domain_profile(self, domain: str) -> Optional[dict[str, Any]]:
        if domain in self._domain_cache:
            return self._domain_cache[domain]
        from inboxanchor.infra.database import session_scope
        from inboxanchor.infra.repository import InboxRepository

        with session_scope() as session:
            profile = InboxRepository(session).get_domain_profile(self.provider, domain)
        self._domain_cache[domain] = dict(profile) if profile else None
        return self._domain_cache[domain]

    def resolve(self, email: EmailMessage) -> SenderIntelligenceContext:
        address = sender_address(email.sender)
        domain = sender_domain(email.sender)
        return SenderIntelligenceContext(
            sender_profile=self._load_sender_profile(address) if address else None,
            domain_profile=self._load_domain_profile(domain) if domain else None,
            message_signals=analyze_message_signals(email),
        )

    def observe(
        self,
        email: EmailMessage,
        *,
        context: Optional[SenderIntelligenceContext] = None,
    ) -> None:
        context = context or self.resolve(email)
        signals = context.message_signals
        address = sender_address(email.sender)
        domain = sender_domain(email.sender)
        if address:
            self._sender_cache[address] = observe_profile_email(
                context.sender_profile,
                provider=self.provider,
                email=email,
                signals=signals,
                profile_kind="sender",
                count_message=True,
            )
        if domain:
            self._domain_cache[domain] = observe_profile_email(
                context.domain_profile,
                provider=self.provider,
                email=email,
                signals=signals,
                profile_kind="domain",
                count_message=True,
            )
