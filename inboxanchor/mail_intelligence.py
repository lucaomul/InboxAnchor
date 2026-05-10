from __future__ import annotations

import re
from email.utils import parseaddr
from typing import TYPE_CHECKING

from inboxanchor.infra.text_normalizer import normalize_email_body_text

if TYPE_CHECKING:
    from inboxanchor.sender_intelligence import MessageSignals

FREE_EMAIL_DOMAINS = {
    "gmail.com",
    "yahoo.com",
    "hotmail.com",
    "outlook.com",
    "icloud.com",
    "me.com",
    "proton.me",
    "protonmail.com",
}

AUTOMATED_LOCAL_PART_MARKERS = {
    "noreply",
    "no-reply",
    "do-not-reply",
    "donotreply",
    "notifications",
    "notification",
    "alerts",
    "updates",
    "digest",
    "newsletter",
    "mailer-daemon",
}

JOB_PLATFORM_MARKERS = {
    "linkedin",
    "greenhouse",
    "lever",
    "workable",
    "ashby",
    "indeed",
    "bestjobs",
    "wellfound",
    "welcome to the jungle",
    "welcometothejungle",
    "adecco",
    "glassdoor",
}

DEV_WORK_MARKERS = {
    "github",
    "gitlab",
    "bitbucket",
    "jira",
    "linear",
    "vercel",
    "sentry",
    "notion",
    "slack",
    "pull request",
    "merge request",
    "build failed",
    "ci",
    "issue",
    "repo",
}

AI_TOPIC_MARKERS = {
    "openai",
    "anthropic",
    "llm",
    "gpt",
    "claude",
    "cursor",
    "ai",
    "artificial intelligence",
    "machine learning",
}

PROMO_MARKERS = {
    "discount",
    "sale",
    "limited offer",
    "promo code",
    "special offer",
    "coupon",
    "upgrade now",
    "trial expires",
    "save big",
    "ends tonight",
}

NEWSLETTER_MARKERS = {
    "unsubscribe",
    "newsletter",
    "digest",
    "briefing",
    "daily update",
    "weekly update",
    "top stories",
}

HIGH_VALUE_NEWSLETTER_MARKERS = {
    "techcrunch",
    "product hunt",
    "producthunt",
    "hacker news",
    "stratechery",
    "substack",
    "a16z",
    "sequoia",
}

SPAM_MARKERS = {
    "claim now",
    "winner",
    "wire transfer",
    "bitcoin",
    "wallet verification",
    "gift card",
    "lottery",
}

FINANCE_INVOICE_MARKERS = {
    "invoice",
    "bill due",
    "payment due",
    "remittance",
    "balance due",
}

FINANCE_RECEIPT_MARKERS = {
    "receipt",
    "payment confirmation",
    "order confirmation",
    "charged",
    "refund processed",
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

LEGAL_MARKERS = {
    "contract",
    "msa",
    "nda",
    "dpa",
    "redline",
    "signature request",
    "sign this",
}

MEETING_MARKERS = {
    "meeting",
    "follow-up",
    "follow up",
    "calendar",
    "sync",
    "agenda",
    "reschedule",
    "call notes",
}

WAITING_MARKERS = {
    "following up",
    "circling back",
    "checking in",
    "any update",
    "just bumping this",
}

REPLY_SIGNAL_MARKERS = {
    "please reply",
    "please respond",
    "reply by",
    "let me know",
    "can you",
    "could you",
    "would you",
    "please review",
    "please confirm",
    "please send",
    "send over",
    "need your input",
    "need your feedback",
    "what do you think",
    "share your thoughts",
    "awaiting your response",
}

DEADLINE_MARKERS = {
    "urgent",
    "asap",
    "today",
    "immediately",
    "by eod",
    "deadline",
    "before 4 pm",
    "before 5 pm",
    "this week",
}

INBOXANCHOR_LABEL_PREFIXES = (
    "needs-reply/",
    "finance/",
    "legal/",
    "meetings/",
    "projects/",
    "newsletters/",
    "promo/",
    "automation/",
    "cleanup/",
    "jobs/",
    "work/",
    "topics/",
    "clients/",
    "priority/",
    "attachments/",
)

INBOXANCHOR_ALIAS_LABEL_PREFIX = "inboxanchor/aliases"

SINGLE_INBOXANCHOR_LABELS = {
    "needs-reply",
    "finance",
    "jobs",
    "newsletter",
    "cleanup",
    "work",
    "personal",
    "security",
}

LEGACY_INBOXANCHOR_LABELS = {
    "work",
    "finance",
    "newsletter",
    "promo",
    "personal",
    "opportunity",
    "urgent",
    "low-priority",
    "low_priority",
    "needs-action",
    "action-needed",
    "cleanup-candidate",
    "spam-review",
    "needs-review",
    "has-attachments",
    "priority-high",
    "priority-critical",
    "waiting-for-response",
}


def signal_text(
    *,
    sender: str,
    subject: str,
    snippet: str = "",
    body: str = "",
) -> str:
    readable_body = normalize_email_body_text(body)
    return " \n".join(
        part.strip().lower()
        for part in (sender, subject, snippet, readable_body)
        if part and part.strip()
    )


def sender_address(sender: str) -> str:
    return parseaddr(sender or "")[1].strip().lower()


def sender_domain(sender: str) -> str:
    address = sender_address(sender)
    return address.partition("@")[2]


def sender_local_part(sender: str) -> str:
    address = sender_address(sender)
    return address.partition("@")[0]


def looks_automated_email(
    *,
    sender: str,
    subject: str,
    snippet: str = "",
    body: str = "",
) -> bool:
    local = sender_local_part(sender)
    text = signal_text(sender=sender, subject=subject, snippet=snippet, body=body)
    if any(marker in local for marker in AUTOMATED_LOCAL_PART_MARKERS):
        return True
    return any(
        marker in text
        for marker in ("unsubscribe", "manage preferences", "view in browser", "notification")
    )


def is_spam_like(*, sender: str, subject: str, snippet: str = "", body: str = "") -> bool:
    return _contains_any(
        signal_text(sender=sender, subject=subject, snippet=snippet, body=body),
        SPAM_MARKERS,
    )


def is_finance_invoice(*, sender: str, subject: str, snippet: str = "", body: str = "") -> bool:
    return _contains_any(
        signal_text(sender=sender, subject=subject, snippet=snippet, body=body),
        FINANCE_INVOICE_MARKERS,
    )


def is_finance_receipt(*, sender: str, subject: str, snippet: str = "", body: str = "") -> bool:
    return _contains_any(
        signal_text(sender=sender, subject=subject, snippet=snippet, body=body),
        FINANCE_RECEIPT_MARKERS,
    )


def is_job_related(*, sender: str, subject: str, snippet: str = "", body: str = "") -> bool:
    text = signal_text(sender=sender, subject=subject, snippet=snippet, body=body)
    return _contains_any(text, JOB_PLATFORM_MARKERS) or _contains_any(
        text,
        {"job", "application", "interview", "recruiter", "hiring", "candidate", "role"},
    )


def is_job_alert(*, sender: str, subject: str, snippet: str = "", body: str = "") -> bool:
    text = signal_text(sender=sender, subject=subject, snippet=snippet, body=body)
    automated = looks_automated_email(
        sender=sender,
        subject=subject,
        snippet=snippet,
        body=body,
    )
    return automated and (
        _contains_any(text, JOB_PLATFORM_MARKERS)
        or _contains_any(text, {"job alert", "new match", "profile viewed", "recommended jobs"})
    )


def is_recruiter_or_interview(
    *,
    sender: str,
    subject: str,
    snippet: str = "",
    body: str = "",
) -> bool:
    text = signal_text(sender=sender, subject=subject, snippet=snippet, body=body)
    return _contains_any(
        text,
        {
            "interview",
            "talent acquisition",
            "recruiter",
            "hiring manager",
            "application was sent",
            "application update",
            "schedule a call",
            "candidate",
        },
    )


def is_work_dev_or_ai(*, sender: str, subject: str, snippet: str = "", body: str = "") -> bool:
    text = signal_text(sender=sender, subject=subject, snippet=snippet, body=body)
    return _contains_any(text, DEV_WORK_MARKERS) or _contains_any(text, AI_TOPIC_MARKERS)


def is_high_value_newsletter(
    *,
    sender: str,
    subject: str,
    snippet: str = "",
    body: str = "",
) -> bool:
    text = signal_text(sender=sender, subject=subject, snippet=snippet, body=body)
    return _contains_any(text, NEWSLETTER_MARKERS) and _contains_any(
        text,
        HIGH_VALUE_NEWSLETTER_MARKERS,
    )


def is_newsletter(*, sender: str, subject: str, snippet: str = "", body: str = "") -> bool:
    return _contains_any(
        signal_text(sender=sender, subject=subject, snippet=snippet, body=body),
        NEWSLETTER_MARKERS,
    )


def is_promo(*, sender: str, subject: str, snippet: str = "", body: str = "") -> bool:
    return _contains_any(
        signal_text(sender=sender, subject=subject, snippet=snippet, body=body),
        PROMO_MARKERS,
    )


def is_legal_contract(*, sender: str, subject: str, snippet: str = "", body: str = "") -> bool:
    return _contains_any(
        signal_text(sender=sender, subject=subject, snippet=snippet, body=body),
        LEGAL_MARKERS,
    )


def is_meeting_followup(*, sender: str, subject: str, snippet: str = "", body: str = "") -> bool:
    return _contains_any(
        signal_text(sender=sender, subject=subject, snippet=snippet, body=body),
        MEETING_MARKERS,
    )


def is_waiting_for_response(
    *,
    sender: str,
    subject: str,
    snippet: str = "",
    body: str = "",
) -> bool:
    return _contains_any(
        signal_text(sender=sender, subject=subject, snippet=snippet, body=body),
        WAITING_MARKERS,
    )


def has_deadline_pressure(*, sender: str, subject: str, snippet: str = "", body: str = "") -> bool:
    return _contains_any(
        signal_text(sender=sender, subject=subject, snippet=snippet, body=body),
        DEADLINE_MARKERS,
    )


def has_reply_needed_signal(
    *,
    sender: str,
    subject: str,
    snippet: str = "",
    body: str = "",
) -> bool:
    return _contains_any(
        signal_text(sender=sender, subject=subject, snippet=snippet, body=body),
        REPLY_SIGNAL_MARKERS,
    )


def extract_project_slug(
    *,
    sender: str,
    subject: str,
    snippet: str = "",
    body: str = "",
) -> str | None:
    text = f"{subject}\n{snippet}\n{body}"
    repo_match = re.search(r"\[([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)\]", text)
    if repo_match:
        return _slug(repo_match.group(2))
    project_match = re.search(r"(?i)\bproject[:\s-]+([A-Za-z0-9][A-Za-z0-9 _.-]{2,30})", text)
    if project_match:
        return _slug(project_match.group(1))
    return None


def extract_client_slug(*, sender: str, category: str) -> str | None:
    if category not in {"work", "finance", "opportunity", "urgent"}:
        return None
    domain = sender_domain(sender)
    if not domain or domain in FREE_EMAIL_DOMAINS:
        return None
    if any(
        platform in domain
        for platform in (
            "linkedin",
            "github",
            "gitlab",
            "openai",
            "anthropic",
            "stripe",
            "techcrunch",
            "producthunt",
        )
    ):
        return None
    return _slug(domain.split(".")[0])


def assign_single_label(
    *,
    sender: str,
    subject: str,
    snippet: str = "",
    body: str = "",
    has_attachments: bool = False,
    signals: "MessageSignals | None" = None,
) -> str:
    """Return exactly one visible mailbox label from InboxAnchor's 8-label set."""

    def _signal(name: str) -> bool:
        if signals is not None:
            return bool(getattr(signals, name, False))
        computed = computed_signals[name]
        return bool(computed)

    computed_signals = {
        "security": _contains_any(
            signal_text(sender=sender, subject=subject, snippet=snippet, body=body),
            {
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
            },
        ),
        "finance_invoice": is_finance_invoice(
            sender=sender,
            subject=subject,
            snippet=snippet,
            body=body,
        ),
        "finance_receipt": is_finance_receipt(
            sender=sender,
            subject=subject,
            snippet=snippet,
            body=body,
        ),
        "reply_needed": has_reply_needed_signal(
            sender=sender,
            subject=subject,
            snippet=snippet,
            body=body,
        ),
        "human_like": not looks_automated_email(
            sender=sender,
            subject=subject,
            snippet=snippet,
            body=body,
        )
        and not is_newsletter(sender=sender, subject=subject, snippet=snippet, body=body)
        and not is_promo(sender=sender, subject=subject, snippet=snippet, body=body)
        and not is_job_alert(sender=sender, subject=subject, snippet=snippet, body=body),
        "automated": looks_automated_email(
            sender=sender,
            subject=subject,
            snippet=snippet,
            body=body,
        ),
        "work_dev": is_work_dev_or_ai(
            sender=sender,
            subject=subject,
            snippet=snippet,
            body=body,
        ),
        "job_related": is_job_related(
            sender=sender,
            subject=subject,
            snippet=snippet,
            body=body,
        ),
        "recruiter": is_recruiter_or_interview(
            sender=sender,
            subject=subject,
            snippet=snippet,
            body=body,
        )
        and not looks_automated_email(
            sender=sender,
            subject=subject,
            snippet=snippet,
            body=body,
        ),
        "personal": _contains_any(
            signal_text(sender=sender, subject=subject, snippet=snippet, body=body),
            PERSONAL_MARKERS,
        )
        and not looks_automated_email(
            sender=sender,
            subject=subject,
            snippet=snippet,
            body=body,
        )
        and not is_job_related(sender=sender, subject=subject, snippet=snippet, body=body)
        and not is_work_dev_or_ai(sender=sender, subject=subject, snippet=snippet, body=body),
        "high_value_newsletter": is_newsletter(
            sender=sender,
            subject=subject,
            snippet=snippet,
            body=body,
        )
        and is_high_value_newsletter(
            sender=sender,
            subject=subject,
            snippet=snippet,
            body=body,
        ),
        "newsletter": is_newsletter(
            sender=sender,
            subject=subject,
            snippet=snippet,
            body=body,
        ),
        "social": _contains_any(
            signal_text(sender=sender, subject=subject, snippet=snippet, body=body),
            {
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
                "new follower",
                "liked your",
                "commented on",
                "mentioned you",
                "tagged you",
                "profile views",
                "new connection",
                "new subscribers",
            },
        )
        or any(
            marker in sender_domain(sender)
            for marker in {
                "instagram",
                "facebook",
                "twitter",
                "tiktok",
                "reddit",
                "discord",
                "youtube",
                "telegram",
            }
        ),
        "spam_like": is_spam_like(
            sender=sender,
            subject=subject,
            snippet=snippet,
            body=body,
        ),
    }
    del has_attachments

    if _signal("security"):
        return "security"
    if _signal("finance_invoice") or _signal("finance_receipt"):
        return "finance"
    if _signal("reply_needed") and _signal("human_like") and not _signal("automated"):
        return "needs-reply"
    if _signal("work_dev") and not _signal("newsletter"):
        return "work"
    if _signal("job_related") or _signal("recruiter"):
        return "jobs"
    if _signal("personal") and _signal("human_like"):
        return "personal"
    if _signal("high_value_newsletter"):
        return "newsletter"
    return "cleanup"


# DEPRECATED — use assign_single_label()
def recommend_mailbox_labels(
    *,
    sender: str,
    subject: str,
    snippet: str = "",
    body: str = "",
    has_attachments: bool = False,
    category: str = "unknown",
    priority: str = "low",
) -> list[str]:
    del category, priority
    return [
        assign_single_label(
            sender=sender,
            subject=subject,
            snippet=snippet,
            body=body,
            has_attachments=has_attachments,
        )
    ]


def select_inboxanchor_labels(
    existing_labels: list[str],
    suggested_labels: list[str] | None = None,
) -> list[str]:
    selected = {
        _normalize_label(label)
        for label in existing_labels
        if _is_inboxanchor_label(label)
    }
    for label in suggested_labels or []:
        normalized = _normalize_label(label)
        if normalized:
            selected.add(normalized)
    return sorted(selected)


def select_provider_cleanup_labels(existing_labels: list[str]) -> list[str]:
    return sorted(
        _normalize_label(label)
        for label in existing_labels
        if _is_inboxanchor_label(label) and not _is_alias_routing_label(label)
    )


def dedupe_labels(labels: list[str]) -> list[str]:
    seen: set[str] = set()
    output: list[str] = []
    for label in labels:
        normalized = _normalize_label(label)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        output.append(normalized)
    return output


def _contains_any(text: str, markers: set[str]) -> bool:
    for marker in markers:
        normalized = marker.strip().lower()
        if not normalized:
            continue
        if re.fullmatch(r"[a-z0-9]+", normalized):
            if re.search(rf"\b{re.escape(normalized)}\b", text):
                return True
            continue
        if normalized in text:
            return True
    return False


def _slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.strip().lower()).strip("-")
    return slug[:32] or "general"


def _normalize_label(label: str) -> str:
    return label.strip().replace(" ", "-").lower()


def _is_inboxanchor_label(label: str) -> bool:
    normalized = _normalize_label(label)
    if normalized in SINGLE_INBOXANCHOR_LABELS:
        return True
    if normalized in LEGACY_INBOXANCHOR_LABELS:
        return True
    return normalized.startswith(INBOXANCHOR_LABEL_PREFIXES)


def _is_alias_routing_label(label: str) -> bool:
    return _normalize_label(label).startswith(INBOXANCHOR_ALIAS_LABEL_PREFIX)
