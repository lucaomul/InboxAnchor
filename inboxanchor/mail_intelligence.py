from __future__ import annotations

import re
from email.utils import parseaddr

from inboxanchor.infra.text_normalizer import normalize_email_body_text

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
    "ai ",
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
    labels: list[str] = []
    text = signal_text(sender=sender, subject=subject, snippet=snippet, body=body)
    automated = looks_automated_email(sender=sender, subject=subject, snippet=snippet, body=body)
    finance_invoice = is_finance_invoice(
        sender=sender,
        subject=subject,
        snippet=snippet,
        body=body,
    )
    finance_receipt = is_finance_receipt(
        sender=sender,
        subject=subject,
        snippet=snippet,
        body=body,
    )
    job_related = is_job_related(sender=sender, subject=subject, snippet=snippet, body=body)
    job_alert = is_job_alert(sender=sender, subject=subject, snippet=snippet, body=body)
    recruiter = is_recruiter_or_interview(
        sender=sender,
        subject=subject,
        snippet=snippet,
        body=body,
    )
    work_dev = is_work_dev_or_ai(sender=sender, subject=subject, snippet=snippet, body=body)
    ai_topic = _contains_any(
        text,
        AI_TOPIC_MARKERS,
    )
    github_thread = _contains_any(text, {"github", "gitlab", "bitbucket"})
    legal_contract = is_legal_contract(
        sender=sender,
        subject=subject,
        snippet=snippet,
        body=body,
    )
    meeting_followup = is_meeting_followup(
        sender=sender,
        subject=subject,
        snippet=snippet,
        body=body,
    )
    waiting = is_waiting_for_response(
        sender=sender,
        subject=subject,
        snippet=snippet,
        body=body,
    )
    deadline = has_deadline_pressure(sender=sender, subject=subject, snippet=snippet, body=body)
    reply_needed = has_reply_needed_signal(
        sender=sender,
        subject=subject,
        snippet=snippet,
        body=body,
    )
    high_value_newsletter = is_high_value_newsletter(
        sender=sender,
        subject=subject,
        snippet=snippet,
        body=body,
    )

    if finance_invoice:
        labels.append("finance/invoice")
    elif finance_receipt:
        labels.append("finance/receipt")
    elif category == "finance":
        labels.append("finance/general")

    if legal_contract:
        labels.append("legal/contract")
    if meeting_followup:
        labels.append("meetings/follow-up")

    if job_related:
        if recruiter and not automated:
            labels.append("jobs/recruiter")
        elif job_alert or automated:
            labels.append("jobs/alert")
        else:
            labels.append("jobs/application")

    if work_dev:
        if github_thread:
            labels.append("work/github")
        elif ai_topic:
            labels.append("work/ai")
        else:
            labels.append("work/dev")
    elif category == "work" and not automated:
        labels.append("work/general")

    if ai_topic:
        labels.append("topics/ai")

    if category == "newsletter":
        labels.append(
            "newsletters/high-value" if high_value_newsletter else "newsletters/routine"
        )
        if automated and not high_value_newsletter:
            labels.append("cleanup/low-priority")

    if category == "promo" or is_promo(sender=sender, subject=subject, snippet=snippet, body=body):
        labels.append("promo/discount")
        if automated:
            labels.append("cleanup/low-priority")

    if category == "low_priority":
        labels.append("cleanup/low-priority")

    if automated and category in {"low_priority", "newsletter", "promo"}:
        labels.append("automation/notification")

    if waiting and not automated:
        labels.append("waiting-for-response")

    if (
        category in {"urgent", "work", "finance", "opportunity"}
        and not automated
        and (reply_needed or recruiter or legal_contract or meeting_followup)
    ):
        if priority == "critical" or deadline:
            labels.append("needs-reply/urgent")
        elif priority in {"high", "medium"}:
            labels.append("needs-reply/this-week")

    if priority in {"critical", "high"} and category in {
        "work",
        "finance",
        "opportunity",
        "urgent",
    }:
        labels.append(f"priority/{priority}")

    if has_attachments and category in {"work", "finance", "opportunity", "urgent"}:
        labels.append("attachments/present")

    project_slug = extract_project_slug(
        sender=sender,
        subject=subject,
        snippet=snippet,
        body=body,
    )
    if project_slug and category in {"work", "opportunity", "urgent"}:
        labels.append(f"projects/{project_slug}")

    client_slug = extract_client_slug(sender=sender, category=category)
    if client_slug and not automated and not job_related:
        labels.append(f"clients/{client_slug}")

    if not labels:
        if category == "personal":
            labels.append("personal/review")
        elif category == "opportunity":
            labels.append("jobs/recruiter" if recruiter else "jobs/application")
        elif category == "spam_like":
            labels.append("cleanup/low-priority")

    return dedupe_labels(labels)


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
    return any(marker in text for marker in markers)


def _slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.strip().lower()).strip("-")
    return slug[:32] or "general"


def _normalize_label(label: str) -> str:
    return label.strip().replace(" ", "-").lower()


def _is_inboxanchor_label(label: str) -> bool:
    normalized = _normalize_label(label)
    if normalized in LEGACY_INBOXANCHOR_LABELS:
        return True
    return normalized.startswith(INBOXANCHOR_LABEL_PREFIXES)


def _is_alias_routing_label(label: str) -> bool:
    return _normalize_label(label).startswith(INBOXANCHOR_ALIAS_LABEL_PREFIX)
