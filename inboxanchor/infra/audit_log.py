from __future__ import annotations

from datetime import datetime, timezone

from inboxanchor.infra.database import AuditLogORM
from inboxanchor.models import AuditLogEntry, AutomationDecision


class AuditLogger:
    def create_entry(self, decision: AutomationDecision) -> AuditLogEntry:
        return AuditLogEntry(
            email_id=decision.email_id,
            proposed_action=decision.proposed_action,
            final_action=decision.final_action or decision.proposed_action,
            approved_by_user=decision.approved_by_user,
            timestamp=datetime.now(timezone.utc),
            reason=decision.reason,
            confidence=decision.confidence,
            agent_decision=decision.reason,
            safety_verifier_status=decision.safety_verifier_status,
        )

    def to_orm(self, entry: AuditLogEntry) -> AuditLogORM:
        return AuditLogORM(
            email_id=entry.email_id,
            proposed_action=entry.proposed_action,
            final_action=entry.final_action,
            approved_by_user=entry.approved_by_user,
            timestamp=entry.timestamp,
            reason=entry.reason,
            confidence=entry.confidence,
            agent_decision=entry.agent_decision,
            safety_verifier_status=entry.safety_verifier_status,
        )
