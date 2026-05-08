from inboxanchor.infra.audit_log import AuditLogger
from inboxanchor.models import AutomationDecision
from inboxanchor.models.email import SafetyStatus


def test_audit_log_entry_creation():
    decision = AutomationDecision(
        email_id="email-1",
        proposed_action="archive",
        final_action="archive",
        approved_by_user=True,
        reason="Old promo email.",
        confidence=0.88,
        safety_verifier_status=SafetyStatus.requires_review,
    )

    entry = AuditLogger().create_entry(decision)

    assert entry.email_id == "email-1"
    assert entry.final_action == "archive"
    assert entry.approved_by_user is True
